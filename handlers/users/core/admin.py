import asyncio
import logging
import time
from math import ceil

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from data.config import ADMINS
from filters.admin import IsBotAdminFilter
from handlers.users.core.start import main_menu_keyboard
from keyboards.inline.buttons import are_you_sure_markup
from loader import bot, db
from states import AdminBroadcastState, AdminCouponState, AdminSettingsState, AdminState, CourseAdminState
from utils.pgtoexcel import export_to_excel

logger = logging.getLogger(__name__)
router = Router()

ADMIN_PANEL_TEXT = "⚙️ Admin panel"
COURSE_CREATE_CANCEL_TEXT = "❌ Bekor qilish"
ADMIN_COURSES_PER_PAGE = 5
SKIP_TEXTS = {"skip", "o'tkazish", "otkazish", "-", "yo'q", "yoq"}
REMOVE_TEXTS = {"remove", "o'chir", "ochir", "tozala", "clear"}
DEFAULT_COURSE_AUTHOR = "Maqsudxon Mo'minxonov"
DEFAULT_TARGET_EXAM = "DTM, Milliy Sertifikat, Attestatsiya"
DEFAULT_ACCESS_TYPE = "Hayotbod"
DEFAULT_SORT_ORDER = 100


class AdminMenuCallback(CallbackData, prefix="adm"):
    section: str


class AdminCoursePageCallback(CallbackData, prefix="adcp"):
    page: int


class AdminCourseViewCallback(CallbackData, prefix="adcv"):
    course_id: int
    page: int


class AdminCourseActionCallback(CallbackData, prefix="adca"):
    action: str
    course_id: int = 0
    page: int = 1


class AdminCourseEditCallback(CallbackData, prefix="adce"):
    field: str
    course_id: int
    page: int = 1


class AdminDashboardSectionCallback(CallbackData, prefix="adbs"):
    section: str  # users | courses | sales


class AdminSettingsCallback(CallbackData, prefix="adsets"):
    action: str


class AdminSettingEditCallback(CallbackData, prefix="adsete"):
    key: str


class AdminBroadcastCallback(CallbackData, prefix="adbr"):
    action: str  # menu | cancel
    page: int = 1


class AdminBroadcastPickCallback(CallbackData, prefix="adbrpick"):
    course_id: int
    page: int = 1


class AdminBroadcastTypeCallback(CallbackData, prefix="adbrtype"):
    msg_type: str


class AdminBroadcastAudienceCallback(CallbackData, prefix="adbraud"):
    action: str  # all | buyers | course_page
    page: int = 1


class AdminExportCallback(CallbackData, prefix="adex"):
    action: str  # menu | all | buyers | course_page
    page: int = 1


class AdminExportPickCallback(CallbackData, prefix="adexpick"):
    course_id: int


class AdminCouponCallback(CallbackData, prefix="adcoup"):
    action: str  # list | add | view | toggle | delete
    coupon_id: int = 0
    page: int = 1


class AdminCouponCourseCallback(CallbackData, prefix="adcoupcourse"):
    course_id: int  # 0 = barcha kurslar uchun


class AdminCouponEditCallback(CallbackData, prefix="adcoupedit"):
    field: str  # code | name | discount | max_uses | expires | course
    coupon_id: int


class AdminInstallmentCallback(CallbackData, prefix="adinst"):
    action: str  # list
    page: int = 1


class AdminCourseInstallmentCallback(CallbackData, prefix="adcourinst"):
    course_id: int
    page: int = 1


def format_price(price: int) -> str:
    if price <= 0:
        return "BEPUL"
    return f"{price:,}".replace(",", " ") + " so'm"


def format_dashboard_amount(amount: int | None) -> str:
    if not amount:
        return "0 so'm"
    return format_price(int(amount))


def format_date(value) -> str:
    if not value:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


def parse_positive_int(value: str, *, allow_zero: bool = True) -> int | None:
    normalized = value.replace(" ", "").replace("_", "").strip()
    if not normalized.isdigit():
        return None
    number = int(normalized)
    if number < 0:
        return None
    if not allow_zero and number == 0:
        return None
    return number


def parse_visibility(value: str) -> bool | None:
    normalized = (value or "").strip().lower().replace("‘", "'").replace("`", "'")
    yes_values = {"ha", "h", "yes", "y", "1", "true", "on", "ochiq", "faol", "ko'rinsin", "korinsin"}
    no_values = {"yo'q", "yoq", "no", "n", "0", "false", "off", "yopiq", "yashir", "ko'rinmasin", "korinmasin"}
    if normalized in yes_values:
        return True
    if normalized in no_values:
        return False
    return None


def optional_course_text(value: str, default: str | None = None) -> str | None:
    text = (value or "").strip()
    if not text or text.lower() in SKIP_TEXTS:
        return default
    return text


def nullable_course_text(value: str) -> str | None:
    text = (value or "").strip()
    if not text or text.lower() in SKIP_TEXTS or text.lower() in REMOVE_TEXTS:
        return None
    return text


def create_cancel_markup() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=COURSE_CREATE_CANCEL_TEXT)]],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📚 Kurslarni boshqarish",
                    callback_data=AdminMenuCallback(section="courses").pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Dashboard",
                    callback_data=AdminMenuCallback(section="dashboard").pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Sozlamalar",
                    callback_data=AdminMenuCallback(section="settings").pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 Xabar yuborish",
                    callback_data=AdminMenuCallback(section="broadcast").pack(),
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Excel eksport",
                    callback_data=AdminMenuCallback(section="excel").pack(),
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎟 Kuponlar",
                    callback_data=AdminMenuCallback(section="coupons").pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="📅 Muddatli to'lovlar",
                    callback_data=AdminMenuCallback(section="installments").pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
        ]
    )


SETTINGS_KEYS = {
    "faq": "❓ Yordam / FAQ",
    "contact": "📞 Admin bilan bog'lanish",
    "support_group_id": "💬 Support guruh ID",
    "admin_username": "👤 Admin username",
}

TEXT_ONLY_SETTINGS = {"support_group_id", "admin_username"}

_SETTINGS_HINTS = {
    "support_group_id": (
        "💬 <b>Support guruh ID</b>\n\n"
        "Botni qo'shgan guruhning Telegram ID sini kiriting.\n"
        "Misol: <code>-1001234567890</code>\n\n"
        "Guruh ID ni olish uchun guruhga @getmyid_bot yuboring."
    ),
    "admin_username": (
        "👤 <b>Admin username</b>\n\n"
        "Admin Telegram username ini kiriting (<code>@</code> belgisiz ham bo'ladi).\n"
        "Misol: <code>biolog_mm02</code>"
    ),
}


def admin_settings_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"✏️ {label}",
                callback_data=AdminSettingEditCallback(key=key).pack(),
                style=ButtonStyle.PRIMARY,
            )
        ]
        for key, label in SETTINGS_KEYS.items()
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ Admin panel",
                callback_data=AdminMenuCallback(section="main").pack(),
                style=ButtonStyle.PRIMARY,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


_DASHBOARD_SECTIONS = [
    ("users",   "👥 Foydalanuvchilar"),
    ("courses", "📚 Kurslar"),
    ("sales",   "🛒 Sotuvlar"),
]


def admin_dashboard_section_keyboard(active: str) -> InlineKeyboardMarkup:
    tab_row = [
        InlineKeyboardButton(
            text=f"[ {label} ]" if s == active else label,
            callback_data=AdminDashboardSectionCallback(section=s).pack(),
            style=ButtonStyle.SUCCESS if s == active else ButtonStyle.PRIMARY,
        )
        for s, label in _DASHBOARD_SECTIONS
    ]
    bottom_row = [
        InlineKeyboardButton(
            text="🔄 Yangilash",
            callback_data=AdminDashboardSectionCallback(section=active).pack(),
            style=ButtonStyle.PRIMARY,
        ),
        InlineKeyboardButton(
            text="↩️ Admin panel",
            callback_data=AdminMenuCallback(section="main").pack(),
            style=ButtonStyle.PRIMARY,
        ),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[tab_row, bottom_row])


def dashboard_status_label(status: str) -> str:
    labels = {
        "pending": "⏳ Kutilmoqda",
        "approved": "✅ Tasdiqlangan",
        "rejected": "❌ Rad etilgan",
    }
    return labels.get(status, status)


async def admin_dashboard_users_text() -> str:
    total_users, registered_users, blocked_users = await asyncio.gather(
        db.count_users(),
        db.count_registered_users(),
        db.count_blocked_users(),
    )
    unregistered = max(total_users - registered_users, 0)
    return "\n".join([
        "👥 <b>FOYDALANUVCHILAR STATISTIKASI</b>",
        "",
        f"Jami: <b>{total_users}</b>",
        f"✅ Ro'yxatdan o'tgan: <b>{registered_users}</b>",
        f"⏳ Ro'yxatdan o'tmagan: <b>{unregistered}</b>",
        f"🚫 Bloklangan: <b>{blocked_users}</b>",
    ])


async def admin_dashboard_courses_text() -> str:
    total_courses, active_courses = await asyncio.gather(
        db.count_courses(),
        db.count_active_courses(),
    )
    hidden = max(total_courses - active_courses, 0)
    return "\n".join([
        "📚 <b>KURSLAR STATISTIKASI</b>",
        "",
        f"Jami kurslar: <b>{total_courses}</b>",
        f"✅ Ko'rinadigan: <b>{active_courses}</b>",
        f"🚫 Yopiq: <b>{hidden}</b>",
    ])


async def admin_dashboard_sales_text() -> str:
    (
        total_purchases,
        pending_purchases,
        approved_purchases,
        rejected_purchases,
        approved_amount,
        pending_amount,
        latest_purchases,
        top_courses,
    ) = await asyncio.gather(
        db.count_purchases(),
        db.count_purchases("pending"),
        db.count_purchases("approved"),
        db.count_purchases("rejected"),
        db.sum_purchases_amount("approved"),
        db.sum_purchases_amount("pending"),
        db.select_latest_purchases(limit=5),
        db.select_top_courses_by_purchases(limit=5),
    )

    lines = [
        "🛒 <b>SOTUVLAR STATISTIKASI</b>",
        "",
        f"Jami xaridlar: <b>{total_purchases}</b>",
        f"⏳ Kutilmoqda: <b>{pending_purchases}</b>",
        f"✅ Tasdiqlangan: <b>{approved_purchases}</b>",
        f"❌ Rad etilgan: <b>{rejected_purchases}</b>",
        "",
        "💰 <b>Moliya</b>",
        f"Tasdiqlangan tushum: <b>{format_dashboard_amount(approved_amount)}</b>",
        f"Kutilayotgan summa: <b>{format_dashboard_amount(pending_amount)}</b>",
        "",
        "🏆 <b>Top kurslar</b>",
    ]
    top_with_sales = [c for c in top_courses if c["purchase_count"]]
    if top_with_sales:
        for i, c in enumerate(top_with_sales, 1):
            lines.append(
                f"{i}. <b>{html.quote(c['name'])}</b> "
                f"({c['purchase_count']} xarid · {format_dashboard_amount(c['revenue'])})"
            )
    else:
        lines.append("Hali xaridlar yo'q.")

    lines.extend(["", "🧾 <b>Oxirgi 5 xarid</b>"])
    if latest_purchases:
        for p in latest_purchases:
            buyer = p["full_name"] or str(p["telegram_id"])
            lines.append(
                f"#{p['id']} · {dashboard_status_label(p['status'])}\n"
                f"<b>{html.quote(p['course_name'])}</b>\n"
                f"{html.quote(buyer)} · {format_price(p['amount'])} · {format_date(p['created_at'])}"
            )
    else:
        lines.append("Hali xaridlar yo'q.")

    return "\n".join(lines)


async def get_dashboard_section_text(section: str) -> str:
    if section == "courses":
        return await admin_dashboard_courses_text()
    if section == "sales":
        return await admin_dashboard_sales_text()
    return await admin_dashboard_users_text()


async def render_dashboard_section(call: types.CallbackQuery, section: str) -> None:
    await call.answer()
    text = await get_dashboard_section_text(section)
    markup = admin_dashboard_section_keyboard(section)
    try:
        if call.message.photo:
            await call.message.delete()
            await call.message.answer(text, reply_markup=markup)
            return
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


def admin_courses_text(courses: list, page: int, total: int) -> str:
    if not courses:
        return (
            "📚 <b>KURSLARNI BOSHQARISH</b>\n\n"
            "Hozircha kurslar mavjud emas.\n"
            "Yangi kurs qo'shish uchun pastdagi tugmani bosing."
        )

    total_pages = max(ceil(total / ADMIN_COURSES_PER_PAGE), 1)
    lines = [
        "📚 <b>KURSLARNI BOSHQARISH</b>",
        f"Sahifa: <b>{page}/{total_pages}</b>",
        "",
    ]
    for index, course in enumerate(courses, start=1):
        status = "✅ Ko'rinadi" if course["is_active"] else "🚫 Yopiq"
        lines.append(
            f"{index}. <b>{html.quote(course['name'])}</b>\n"
            f"   {status} | {format_price(course['price'])} | {course['video_count']} video"
        )
    return "\n".join(lines)


