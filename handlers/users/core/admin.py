import asyncio
import logging
from math import ceil

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from data.config import ADMINS
from filters.admin import IsBotAdminFilter
from keyboards.inline.buttons import are_you_sure_markup
from loader import bot, db
from states import AdminState, CourseAdminState
from utils.pgtoexcel import export_to_excel

logger = logging.getLogger(__name__)
router = Router()

ADMIN_PANEL_TEXT = "⚙️ Admin panel"
ADMIN_COURSES_PER_PAGE = 5
SKIP_TEXTS = {"skip", "o'tkazish", "otkazish", "-", "yo'q", "yoq"}


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


def format_price(price: int) -> str:
    if price <= 0:
        return "BEPUL"
    return f"{price:,}".replace(",", " ") + " so'm"


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
        ]
    )


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
    return (
        f"📘 <b>{html.quote(course['name'])}</b>\n"
        f"Holat: <b>{status}</b>\n"
        f"Narx: <b>{format_price(course['price'])}</b>\n"
        f"Video: <b>{course['video_count']} ta</b>\n"
        f"Muallif: {html.quote(course['author'])}\n"
        f"Davomiylik: {html.quote(course['duration'] or '-')}\n"
        f"Imtihon: {html.quote(course['target_exam'] or '-')}\n"
        f"Qo'shimcha: {html.quote(course['includes'] or '-')}\n"
        f"Kirish: {html.quote(course['access_type'])}\n"
        f"Guruh link: {html.quote(course['telegram_link'] or '-')}\n"
        f"Sort: {course['sort_order']}\n\n"
        "<b>Tavsif:</b>\n"
        f"{html.quote(course['description'])}"
    )


