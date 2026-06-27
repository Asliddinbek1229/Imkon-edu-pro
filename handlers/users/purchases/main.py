from __future__ import annotations

from datetime import datetime
from math import ceil

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.users.payment.main import NextInstallmentCallback
from loader import db
from utils.misc.api.course_payment import check_order_status, create_course_payment

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


def status_label(status: str, purchase_type: str = "paid") -> str:
    if status == "approved" and purchase_type == "free":
        return "🎁 Bepul kirish"
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
            f"   {status_label(purchase['status'], purchase.get('purchase_type', 'paid'))} | {format_price(purchase['amount'])}\n"
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


def purchase_detail_text(purchase, plan=None, payments=None) -> str:
    purchase_type = purchase.get("purchase_type", "paid")
    is_free_type = purchase_type == "free"
    access_link = purchase["invite_link"] or (
        purchase["course_free_telegram_link"] if is_free_type else purchase["course_telegram_link"]
    ) or "-"
    admin_note = purchase["admin_note"] or "-"
    type_label = "🎁 Bepul kirish" if is_free_type else "💎 To'lov orqali"
    coupon_line = ""
    if purchase.get("coupon_code"):
        coupon_line = f"\n🎟 Kupon: <code>{html.quote(purchase['coupon_code'])}</code>"
        orig = purchase.get("original_amount", 0) or 0
        disc = purchase.get("coupon_discount", 0) or 0
        if disc:
            coupon_line += f" (−{format_price(disc)}, asl narx: {format_price(orig)})"

    approved_line = ""
    if purchase["status"] == "approved":
        if access_link:
            approved_line = (
                "\n\n🎉 <b>Kirish huquqi berilgan.</b>\n"
                "Pastdagi tugma orqali guruh yoki kanalga qo'shiling.\n"
                "Kirgach pinned postni o'qing va darslarni tartib bilan o'rganing."
            )
        else:
            approved_line = "\n\n🎉 <b>Kirish huquqi berilgan.</b>"
    elif purchase["status"] == "pending":
        if purchase.get("click_order_id"):
            approved_line = (
                "\n\n⏳ <b>CLICK to'lov kutilmoqda.</b>\n"
                "To'lov tasdiqlangach kurs linki avtomatik yuboriladi."
            )
        else:
            approved_line = (
                "\n\n⏳ <b>To'lov tekshirilmoqda.</b>\n"
                "Admin tasdiqlagach kurs linki avtomatik ko'rinadi."
            )
    elif purchase["status"] == "rejected":
        admin_note_txt = purchase.get("admin_note") or "Rad etildi."
        approved_line = f"\n\n❌ <b>To'lov rad etilgan.</b>\nSabab: {html.quote(admin_note_txt)}"

    installment_line = ""
    if plan and payments:
        paid_count = sum(1 for p in payments if p["status"] == "paid")
        total_count = plan["installments_count"]
        paid_amount = sum(p["amount"] for p in payments if p["status"] == "paid")
        remaining_amount = plan["total_amount"] - paid_amount
        remaining_str = format_price(remaining_amount) if remaining_amount > 0 else "✅ To'liq to'langan"
        installment_line = (
            f"\n\n📅 <b>Muddatli to'lov: {paid_count}/{total_count}</b>\n"
            f"Kurs narxi: <b>{format_price(plan['total_amount'])}</b>\n"
            f"To'langan: <b>{format_price(paid_amount)}</b>\n"
            f"Qolgan qarz: <b>{remaining_str}</b>"
        )
        pending_payments = [p for p in payments if p["status"] == "pending"]
        if pending_payments:
            nxt = pending_payments[0]
            due_str = nxt["due_date"].strftime("%d.%m.%Y") if nxt.get("due_date") else "—"
            installment_line += (
                f"\n\nKeyingi to'lov: <b>{format_price(nxt['amount'])}</b> "
                f"({nxt['payment_number']}/{total_count}) – {due_str}"
            )

    return (
        f"📘 <b>{html.quote(purchase['course_name'])}</b>\n\n"
        f"Tur: <b>{type_label}</b>\n"
        f"Holat: <b>{status_label(purchase['status'], purchase_type)}</b>\n"
        f"Summa: <b>{format_price(purchase['amount'])}</b>"
        f"{coupon_line}\n"
        f"Video: <b>{purchase['course_video_count']} ta</b>\n"
        f"Kirish: <b>{html.quote(purchase['course_access_type'])}</b>\n"
        f"Sana: {format_date(purchase['created_at'])}\n"
        f"Tasdiqlangan: {format_date(purchase['approved_at'])}\n"
        f"Rad etilgan: {format_date(purchase['rejected_at'])}"
        f"{installment_line}"
        f"{approved_line}"
    )


