"""Notifikasi hasil pengiriman ke buyer & admin (dipakai webhook, polling, tombol cek)."""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from app import config
from app.services.orders import DeliveryResult
from app.utils import esc, rupiah

log = logging.getLogger(__name__)


def _delivered_text(res: DeliveryResult) -> str:
    o = res.order_row
    lines = [
        "✅ <b>Pembayaran berhasil!</b>",
        "",
        f"🧾 Order: <code>{esc(o['order_id'])}</code>",
        f"📦 {esc(o['product_name_snap'])} — {esc(o['variant_name_snap'])}",
        f"🔢 Jumlah: {o['qty']}",
        f"💰 Total: {rupiah(o['total_amount'])}",
        "",
        "🎁 <b>Produk kamu:</b>",
        f"<pre>{esc(res.content)}</pre>",
        "",
        "Terima kasih sudah berbelanja! 🙏",
    ]
    if res.shortage > 0:
        lines.insert(
            1,
            f"\n⚠️ {res.shortage} unit belum bisa dikirim otomatis (stok kurang). "
            "Admin akan segera menindaklanjuti.",
        )
    return "\n".join(lines)


async def notify_delivery(bot: Bot, res: DeliveryResult) -> None:
    """Kirim hasil pengiriman ke buyer. Jika ada kekurangan stok, beri tahu admin."""
    o = res.order_row
    try:
        await bot.send_message(o["buyer_tg_id"], _delivered_text(res))
    except TelegramBadRequest:
        log.exception("Gagal kirim notifikasi delivery ke buyer %s", o["buyer_tg_id"])

    if res.shortage > 0:
        warn = (
            "⚠️ <b>Stok kurang saat pengiriman</b>\n"
            f"Order <code>{esc(o['order_id'])}</code> "
            f"({esc(o['product_name_snap'])} — {esc(o['variant_name_snap'])})\n"
            f"Kurang {res.shortage} unit. Buyer: "
            f"<code>{o['buyer_tg_id']}</code> (@{esc(o['buyer_username']) or '-'})"
        )
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(admin_id, warn)
            except TelegramBadRequest:
                pass
