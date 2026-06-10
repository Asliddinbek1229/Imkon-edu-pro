from __future__ import annotations

from math import ceil

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from handlers.users.purchases.main import MyPurchaseDetailCallback, MyPurchasesPageCallback
from loader import db
from utils.misc.api.course_payment import create_course_payment

router = Router()

COURSES_PER_PAGE = 5
CATALOG_BUTTON_TEXT = "📚 Kurslar katalogi"
TELEGRAM_CAPTION_LIMIT = 1024


class CatalogPageCallback(CallbackData, prefix="cat_page"):
    page: int


class CatalogDetailCallback(CallbackData, prefix="cat_detail"):
    course_id: int
    page: int


class CatalogActionCallback(CallbackData, prefix="cat_action"):
    action: str
    page: int = 1
    course_id: int = 0


def format_price(price: int) -> str:
    if price <= 0:
        return "BEPUL"
    return f"{price:,}".replace(",", " ") + " so'm"


def fit_caption(text: str) -> str:
    if len(text) <= TELEGRAM_CAPTION_LIMIT:
        return text
    suffix = "\n\n…\nTo'liq tavsif uchun admin bilan bog'laning."
    return text[: TELEGRAM_CAPTION_LIMIT - len(suffix)].rstrip() + suffix


def course_catalog_text(courses: list, page: int, total: int) -> str:
    if not courses:
        return (
            "💎 <b>IMKON-EDU PRO KURSLAR</b>\n\n"
            "Hozircha faol kurslar mavjud emas.\n"
            "Keyinroq qayta tekshirib ko'ring."
        )

    total_pages = max(ceil(total / COURSES_PER_PAGE), 1)
    lines = [
        "💎 <b>IMKON-EDU PRO KURSLAR</b>",
        "Biologiya bo'yicha saralangan video kurslar",
        "",
        f"📄 Sahifa: <b>{page}/{total_pages}</b>",
        "",
    ]
    for index, course in enumerate(courses, start=1):
        status = "🎁" if course["price"] <= 0 else "💎"
        video = f"{course['video_count']} video" if course["video_count"] else "video darslar"
        lines.append(
            f"{index}. {status} <b>{html.quote(course['name'])}</b>\n"
            f"   {video} · {format_price(course['price'])}"
        )

    lines.extend(
        [
            "",
            "Kurs haqida premium taqdimotni ko'rish uchun raqamni tanlang.",
        ]
    )
    return "\n".join(lines)