def admin_courses_keyboard(courses: list, page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(ceil(total / ADMIN_COURSES_PER_PAGE), 1)
    rows: list[list[InlineKeyboardButton]] = []

    if courses:
        rows.append(
            [
                InlineKeyboardButton(
                    text=str(index),
                    callback_data=AdminCourseViewCallback(course_id=course["id"], page=page).pack(),
                    style=ButtonStyle.PRIMARY,
                )
                for index, course in enumerate(courses, start=1)
            ]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Oldingi",
                callback_data=AdminCoursePageCallback(page=page - 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Keyingi ➡️",
                callback_data=AdminCoursePageCallback(page=page + 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Yangi kurs",
                callback_data=AdminCourseActionCallback(action="create", page=page).pack(),
                style=ButtonStyle.SUCCESS,
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ Admin panel",
                callback_data=AdminMenuCallback(section="main").pack(),
                style=ButtonStyle.PRIMARY,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_course_detail_text(course) -> str:
    status = "✅ Userlarga ko'rinadi" if course["is_active"] else "🚫 Userlarga ko'rinmaydi"
    free_btn = "✅ Yoqilgan" if course["show_free_button"] else "🚫 O'chirilgan"
    paid_btn = "✅ Yoqilgan" if course["show_paid_button"] else "🚫 O'chirilgan"
    price_visible = "✅ Ko'rinadi" if course["show_price"] else "🚫 Yashirilgan"
    video_status = "✅ Bor" if course.get("video_file_id") else "🚫 Yo'q"
    inst_status = "✅ Yoqilgan" if course.get("installment_available") else "🚫 O'chirilgan"
    return (
        f"📘 <b>{html.quote(course['name'])}</b>\n"
        f"Holat: <b>{status}</b>\n"
        f"Narx: <b>{format_price(course['price'])}</b> ({price_visible})\n"
        f"Bo'lib to'lash: <b>{inst_status}</b>\n"
        f"Video darslar: <b>{course['video_count']} ta</b>\n"
        f"Muallif: {html.quote(course['author'])}\n"
        f"Davomiylik: {html.quote(course['duration'] or '-')}\n"
        f"Imtihon: {html.quote(course['target_exam'] or '-')}\n"
        f"Qo'shimcha: {html.quote(course['includes'] or '-')}\n"
        f"Kirish: {html.quote(course['access_type'])}\n"
        f"Pullik kanal link: {html.quote(course['telegram_link'] or '-')}\n"
        f"Bepul kanal link: {html.quote(course['free_telegram_link'] or '-')}\n"
        f"Bepul tugma: {free_btn}\n"
        f"Pullik tugma: {paid_btn}\n"
        f"Taqdimot video: {video_status}\n"
        f"Sort: {course['sort_order']}\n\n"
        "<b>Tavsif:</b>\n"
        f"{html.quote(course['description'])}"
    )


def _caption_warning(course) -> str | None:
    total = len(admin_course_detail_text(course))
    if total <= 1024:
        return None
    excess = total - 1024
    desc_len = len(course.get("description") or "")
    name_len = len(course.get("name") or "")
    parts = [
        "⚠️ <b>Caption limit oshib ketdi!</b>",
        f"Jami belgilar: <b>{total}</b> / 1024 (<b>+{excess}</b> ta ortiqcha)\n",
    ]
    if desc_len > 150:
        parts.append(f"📝 Tavsif: <b>{desc_len}</b> belgi — eng ko'p joy olayapti, qisqartiring")
    if name_len > 60:
        parts.append(f"📌 Nomi: <b>{name_len}</b> belgi — nomni qisqartiring")
    parts.append("\n<i>Kurs sahifasini to'g'ri ko'rsatish uchun yuqoridagi maydonlarni qisqartiring.</i>")
    return "\n".join(parts)


def admin_course_detail_keyboard(course) -> InlineKeyboardMarkup:
    status_button_text = "✅ Holat: ko'rinadi" if course["is_active"] else "🚫 Holat: yopiq"
    toggle_style = ButtonStyle.DANGER if course["is_active"] else ButtonStyle.SUCCESS
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Nomi",
                    callback_data=AdminCourseEditCallback(field="name", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text=status_button_text,
                    callback_data=AdminCourseActionCallback(action="toggle", course_id=course["id"]).pack(),
                    style=toggle_style,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💰 Narx",
                    callback_data=AdminCourseEditCallback(field="price", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="👁 Narx: " + ("✅" if course["show_price"] else "🚫"),
                    callback_data=AdminCourseActionCallback(action="toggle_show_price", course_id=course["id"]).pack(),
                    style=ButtonStyle.SUCCESS if course["show_price"] else ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(
                    text="📊 Video",
                    callback_data=AdminCourseEditCallback(field="video_count", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👨‍🏫 Muallif",
                    callback_data=AdminCourseEditCallback(field="author", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="⏱ Davomiylik",
                    callback_data=AdminCourseEditCallback(field="duration", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Imtihon",
                    callback_data=AdminCourseEditCallback(field="target_exam", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="✨ Qo'shimcha",
                    callback_data=AdminCourseEditCallback(field="includes", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="♾ Kirish",
                    callback_data=AdminCourseEditCallback(field="access_type", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="🔗 Pullik link",
                    callback_data=AdminCourseEditCallback(field="telegram_link", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="🆓 Bepul link",
                    callback_data=AdminCourseEditCallback(field="free_telegram_link", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎁 Bepul tugma: " + ("✅" if course["show_free_button"] else "🚫"),
                    callback_data=AdminCourseActionCallback(action="toggle_free_btn", course_id=course["id"]).pack(),
                    style=ButtonStyle.SUCCESS if course["show_free_button"] else ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(
                    text="💎 Pullik tugma: " + ("✅" if course["show_paid_button"] else "🚫"),
                    callback_data=AdminCourseActionCallback(action="toggle_paid_btn", course_id=course["id"]).pack(),
                    style=ButtonStyle.SUCCESS if course["show_paid_button"] else ButtonStyle.DANGER,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔢 Sort",
                    callback_data=AdminCourseEditCallback(field="sort_order", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="📝 Tavsif",
                    callback_data=AdminCourseEditCallback(field="description", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="🖼 Rasm",
                    callback_data=AdminCourseEditCallback(field="thumbnail", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎬 Video",
                    callback_data=AdminCourseEditCallback(field="video_file_id", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📅 Bo'lib to'lash: " + ("✅" if course.get("installment_available") else "🚫"),
                    callback_data=AdminCourseInstallmentCallback(course_id=course["id"]).pack(),
                    style=ButtonStyle.SUCCESS if course.get("installment_available") else ButtonStyle.DANGER,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 O'chirish",
                    callback_data=AdminCourseActionCallback(action="delete_ask", course_id=course["id"]).pack(),
                    style=ButtonStyle.DANGER,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Ro'yxat",
                    callback_data=AdminCoursePageCallback(page=1).pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ],
        ]
    )


async def render_admin_menu(message: types.Message) -> None:
    await message.answer("⚙️ <b>ADMIN PANEL</b>", reply_markup=admin_main_keyboard())


async def edit_or_send_admin_menu(call: types.CallbackQuery) -> None:
    await call.answer()
    if call.message.photo:
        await call.message.delete()
        await call.message.answer("⚙️ <b>ADMIN PANEL</b>", reply_markup=admin_main_keyboard())
        return
    await call.message.edit_text("⚙️ <b>ADMIN PANEL</b>", reply_markup=admin_main_keyboard())


async def render_admin_dashboard(call_or_message, answer: bool = True, section: str = "users") -> None:
    text = await get_dashboard_section_text(section)
    markup = admin_dashboard_section_keyboard(section)

    if isinstance(call_or_message, types.CallbackQuery):
        call = call_or_message
        if answer:
            await call.answer()
        if call.message.photo:
            await call.message.delete()
            await call.message.answer(text, reply_markup=markup)
            return
        try:
            await call.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as error:
            if "message is not modified" in str(error):
                return
            raise
        return

    await call_or_message.answer(text, reply_markup=markup)


async def render_admin_courses_list(call_or_message, page: int = 1, answer: bool = True) -> None:
    total = await db.count_courses()
    total_pages = max(ceil(total / ADMIN_COURSES_PER_PAGE), 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * ADMIN_COURSES_PER_PAGE
    courses = await db.select_courses_page(limit=ADMIN_COURSES_PER_PAGE, offset=offset)
    text = admin_courses_text(courses=courses, page=page, total=total)
    markup = admin_courses_keyboard(courses=courses, page=page, total=total)

    if isinstance(call_or_message, types.CallbackQuery):
        call = call_or_message
        if answer:
            await call.answer()
        if call.message.photo:
            await call.message.delete()
            await call.message.answer(text, reply_markup=markup)
            return
        await call.message.edit_text(text, reply_markup=markup)
        return

    await call_or_message.answer(text, reply_markup=markup)


async def render_admin_course_detail(call: types.CallbackQuery, course_id: int) -> None:
    course = await db.select_course(course_id)
    await call.answer()
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        await render_admin_courses_list(call, page=1)
        return

    text = admin_course_detail_text(course)
    markup = admin_course_detail_keyboard(course)
    caption_too_long = len(text) > 1024

    if course["thumbnail"]:
        if caption_too_long:
            await call.message.delete()
            await call.message.answer_photo(photo=course["thumbnail"])
            await call.message.answer(text, reply_markup=markup)
        elif call.message.photo:
            await call.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await call.message.delete()
            await call.message.answer_photo(photo=course["thumbnail"], caption=text, reply_markup=markup)
    elif call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
    else:
        await call.message.edit_text(text, reply_markup=markup)

    warning = _caption_warning(course)
    if warning:
        await call.message.answer(warning)


@router.message(Command("admin"), IsBotAdminFilter(ADMINS))
@router.message(F.text == ADMIN_PANEL_TEXT, IsBotAdminFilter(ADMINS))
async def admin_panel(message: types.Message):
    await render_admin_menu(message)


@router.message(Command("buyurtma"), IsBotAdminFilter(ADMINS))
async def admin_purchase_detail_cmd(message: types.Message):
    from utils.misc.api.course_payment import check_order_status
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(
            "Foydalanish: <code>/buyurtma &lt;xarid_id&gt;</code>\n"
            "Misol: <code>/buyurtma 42</code>"
        )
        return
    purchase_id = int(args[1])
    purchase = await db.select_purchase_by_id(purchase_id)
    if not purchase:
        await message.answer(f"❌ Xarid #{purchase_id} topilmadi.")
        return

    lines = [f"🧾 <b>XARID #{purchase['id']} — TO'LIQ HISOBOT</b>\n"]
    lines.append(f"📚 Kurs: <b>{html.quote(purchase['course_name'])}</b>")

    orig = purchase.get("original_amount") or 0
    paid_amt = purchase.get("amount", 0)
    if orig and orig != paid_amt:
        lines.append(f"💰 Asl narx: <b>{format_price(orig)}</b>")
        lines.append(f"💸 Chegirma: <b>−{format_price(orig - paid_amt)}</b>")
    lines.append(f"✅ To'lov summasi: <b>{format_price(paid_amt)}</b>")

    if purchase.get("coupon_code"):
        lines.append(f"🎟 Kupon: <code>{html.quote(purchase['coupon_code'])}</code>")

    is_inst = purchase.get("is_installment", False)
    pay_type = "Muddatli to'lov" if is_inst else ("CLICK" if purchase.get("click_order_id") else "Chek")
    lines.append(f"📊 To'lov turi: <b>{pay_type}</b>")
    lines.append(f"📋 Holat: <b>{purchase['status']}</b>")
    lines.append(f"📅 Yaratilgan: {purchase['created_at'].strftime('%d.%m.%Y %H:%M') if purchase.get('created_at') else '—'}")

    lines.append("\n━━━━━━━━━━━━━━")
    lines.append(f"👤 Ismi: <b>{html.quote(purchase.get('full_name') or '—')}</b>")
    lines.append(f"📱 Tel: <b>{html.quote(purchase.get('phone') or '—')}</b>")
    un = purchase.get("username")
    lines.append(f"🔗 Username: {'@' + html.quote(un) if un else '—'}")
    lines.append(f"🆔 TG ID: <code>{purchase['telegram_id']}</code>")

    if purchase.get("click_order_id"):
        lines.append(f"\n━━━━━━━━━━━━━━")
        lines.append(f"🔗 CLICK buyurtma ID: <code>{purchase['click_order_id']}</code>")
        try:
            order = await check_order_status(purchase["click_order_id"])
            if order:
                click_status = "✅ To'langan" if order.get("paid") else "⏳ Kutilmoqda"
                lines.append(f"📊 CLICK holati: <b>{click_status}</b>")
                if order.get("amount"):
                    lines.append(f"💰 CLICK summasi: <b>{format_price(int(order['amount']))}</b>")
            else:
                lines.append("📊 CLICK holati: <i>ma'lumot olishda xato</i>")
        except Exception:
            lines.append("📊 CLICK holati: <i>API'ga ulanib bo'lmadi</i>")

    if is_inst:
        plan = await db.get_installment_plan_by_purchase(purchase_id)
        if plan:
            payments = await db.get_installment_payments(plan["id"])
            paid_count = sum(1 for p in payments if p["status"] == "paid")
            lines.append(f"\n━━━━━━━━━━━━━━")
            lines.append(f"📅 Muddatli to'lov: <b>{paid_count}/{plan['installments_count']}</b>")
            lines.append(f"💰 Jami summa: <b>{format_price(plan['total_amount'])}</b>")
            for p in payments:
                status_icon = "✅" if p["status"] == "paid" else ("💳 CLICK" if p.get("click_order_id") else "⏳")
                due = p["due_date"].strftime("%d.%m.%Y") if p.get("due_date") else "—"
                lines.append(f"  {status_icon} {p['payment_number']}-qism: {format_price(p['amount'])} | {due}")

    await message.answer("\n".join(lines))


@router.callback_query(AdminMenuCallback.filter(F.section == "main"), IsBotAdminFilter(ADMINS))
async def admin_menu_callback(call: types.CallbackQuery):
    await edit_or_send_admin_menu(call)


@router.callback_query(AdminMenuCallback.filter(F.section == "courses"), IsBotAdminFilter(ADMINS))
async def admin_courses_callback(call: types.CallbackQuery):
    await render_admin_courses_list(call, page=1)


@router.callback_query(AdminMenuCallback.filter(F.section == "settings"), IsBotAdminFilter(ADMINS))
async def admin_settings_callback(call: types.CallbackQuery):
    await call.answer()
    text = (
        "⚙️ <b>SOZLAMALAR</b>\n\n"
        "Foydalanuvchilarga ko'rsatiladigan matnlarni tahrirlang.\n"
        "Rasm + izoh yoki faqat matn yuboring."
    )
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=admin_settings_keyboard())
        return
    await call.message.edit_text(text, reply_markup=admin_settings_keyboard())


@router.callback_query(AdminSettingEditCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_setting_edit_start(call: types.CallbackQuery, callback_data: AdminSettingEditCallback, state: FSMContext):
    await call.answer()
    key = callback_data.key
    label = SETTINGS_KEYS.get(key, key)
    current = await db.get_setting(key)

    await state.clear()
    await state.update_data(setting_key=key)
    await state.set_state(AdminSettingsState.awaiting_content)

    current_hint = ""
    if current and current["text"]:
        current_hint = f"\n\n<i>Hozirgi qiymat: <code>{html.quote(current['text'])}</code></i>"

    if key in _SETTINGS_HINTS:
        await call.message.answer(
            _SETTINGS_HINTS[key] + current_hint,
            reply_markup=create_cancel_markup(),
        )
        return

    hint = ""
    if current:
        hint = "\n\n<i>Hozirgi kontent mavjud. Yangi xabar yuborsangiz, o'rnini egallaydi.</i>"

    await call.message.answer(
        f"✏️ <b>{label}</b> uchun yangi kontent yuboring.\n\n"
        "📌 Qoidalar:\n"
        "• Faqat matn → matn sifatida saqlanadi\n"
        "• Rasm + izoh (caption) → rasm bilan saqlanadi\n"
        "• <b>Bold</b>, <i>italic</i>, emoji — barchasi saqlanadi"
        f"{hint}",
        reply_markup=create_cancel_markup(),
    )


@router.message(StateFilter(AdminSettingsState.awaiting_content), IsBotAdminFilter(ADMINS))
async def admin_setting_receive_content(message: types.Message, state: FSMContext):
    if message.text and message.text.strip() == COURSE_CREATE_CANCEL_TEXT:
        await state.clear()
        await message.answer("❌ Bekor qilindi.", reply_markup=main_menu_keyboard(user_id=message.from_user.id))
        await message.answer("⚙️ <b>SOZLAMALAR</b>", reply_markup=admin_settings_keyboard())
        return

    data = await state.get_data()
    key = data.get("setting_key", "")
    label = SETTINGS_KEYS.get(key, key)

    if key in TEXT_ONLY_SETTINGS:
        if not message.text:
            await message.answer("Faqat matn kiriting.")
            return
        value = message.text.strip()
        if key == "support_group_id":
            try:
                int(value)
            except ValueError:
                await message.answer(
                    "❗ Guruh ID faqat raqam bo'lishi kerak.\n"
                    "Misol: <code>-1001234567890</code>"
                )
                return
        if key == "admin_username":
            value = value.lstrip("@")
        await db.upsert_setting(key=key, text=value, photo_file_id=None)
        await state.clear()
        await message.answer(
            f"✅ <b>{label}</b> saqlandi: <code>{html.quote(value)}</code>",
            reply_markup=main_menu_keyboard(user_id=message.from_user.id),
        )
        await message.answer("⚙️ <b>SOZLAMALAR</b>", reply_markup=admin_settings_keyboard())
        return

    if message.photo:
        photo_file_id = message.photo[-1].file_id
        text = message.caption_html or ""
    elif message.text:
        photo_file_id = None
        text = message.html_text
    else:
        await message.answer("Faqat matn yoki rasm+izoh yuboring.")
        return

    await db.upsert_setting(key=key, text=text, photo_file_id=photo_file_id)
    await state.clear()

    await message.answer(
        f"✅ <b>{label}</b> muvaffaqiyatli saqlandi.",
        reply_markup=main_menu_keyboard(user_id=message.from_user.id),
    )
    await message.answer("⚙️ <b>SOZLAMALAR</b>", reply_markup=admin_settings_keyboard())


@router.callback_query(AdminMenuCallback.filter(F.section == "dashboard"), IsBotAdminFilter(ADMINS))
async def admin_dashboard_placeholder(call: types.CallbackQuery):
    await render_admin_dashboard(call, section="users")


@router.callback_query(AdminDashboardSectionCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_dashboard_section(call: types.CallbackQuery, callback_data: AdminDashboardSectionCallback):
    await render_dashboard_section(call, section=callback_data.section)


@router.callback_query(AdminCoursePageCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_courses_page(call: types.CallbackQuery, callback_data: AdminCoursePageCallback):
    await render_admin_courses_list(call, page=callback_data.page)


@router.callback_query(AdminCourseViewCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_course_view(call: types.CallbackQuery, callback_data: AdminCourseViewCallback):
    await render_admin_course_detail(call, course_id=callback_data.course_id)


@router.callback_query(AdminCourseActionCallback.filter(F.action == "create"), IsBotAdminFilter(ADMINS))
async def admin_course_create_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await state.set_state(CourseAdminState.add_name)
    await call.message.answer(
        "➕ <b>Yangi kurs qo'shish</b>\n\n"
        "1/13. Kurs nomini kiriting:\n"
        "Masalan: <b>6-botanika | Imkon-edu Pro</b>",
        reply_markup=create_cancel_markup(),
    )


@router.message(StateFilter(CourseAdminState), F.text == COURSE_CREATE_CANCEL_TEXT, IsBotAdminFilter(ADMINS))
async def admin_course_create_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Kurs qo'shish bekor qilindi.",
        reply_markup=main_menu_keyboard(user_id=message.from_user.id),
    )
    await render_admin_courses_list(message, page=1)


@router.message(CourseAdminState.add_name, IsBotAdminFilter(ADMINS))
async def admin_course_add_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    await state.update_data(name=name)
    await state.set_state(CourseAdminState.add_is_active)
    await message.answer(
        "2/13. Kurs userlarga ko'rinsinmi?\n\n<code>ha</code> yoki <code>yo'q</code> yozing.",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_is_active, IsBotAdminFilter(ADMINS))
async def admin_course_add_is_active(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip().lower()
    is_active = False if raw in ("yo'q", "yoq", "no", "false", "0") else True
    await state.update_data(is_active=is_active)
    await state.set_state(CourseAdminState.add_price)
    await message.answer(
        "3/13. 💰 Kurs narxini kiriting. Bepul kurs uchun <code>0</code> yozing.",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_price, IsBotAdminFilter(ADMINS))
async def admin_course_add_price(message: types.Message, state: FSMContext):
    price = parse_positive_int(message.text or "") or 0
    await state.update_data(price=price)
    await state.set_state(CourseAdminState.add_video_count)
    await message.answer(
        "4/13. 📊 Video darslar sonini kiriting. Masalan: <code>12</code>",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_video_count, IsBotAdminFilter(ADMINS))
async def admin_course_add_video_count(message: types.Message, state: FSMContext):
    video_count = parse_positive_int(message.text or "") or 0
    await state.update_data(video_count=video_count)
    await state.set_state(CourseAdminState.add_author)
    await message.answer(
        "5/13. 👨‍🏫 Muallifni kiriting.\n\n"
        f"Standart qiymat uchun <code>skip</code>: <b>{html.quote(DEFAULT_COURSE_AUTHOR)}</b>",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_author, IsBotAdminFilter(ADMINS))
async def admin_course_add_author(message: types.Message, state: FSMContext):
    author = optional_course_text(message.text or "", DEFAULT_COURSE_AUTHOR) or DEFAULT_COURSE_AUTHOR
    await state.update_data(author=author)
    await state.set_state(CourseAdminState.add_duration)
    await message.answer(
        "6/13. ⏱ Davomiylikni kiriting yoki bo'sh qoldirish uchun <code>skip</code> yozing.",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_duration, IsBotAdminFilter(ADMINS))
async def admin_course_add_duration(message: types.Message, state: FSMContext):
    duration = optional_course_text(message.text or "")
    await state.update_data(duration=duration)
    await state.set_state(CourseAdminState.add_target_exam)
    await message.answer(
        "7/13. 🎯 Imtihon yo'nalishlarini kiriting.\n\n"
        f"Standart qiymat uchun <code>skip</code>: <b>{html.quote(DEFAULT_TARGET_EXAM)}</b>",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_target_exam, IsBotAdminFilter(ADMINS))
async def admin_course_add_target_exam(message: types.Message, state: FSMContext):
    target_exam = optional_course_text(message.text or "", DEFAULT_TARGET_EXAM)
    await state.update_data(target_exam=target_exam)
    await state.set_state(CourseAdminState.add_includes)
    await message.answer(
        "8/13. ✨ Qo'shimcha tarkibni kiriting yoki bo'sh qoldirish uchun <code>skip</code> yozing.",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_includes, IsBotAdminFilter(ADMINS))
async def admin_course_add_includes(message: types.Message, state: FSMContext):
    includes = optional_course_text(message.text or "")
    await state.update_data(includes=includes)
    await state.set_state(CourseAdminState.add_access_type)
    await message.answer(
        "9/13. ♾ Kirish turini kiriting.\n\n"
        f"Standart qiymat uchun <code>skip</code>: <b>{html.quote(DEFAULT_ACCESS_TYPE)}</b>",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_access_type, IsBotAdminFilter(ADMINS))
async def admin_course_add_access_type(message: types.Message, state: FSMContext):
    access_type = optional_course_text(message.text or "", DEFAULT_ACCESS_TYPE) or DEFAULT_ACCESS_TYPE
    await state.update_data(access_type=access_type)
    await state.set_state(CourseAdminState.add_link)
    await message.answer(
        "10/13. 🔗 Kurs guruhi/linkini yuboring yoki bo'sh qoldirish uchun <code>skip</code> yozing.",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_link, IsBotAdminFilter(ADMINS))
async def admin_course_add_link(message: types.Message, state: FSMContext):
    telegram_link = optional_course_text(message.text or "")
    await state.update_data(telegram_link=telegram_link)
    await state.set_state(CourseAdminState.add_sort_order)
    await message.answer(
        f"11/13. 🔢 Sort tartibini kiriting. Standart uchun <code>skip</code>: <b>{DEFAULT_SORT_ORDER}</b>",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_sort_order, IsBotAdminFilter(ADMINS))
async def admin_course_add_sort_order(message: types.Message, state: FSMContext):
    raw_sort_order = (message.text or "").strip()
    sort_order = parse_positive_int(raw_sort_order) if raw_sort_order.lower() not in SKIP_TEXTS else None
    await state.update_data(sort_order=sort_order or DEFAULT_SORT_ORDER)
    await state.set_state(CourseAdminState.add_description)
    await message.answer(
        "12/13. 📝 Kurs tavsifini yuboring.",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_description, IsBotAdminFilter(ADMINS))
async def admin_course_add_description(message: types.Message, state: FSMContext):
    description = (message.text or "").strip()
    await state.update_data(description=description)
    await state.set_state(CourseAdminState.add_photo)
    await message.answer(
        "13/14. 🖼 Premium ko'rinish uchun kurs rasmini yuboring yoki o'tkazish uchun <code>skip</code> yozing.",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_photo, IsBotAdminFilter(ADMINS))
async def admin_course_add_photo(message: types.Message, state: FSMContext):
    thumbnail = None
    if message.photo:
        thumbnail = message.photo[-1].file_id
    elif (message.text or "").strip().lower() not in SKIP_TEXTS:
        await message.answer("Rasm yuboring yoki <code>skip</code> yozing.")
        return

    await state.update_data(thumbnail=thumbnail)
    await state.set_state(CourseAdminState.add_video)
    await message.answer(
        "14/14. 🎬 Kurs taqdimot videosi (ixtiyoriy).\n\n"
        "Foydalanuvchilarga kurs kartochkasida ko'rsatiladigan video yuboring.\n"
        "O'tkazish uchun <code>skip</code> yozing.",
        reply_markup=create_cancel_markup(),
    )


@router.message(CourseAdminState.add_video, IsBotAdminFilter(ADMINS))
async def admin_course_add_video(message: types.Message, state: FSMContext):
    video_file_id = None
    if message.video:
        video_file_id = message.video.file_id
    elif (message.text or "").strip().lower() not in SKIP_TEXTS:
        await message.answer("Video yuboring yoki <code>skip</code> yozing.")
        return

    await state.update_data(video_file_id=video_file_id)
    data = await state.get_data()

    course = await db.add_course(
        name=data["name"],
        description=data["description"],
        price=data["price"],
        video_count=data["video_count"],
        is_active=data["is_active"],
        thumbnail=data.get("thumbnail"),
        video_file_id=data.get("video_file_id"),
        telegram_link=data.get("telegram_link"),
        author=data["author"],
        duration=data.get("duration"),
        target_exam=data.get("target_exam"),
        includes=data.get("includes"),
        access_type=data["access_type"],
        sort_order=data["sort_order"],
    )
    await state.clear()
    warning = _caption_warning(course)
    if warning:
        await message.answer(warning)
    await message.answer(
        f"✅ Kurs yaratildi: <b>{html.quote(course['name'])}</b>",
        reply_markup=main_menu_keyboard(user_id=message.from_user.id),
    )
    await message.answer(
        "Kursni boshqarish:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📘 Kursni ko'rish",
                        callback_data=AdminCourseViewCallback(course_id=course["id"], page=1).pack(),
                        style=ButtonStyle.PRIMARY,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📚 Ro'yxat",
                        callback_data=AdminCoursePageCallback(page=1).pack(),
                        style=ButtonStyle.SUCCESS,
                    )
                ],
            ]
        ),
    )


@router.callback_query(AdminCourseActionCallback.filter(F.action == "toggle"), IsBotAdminFilter(ADMINS))
async def admin_course_toggle(call: types.CallbackQuery, callback_data: AdminCourseActionCallback):
    course = await db.select_course(callback_data.course_id)
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return
    await db.set_course_active(course_id=course["id"], is_active=not course["is_active"])
    await render_admin_course_detail(call, course_id=course["id"])


@router.callback_query(AdminCourseActionCallback.filter(F.action == "toggle_show_price"), IsBotAdminFilter(ADMINS))
async def admin_course_toggle_show_price(call: types.CallbackQuery, callback_data: AdminCourseActionCallback):
    course = await db.select_course(callback_data.course_id)
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return
    await db.update_course_field(course_id=course["id"], field_name="show_price", value=not course["show_price"])
    await render_admin_course_detail(call, course_id=course["id"])


@router.callback_query(AdminCourseActionCallback.filter(F.action == "toggle_free_btn"), IsBotAdminFilter(ADMINS))
async def admin_course_toggle_free_btn(call: types.CallbackQuery, callback_data: AdminCourseActionCallback):
    course = await db.select_course(callback_data.course_id)
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return
    new_val = not course["show_free_button"]
    await db.update_course_field(course_id=course["id"], field_name="show_free_button", value=new_val)
    await render_admin_course_detail(call, course_id=course["id"])


@router.callback_query(AdminCourseActionCallback.filter(F.action == "toggle_paid_btn"), IsBotAdminFilter(ADMINS))
async def admin_course_toggle_paid_btn(call: types.CallbackQuery, callback_data: AdminCourseActionCallback):
    course = await db.select_course(callback_data.course_id)
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return
    new_val = not course["show_paid_button"]
    await db.update_course_field(course_id=course["id"], field_name="show_paid_button", value=new_val)
    await render_admin_course_detail(call, course_id=course["id"])


@router.callback_query(AdminCourseActionCallback.filter(F.action == "delete_ask"), IsBotAdminFilter(ADMINS))
async def admin_course_delete_ask(call: types.CallbackQuery, callback_data: AdminCourseActionCallback):
    course = await db.select_course(callback_data.course_id)
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return
    await call.answer()
    await call.message.answer(
        f"🗑 <b>{html.quote(course['name'])}</b> kursini o'chirishni tasdiqlaysizmi?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Ha, o'chirish",
                        callback_data=AdminCourseActionCallback(action="delete_do", course_id=course["id"]).pack(),
                        style=ButtonStyle.DANGER,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="❌ Bekor qilish",
                        callback_data=AdminCourseViewCallback(course_id=course["id"], page=1).pack(),
                        style=ButtonStyle.PRIMARY,
                    )
                ],
            ]
        ),
    )


@router.callback_query(AdminCourseActionCallback.filter(F.action == "delete_do"), IsBotAdminFilter(ADMINS))
async def admin_course_delete_do(call: types.CallbackQuery, callback_data: AdminCourseActionCallback):
    await db.delete_course(callback_data.course_id)
    await call.answer("Kurs o'chirildi.")
    await render_admin_courses_list(call, page=1, answer=False)


@router.callback_query(AdminCourseEditCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_course_edit_start(
    call: types.CallbackQuery,
    callback_data: AdminCourseEditCallback,
    state: FSMContext,
):
    course = await db.select_course(callback_data.course_id)
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return
    if callback_data.field == "is_active":
        await state.clear()
        await db.set_course_active(course_id=course["id"], is_active=not course["is_active"])
        await render_admin_course_detail(call, course_id=course["id"])
        return

    field_titles = {
        "name": "yangi kurs nomini",
        "price": "yangi narxni",
        "video_count": "yangi video sonini",
        "author": "yangi muallifni",
        "duration": "yangi davomiylikni",
        "target_exam": "yangi imtihon yo'nalishlarini",
        "includes": "yangi qo'shimcha tarkibni",
        "access_type": "yangi kirish turini",
        "sort_order": "yangi sort tartibini",
        "description": "yangi tavsifni",
        "thumbnail": "yangi rasmni",
        "video_file_id": "yangi taqdimot videosini",
        "telegram_link": "yangi pullik guruh/linkni",
        "free_telegram_link": "yangi bepul kanal linkini",
    }
    await call.answer()
    await state.clear()
    await state.update_data(course_id=course["id"], field=callback_data.field)
    await state.set_state(CourseAdminState.edit_value)

    if callback_data.field == "thumbnail":
        await call.message.answer("🖼 Yangi rasm yuboring. Rasmni o'chirish uchun <code>remove</code> yozing.")
        return
    if callback_data.field == "video_file_id":
        await call.message.answer("🎬 Yangi video yuboring. Videoni o'chirish uchun <code>remove</code> yozing.")
        return
    if callback_data.field in {"duration", "target_exam", "includes", "telegram_link", "free_telegram_link"}:
        await call.message.answer(
            f"✏️ {field_titles.get(callback_data.field, 'yangi qiymatni')} kiriting.\n"
            "Maydonni tozalash uchun <code>remove</code> yozing."
        )
        return
    await call.message.answer(f"✏️ {field_titles.get(callback_data.field, 'yangi qiymatni')} kiriting:")


@router.message(CourseAdminState.edit_value, IsBotAdminFilter(ADMINS))
async def admin_course_edit_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    course_id = data["course_id"]
    field = data["field"]

    if field == "thumbnail":
        if message.photo:
            value = message.photo[-1].file_id
        elif (message.text or "").strip().lower() == "remove":
            value = None
        else:
            await message.answer("Rasm yuboring yoki <code>remove</code> yozing.")
            return
    elif field == "video_file_id":
        if message.video:
            value = message.video.file_id
        elif (message.text or "").strip().lower() == "remove":
            value = None
        else:
            await message.answer("Video yuboring yoki <code>remove</code> yozing.")
            return
    elif field == "is_active":
        value = parse_visibility(message.text or "")
        if value is None:
            await message.answer("Holat uchun <code>ha</code> yoki <code>yo'q</code> yozing.")
            return
    elif field in {"price", "video_count", "sort_order"}:
        value = parse_positive_int(message.text or "")
        if value is None:
            await message.answer("Bu maydon faqat raqam qabul qiladi.")
            return
    elif field in {"duration", "target_exam", "includes", "telegram_link", "free_telegram_link"}:
        value = nullable_course_text(message.text or "")
        if value and field == "duration" and len(value) > 100:
            await message.answer("Davomiylik 100 belgidan oshmasin.")
            return
        if value and field == "target_exam" and len(value) > 200:
            await message.answer("Imtihon matni 200 belgidan oshmasin.")
            return
        if value and field in {"telegram_link", "free_telegram_link"} and len(value) > 500:
            await message.answer("Link 500 belgidan oshmasin.")
            return
    else:
        value = (message.text or "").strip()
        if not value:
            await message.answer("Bo'sh qiymat qabul qilinmaydi.")
            return
        if field == "name" and not 3 <= len(value) <= 200:
            await message.answer("Kurs nomi 3-200 belgi oralig'ida bo'lishi kerak.")
            return
        if field == "description" and len(value) < 10:
            await message.answer("Tavsif kamida 10 belgi bo'lishi kerak.")
            return
        if field == "author" and len(value) > 200:
            await message.answer("Muallif 200 belgidan oshmasin.")
            return
        if field == "access_type" and len(value) > 100:
            await message.answer("Kirish turi 100 belgidan oshmasin.")
            return

    if field == "is_active":
        course = await db.set_course_active(course_id=course_id, is_active=value)
    else:
        course = await db.update_course_field(course_id=course_id, field_name=field, value=value)
    await state.clear()
    await message.answer(
        f"✅ Yangilandi: <b>{html.quote(course['name'])}</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📘 Kursni ko'rish",
                        callback_data=AdminCourseViewCallback(course_id=course["id"], page=1).pack(),
                        style=ButtonStyle.PRIMARY,
                    )
                ]
            ]
        ),
    )


@router.message(Command('allusers'), IsBotAdminFilter(ADMINS))
async def get_all_users(message: types.Message):
    users = await db.select_all_users()
    mapped_rows = [
        (
            user["id"],
            user["full_name"],
            user["username"],
            user["telegram_id"],
            user["phone"],
            user["is_registered"],
            user["is_blocked"],
            user["created_at"],
        )
        for user in users
    ]

    file_path = "data/users_list.xlsx"
    await export_to_excel(
        data=mapped_rows,
        headings=['ID', 'Full Name', 'Username', 'Telegram ID', 'Phone', 'Registered', 'Blocked', 'Created At'],
        filepath=file_path,
    )

    await message.answer_document(FSInputFile(file_path))


@router.message(Command('ads_send'), IsBotAdminFilter(ADMINS))
async def ask_ad_content(message: types.Message, state: FSMContext):
    await message.answer("Reklama uchun post yuboring")
    await state.set_state(AdminState.ask_ad_content)


@router.message(AdminState.ask_ad_content, IsBotAdminFilter(ADMINS))
async def send_ad_to_users(message: types.Message, state: FSMContext):
    users = await db.select_all_users()
    count = 0
    for user in users:
        user_id = user["telegram_id"]
        try:
            await message.send_copy(chat_id=user_id)
            count += 1
            await asyncio.sleep(0.05)
        except Exception as error:
            logging.info(f"Ad did not send to user: {user_id}. Error: {error}")
    await message.answer(text=f"Reklama {count} ta foydalanuvchiga muvaffaqiyatli yuborildi.")
    await state.clear()


@router.message(Command('cleandb'), IsBotAdminFilter(ADMINS))
async def ask_are_you_sure(message: types.Message, state: FSMContext):
    msg = await message.reply("Haqiqatdan ham bazani tozalab yubormoqchimisiz?", reply_markup=are_you_sure_markup)
    await state.update_data(msg_id=msg.message_id)
    await state.set_state(AdminState.are_you_sure)


@router.callback_query(AdminState.are_you_sure, IsBotAdminFilter(ADMINS))
async def clean_db(call: types.CallbackQuery, state: FSMContext):
    await call.answer("⏳ Bajarilmoqda...")
    data = await state.get_data()
    msg_id = data.get('msg_id')
    text = "Bekor qilindi."
    if call.data == 'yes':
        await db.delete_users()
        text = "Baza tozalandi!"
    await bot.edit_message_text(text=text, chat_id=call.message.chat.id, message_id=msg_id)
    await state.clear()


# ─── BROADCAST (Xabar yuborish) ──────────────────────────────────────────────

BROADCAST_COURSES_PER_PAGE = 8

MSG_TYPE_LABELS = {
    "text":        "📝 Faqat matn",
    "photo":       "🖼 Rasm + izoh",
    "video":       "🎬 Video + izoh",
    "photo_video": "🖼+🎬 Rasm + Video",
    "group_photo": "📸 Guruhli rasm",
    "group_video": "🎥 Guruhli video",
    "group_mixed": "📸+🎥 Aralash guruh",
}


def broadcast_type_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=label,
            callback_data=AdminBroadcastTypeCallback(msg_type=key).pack(),
            style=ButtonStyle.PRIMARY,
        )]
        for key, label in MSG_TYPE_LABELS.items()
    ]
    rows.append([InlineKeyboardButton(
        text="↩️ Admin panel",
        callback_data=AdminMenuCallback(section="main").pack(),
        style=ButtonStyle.PRIMARY,
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def audience_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="👥 Barcha foydalanuvchilarga",
            callback_data=AdminBroadcastAudienceCallback(action="all").pack(),
            style=ButtonStyle.PRIMARY,
        )],
        [InlineKeyboardButton(
            text="📚 Aniq bir kurs xaridorlariga",
            callback_data=AdminBroadcastAudienceCallback(action="course_page", page=1).pack(),
            style=ButtonStyle.PRIMARY,
        )],
        [InlineKeyboardButton(
            text="🛒 Barcha kurs xaridorlariga",
            callback_data=AdminBroadcastAudienceCallback(action="buyers").pack(),
            style=ButtonStyle.PRIMARY,
        )],
        [InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data=AdminBroadcastCallback(action="cancel").pack(),
            style=ButtonStyle.DANGER,
        )],
    ])


def skip_caption_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⏭️ Izoħsiz davom etish",
            callback_data="br_skip_caption",
            style=ButtonStyle.PRIMARY,
        )],
        [InlineKeyboardButton(
            text="❌ Bekor qilish",
            callback_data=AdminBroadcastCallback(action="cancel").pack(),
            style=ButtonStyle.DANGER,
        )],
    ])


def group_collect_keyboard(count: int) -> InlineKeyboardMarkup:
    rows = []
    if count >= 2:
        rows.append([InlineKeyboardButton(
            text=f"✅ Tayyor ({count} ta)",
            callback_data="br_group_done",
            style=ButtonStyle.SUCCESS,
        )])
    rows.append([InlineKeyboardButton(
        text="❌ Bekor qilish",
        callback_data=AdminBroadcastCallback(action="cancel").pack(),
        style=ButtonStyle.DANGER,
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_status(chat_id: int, msg_id: int, text: str, markup=None) -> None:
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=text, reply_markup=markup
        )
    except TelegramBadRequest:
        pass


async def _show_audience(chat_id: int, msg_id: int, msg_type: str) -> None:
    label = MSG_TYPE_LABELS.get(msg_type, msg_type)
    await _edit_status(
        chat_id, msg_id,
        f"✅ <b>Kontent tayyor</b>\nTur: {label}\n\nKimga yuboramiz?",
        markup=audience_keyboard(),
    )


async def do_send_broadcast(msg_data: dict, chat_id: int) -> None:
    msg_type = msg_data["msg_type"]
    caption = msg_data.get("caption") or None

    if msg_type == "text":
        await bot.send_message(chat_id, msg_data["text_content"])
    elif msg_type == "photo":
        await bot.send_photo(chat_id, msg_data["photo_id"], caption=caption)
    elif msg_type == "video":
        await bot.send_video(chat_id, msg_data["video_id"], caption=caption)
    elif msg_type == "photo_video":
        await bot.send_media_group(chat_id, [
            InputMediaPhoto(media=msg_data["photo_id"], caption=caption),
            InputMediaVideo(media=msg_data["video_id"]),
        ])
    elif msg_type in ("group_photo", "group_video", "group_mixed"):
        items = msg_data.get("group_items", [])
        media = []
        for i, item in enumerate(items):
            cap = caption if i == 0 else None
            if item["type"] == "photo":
                media.append(InputMediaPhoto(media=item["file_id"], caption=cap))
            else:
                media.append(InputMediaVideo(media=item["file_id"], caption=cap))
        if media:
            await bot.send_media_group(chat_id, media)


async def run_broadcast_loop(
    status_chat_id: int,
    status_msg_id: int,
    users: list,
    msg_data: dict,
    label: str,
) -> None:
    total = len(users)
    count = 0
    failed = 0
    last_edit = time.monotonic()

    for i, user in enumerate(users):
        try:
            await do_send_broadcast(msg_data, user["telegram_id"])
            count += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await do_send_broadcast(msg_data, user["telegram_id"])
                count += 1
            except Exception:
                failed += 1
        except Exception as err:
            failed += 1
            logger.info(f"Broadcast [{user['telegram_id']}]: {err}")

        await asyncio.sleep(0.034)

        now = time.monotonic()
        if (i + 1) % 20 == 0 or now - last_edit >= 3.0:
            filled = (count * 10) // max(total, 1)
            bar = "█" * filled + "░" * (10 - filled)
            try:
                await bot.edit_message_text(
                    chat_id=status_chat_id,
                    message_id=status_msg_id,
                    text=(
                        f"⏳ <b>Yuborilmoqda...</b>\n\n"
                        f"Guruh: {label}\n"
                        f"[{bar}] {count}/{total}"
                        + (f"\n❌ Xato: {failed}" if failed else "")
                    ),
                )
                last_edit = now
            except TelegramBadRequest:
                pass

    try:
        await bot.edit_message_text(
            chat_id=status_chat_id,
            message_id=status_msg_id,
            text=(
                f"{'✅' if not failed else '⚠️'} <b>Xabar yuborildi</b>\n\n"
                f"Guruh: {label}\n"
                f"✅ Muvaffaqiyatli: <b>{count}</b>\n"
                f"❌ Yuborilmadi: <b>{failed}</b>"
            ),
        )
    except TelegramBadRequest:
        pass


@router.callback_query(AdminMenuCallback.filter(F.section == "broadcast"), IsBotAdminFilter(ADMINS))
async def admin_broadcast_menu(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    text = "📢 <b>XABAR YUBORISH</b>\n\nXabar turini tanlang:"
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=broadcast_type_keyboard())
        return
    await call.message.edit_text(text, reply_markup=broadcast_type_keyboard())


@router.callback_query(AdminBroadcastCallback.filter(F.action == "menu"), IsBotAdminFilter(ADMINS))
async def admin_broadcast_back_to_type_menu(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    text = "📢 <b>XABAR YUBORISH</b>\n\nXabar turini tanlang:"
    try:
        await call.message.edit_text(text, reply_markup=broadcast_type_keyboard())
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=broadcast_type_keyboard())


@router.callback_query(AdminBroadcastTypeCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_broadcast_type_selected(
    call: types.CallbackQuery,
    callback_data: AdminBroadcastTypeCallback,
    state: FSMContext,
):
    await call.answer()
    msg_type = callback_data.msg_type
    label = MSG_TYPE_LABELS[msg_type]

    await state.clear()
    await state.update_data(
        msg_type=msg_type,
        status_chat_id=call.message.chat.id,
        status_msg_id=call.message.message_id,
    )

    if msg_type == "text":
        await _edit_status(
            call.message.chat.id, call.message.message_id,
            f"📢 <b>Xabar yuborish</b>\nTur: {label}\n\nXabar matnini yuboring:",
        )
        await state.set_state(AdminBroadcastState.collect_text)

    elif msg_type == "photo":
        await _edit_status(
            call.message.chat.id, call.message.message_id,
            f"📢 <b>Xabar yuborish</b>\nTur: {label}\n\nRasmni yuboring:",
        )
        await state.set_state(AdminBroadcastState.collect_photo)

    elif msg_type == "video":
        await _edit_status(
            call.message.chat.id, call.message.message_id,
            f"📢 <b>Xabar yuborish</b>\nTur: {label}\n\nVideoni yuboring:",
        )
        await state.set_state(AdminBroadcastState.collect_video)

    elif msg_type == "photo_video":
        await _edit_status(
            call.message.chat.id, call.message.message_id,
            f"📢 <b>Xabar yuborish</b>\nTur: {label}\n\n1-qadam: Rasmni yuboring:",
        )
        await state.set_state(AdminBroadcastState.collect_photo)

    elif msg_type in ("group_photo", "group_video", "group_mixed"):
        type_hint = {"group_photo": "Rasm", "group_video": "Video", "group_mixed": "Rasm yoki video"}[msg_type]
        await state.update_data(group_items=[])
        await _edit_status(
            call.message.chat.id, call.message.message_id,
            f"📢 <b>Xabar yuborish</b>\nTur: {label}\n\n"
            f"{type_hint}larni yuboring (2–10 ta).\n"
            "Tugatish uchun <b>Tayyor</b> tugmasini bosing:",
            markup=group_collect_keyboard(0),
        )
        await state.set_state(AdminBroadcastState.collect_group)


# ── content collection ────────────────────────────────────────────────────────

@router.message(AdminBroadcastState.collect_text, F.text, IsBotAdminFilter(ADMINS))
async def admin_collect_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(text_content=message.text)
    await _show_audience(data["status_chat_id"], data["status_msg_id"], data["msg_type"])


@router.message(AdminBroadcastState.collect_photo, F.photo, IsBotAdminFilter(ADMINS))
async def admin_collect_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(photo_id=message.photo[-1].file_id)
    msg_type = data.get("msg_type")

    if msg_type == "photo_video":
        await _edit_status(
            data["status_chat_id"], data["status_msg_id"],
            "📢 <b>Xabar yuborish</b>\n🖼 Rasm ✅\n\n2-qadam: Videoni yuboring:",
        )
        await state.set_state(AdminBroadcastState.collect_video_after_photo)
    else:
        await _edit_status(
            data["status_chat_id"], data["status_msg_id"],
            "📢 <b>Xabar yuborish</b>\n🖼 Rasm ✅\n\nIzoh yozing (ixtiyoriy):",
            markup=skip_caption_keyboard(),
        )
        await state.set_state(AdminBroadcastState.collect_caption)


@router.message(AdminBroadcastState.collect_photo, ~F.photo, IsBotAdminFilter(ADMINS))
async def admin_collect_photo_invalid(message: types.Message):
    await message.answer("❗ Iltimos, rasm yuboring.")


@router.message(AdminBroadcastState.collect_video, F.video, IsBotAdminFilter(ADMINS))
async def admin_collect_video_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(video_id=message.video.file_id)
    await _edit_status(
        data["status_chat_id"], data["status_msg_id"],
        "📢 <b>Xabar yuborish</b>\n🎬 Video ✅\n\nIzoh yozing (ixtiyoriy):",
        markup=skip_caption_keyboard(),
    )
    await state.set_state(AdminBroadcastState.collect_caption)


@router.message(AdminBroadcastState.collect_video, ~F.video, IsBotAdminFilter(ADMINS))
async def admin_collect_video_invalid(message: types.Message):
    await message.answer("❗ Iltimos, video yuboring.")


@router.message(AdminBroadcastState.collect_video_after_photo, F.video, IsBotAdminFilter(ADMINS))
async def admin_collect_video_after_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(video_id=message.video.file_id)
    await _edit_status(
        data["status_chat_id"], data["status_msg_id"],
        "📢 <b>Xabar yuborish</b>\n🖼 Rasm ✅\n🎬 Video ✅\n\nIzoh yozing (ixtiyoriy):",
        markup=skip_caption_keyboard(),
    )
    await state.set_state(AdminBroadcastState.collect_caption)


@router.message(AdminBroadcastState.collect_video_after_photo, ~F.video, IsBotAdminFilter(ADMINS))
async def admin_collect_video_after_photo_invalid(message: types.Message):
    await message.answer("❗ Iltimos, video yuboring.")


@router.message(AdminBroadcastState.collect_caption, F.text, IsBotAdminFilter(ADMINS))
async def admin_collect_caption_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(caption=message.text)
    await _show_audience(data["status_chat_id"], data["status_msg_id"], data["msg_type"])


@router.callback_query(
    F.data == "br_skip_caption",
    StateFilter(AdminBroadcastState.collect_caption),
    IsBotAdminFilter(ADMINS),
)
async def admin_skip_caption(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    await state.update_data(caption=None)
    await _show_audience(data["status_chat_id"], data["status_msg_id"], data["msg_type"])


@router.message(AdminBroadcastState.collect_group, IsBotAdminFilter(ADMINS))
async def admin_collect_group_item(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg_type = data.get("msg_type")
    group_items: list = list(data.get("group_items", []))
    MAX_ITEMS = 10

    if len(group_items) >= MAX_ITEMS:
        await message.answer(f"❗ Maksimal {MAX_ITEMS} ta element yuklash mumkin.")
        return

    if msg_type == "group_photo":
        if not message.photo:
            await message.answer("❗ Faqat rasm yuboring.")
            return
        group_items.append({"type": "photo", "file_id": message.photo[-1].file_id})
    elif msg_type == "group_video":
        if not message.video:
            await message.answer("❗ Faqat video yuboring.")
            return
        group_items.append({"type": "video", "file_id": message.video.file_id})
    elif msg_type == "group_mixed":
        if message.photo:
            group_items.append({"type": "photo", "file_id": message.photo[-1].file_id})
        elif message.video:
            group_items.append({"type": "video", "file_id": message.video.file_id})
        else:
            await message.answer("❗ Rasm yoki video yuboring.")
            return

    await state.update_data(group_items=group_items)
    count = len(group_items)
    label = MSG_TYPE_LABELS.get(msg_type, msg_type)
    type_hint = {"group_photo": "rasm", "group_video": "video", "group_mixed": "element"}[msg_type]
    extra = "Tugatish uchun <b>Tayyor</b> tugmasini bosing:" if count < MAX_ITEMS else "Limit to'ldi:"

    await _edit_status(
        data["status_chat_id"], data["status_msg_id"],
        f"📢 <b>Xabar yuborish</b>\nTur: {label}\n\n"
        f"✅ Qabul qilindi: {count}/{MAX_ITEMS} ta {type_hint}\n{extra}",
        markup=group_collect_keyboard(count),
    )

    if count >= MAX_ITEMS:
        await state.set_state(AdminBroadcastState.collect_caption)
        await _edit_status(
            data["status_chat_id"], data["status_msg_id"],
            f"📢 <b>Xabar yuborish</b>\nTur: {label}\n✅ {count} ta element\n\nIzoh yozing (ixtiyoriy):",
            markup=skip_caption_keyboard(),
        )


@router.callback_query(
    F.data == "br_group_done",
    StateFilter(AdminBroadcastState.collect_group),
    IsBotAdminFilter(ADMINS),
)
async def admin_group_done(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    group_items = data.get("group_items", [])
    if len(group_items) < 2:
        await call.answer("Kamida 2 ta element kerak!", show_alert=True)
        return
    await call.answer()
    msg_type = data.get("msg_type")
    label = MSG_TYPE_LABELS.get(msg_type, msg_type)
    await state.set_state(AdminBroadcastState.collect_caption)
    await _edit_status(
        data["status_chat_id"], data["status_msg_id"],
        f"📢 <b>Xabar yuborish</b>\nTur: {label}\n✅ {len(group_items)} ta element\n\nIzoh yozing (ixtiyoriy):",
        markup=skip_caption_keyboard(),
    )


# ── audience selection & broadcast ────────────────────────────────────────────

async def _broadcast_course_list_keyboard(page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(ceil(total / BROADCAST_COURSES_PER_PAGE), 1)
    offset = (page - 1) * BROADCAST_COURSES_PER_PAGE
    courses = await db.select_courses_page(limit=BROADCAST_COURSES_PER_PAGE, offset=offset)
    rows: list[list[InlineKeyboardButton]] = []
    for course in courses:
        rows.append([InlineKeyboardButton(
            text=f"{'✅' if course['is_active'] else '🚫'} {course['name']}",
            callback_data=AdminBroadcastPickCallback(course_id=course["id"], page=page).pack(),
            style=ButtonStyle.PRIMARY,
        )])
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(
            text="⬅️",
            callback_data=AdminBroadcastAudienceCallback(action="course_page", page=page - 1).pack(),
            style=ButtonStyle.PRIMARY,
        ))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(
            text="➡️",
            callback_data=AdminBroadcastAudienceCallback(action="course_page", page=page + 1).pack(),
            style=ButtonStyle.PRIMARY,
        ))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(
        text="↩️ Orqaga",
        callback_data="br_back_to_audience",
        style=ButtonStyle.PRIMARY,
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "br_back_to_audience", IsBotAdminFilter(ADMINS))
async def admin_broadcast_back_to_audience(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    await _show_audience(
        call.message.chat.id, call.message.message_id,
        data.get("msg_type", "text"),
    )


@router.callback_query(AdminBroadcastAudienceCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_broadcast_audience(
    call: types.CallbackQuery,
    callback_data: AdminBroadcastAudienceCallback,
    state: FSMContext,
):
    data = await state.get_data()
    if not data.get("msg_type"):
        await call.answer("Xabar turi topilmadi. Qaytadan boshlang.", show_alert=True)
        return

    if callback_data.action == "course_page":
        await call.answer()
        total = await db.count_courses()
        page = callback_data.page
        markup = await _broadcast_course_list_keyboard(page=page, total=total)
        total_pages = max(ceil(total / BROADCAST_COURSES_PER_PAGE), 1)
        await _edit_status(
            call.message.chat.id, call.message.message_id,
            f"📚 <b>Kurs tanlang</b> — {page}/{total_pages}\n\nXabar yubormoqchi bo'lgan kurs xaridorlarini tanlang:",
            markup=markup,
        )
        return

    await call.answer()

    if callback_data.action == "all":
        users = await db.select_all_users()
        label = "Barcha foydalanuvchilar"
    else:
        users = await db.select_users_with_any_approved_purchase()
        label = "Barcha kurs xaridorlari"

    msg_data = dict(data)
    await state.clear()

    if not users:
        await _edit_status(
            call.message.chat.id, call.message.message_id,
            f"⚠️ {label} bo'yicha foydalanuvchilar topilmadi.",
        )
        return

    await _edit_status(
        call.message.chat.id, call.message.message_id,
        f"⏳ <b>Yuborilmoqda...</b>\n\nGuruh: {label}\n[░░░░░░░░░░] 0/{len(users)}",
    )
    await run_broadcast_loop(call.message.chat.id, call.message.message_id, users, msg_data, label)


@router.callback_query(AdminBroadcastPickCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_broadcast_course_pick(
    call: types.CallbackQuery,
    callback_data: AdminBroadcastPickCallback,
    state: FSMContext,
):
    data = await state.get_data()
    if not data.get("msg_type"):
        await call.answer("Xabar turi topilmadi. Qaytadan boshlang.", show_alert=True)
        return

    course = await db.select_course(callback_data.course_id)
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return

    await call.answer()
    users = await db.select_users_by_course_approved(course["id"])
    label = f"«{html.quote(course['name'])}» xaridorlari"
    msg_data = dict(data)
    await state.clear()

    if not users:
        await _edit_status(
            call.message.chat.id, call.message.message_id,
            f"⚠️ {label} bo'yicha tasdiqlangan xaridorlar topilmadi.",
        )
        return

    await _edit_status(
        call.message.chat.id, call.message.message_id,
        f"⏳ <b>Yuborilmoqda...</b>\n\nGuruh: {label}\n[░░░░░░░░░░] 0/{len(users)}",
    )
    await run_broadcast_loop(call.message.chat.id, call.message.message_id, users, msg_data, label)


@router.callback_query(AdminBroadcastCallback.filter(F.action == "cancel"), IsBotAdminFilter(ADMINS))
async def admin_broadcast_cancel(call: types.CallbackQuery, state: FSMContext):
    await call.answer("Bekor qilindi.")
    await state.clear()
    try:
        await call.message.edit_text(
            "❌ Xabar yuborish bekor qilindi.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ Admin panel",
                    callback_data=AdminMenuCallback(section="main").pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ]]),
        )
    except TelegramBadRequest:
        pass


# ─── EXCEL EKSPORT ────────────────────────────────────────────────────────────

EXCEL_COURSES_PER_PAGE = 8

BUYER_HEADINGS = [
    "To'liq ism", "Ism", "Familiya", "Username", "Telegram ID", "Telefon",
    "Kurs nomi", "Xarid ID", "To'langan summa", "To'lov turi", "Holat",
    "Tasdiq. sana", "Buyurtma sanasi", "Karta raqami", "Admin izohi",
    "Invite link", "CLICK order ID", "Chek bormi",
]


def format_date_val(value) -> str:
    if not value:
        return "—"
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


def _buyer_row(r: dict) -> tuple:
    return (
        r.get("full_name") or "—",
        r.get("first_name") or "—",
        r.get("last_name") or "—",
        f"@{r['username']}" if r.get("username") else "—",
        r.get("telegram_id"),
        r.get("phone") or "—",
        r.get("course_name") or "—",
        r.get("purchase_id"),
        r.get("amount", 0),
        "Bepul" if r.get("purchase_type") == "free" else "Pullik",
        "Tasdiqlangan",
        format_date_val(r.get("purchase_date")),
        format_date_val(r.get("order_date")),
        r.get("card_number_used") or "—",
        r.get("admin_note") or "—",
        r.get("invite_link") or "—",
        r.get("click_order_id") or "—",
        r.get("has_receipt", "Yo'q"),
    )


def excel_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="👥 Barcha foydalanuvchilar",
            callback_data=AdminExportCallback(action="all").pack(),
            style=ButtonStyle.PRIMARY,
        )],
        [InlineKeyboardButton(
            text="📚 Aniq bir kurs xaridorlari",
            callback_data=AdminExportCallback(action="course_page", page=1).pack(),
            style=ButtonStyle.PRIMARY,
        )],
        [InlineKeyboardButton(
            text="🛒 Barcha kurs xaridorlari",
            callback_data=AdminExportCallback(action="buyers").pack(),
            style=ButtonStyle.PRIMARY,
        )],
        [InlineKeyboardButton(
            text="↩️ Admin panel",
            callback_data=AdminMenuCallback(section="main").pack(),
            style=ButtonStyle.PRIMARY,
        )],
    ])


async def excel_course_list_keyboard(page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(ceil(total / EXCEL_COURSES_PER_PAGE), 1)
    offset = (page - 1) * EXCEL_COURSES_PER_PAGE
    courses = await db.select_courses_page(limit=EXCEL_COURSES_PER_PAGE, offset=offset)
    rows: list[list[InlineKeyboardButton]] = []
    for course in courses:
        rows.append([InlineKeyboardButton(
            text=f"{'✅' if course['is_active'] else '🚫'} {course['name']}",
            callback_data=AdminExportPickCallback(course_id=course["id"]).pack(),
            style=ButtonStyle.PRIMARY,
        )])
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(
            text="⬅️",
            callback_data=AdminExportCallback(action="course_page", page=page - 1).pack(),
            style=ButtonStyle.PRIMARY,
        ))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(
            text="➡️",
            callback_data=AdminExportCallback(action="course_page", page=page + 1).pack(),
            style=ButtonStyle.PRIMARY,
        ))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton(
        text="↩️ Orqaga",
        callback_data=AdminMenuCallback(section="excel").pack(),
        style=ButtonStyle.PRIMARY,
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(AdminMenuCallback.filter(F.section == "excel"), IsBotAdminFilter(ADMINS))
async def admin_excel_menu(call: types.CallbackQuery):
    await call.answer()
    text = "📊 <b>EXCEL EKSPORT</b>\n\nQaysi ma'lumotlarni eksport qilish kerak?"
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=excel_menu_keyboard())
        return
    await call.message.edit_text(text, reply_markup=excel_menu_keyboard())


@router.callback_query(AdminExportCallback.filter(F.action == "all"), IsBotAdminFilter(ADMINS))
async def admin_export_all(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_text(
            "📊 <b>Excel eksport</b>\n\n⏳ Tayyorlanmoqda...",
            reply_markup=None,
        )
    except TelegramBadRequest:
        pass
    users = await db.select_all_users()
    rows = [
        (
            u["id"],
            u["full_name"] or "—",
            u["first_name"] or "—",
            u["last_name"] or "—",
            f"@{u['username']}" if u.get("username") else "—",
            u["telegram_id"],
            u["phone"] or "—",
            "Ha" if u["is_registered"] else "Yo'q",
            format_date_val(u["created_at"]),
        )
        for u in users
    ]
    file_path = "data/export_all_users.xlsx"
    await export_to_excel(
        data=rows,
        headings=["ID", "To'liq ism", "Ism", "Familiya", "Username", "Telegram ID", "Telefon",
                  "Ro'yxatdan o'tgan", "Sana"],
        filepath=file_path,
    )
    try:
        await call.message.edit_text(
            f"✅ <b>Tayyor</b>\n\n👥 Barcha foydalanuvchilar — <b>{len(rows)} ta</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ Excel menyu",
                    callback_data=AdminMenuCallback(section="excel").pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ]]),
        )
    except TelegramBadRequest:
        pass
    await call.message.answer_document(
        FSInputFile(file_path),
        caption=f"👥 Barcha foydalanuvchilar — {len(rows)} ta",
    )


