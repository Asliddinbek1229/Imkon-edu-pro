from __future__ import annotations

from datetime import datetime
from math import ceil

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.users.payment.main import PaymentActionCallback, render_payment_instructions
from loader import db
from utils.misc.api.course_payment import create_course_payment

router = Router()

PURCHASES_BUTTON_TEXT = "🛒 Mening sotib olganlarim"
PURCHASES_PER_PAGE = 5


class MyPurchasesPageCallback(CallbackData, prefix="myp"):
    page: int


class MyPurchaseDetailCallback(CallbackData, prefix="mypd"):
    purchase_id: int
    page: int = 1


class MyPurchaseActionCallback(CallbackData, prefix="mypa"):
    action: str
    purchase_id: int = 0
    page: int = 1


def format_price(price: int) -> str:
    if price <= 0:
        return "BEPUL"
    return f"{price:,}".replace(",", " ") + " so'm"


def format_date(value) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


def status_label(status: str) -> str:
    labels = {
        "pending": "⏳ Tekshirilmoqda",
        "approved": "✅ Faol",
        "rejected": "❌ Rad etilgan",
    }
    return labels.get(status, status)


def purchases_text(purchases: list, page: int, total: int) -> str:
    if not purchases:
        return (
            "🛒 <b>MENING SOTIB OLGANLARIM</b>\n\n"
            "Sizda hali sotib olingan kurslar yo'q.\n"
            "Kurslar katalogidan o'zingizga kerakli kursni tanlang."
        )

    total_pages = max(ceil(total / PURCHASES_PER_PAGE), 1)
    lines = [
        "🛒 <b>MENING SOTIB OLGANLARIM</b>",
        f"Sahifa: <b>{page}/{total_pages}</b>",
        "",
    ]
    for index, purchase in enumerate(purchases, start=1):
        lines.append(
            f"{index}. <b>{html.quote(purchase['course_name'])}</b>\n"
            f"   {status_label(purchase['status'])} | {format_price(purchase['amount'])}\n"
            f"   Sana: {format_date(purchase['created_at'])}"
        )

    lines.append("")
    lines.append("Batafsil ko'rish uchun pastdagi raqamni tanlang.")
    return "\n".join(lines)