def purchase_detail_keyboard(purchase, page: int, plan=None, payments=None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    purchase_type = purchase.get("purchase_type", "paid")
    is_free_type = purchase_type == "free"
    access_link = purchase["invite_link"] or (
        purchase.get("course_free_telegram_link") if is_free_type else purchase["course_telegram_link"]
    )

    if purchase["status"] == "approved" and access_link:
        rows.append([
            InlineKeyboardButton(text="🔗 Kursga qo'shilish", url=access_link, style=ButtonStyle.SUCCESS)
        ])

    is_installment = purchase.get("is_installment", False)

    if is_installment and plan and payments:
        pending = [p for p in payments if p["status"] == "pending"]
        if pending and purchase["status"] == "approved":
            nxt = pending[0]
            has_click = bool(nxt.get("click_order_id"))
            btn_text = "⏳ To'lov kutilmoqda (CLICK)" if has_click else "💳 Keyingi to'lovni amalga oshirish"
            rows.append([
                InlineKeyboardButton(
                    text=btn_text,
                    callback_data=NextInstallmentCallback(
                        plan_id=plan["id"], purchase_id=purchase["id"]
                    ).pack(),
                    style=ButtonStyle.PRIMARY if has_click else ButtonStyle.SUCCESS,
                )
            ])

    if purchase["status"] == "rejected" and not is_installment:
        rows.append([
            InlineKeyboardButton(
                text="🔁 Qayta sotib olish",
                callback_data=MyPurchaseActionCallback(action="retry", purchase_id=purchase["id"], page=page).pack(),
                style=ButtonStyle.SUCCESS,
            )
        ])

    rows.append([
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
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def sync_pending_click_purchases(telegram_id: int) -> None:
    """Pending CLICK xaridlarini Django dan tekshirib avtomatik approve qiladi."""
    pending = await db.get_pending_click_purchases(telegram_id)
    for row in pending:
        order_data = await check_order_status(row["click_order_id"])
        if order_data and order_data.get("paid"):
            invite_link = order_data.get("course_link") or None
            await db.approve_click_purchase(
                click_order_id=row["click_order_id"],
                invite_link=invite_link,
            )


async def render_purchases(message: types.Message, page: int = 1) -> None:
    await sync_pending_click_purchases(message.from_user.id)
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
    await sync_pending_click_purchases(call.from_user.id)
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

    if purchase["status"] == "pending" and purchase.get("click_order_id"):
        order_data = await check_order_status(purchase["click_order_id"])
        if order_data and order_data.get("paid"):
            updated = await db.approve_click_purchase(
                click_order_id=purchase["click_order_id"],
                invite_link=order_data.get("course_link") or None,
            )
            if updated:
                purchase = updated

    plan = None
    payments = None
    if purchase.get("is_installment"):
        plan = await db.get_installment_plan_by_purchase(purchase["id"])
        if plan:
            payments = await db.get_installment_payments(plan["id"])

    if answer:
        await call.answer()
    text = purchase_detail_text(purchase, plan=plan, payments=payments)
    markup = purchase_detail_keyboard(purchase, page=page, plan=plan, payments=payments)
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
        course_link="",
        amount=course["price"],
    )
    if not result or not result.get("payment_url"):
        await call.answer("To'lov tizimida xatolik. Qayta urinib ko'ring.", show_alert=True)
        return

    await db.create_click_pending_purchase(
        telegram_id=call.from_user.id,
        course_id=course["id"],
        click_order_id=result["order_id"],
        amount=course["price"],
    )

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