def admin_course_detail_keyboard(course) -> InlineKeyboardMarkup:
    toggle_text = "🚫 Yopish" if course["is_active"] else "✅ Ko'rsatish"
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
                    text="💰 Narx",
                    callback_data=AdminCourseEditCallback(field="price", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="📊 Video",
                    callback_data=AdminCourseEditCallback(field="video_count", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
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
                InlineKeyboardButton(
                    text="🔗 Link",
                    callback_data=AdminCourseEditCallback(field="telegram_link", course_id=course["id"]).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data=AdminCourseActionCallback(action="toggle", course_id=course["id"]).pack(),
                    style=toggle_style,
                ),
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
    if course["thumbnail"]:
        if call.message.photo:
            await call.message.edit_caption(caption=text, reply_markup=markup)
            return
        await call.message.delete()
        await call.message.answer_photo(photo=course["thumbnail"], caption=text, reply_markup=markup)
        return

    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


@router.message(Command("admin"), IsBotAdminFilter(ADMINS))
@router.message(F.text == ADMIN_PANEL_TEXT, IsBotAdminFilter(ADMINS))
async def admin_panel(message: types.Message):
    await render_admin_menu(message)


@router.callback_query(AdminMenuCallback.filter(F.section == "main"), IsBotAdminFilter(ADMINS))
async def admin_menu_callback(call: types.CallbackQuery):
    await edit_or_send_admin_menu(call)


@router.callback_query(AdminMenuCallback.filter(F.section == "courses"), IsBotAdminFilter(ADMINS))
async def admin_courses_callback(call: types.CallbackQuery):
    await render_admin_courses_list(call, page=1)


@router.callback_query(AdminMenuCallback.filter(F.section == "dashboard"), IsBotAdminFilter(ADMINS))
async def admin_dashboard_placeholder(call: types.CallbackQuery):
    await call.answer("Dashboard keyingi bosqichda ulanadi.", show_alert=True)


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
    await call.message.answer("➕ Yangi kurs nomini kiriting:\n\nMasalan: <b>6-botanika | Imkon-edu Pro</b>")


@router.message(CourseAdminState.add_name, IsBotAdminFilter(ADMINS))
async def admin_course_add_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 3 or len(name) > 200:
        await message.answer("Kurs nomi 3-200 belgi oralig'ida bo'lishi kerak.")
        return
    await state.update_data(name=name)
    await state.set_state(CourseAdminState.add_price)
    await message.answer("💰 Kurs narxini kiriting. Bepul kurs uchun <code>0</code> yozing.")


@router.message(CourseAdminState.add_price, IsBotAdminFilter(ADMINS))
async def admin_course_add_price(message: types.Message, state: FSMContext):
    price = parse_positive_int(message.text or "")
    if price is None:
        await message.answer("Narx faqat raqam bo'lishi kerak. Masalan: <code>250000</code>")
        return
    await state.update_data(price=price)
    await state.set_state(CourseAdminState.add_video_count)
    await message.answer("📊 Video darslar sonini kiriting. Masalan: <code>12</code>")


@router.message(CourseAdminState.add_video_count, IsBotAdminFilter(ADMINS))
async def admin_course_add_video_count(message: types.Message, state: FSMContext):
    video_count = parse_positive_int(message.text or "")
    if video_count is None:
        await message.answer("Video soni faqat raqam bo'lishi kerak. Masalan: <code>12</code>")
        return
    await state.update_data(video_count=video_count)
    await state.set_state(CourseAdminState.add_description)
    await message.answer("📝 Kurs tavsifini yuboring.")


@router.message(CourseAdminState.add_description, IsBotAdminFilter(ADMINS))
async def admin_course_add_description(message: types.Message, state: FSMContext):
    description = (message.text or "").strip()
    if len(description) < 10:
        await message.answer("Tavsif kamida 10 belgi bo'lishi kerak.")
        return
    await state.update_data(description=description)
    await state.set_state(CourseAdminState.add_photo)
    await message.answer("🖼 Kurs rasmini yuboring yoki o'tkazish uchun <code>skip</code> yozing.")


@router.message(CourseAdminState.add_photo, IsBotAdminFilter(ADMINS))
async def admin_course_add_photo(message: types.Message, state: FSMContext):
    thumbnail = None
    if message.photo:
        thumbnail = message.photo[-1].file_id
    elif (message.text or "").strip().lower() not in SKIP_TEXTS:
        await message.answer("Rasm yuboring yoki <code>skip</code> yozing.")
        return

    await state.update_data(thumbnail=thumbnail)
    await state.set_state(CourseAdminState.add_link)
    await message.answer("🔗 Kurs guruhi/linkini yuboring yoki o'tkazish uchun <code>skip</code> yozing.")


@router.message(CourseAdminState.add_link, IsBotAdminFilter(ADMINS))
async def admin_course_add_link(message: types.Message, state: FSMContext):
    raw_link = (message.text or "").strip()
    telegram_link = None if not raw_link or raw_link.lower() in SKIP_TEXTS else raw_link
    data = await state.get_data()

    course = await db.add_course(
        name=data["name"],
        description=data["description"],
        price=data["price"],
        video_count=data["video_count"],
        thumbnail=data.get("thumbnail"),
        telegram_link=telegram_link,
    )
    await state.clear()
    await message.answer(
        f"✅ Kurs yaratildi: <b>{html.quote(course['name'])}</b>",
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

    field_titles = {
        "name": "yangi kurs nomini",
        "price": "yangi narxni",
        "video_count": "yangi video sonini",
        "description": "yangi tavsifni",
        "thumbnail": "yangi rasmni",
        "telegram_link": "yangi guruh/linkni",
    }
    await call.answer()
    await state.clear()
    await state.update_data(course_id=course["id"], field=callback_data.field)
    await state.set_state(CourseAdminState.edit_value)

    if callback_data.field == "thumbnail":
        await call.message.answer("🖼 Yangi rasm yuboring. Rasmni o'chirish uchun <code>remove</code> yozing.")
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
    elif field in {"price", "video_count", "sort_order"}:
        value = parse_positive_int(message.text or "")
        if value is None:
            await message.answer("Bu maydon faqat raqam qabul qiladi.")
            return
    else:
        value = (message.text or "").strip()
        if not value:
            await message.answer("Bo'sh qiymat qabul qilinmaydi.")
            return

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