def purchases_keyboard(purchases: list, page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(ceil(total / PURCHASES_PER_PAGE), 1)
    rows: list[list[InlineKeyboardButton]] = []

    if purchases:
        rows.append(
            [
                InlineKeyboardButton(
                    text=str(index),
                    callback_data=MyPurchaseDetailCallback(purchase_id=purchase["id"], page=page).pack(),
                    style=ButtonStyle.PRIMARY,
                )
                for index, purchase in enumerate(purchases, start=1)
            ]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Oldingi",
                callback_data=MyPurchasesPageCallback(page=page - 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                text="Keyingi ➡️",
                callback_data=MyPurchasesPageCallback(page=page + 1).pack(),
                style=ButtonStyle.PRIMARY,
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="📚 Kurslar katalogi",
                callback_data=MyPurchaseActionCallback(action="catalog").pack(),
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=MyPurchaseActionCallback(action="cancel").pack(),
                style=ButtonStyle.DANGER,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def purchase_detail_text(purchase) -> str:
    access_link = purchase["invite_link"] or purchase["course_telegram_link"] or "-"
    admin_note = purchase["admin_note"] or "-"
    approved_line = ""
    if purchase["status"] == "approved":
        approved_line = (
            "\n🎉 <b>Kirish huquqi berilgan.</b>\n"
            "Guruhga kirgach pinned postni o'qing va darslarni tartib bilan o'rganing."
        )
    elif purchase["status"] == "pending":
        approved_line = (
            "\n⏳ <b>To'lov tekshirilmoqda.</b>\n"
            "Admin tasdiqlagach kurs linki avtomatik ko'rinadi."
        )
    elif purchase["status"] == "rejected":
        approved_line = "\n❌ <b>To'lov rad etilgan.</b> Qayta sotib olish mumkin."

    return (
        f"📘 <b>{html.quote(purchase['course_name'])}</b>\n\n"
        f"Holat: <b>{status_label(purchase['status'])}</b>\n"
        f"Summa: <b>{format_price(purchase['amount'])}</b>\n"
        f"Video: <b>{purchase['course_video_count']} ta</b>\n"
        f"Kirish: <b>{html.quote(purchase['course_access_type'])}</b>\n"
        f"Sotib olish sanasi: {format_date(purchase['created_at'])}\n"
        f"Tasdiqlangan sana: {format_date(purchase['approved_at'])}\n"
        f"Rad etilgan sana: {format_date(purchase['rejected_at'])}\n"
        f"Admin izohi: {html.quote(admin_note)}\n"
        f"Kurs linki: {html.quote(access_link)}"
        f"{approved_line}"
    )


def purchase_detail_keyboard(purchase, page: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    access_link = purchase["invite_link"] or purchase["course_telegram_link"]

    if purchase["status"] == "approved" and access_link:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔗 Kursga kirish",
                    url=access_link,
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )

    if purchase["status"] == "pending":
        receipt_text = "📸 Chekni qayta yuborish" if purchase["receipt_file_id"] else "📸 Chek yuborish"
        rows.append(
            [
                InlineKeyboardButton(
                    text=receipt_text,
                    callback_data=PaymentActionCallback(action="instructions", purchase_id=purchase["id"]).pack(),
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )

    if purchase["status"] == "rejected":
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔁 Qayta sotib olish",
                    callback_data=MyPurchaseActionCallback(
                        action="retry",
                        purchase_id=purchase["id"],
                        page=page,
                    ).pack(),
                    style=ButtonStyle.SUCCESS,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ Orqaga",
                callback_data=MyPurchasesPageCallback(page=page).pack(),
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                text="❌ Bekor qilish",
                callback_data=MyPurchaseActionCallback(action="cancel").pack(),
                style=ButtonStyle.DANGER,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_purchases(message: types.Message, page: int = 1) -> None:
    total = await db.count_user_purchases(message.from_user.id)
    total_pages = max(ceil(total / PURCHASES_PER_PAGE), 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * PURCHASES_PER_PAGE
    purchases = await db.select_user_purchases_page(message.from_user.id, PURCHASES_PER_PAGE, offset)

    await message.answer(
        purchases_text(purchases=purchases, page=page, total=total),
        reply_markup=purchases_keyboard(purchases=purchases, page=page, total=total),
    )


async def edit_or_send_purchases(call: types.CallbackQuery, page: int = 1, answer: bool = True) -> None:
    total = await db.count_user_purchases(call.from_user.id)
    total_pages = max(ceil(total / PURCHASES_PER_PAGE), 1)
    page = min(max(page, 1), total_pages)
    offset = (page - 1) * PURCHASES_PER_PAGE
    purchases = await db.select_user_purchases_page(call.from_user.id, PURCHASES_PER_PAGE, offset)
    text = purchases_text(purchases=purchases, page=page, total=total)
    markup = purchases_keyboard(purchases=purchases, page=page, total=total)

    if answer:
        await call.answer()
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


async def render_purchase_detail(
    call: types.CallbackQuery,
    purchase_id: int,
    page: int,
    answer: bool = True,
) -> None:
    purchase = await db.select_user_purchase(call.from_user.id, purchase_id)
    if not purchase:
        await call.answer("Xarid topilmadi.", show_alert=True)
        await edit_or_send_purchases(call, page=page, answer=False)
        return

    if answer:
        await call.answer()
    text = purchase_detail_text(purchase)
    markup = purchase_detail_keyboard(purchase, page=page)
    if call.message.photo:
        await call.message.delete()
        await call.message.answer(text, reply_markup=markup)
        return
    await call.message.edit_text(text, reply_markup=markup)


@router.message(F.text == PURCHASES_BUTTON_TEXT)
async def my_purchases(message: types.Message):
    await render_purchases(message, page=1)


@router.callback_query(MyPurchasesPageCallback.filter())
async def my_purchases_page(call: types.CallbackQuery, callback_data: MyPurchasesPageCallback):
    await edit_or_send_purchases(call, page=callback_data.page)


@router.callback_query(MyPurchaseDetailCallback.filter())
async def my_purchase_detail(call: types.CallbackQuery, callback_data: MyPurchaseDetailCallback):
    await render_purchase_detail(call, purchase_id=callback_data.purchase_id, page=callback_data.page)


@router.callback_query(MyPurchaseActionCallback.filter(F.action == "cancel"))
async def my_purchase_cancel(call: types.CallbackQuery):
    await call.answer("Bekor qilindi.")
    await call.message.delete()


@router.callback_query(MyPurchaseActionCallback.filter(F.action == "catalog"))
async def my_purchase_catalog(call: types.CallbackQuery):
    await call.answer("Kurslar katalogini menyudan oching.")
    await call.message.delete()


@router.callback_query(MyPurchaseActionCallback.filter(F.action == "retry"))
async def my_purchase_retry(call: types.CallbackQuery, callback_data: MyPurchaseActionCallback, state: FSMContext):
    old_purchase = await db.select_user_purchase(call.from_user.id, callback_data.purchase_id)
    if not old_purchase:
        await call.answer("Xarid topilmadi.", show_alert=True)
        return

    course = await db.select_course(old_purchase["course_id"])
    if not course or not course["is_active"]:
        await call.answer("Kurs topilmadi yoki vaqtincha yopilgan.", show_alert=True)
        return

    await state.clear()

    if course["price"] <= 0:
        new_purchase = await db.create_pending_purchase(call.from_user.id, course["id"])
        if not new_purchase:
            await call.answer("Kurs topilmadi.", show_alert=True)
            return
        await call.answer("Kurs sizga biriktirildi.")
        await render_purchase_detail(call, purchase_id=new_purchase["id"], page=callback_data.page, answer=False)
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
        await call.answer("To'lov tizimida xatolik. Qayta urinib ko'ring.", show_alert=True)
        return

    payment_url = result["payment_url"]
    text = (
        "💳 <b>CLICK orqali to'lov</b>\n\n"
        f"📚 Kurs: <b>{html.quote(course['name'])}</b>\n"
        f"💰 Summa: <b>{format_price(course['price'])}</b>\n\n"
        "Pastdagi tugmani bosib to'lovni amalga oshiring.\n"
        "To'lov tasdiqlangach, kurs linki <b>avtomatik</b> yuboriladi."
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 CLICK orqali to'lash", url=payment_url)],
            [
                InlineKeyboardButton(
                    text="❌ Bekor qilish",
                    callback_data=MyPurchaseActionCallback(action="cancel").pack(),
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
