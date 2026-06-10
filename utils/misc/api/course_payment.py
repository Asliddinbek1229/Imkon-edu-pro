from __future__ import annotations

import logging

import aiohttp

from data.config import COURSE_INTEGRATION_KEY, COURSE_PAYMENT_API_BASE

logger = logging.getLogger(__name__)

_HEADERS = {"X-Integration-Key": COURSE_INTEGRATION_KEY, "Content-Type": "application/json"}
_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def create_course_payment(
    tg_id: int,
    course_id: int,
    course_name: str,
    course_link: str,
    amount: int,
) -> dict | None:
    url = f"{COURSE_PAYMENT_API_BASE.rstrip('/')}/bot/pro/course/create/"
    payload = {
        "tg_id": tg_id,
        "course_id": course_id,
        "course_name": course_name,
        "course_link": course_link or "",
        "amount": str(amount),
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=_HEADERS, timeout=_TIMEOUT) as resp:
                data = await resp.json()
                if resp.status in (200, 201):
                    return data
                logger.warning("course_payment API error: status=%s body=%s", resp.status, data)
                return None
    except Exception:
        logger.exception("create_course_payment request failed")
        return None


async def check_order_status(order_id: int) -> dict | None:
    """Django dan order holati va course_link ni oladi."""
    url = f"{COURSE_PAYMENT_API_BASE.rstrip('/')}/bot/pro/course/status/{order_id}/"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_HEADERS, timeout=_TIMEOUT) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
    except Exception:
        logger.warning("check_order_status request failed | order_id=%s", order_id)
        return None
