"""Server aiohttp: webhook pembayaran Pakasir + health check."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiohttp import web

from app.notify import notify_delivery
from app.services import orders as orders_svc
from app.services import pakasir

log = logging.getLogger(__name__)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def pakasir_webhook(request: web.Request) -> web.Response:
    bot: Bot = request.app["bot"]
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001
        log.warning("Webhook Pakasir: body bukan JSON")
        return web.json_response({"ok": False, "error": "invalid json"}, status=400)

    # Pakasir membungkus data di key 'payment'/'transaction' (sama seperti API lain).
    data = pakasir._unwrap(raw)
    order_id = str(data.get("order_id", ""))
    status = str(data.get("status", "")).lower()
    amount = data.get("amount")
    method = data.get("payment_method")
    log.info("Webhook Pakasir: order_id=%s status=%s amount=%s", order_id, status, amount)

    if not order_id or status != "completed":
        return web.json_response({"ok": True})  # akui terima, abaikan non-completed

    order = await orders_svc.get_order_by_orderid(order_id)
    if order is None:
        log.warning("Webhook: order_id %s tidak ditemukan", order_id)
        return web.json_response({"ok": True})

    # Verifikasi nominal cocok dengan catatan kita (anti-spoof)
    try:
        amt = int(amount)
        if amt not in (int(order["total_amount"]), int(order["pakasir_total"])):
            log.warning("Webhook: amount %s tidak cocok untuk %s", amt, order_id)
            return web.json_response({"ok": False, "error": "amount mismatch"}, status=400)
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "bad amount"}, status=400)

    res = await orders_svc.deliver_order(order["id"], payment_method=method)
    if res is not None:
        await notify_delivery(bot, res)
    return web.json_response({"ok": True})


def build_web_app(bot: Bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_post("/pakasir/webhook", pakasir_webhook)
    # GET ke path webhook (dari browser/crawler) → balas OK, bukan 405.
    app.router.add_get("/pakasir/webhook", health)
    return app
