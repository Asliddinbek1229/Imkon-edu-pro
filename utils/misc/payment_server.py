from __future__ import annotations

import logging

from aiohttp import web
from aiogram import html

from data.config import BOT_PAYMENT_SERVER_SECRET
from loader import bot, db

logger = logging.getLogger(__name__)


def _fmt(price: int) -> str:
    return f"{price:,}".replace(",", " ") + " so'm"


async def _notify_regular_approved(purchase) -> None:
    access_link = purchase.get("invite_link") or purchase.get("course_telegram_link")
    text = (
        "✅ <b>To'lov tasdiqlandi!</b>\n\n"
        f"📚 Kurs: <b>{html.quote(purchase['course_name'])}</b>\n"
        f"💰 Summa: <b>{_fmt(purchase['amount'])}</b>\n\n"
        "Kursga kirish huquqi berildi.\n"
        + ("Pastdagi tugma orqali guruhga/kanalga qo'shiling.\n"
           "Kirgach pinned postni o'qing va darslarni tartib bilan o'rganing."
           if access_link else
           "Admin tez orada kurs linkini yuboradi.")
    )
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.enums import ButtonStyle
    markup = None
    if access_link:
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🔗 Kursga qo'shilish",
                url=access_link,
                style=ButtonStyle.SUCCESS,
            )
        ]])
    try:
        await bot.send_message(
            chat_id=purchase["telegram_id"],
            text=text,
            reply_markup=markup,
        )
    except Exception as exc:
        logger.warning("User notification failed tg_id=%s: %s", purchase.get("telegram_id"), exc)


async def _notify_installment_approved(detail) -> None:
    is_first = detail["payment_number"] == 1
    plan_total = detail.get("plan_total", 0)
    paid_amount = detail.get("amount", 0)
    total_count = detail.get("installments_count", 1)
    paid_count = detail.get("paid_count", 0)

    # To'g'ri formula: DB dan hisoblangan yig'indi orqali qolgan qarz
    paid_sum = detail.get("paid_sum", 0)
    remaining = max(plan_total - paid_sum, 0)

    if is_first:
        purchase = await db.select_purchase_by_id(detail["purchase_id"])
        access_link = (purchase or {}).get("invite_link") or detail.get("course_telegram_link")
        text = (
            "✅ <b>Birinchi to'lov tasdiqlandi!</b>\n\n"
            f"📚 Kurs: <b>{html.quote(detail['course_name'])}</b>\n"
            f"💰 To'langan: <b>{_fmt(paid_amount)}</b> (1/{total_count}-qism)\n"
            f"💳 Qolgan qarz: <b>{_fmt(remaining)}</b>\n\n"
            "Kursga kirish huquqi berildi.\n"
            + ("Pastdagi tugma orqali kursga qo'shiling." if access_link else "")
        )
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from aiogram.enums import ButtonStyle
        markup = None
        if access_link:
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔗 Kursga qo'shilish", url=access_link, style=ButtonStyle.SUCCESS
                )
            ]])
    else:
        is_complete = (paid_count >= total_count)
        if is_complete:
            text = (
                "✅ <b>Barcha to'lovlar yakunlandi!</b>\n\n"
                f"📚 Kurs: <b>{html.quote(detail['course_name'])}</b>\n"
                f"💰 Jami to'langan: <b>{_fmt(plan_total)}</b>\n\n"
                "Kurs uchun to'lov to'liq amalga oshirildi. Rahmat!"
            )
        else:
            text = (
                f"✅ <b>{detail['payment_number']}/{total_count}-to'lov tasdiqlandi!</b>\n\n"
                f"📚 Kurs: <b>{html.quote(detail['course_name'])}</b>\n"
                f"💰 To'langan: <b>{_fmt(paid_amount)}</b>\n"
                f"💳 Qolgan qarz: <b>{_fmt(remaining)}</b>\n\n"
                "Keyingi to'lov sanasi yaqinlashganda xabar yuboriladi.\n"
                "\"Mening sotib olganlarim\" bo'limidan keyingi to'lovni amalga oshiring."
            )
        markup = None

    try:
        await bot.send_message(chat_id=detail["telegram_id"], text=text, reply_markup=markup)
    except Exception as exc:
        logger.warning("Installment notification failed tg_id=%s: %s", detail.get("telegram_id"), exc)


async def handle_purchase_confirm(request: web.Request) -> web.Response:
    # Webhook autentifikatsiyasi — har doim tekshirish (shartli emas)
    secret = request.headers.get("X-Bot-Secret", "")
    if secret != BOT_PAYMENT_SERVER_SECRET:
        logger.warning("Purchase confirm: noto'g'ri secret | ip=%s", request.remote)
        return web.json_response({"error": "Unauthorized"}, status=403)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    click_order_id = data.get("click_order_id")
    invite_link = data.get("invite_link") or None

    if not click_order_id:
        return web.json_response({"error": "click_order_id required"}, status=400)

    click_order_id = int(click_order_id)

    # Idempotentlik tekshiruvi — takroriy webhookni e'tiborsiz qoldirish
    event_key = f"click:{click_order_id}"
    is_new = await db.try_claim_webhook_event(event_key, data)
    if not is_new:
        logger.info("Takroriy webhook e'tiborsiz qoldirildi: %s", event_key)
        return web.json_response({"success": True, "note": "already_processed"})

    # 1. Oddiy to'lovni tekshirish
    try:
        purchase = await db.approve_click_purchase(
            click_order_id=click_order_id,
            invite_link=invite_link,
        )
    except Exception as exc:
        logger.error("approve_click_purchase error: %s | click_order_id=%s", exc, click_order_id)
        return web.json_response({"error": "DB error"}, status=500)

    if purchase:
        logger.info("Purchase approved | purchase_id=%s | click_order_id=%s", purchase["id"], click_order_id)
        await _notify_regular_approved(purchase)
        return web.json_response({"success": True, "purchase_id": purchase["id"]})

    # 2. Bo'lib to'lash to'lovini tekshirish
    try:
        detail = await db.approve_installment_by_click(
            click_order_id=click_order_id,
            invite_link=invite_link,
        )
    except Exception as exc:
        logger.error("approve_installment_by_click error: %s | click_order_id=%s", exc, click_order_id)
        return web.json_response({"error": "DB error"}, status=500)

    if detail:
        logger.info(
            "Installment payment approved | inst_id=%s | click_order_id=%s",
            detail["id"], click_order_id,
        )
        await _notify_installment_approved(detail)
        return web.json_response({"success": True, "installment_payment_id": detail["id"]})

    logger.warning("Pending purchase topilmadi | click_order_id=%s", click_order_id)
    return web.json_response({"success": False, "note": "No pending purchase found"})


async def handle_healthcheck(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def make_payment_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/purchase/confirm/", handle_purchase_confirm)
    app.router.add_get("/health/", handle_healthcheck)
    return app