@router.callback_query(AdminExportCallback.filter(F.action == "buyers"), IsBotAdminFilter(ADMINS))
async def admin_export_buyers(call: types.CallbackQuery):
    await call.answer()
    try:
        await call.message.edit_text(
            "📊 <b>Excel eksport</b>\n\n⏳ Tayyorlanmoqda...",
            reply_markup=None,
        )
    except TelegramBadRequest:
        pass
    data = await db.select_all_buyers_export()
    rows = [_buyer_row(r) for r in data]
    file_path = "data/export_all_buyers.xlsx"
    await export_to_excel(data=rows, headings=BUYER_HEADINGS, filepath=file_path)
    try:
        await call.message.edit_text(
            f"✅ <b>Tayyor</b>\n\n🛒 Barcha kurs xaridorlari — <b>{len(rows)} ta yozuv</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ Excel menyu",
                    callback_data=AdminMenuCallback(section="excel").pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ]]),
        )
    except TelegramBadRequest:
        pass
    await call.message.answer_document(
        FSInputFile(file_path),
        caption=f"🛒 Barcha kurs xaridorlari — {len(rows)} ta yozuv",
    )


@router.callback_query(AdminExportCallback.filter(F.action == "course_page"), IsBotAdminFilter(ADMINS))
async def admin_export_course_page(call: types.CallbackQuery, callback_data: AdminExportCallback):
    await call.answer()
    total = await db.count_courses()
    page = callback_data.page
    markup = await excel_course_list_keyboard(page=page, total=total)
    total_pages = max(ceil(total / EXCEL_COURSES_PER_PAGE), 1)
    text = (
        f"📚 <b>Kurs tanlang</b> — Sahifa {page}/{total_pages}\n\n"
        "Excel eksport qilmoqchi bo'lgan kursni tanlang:"
    )
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


