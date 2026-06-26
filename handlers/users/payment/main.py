from __future__ import annotations

from aiogram import F, Router, html, types
from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from loader import bot, db
from utils.misc.api.course_payment import create_course_payment

payment_router = Router()


class PaymentActionCallback(CallbackData, prefix="pay"):
    action: str
    purchase_id: int = 0


class NextInstallmentCallback(CallbackData, prefix="nextinst"):
    plan_id: int
    purchase_id: int


def format_price(price: int) -> str:
    if price <= 0:
        return "BEPUL"
    return f"{price:,}".replace(",", " ") + " so'm"


@payment_router.callback_query(NextInstallmentCallback.filter())
async def pay_next_installment(
    call: types.CallbackQuery,
    callback_data: NextInstallmentCallback,
):
    next_payment = await db.get_next_pending_installment(callback_data.plan_id)
    if not next_payment:
        await call.answer("Barcha to'lovlar amalga oshirilgan!", show_alert=True)
        return

    if next_payment.get("click_order_id"):
        await call.answer(
            "To'lov havolasi allaqachon yaratilgan. "
            "Eski havola orqali to'lang yoki admin bilan bog'laning.",
            show_alert=True,
        )
        return

    detail = await db.get_installment_payment_detail(next_payment["id"])
    if not detail:
        await call.answer("Xatolik. Qayta urinib ko'ring.", show_alert=True)
        return

    purchase = await db.select_purchase_by_id(callback_data.purchase_id)
    course_link = (purchase or {}).get("course_telegram_link") or ""

    result = await create_course_payment(
        tg_id=call.from_user.id,
        course_id=detail["course_id"],
        course_name=detail["course_name"],
        course_link=course_link,
        amount=next_payment["amount"],
    )

    if not result or not result.get("payment_url"):
        await call.answer("To'lov tizimida xatolik. Keyinroq urinib ko'ring.", show_alert=True)
        return

    await db.set_installment_click_order(next_payment["id"], result["order_id"])
    await call.answer()

    total = detail.get("installments_count", "?")
    payment_no = next_payment["payment_number"]
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💳 CLICK orqali to'lash",
            url=result["payment_url"],
            style=ButtonStyle.SUCCESS,
        )],
    ])
    await call.message.answer(
        f"📅 <b>MUDDATLI TO'LOV — {payment_no}/{total}</b>\n\n"
        f"📚 Kurs: <b>{html.quote(detail['course_name'])}</b>\n"
        f"💰 To'lanadigan summa: <b>{format_price(next_payment['amount'])}</b>\n\n"
        "Pastdagi tugma orqali CLICK to'lovini amalga oshiring.\n"
        "To'lov tasdiqlanishi bilan avtomatik xabar olasiz.",
        reply_markup=markup,
    )
