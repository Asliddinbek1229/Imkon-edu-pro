from __future__ import annotations

import logging

from aiohttp import web

from data.config import BOT_PAYMENT_SERVER_SECRET
from loader import db

logger = logging.getLogger(__name__)


async def handle_purchase_confirm(request: web.Request) -> web.Response:
    secret = request.headers.get("X-Bot-Secret", "")
    if BOT_PAYMENT_SERVER_SECRET and secret != BOT_PAYMENT_SERVER_SECRET:
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

    try:
        purchase = await db.approve_click_purchase(
            click_order_id=int(click_order_id),
            invite_link=invite_link,
        )
    except Exception as exc:
        logger.error("approve_click_purchase xatolik: %s | click_order_id=%s", exc, click_order_id)
        return web.json_response({"error": "DB error"}, status=500)

    if purchase:
        logger.info(
            "Purchase tasdiqlandi | purchase_id=%s | click_order_id=%s",
            purchase["id"], click_order_id,
        )
        return web.json_response({"success": True, "purchase_id": purchase["id"]})

    logger.warning("Pending purchase topilmadi | click_order_id=%s", click_order_id)
    return web.json_response({"success": False, "note": "No pending purchase found"})


async def handle_healthcheck(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def make_payment_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/api/purchase/confirm/", handle_purchase_confirm)
    app.router.add_get("/health/", handle_healthcheck)
    return app
