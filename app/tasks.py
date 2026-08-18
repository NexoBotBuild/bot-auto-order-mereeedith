"""Background task: expire order kedaluwarsa & polling status pembayaran (cadangan)."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from app.db import get_pool
from app.keyboards import buyer as buyer_kb
from app.notify import notify_delivery
from app.services import orders as orders_svc
from app.services import pakasir

log = logging.getLogger(__name__)

EXPIRE_INTERVAL = 60       # detik
POLL_INTERVAL = 20         # detik
KEEPALIVE_INTERVAL = 240   # detik — jaga koneksi DB tetap "hangat"


async def keepalive_loop() -> None:
    """Ping DB berkala agar koneksi tidak ditutup saat idle → hindari spike
    handshake ulang (latency 2–5 dtk) pada aksi pertama setelah lama sepi."""
    while True:
        await asyncio.sleep(KEEPALIVE_INTERVAL)
        try:
            await get_pool().fetchval("SELECT 1")
        except Exception:  # noqa: BLE001
            log.exception("keepalive_loop error")


async def expire_loop(bot: Bot) -> None:
    """Tandai order pending yang lewat waktu jadi expired & beri tahu buyer."""
    while True:
        try:
            expired = await orders_svc.expire_due_orders()
            for o in expired:
                try:
                    await bot.send_message(
                        o["buyer_tg_id"],
                        "⌛ Pesanan kamu kedaluwarsa karena belum dibayar. "
                        "Stok sudah dikembalikan. Tekan 🛍️ List Produk untuk pesan lagi.",
                        reply_markup=buyer_kb.menu_reply_kb(),
                    )
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            log.exception("expire_loop error")
        await asyncio.sleep(EXPIRE_INTERVAL)


async def poll_payments_loop(bot: Bot) -> None:
    """Cadangan jika webhook gagal: cek status order pending ke Pakasir."""
    while True:
        try:
            pending = await orders_svc.list_pending_orders()
            for o in pending:
                try:
                    tx = await pakasir.check_status(o["order_id"], o["total_amount"])
                except Exception:  # noqa: BLE001
                    continue
                if pakasir.is_completed(tx):
                    res = await orders_svc.deliver_order(
                        o["id"], payment_method=tx.get("payment_method")
                    )
                    if res is not None:
                        await notify_delivery(bot, res)
        except Exception:  # noqa: BLE001
            log.exception("poll_payments_loop error")
        await asyncio.sleep(POLL_INTERVAL)


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    return [
        asyncio.create_task(expire_loop(bot)),
        asyncio.create_task(poll_payments_loop(bot)),
        asyncio.create_task(keepalive_loop()),
    ]