@router.callback_query(AdminExportPickCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_export_course_selected(call: types.CallbackQuery, callback_data: AdminExportPickCallback):
    course = await db.select_course(callback_data.course_id)
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return
    await call.answer()
    try:
        await call.message.edit_text(
            f"📊 <b>Excel eksport</b>\n📚 {html.quote(course['name'])}\n\n⏳ Tayyorlanmoqda...",
            reply_markup=None,
        )
    except TelegramBadRequest:
        pass
    data = await db.select_course_purchase_export(callback_data.course_id)
    rows = [_buyer_row(r) for r in data]
    file_path = f"data/export_course_{callback_data.course_id}.xlsx"
    await export_to_excel(data=rows, headings=BUYER_HEADINGS, filepath=file_path)
    try:
        await call.message.edit_text(
            f"✅ <b>Tayyor</b>\n\n📚 {html.quote(course['name'])} — <b>{len(rows)} ta xaridor</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="↩️ Excel menyu",
                    callback_data=AdminMenuCallback(section="excel").pack(),
                    style=ButtonStyle.PRIMARY,
                )
            ]]),
        )
    except TelegramBadRequest:
        pass
    await call.message.answer_document(
        FSInputFile(file_path),
        caption=f"📚 <b>{html.quote(course['name'])}</b> xaridorlari — {len(rows)} ta",
    )