def catalog_keyboard(courses: list, page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(ceil(total / COURSES_PER_PAGE), 1)
    rows: list[list[InlineKeyboardButton]] = []

    if courses:
        rows.append(
            [
                InlineKeyboardButton(
                    text=str(index),
                    callback_data=CatalogDetailCallback(course_id=course["id"], page=page).pack(),
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
                callback_data=CatalogPageCallback(page=page - 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Keyingi ➡️",
                callback_data=CatalogPageCallback(page=page + 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="🏠 Asosiy menyu",
                callback_data=CatalogActionCallback(action="menu").pack(),
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=CatalogActionCallback(action="cancel").pack(),
                style=ButtonStyle.DANGER,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def course_detail_text(course) -> str:
    includes = course["includes"] or "Video darslar, chizmalar, testlar va tahlillar"
    target_exam = course["target_exam"] or "DTM, Milliy Sertifikat, Attestatsiya"
    duration = course["duration"] or "Admin tomonidan belgilanadi"
    price_badge = "🎁 <b>BEPUL KURS</b>" if course["price"] <= 0 else "💎 <b>PREMIUM KURS</b>"

    return (
        "✨ <b>IMKON-EDU PRO</b>\n"
        f"{price_badge}\n\n"
        f"📘 <b>{html.quote(course['name'])}</b>\n"
        f"👨‍🏫 <b>Muallif:</b> {html.quote(course['author'])}\n\n"
        "━━━━━━━━━━━━━━\n"
        "📌 <b>Kurs paketi</b>\n"
        f"💰 Narx: <b>{format_price(course['price'])}</b>\n"
        f"🎬 Video: <b>{course['video_count']} ta dars</b>\n"
        f"⏱ Davomiylik: <b>{html.quote(duration)}</b>\n"
        f"♾ Kirish: <b>{html.quote(course['access_type'])}</b>\n\n"
        "🎯 <b>Imtihonlar</b>\n"
        f"{html.quote(target_exam)}\n\n"
        "✨ <b>Ichida nimalar bor</b>\n"
        f"{html.quote(includes)}\n\n"
        "📝 <b>Tavsif</b>\n"
        f"{html.quote(course['description'])}\n\n"
        "⚡️ Joyingizni band qilish uchun pastdagi tugmani bosing."
    )


def course_detail_keyboard(course, page: int) -> InlineKeyboardMarkup:
    course_id = course["id"]
    buy_text = "🎁 Bepul olish" if course["price"] <= 0 else f"💎 {format_price(course['price'])} | Sotib olish"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=buy_text,
                    callback_data=CatalogActionCallback(action="buy", course_id=course_id, page=page).pack(),
                    style=ButtonStyle.SUCCESS,
                )
            ],
            [
                InlineKeyboardButton(
                    text="📋 Kurs nomini nusxalash",
                    copy_text=CopyTextButton(text=course["name"][:256]),
                    style=ButtonStyle.PRIMARY,
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Orqaga",
                    callback_data=CatalogPageCallback(page=page).pack(),
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=CatalogActionCallback(action="cancel").pack(),
                    style=ButtonStyle.DANGER,
                ),
            ],
        ]
    )


async def render_catalog(message: types.Message, page: int = 1) -> None:
    total = await db.count_active_courses()
    total_pages = max(ceil(total / COURSES_PER_PAGE), 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * COURSES_PER_PAGE
    courses = await db.select_active_courses_page(limit=COURSES_PER_PAGE, offset=offset)

    await message.answer(
        course_catalog_text(courses=courses, page=page, total=total),
        reply_markup=catalog_keyboard(courses=courses, page=page, total=total),
    )


async def edit_or_send_catalog(call: types.CallbackQuery, page: int = 1, answer: bool = True) -> None:
    total = await db.count_active_courses()
    total_pages = max(ceil(total / COURSES_PER_PAGE), 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * COURSES_PER_PAGE
    courses = await db.select_active_courses_page(limit=COURSES_PER_PAGE, offset=offset)
    text = course_catalog_text(courses=courses, page=page, total=total)
    markup = catalog_keyboard(courses=courses, page=page, total=total)

    if answer:
        await call.answer()
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


async def render_course_detail(call: types.CallbackQuery, course_id: int, page: int) -> None:
    course = await db.select_course(course_id)
    if not course or not course["is_active"]:
        await call.answer("Kurs topilmadi yoki vaqtincha yopilgan.", show_alert=True)
        await edit_or_send_catalog(call, page=page, answer=False)
        return

    await call.answer()
    text = course_detail_text(course)
    markup = course_detail_keyboard(course=course, page=page)

    if course["thumbnail"]:
        caption = fit_caption(text)
        if call.message.photo:
            await call.message.edit_caption(caption=caption, reply_markup=markup)
            return
        await call.message.delete()
        await call.message.answer_photo(photo=course["thumbnail"], caption=caption, reply_markup=markup)
        return

    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


@router.message(F.text == CATALOG_BUTTON_TEXT)
async def show_catalog(message: types.Message):
    await render_catalog(message=message, page=1)


@router.callback_query(CatalogPageCallback.filter())
async def paginate_catalog(call: types.CallbackQuery, callback_data: CatalogPageCallback):
    await edit_or_send_catalog(call=call, page=callback_data.page)


@router.callback_query(CatalogDetailCallback.filter())
async def show_course_detail(call: types.CallbackQuery, callback_data: CatalogDetailCallback):
    await render_course_detail(
        call=call,
        course_id=callback_data.course_id,
        page=callback_data.page,
    )


@router.callback_query(CatalogActionCallback.filter(F.action == "menu"))
async def catalog_back_to_menu(call: types.CallbackQuery):
    await call.answer("Asosiy menyu ochiq.")
    await call.message.delete()


@router.callback_query(CatalogActionCallback.filter(F.action == "cancel"))
async def catalog_cancel(call: types.CallbackQuery):
    await call.answer("Bekor qilindi.")
    await call.message.delete()


@router.callback_query(CatalogActionCallback.filter(F.action == "buy"))
async def catalog_buy(call: types.CallbackQuery, callback_data: CatalogActionCallback, state: FSMContext):
    course = await db.select_course(callback_data.course_id)
    if not course or not course["is_active"]:
        await call.answer("Kurs topilmadi yoki vaqtincha yopilgan.", show_alert=True)
        return

    await state.clear()

    if course["price"] <= 0:
        # Bepul kurs: darhol tasdiqlash
        purchase = await db.create_pending_purchase(call.from_user.id, course["id"])
        if not purchase:
            await call.answer("Avval ro'yxatdan o'ting: /start", show_alert=True)
            return

        await call.answer("Kurs biriktirildi.")
        text = (
            "✅ <b>Kurs sizga biriktirildi.</b>\n\n"
            f"📚 Kurs: <b>{html.quote(purchase['course_name'])}</b>\n"
            "Holat: ✅ Faol\n\n"
            "Kursni 'Mening sotib olganlarim' bo'limidan ko'rishingiz mumkin."
        )
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🛒 Xaridni ko'rish",
                        callback_data=MyPurchaseDetailCallback(purchase_id=purchase["id"], page=1).pack(),
                        style=ButtonStyle.SUCCESS,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📚 Katalogga qaytish",
                        callback_data=CatalogPageCallback(page=callback_data.page).pack(),
                        style=ButtonStyle.PRIMARY,
                    )
                ],
            ]
        )
        if call.message.photo:
            await call.message.delete()
            await call.message.answer(text, reply_markup=markup)
            return
        await call.message.edit_text(text, reply_markup=markup)
        return

    # Pullik kurs: CLICK to'lov
    await call.answer("To'lov sahifasi tayyorlanmoqda…")
    result = await create_course_payment(
        tg_id=call.from_user.id,
        course_id=course["id"],
        course_name=course["name"],
        course_link=course["telegram_link"] or "",
        amount=course["price"],
    )

    if not result or not result.get("payment_url"):
        text = (
            "⚠️ <b>To'lov tizimida xatolik yuz berdi.</b>\n\n"
            "Iltimos, keyinroq qayta urinib ko'ring yoki admin bilan bog'laning."
        )
        if call.message.photo:
            await call.message.delete()
            await call.message.answer(text)
            return
        await call.message.edit_text(text)
        return

    payment_url = result["payment_url"]
    amount_str = format_price(course["price"])
    text = (
        "💳 <b>CLICK orqali to'lov</b>\n\n"
        f"📚 Kurs: <b>{html.quote(course['name'])}</b>\n"
        f"💰 Summa: <b>{amount_str}</b>\n\n"
        "Pastdagi tugmani bosib to'lovni amalga oshiring.\n"
        "To'lov tasdiqlangach, kurs linki <b>avtomatik</b> yuboriladi."
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💳 CLICK orqali to'lash",
                    url=payment_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=CatalogActionCallback(action="cancel").pack(),
                    style=ButtonStyle.DANGER,
                )
            ],
        ]
    )

    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)
