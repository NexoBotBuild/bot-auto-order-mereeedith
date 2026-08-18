"""Entrypoint: jalankan webhook server (aiohttp) + bot polling + background task."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web

from app import config
from app.db import close_pool, init_pool
from app.handlers import (
    admin_broadcast,
    admin_orders,
    admin_products,
    admin_stock,
    buyer,
    common,
)
from app.middlewares import UserTrackingMiddleware
from app.services import pakasir
from app.tasks import start_background_tasks
from app.webhook import build_web_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # Rekam pengguna untuk broadcast (outer: jalan untuk semua update).
    tracker = UserTrackingMiddleware()
    dp.message.outer_middleware(tracker)
    dp.callback_query.outer_middleware(tracker)
    # common dulu (/start, /cancel, noop, close), lalu router admin, lalu buyer.
    dp.include_router(common.router)
    dp.include_router(admin_products.router)
    dp.include_router(admin_stock.router)
    dp.include_router(admin_orders.router)
    dp.include_router(admin_broadcast.router)
    dp.include_router(buyer.router)
    return dp


async def main() -> None:
    if not config.ADMIN_IDS:
        log.warning("ADMIN_IDS kosong — tidak ada yang bisa mengakses panel admin!")

    await init_pool()
    log.info("Pool DB siap.")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()

    # ---- web server (webhook Pakasir + health) ----
    web_app = build_web_app(bot)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
    await site.start()
    log.info("Web server jalan di port %s (POST /pakasir/webhook).", config.PORT)
    if config.PUBLIC_BASE_URL:
        log.info("Pasang webhook Pakasir ke: %s/pakasir/webhook", config.PUBLIC_BASE_URL)

    # ---- background tasks ----
    tasks = start_background_tasks(bot)

    # ---- jalankan polling Telegram ----
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Mulai polling Telegram…")
        await dp.start_polling(bot, handle_signals=True)
    finally:
        for t in tasks:
            t.cancel()
        await runner.cleanup()
        await pakasir.close_session()
        await bot.session.close()
        await close_pool()
        log.info("Shutdown selesai.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