# ── COURSE INSTALLMENT TOGGLE ─────────────────────────────────────────────────

@router.callback_query(AdminCourseInstallmentCallback.filter(), IsBotAdminFilter(ADMINS))
async def toggle_course_installment(
    call: types.CallbackQuery, callback_data: AdminCourseInstallmentCallback
):
    course = await db.set_course_installment(
        callback_data.course_id,
        not (await db.select_course(callback_data.course_id) or {}).get("installment_available", False),
    )
    if not course:
        await call.answer("Kurs topilmadi.", show_alert=True)
        return
    status = "✅ yoqildi" if course["installment_available"] else "🚫 o'chirildi"
    await call.answer(f"Bo'lib to'lash {status}.")
    text = admin_course_detail_text(course)
    markup = admin_course_detail_keyboard(course)
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


# ── COUPON MANAGEMENT ─────────────────────────────────────────────────────────

def _coupon_list_text(coupons: list) -> str:
    if not coupons:
        return "🎟 <b>KUPONLAR</b>\n\nHozircha kuponlar yo'q."
    lines = ["🎟 <b>KUPONLAR</b>\n"]
    for c in coupons:
        active = "✅" if c["is_active"] else "🚫"
        if c["discount_percent"]:
            discount_str = f"{c['discount_percent']}%"
        else:
            discount_str = format_price(c["discount_amount"])
        uses = f"{c['uses_count']}/{c['max_uses']}" if c["max_uses"] else str(c["uses_count"])
        lines.append(f"{active} <code>{html.quote(c['code'])}</code> — {discount_str} | {uses} ta ishlatilgan")
    return "\n".join(lines)


