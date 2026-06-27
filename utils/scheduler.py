from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, html

logger = logging.getLogger(__name__)

# Scheduler uchun PostgreSQL Advisory Lock ID (tizimda yagona raqam)
_SCHEDULER_LOCK_ID = 874561234


async def start_notification_scheduler(bot: Bot, db) -> None:
    logger.info("Installment notification scheduler started.")
    while True:
        await asyncio.sleep(3600)
        try:
            now = datetime.now(tz=timezone.utc)
            if 8 <= now.hour < 20:
                await _run_with_lock(bot, db)
        except Exception as exc:
            logger.error("Scheduler error: %s", exc)


async def _run_with_lock(bot: Bot, db) -> None:
    """Bir nechta bot nusxasi bo'lganda faqat bittasi ishlaydi (distributed lock)."""
    async with db.pool.acquire() as conn:
        acquired = await conn.fetchval(
            "SELECT pg_try_advisory_lock($1)", _SCHEDULER_LOCK_ID
        )
        if not acquired:
            logger.info("Scheduler: boshqa nusxa ishlayapti, o'tkazib yuborildi.")
            return
        try:
            await _send_due_notifications(bot, db)
        finally:
            await conn.execute("SELECT pg_advisory_unlock($1)", _SCHEDULER_LOCK_ID)


async def _send_due_notifications(bot: Bot, db) -> None:
    rows = await db.get_upcoming_due_installments()
    for row in rows:
        try:
            due_str = row["due_date"].strftime("%d.%m.%Y") if row.get("due_date") else "—"
            paid = row.get("paid_count", 0)
            total = row.get("installments_count", 1)
            text = (
                "⚠️ <b>Muddatli to'lov eslatmasi</b>\n\n"
                f"📚 Kurs: <b>{html.quote(row['course_name'])}</b>\n"
                f"💰 To'lanadigan summa: <b>{_fmt(row['amount'])}</b>\n"
                f"📅 To'lov sanasi: <b>{due_str}</b>\n"
                f"📊 Holat: {paid}/{total} to'lov amalga oshirilgan\n\n"
                "Iltimos, to'lovni o'z vaqtida amalga oshiring.\n"
                "'Mening sotib olganlarim' bo'limida keyingi to'lovni amalga oshiring."
            )
            await bot.send_message(chat_id=row["telegram_id"], text=text)
            await db.mark_installment_notified(row["id"])
        except Exception as exc:
            logger.warning("Could not notify %s: %s", row.get("telegram_id"), exc)
        await asyncio.sleep(0.1)


def _fmt(price: int) -> str:
    return f"{price:,}".replace(",", " ") + " so'm"