def _coupon_list_keyboard(coupons: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for c in coupons:
        active_icon = "✅" if c["is_active"] else "🚫"
        rows.append([
            InlineKeyboardButton(
                text=f"{active_icon} {c['code']}",
                callback_data=AdminCouponCallback(action="view", coupon_id=c["id"]).pack(),
                style=ButtonStyle.PRIMARY,
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="➕ Yangi kupon",
            callback_data=AdminCouponCallback(action="add").pack(),
            style=ButtonStyle.SUCCESS,
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text="↩️ Admin panel",
            callback_data=AdminMenuCallback(section="main").pack(),
            style=ButtonStyle.PRIMARY,
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _coupon_detail_text(c, course_name: str | None = None) -> str:
    active = "✅ Faol" if c["is_active"] else "🚫 Faol emas"
    if c["discount_percent"]:
        discount_str = f"{c['discount_percent']}% chegirma"
    else:
        discount_str = f"{format_price(c['discount_amount'])} chegirma"
    if c["max_uses"]:
        remaining = c["max_uses"] - c["uses_count"]
        limit_status = "⚠️ TUGAGAN" if remaining <= 0 else f"{remaining} ta qoldi"
        uses = f"{c['uses_count']}/{c['max_uses']} ({limit_status})"
    else:
        uses = f"{c['uses_count']} (cheksiz)"
    expires = c["expires_at"].strftime("%d.%m.%Y %H:%M") if c.get("expires_at") else "muddatsiz"
    if c.get("course_id"):
        name_display = html.quote(course_name) if course_name else f"#{c['course_id']}"
        course_line = f"Kurs: <b>{name_display}</b>"
    else:
        course_line = "Kurs: <b>barcha kurslar uchun</b>"
    return (
        f"🎟 <b>KUPON: <code>{html.quote(c['code'])}</code></b>\n\n"
        f"Nomi: <b>{html.quote(c['name'])}</b>\n"
        f"Chegirma: <b>{discount_str}</b>\n"
        f"Holat: <b>{active}</b>\n"
        f"Ishlatilgan: <b>{uses}</b>\n"
        f"Muddat: <b>{expires}</b>\n"
        f"{course_line}"
    )


def _coupon_course_keyboard(courses: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for course in courses:
        rows.append([InlineKeyboardButton(
            text=f"📘 {html.quote(course['name'])}",
            callback_data=AdminCouponCourseCallback(course_id=course["id"]).pack(),
            style=ButtonStyle.PRIMARY,
        )])
    rows.append([InlineKeyboardButton(
        text="🌐 Barcha kurslar uchun",
        callback_data=AdminCouponCourseCallback(course_id=0).pack(),
        style=ButtonStyle.SUCCESS,
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _coupon_detail_keyboard(c) -> InlineKeyboardMarkup:
    cid = c["id"]
    toggle_text = "🚫 O'chirish" if c["is_active"] else "✅ Yoqish"
    toggle_style = ButtonStyle.DANGER if c["is_active"] else ButtonStyle.SUCCESS

    def edit_btn(label: str, field: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=label,
            callback_data=AdminCouponEditCallback(field=field, coupon_id=cid).pack(),
            style=ButtonStyle.PRIMARY,
        )

    return InlineKeyboardMarkup(inline_keyboard=[
        [edit_btn("✏️ Kod", "code"), edit_btn("✏️ Nomi", "name")],
        [edit_btn("💰 Chegirma", "discount"), edit_btn("📊 Limit", "max_uses")],
        [edit_btn("📅 Muddat", "expires"), edit_btn("📚 Kurs", "course")],
        [
            InlineKeyboardButton(
                text=toggle_text,
                callback_data=AdminCouponCallback(action="toggle", coupon_id=cid).pack(),
                style=toggle_style,
            ),
            InlineKeyboardButton(
                text="🗑 O'chirish",
                callback_data=AdminCouponCallback(action="delete", coupon_id=cid).pack(),
                style=ButtonStyle.DANGER,
            ),
        ],
        [
            InlineKeyboardButton(
                text="↩️ Kuponlar",
                callback_data=AdminMenuCallback(section="coupons").pack(),
                style=ButtonStyle.PRIMARY,
            )
        ],
    ])


@router.callback_query(AdminMenuCallback.filter(F.section == "coupons"), IsBotAdminFilter(ADMINS))
async def admin_coupon_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    coupons = await db.list_coupons()
    text = _coupon_list_text(coupons)
    markup = _coupon_list_keyboard(coupons)
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


@router.callback_query(AdminCouponCallback.filter(F.action == "view"), IsBotAdminFilter(ADMINS))
async def admin_coupon_view(call: types.CallbackQuery, callback_data: AdminCouponCallback):
    c = await db.get_coupon(callback_data.coupon_id)
    if not c:
        await call.answer("Kupon topilmadi.", show_alert=True)
        return
    await call.answer()
    course_name = None
    if c.get("course_id"):
        course = await db.select_course(c["course_id"])
        course_name = course["name"] if course else None
    await call.message.edit_text(_coupon_detail_text(c, course_name), reply_markup=_coupon_detail_keyboard(c))


@router.callback_query(AdminCouponCallback.filter(F.action == "toggle"), IsBotAdminFilter(ADMINS))
async def admin_coupon_toggle(call: types.CallbackQuery, callback_data: AdminCouponCallback):
    c = await db.toggle_coupon_active(callback_data.coupon_id)
    if not c:
        await call.answer("Kupon topilmadi.", show_alert=True)
        return
    status = "yoqildi" if c["is_active"] else "o'chirildi"
    await call.answer(f"Kupon {status}.")
    course_name = None
    if c.get("course_id"):
        course = await db.select_course(c["course_id"])
        course_name = course["name"] if course else None
    await call.message.edit_text(_coupon_detail_text(c, course_name), reply_markup=_coupon_detail_keyboard(c))


@router.callback_query(AdminCouponCallback.filter(F.action == "delete"), IsBotAdminFilter(ADMINS))
async def admin_coupon_delete(call: types.CallbackQuery, callback_data: AdminCouponCallback):
    await db.delete_coupon(callback_data.coupon_id)
    await call.answer("Kupon o'chirildi.")
    coupons = await db.list_coupons()
    text = _coupon_list_text(coupons)
    markup = _coupon_list_keyboard(coupons)
    await call.message.edit_text(text, reply_markup=markup)


# ── COUPON EDIT ───────────────────────────────────────────────────────────────

async def _render_coupon(coupon_id: int) -> tuple[str | None, object]:
    c = await db.get_coupon(coupon_id)
    if not c:
        return None, None
    course_name = None
    if c.get("course_id"):
        course = await db.select_course(c["course_id"])
        course_name = course["name"] if course else None
    return _coupon_detail_text(c, course_name), _coupon_detail_keyboard(c)


@router.callback_query(AdminCouponEditCallback.filter(), IsBotAdminFilter(ADMINS))
async def admin_coupon_edit_start(
    call: types.CallbackQuery,
    callback_data: AdminCouponEditCallback,
    state: FSMContext,
):
    await state.clear()
    coupon_id = callback_data.coupon_id
    field = callback_data.field
    c = await db.get_coupon(coupon_id)
    if not c:
        await call.answer("Kupon topilmadi.", show_alert=True)
        return
    await call.answer()
    await state.update_data(editing_coupon_id=coupon_id)

    cancel_markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="❌ Bekor",
            callback_data=AdminCouponCallback(action="view", coupon_id=coupon_id).pack(),
            style=ButtonStyle.DANGER,
        )
    ]])

    if field == "code":
        await state.set_state(AdminCouponState.edit_code)
        await call.message.edit_text(
            f"✏️ <b>Yangi kupon kodi</b>\n\nHozirgi: <code>{html.quote(c['code'])}</code>\n\nYangi kod kiriting:",
            reply_markup=cancel_markup,
        )
    elif field == "name":
        await state.set_state(AdminCouponState.edit_name)
        await call.message.edit_text(
            f"✏️ <b>Yangi nom</b>\n\nHozirgi: <b>{html.quote(c['name'])}</b>\n\nYangi nom kiriting:",
            reply_markup=cancel_markup,
        )
    elif field == "discount":
        await state.set_state(AdminCouponState.edit_discount)
        cur = f"{c['discount_percent']}%" if c["discount_percent"] else format_price(c["discount_amount"])
        await call.message.edit_text(
            f"💰 <b>Yangi chegirma</b>\n\nHozirgi: <b>{cur}</b>\n\n"
            "Foiz uchun: <code>20%</code>\nSo'm uchun: <code>200000</code>",
            reply_markup=cancel_markup,
        )
    elif field == "max_uses":
        await state.set_state(AdminCouponState.edit_max_uses)
        cur = str(c["max_uses"]) if c["max_uses"] else "cheksiz"
        await call.message.edit_text(
            f"📊 <b>Yangi foydalanish limiti</b>\n\nHozirgi: <b>{cur}</b>\n\n"
            "Son kiriting yoki cheksiz uchun: <code>skip</code>",
            reply_markup=cancel_markup,
        )
    elif field == "expires":
        await state.set_state(AdminCouponState.edit_expires)
        cur = c["expires_at"].strftime("%d.%m.%Y") if c.get("expires_at") else "muddatsiz"
        await call.message.edit_text(
            f"📅 <b>Yangi muddat</b>\n\nHozirgi: <b>{cur}</b>\n\n"
            "Sana kiriting: <code>31.12.2025</code>\nMuddatsiz: <code>skip</code>",
            reply_markup=cancel_markup,
        )
    elif field == "course":
        await state.set_state(AdminCouponState.edit_course)
        courses = await db.select_courses_page(limit=50, offset=0)
        await call.message.edit_text(
            "📚 <b>Yangi kurs</b>\n\nQaysi kurs uchun ishlashini tanlang:",
            reply_markup=_coupon_course_keyboard(courses),
        )


@router.message(StateFilter(AdminCouponState.edit_code), IsBotAdminFilter(ADMINS))
async def admin_coupon_edit_code(message: types.Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    if not code or not all(ch.isalnum() or ch in "_-" for ch in code):
        await message.answer("❌ Noto'g'ri format. Faqat lotin harflari, raqamlar, '-' va '_'.")
        return
    data = await state.get_data()
    coupon_id = data["editing_coupon_id"]
    existing = await db.get_coupon_by_code(code)
    if existing and existing["id"] != coupon_id:
        await message.answer(f"❌ <code>{html.quote(code)}</code> kodi allaqachon mavjud.")
        return
    c = await db.get_coupon(coupon_id)
    await db.update_coupon(
        coupon_id=coupon_id, code=code, name=c["name"],
        discount_percent=c["discount_percent"], discount_amount=c["discount_amount"],
        max_uses=c["max_uses"], course_id=c.get("course_id"), expires_at=c.get("expires_at"),
    )
    await state.clear()
    text, markup = await _render_coupon(coupon_id)
    await message.answer(f"✅ Kod yangilandi: <code>{html.quote(code)}</code>")
    await message.answer(text, reply_markup=markup)


@router.message(StateFilter(AdminCouponState.edit_name), IsBotAdminFilter(ADMINS))
async def admin_coupon_edit_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("❌ Nom bo'sh bo'lmasin.")
        return
    data = await state.get_data()
    coupon_id = data["editing_coupon_id"]
    c = await db.get_coupon(coupon_id)
    await db.update_coupon(
        coupon_id=coupon_id, code=c["code"], name=name,
        discount_percent=c["discount_percent"], discount_amount=c["discount_amount"],
        max_uses=c["max_uses"], course_id=c.get("course_id"), expires_at=c.get("expires_at"),
    )
    await state.clear()
    text, markup = await _render_coupon(coupon_id)
    await message.answer(f"✅ Nom yangilandi: <b>{html.quote(name)}</b>")
    await message.answer(text, reply_markup=markup)


@router.message(StateFilter(AdminCouponState.edit_discount), IsBotAdminFilter(ADMINS))
async def admin_coupon_edit_discount(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip()
    discount_percent, discount_amount = 0, 0
    if raw.endswith("%"):
        try:
            val = int(raw[:-1])
            if not 1 <= val <= 99:
                raise ValueError
            discount_percent = val
        except ValueError:
            await message.answer("❌ Foiz 1–99 oralig'ida bo'lishi kerak.")
            return
    else:
        try:
            val = int(raw.replace(" ", "").replace(",", ""))
            if val <= 0:
                raise ValueError
            discount_amount = val
        except ValueError:
            await message.answer("❌ Raqam kiriting. Misol: <code>200000</code> yoki <code>20%</code>")
            return
    data = await state.get_data()
    coupon_id = data["editing_coupon_id"]
    c = await db.get_coupon(coupon_id)
    await db.update_coupon(
        coupon_id=coupon_id, code=c["code"], name=c["name"],
        discount_percent=discount_percent, discount_amount=discount_amount,
        max_uses=c["max_uses"], course_id=c.get("course_id"), expires_at=c.get("expires_at"),
    )
    await state.clear()
    text, markup = await _render_coupon(coupon_id)
    disc_str = f"{discount_percent}%" if discount_percent else format_price(discount_amount)
    await message.answer(f"✅ Chegirma yangilandi: <b>{disc_str}</b>")
    await message.answer(text, reply_markup=markup)


@router.message(StateFilter(AdminCouponState.edit_max_uses), IsBotAdminFilter(ADMINS))
async def admin_coupon_edit_max_uses(message: types.Message, state: FSMContext):
    raw = (message.text or "").strip().lower()
    max_uses = None
    if raw not in SKIP_TEXTS:
        try:
            max_uses = int(raw)
            if max_uses <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Musbat son kiriting yoki <code>skip</code> yozing.")
            return
    data = await state.get_data()
    coupon_id = data["editing_coupon_id"]
    c = await db.get_coupon(coupon_id)
    await db.update_coupon(
        coupon_id=coupon_id, code=c["code"], name=c["name"],
        discount_percent=c["discount_percent"], discount_amount=c["discount_amount"],
        max_uses=max_uses, course_id=c.get("course_id"), expires_at=c.get("expires_at"),
    )
    await state.clear()
    text, markup = await _render_coupon(coupon_id)
    uses_str = str(max_uses) if max_uses else "cheksiz"
    await message.answer(f"✅ Limit yangilandi: <b>{uses_str}</b>")
    await message.answer(text, reply_markup=markup)


@router.message(StateFilter(AdminCouponState.edit_expires), IsBotAdminFilter(ADMINS))
async def admin_coupon_edit_expires(message: types.Message, state: FSMContext):
    from datetime import datetime, timezone
    raw = (message.text or "").strip().lower()
    expires_at = None
    if raw not in SKIP_TEXTS:
        try:
            expires_at = datetime.strptime(raw, "%d.%m.%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            await message.answer("❌ Format noto'g'ri. <code>31.12.2025</code> shaklida yozing yoki <code>skip</code>:")
            return
    data = await state.get_data()
    coupon_id = data["editing_coupon_id"]
    c = await db.get_coupon(coupon_id)
    await db.update_coupon(
        coupon_id=coupon_id, code=c["code"], name=c["name"],
        discount_percent=c["discount_percent"], discount_amount=c["discount_amount"],
        max_uses=c["max_uses"], course_id=c.get("course_id"), expires_at=expires_at,
    )
    await state.clear()
    text, markup = await _render_coupon(coupon_id)
    exp_str = expires_at.strftime("%d.%m.%Y") if expires_at else "muddatsiz"
    await message.answer(f"✅ Muddat yangilandi: <b>{exp_str}</b>")
    await message.answer(text, reply_markup=markup)


@router.callback_query(AdminCouponCourseCallback.filter(), StateFilter(AdminCouponState.edit_course), IsBotAdminFilter(ADMINS))
async def admin_coupon_edit_course(
    call: types.CallbackQuery,
    callback_data: AdminCouponCourseCallback,
    state: FSMContext,
):
    course_id = callback_data.course_id if callback_data.course_id != 0 else None
    data = await state.get_data()
    coupon_id = data["editing_coupon_id"]
    c = await db.get_coupon(coupon_id)
    if not c:
        await call.answer("Kupon topilmadi.", show_alert=True)
        await state.clear()
        return
    await db.update_coupon(
        coupon_id=coupon_id, code=c["code"], name=c["name"],
        discount_percent=c["discount_percent"], discount_amount=c["discount_amount"],
        max_uses=c["max_uses"], course_id=course_id, expires_at=c.get("expires_at"),
    )
    await state.clear()
    text, markup = await _render_coupon(coupon_id)
    await call.answer("✅ Kurs yangilandi!")
    await call.message.edit_text(text, reply_markup=markup)


@router.callback_query(AdminCouponCallback.filter(F.action == "add"), IsBotAdminFilter(ADMINS))
async def admin_coupon_add_start(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await state.set_state(AdminCouponState.enter_code)
    await call.message.edit_text(
        "🎟 <b>YANGI KUPON</b>\n\nKupon kodi kiriting (lotin harflari, raqamlar):\n<i>Misol: IMKON200</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="❌ Bekor",
                callback_data=AdminMenuCallback(section="coupons").pack(),
                style=ButtonStyle.DANGER,
            )
        ]]),
    )


@router.message(StateFilter(AdminCouponState.enter_code), IsBotAdminFilter(ADMINS))
async def admin_coupon_enter_code(message: types.Message, state: FSMContext):
    code = (message.text or "").strip().upper()
    if not code or not all(c.isalnum() or c in "_-" for c in code):
        await message.answer("❌ Noto'g'ri format. Faqat lotin harflari, raqamlar, '-' va '_' ishlatiladi.")
        return
    existing = await db.get_coupon_by_code(code)
    if existing:
        await message.answer(f"❌ <code>{html.quote(code)}</code> kodi allaqachon mavjud. Boshqa kod kiriting:")
        return
    await state.update_data(coup_code=code)
    await state.set_state(AdminCouponState.enter_name)
    await message.answer(f"✅ Kod: <code>{html.quote(code)}</code>\n\nKupon nomini kiriting (ichki eslatma):")


@router.message(StateFilter(AdminCouponState.enter_name), IsBotAdminFilter(ADMINS))
async def admin_coupon_enter_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("❌ Ism bo'sh bo'lmasin.")
        return
    await state.update_data(coup_name=name)
    await state.set_state(AdminCouponState.enter_discount_value)
    await message.answer(
        "💰 Chegirma miqdorini kiriting:\n\n"
        "• Foiz uchun: <code>20%</code>\n"
        "• So'm uchun: <code>200000</code>"
    )


@router.message(StateFilter(AdminCouponState.enter_discount_value), IsBotAdminFilter(ADMINS))
async def admin_coupon_enter_discount(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    discount_percent = 0
    discount_amount = 0
    if text.endswith("%"):
        try:
            val = int(text[:-1])
            if not 1 <= val <= 99:
                raise ValueError
            discount_percent = val
        except ValueError:
            await message.answer("❌ Foiz 1–99 oralig'ida bo'lishi kerak. Qayta kiriting:")
            return
    else:
        try:
            val = int(text.replace(" ", "").replace(",", ""))
            if val <= 0:
                raise ValueError
            discount_amount = val
        except ValueError:
            await message.answer("❌ Raqam kiriting. Misol: <code>200000</code> yoki <code>20%</code>")
            return
    await state.update_data(coup_discount_percent=discount_percent, coup_discount_amount=discount_amount)
    await state.set_state(AdminCouponState.enter_max_uses)
    await message.answer(
        "📊 <b>Foydalanish limiti</b>\n\n"
        "Bu kuponden nechta user foydalana olishini kiriting.\n"
        "Misol: <code>10</code> → 10 ta user ishlatsa, kupon avtomatik yaroqsiz bo'ladi.\n\n"
        "Cheksiz uchun: <code>skip</code>"
    )


@router.message(StateFilter(AdminCouponState.enter_max_uses), IsBotAdminFilter(ADMINS))
async def admin_coupon_enter_max_uses(message: types.Message, state: FSMContext):
    text = (message.text or "").strip().lower()
    max_uses = None
    if text not in SKIP_TEXTS:
        try:
            max_uses = int(text)
            if max_uses <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Musbat son kiriting yoki <code>skip</code> yozing.")
            return
    await state.update_data(coup_max_uses=max_uses)
    await state.set_state(AdminCouponState.enter_expires)
    await message.answer(
        "📅 Muddatini kiriting (KK.OO.YYYY formatida).\n"
        "Muddatsiz: <code>skip</code>\n"
        "Misol: <code>31.12.2025</code>"
    )


@router.message(StateFilter(AdminCouponState.enter_expires), IsBotAdminFilter(ADMINS))
async def admin_coupon_enter_expires(message: types.Message, state: FSMContext):
    from datetime import datetime, timezone
    text = (message.text or "").strip().lower()
    expires_at = None
    if text not in SKIP_TEXTS:
        try:
            expires_at = datetime.strptime(text, "%d.%m.%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            await message.answer("❌ Format noto'g'ri. <code>31.12.2025</code> shaklida yozing yoki <code>skip</code>:")
            return

    await state.update_data(coup_expires_at=expires_at)
    await state.set_state(AdminCouponState.enter_course)

    courses = await db.select_courses_page(limit=50, offset=0)
    await message.answer(
        "📚 <b>Kupon qaysi kurs uchun?</b>\n\nKursni tanlang yoki barcha kurslar uchun belgilang:",
        reply_markup=_coupon_course_keyboard(courses),
    )


@router.callback_query(AdminCouponCourseCallback.filter(), StateFilter(AdminCouponState.enter_course), IsBotAdminFilter(ADMINS))
async def admin_coupon_select_course(call: types.CallbackQuery, callback_data: AdminCouponCourseCallback, state: FSMContext):
    course_id = callback_data.course_id if callback_data.course_id != 0 else None
    data = await state.get_data()
    await state.clear()

    coupon = await db.add_coupon(
        code=data["coup_code"],
        name=data["coup_name"],
        discount_percent=data.get("coup_discount_percent", 0),
        discount_amount=data.get("coup_discount_amount", 0),
        max_uses=data.get("coup_max_uses"),
        course_id=course_id,
        expires_at=data.get("coup_expires_at"),
    )
    if not coupon:
        await call.answer("❌ Kupon yaratishda xatolik.", show_alert=True)
        return

    course_name = None
    if course_id:
        course = await db.select_course(course_id)
        course_name = course["name"] if course else None

    await call.answer("✅ Kupon yaratildi!")
    await call.message.edit_text(
        f"✅ <b>Kupon yaratildi!</b>\n\n{_coupon_detail_text(coupon, course_name)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🎟 Kuponlar ro'yxati",
                callback_data=AdminMenuCallback(section="coupons").pack(),
                style=ButtonStyle.PRIMARY,
            )
        ]]),
    )


# ── INSTALLMENT OVERVIEW ──────────────────────────────────────────────────────

@router.callback_query(AdminMenuCallback.filter(F.section == "installments"), IsBotAdminFilter(ADMINS))
async def admin_installments_menu(call: types.CallbackQuery):
    await call.answer()
    rows = await db.get_upcoming_due_installments()
    if not rows:
        text = "📅 <b>MUDDATLI TO'LOVLAR</b>\n\nYaqin 3 kun ichida to'lanadigan qarzlar yo'q."
    else:
        lines = ["📅 <b>MUDDATLI TO'LOVLAR</b> (3 kun ichida)\n"]
        for r in rows:
            due_str = r["due_date"].strftime("%d.%m.%Y") if r.get("due_date") else "—"
            lines.append(
                f"• {html.quote(r['course_name'])} | "
                f"<b>{format_price(r['amount'])}</b> | "
                f"To'lov #{r['payment_number']}/{r['installments_count']} | "
                f"Sana: {due_str} | "
                f"ID: <code>{r['telegram_id']}</code>"
            )
        text = "\n".join(lines)

    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="↩️ Admin panel",
            callback_data=AdminMenuCallback(section="main").pack(),
            style=ButtonStyle.PRIMARY,
        )
    ]])
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)
