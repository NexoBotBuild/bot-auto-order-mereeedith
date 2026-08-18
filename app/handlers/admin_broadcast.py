"""Handler admin: Broadcast pesan ke semua pengguna (stabil, throttled, background)."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.keyboards import admin as kb
from app.middlewares import AdminOnlyMiddleware
from app.services import users
from app.states import Broadcast

log = logging.getLogger(__name__)
router = Router(name="admin_broadcast")
router.message.middleware(AdminOnlyMiddleware())
router.callback_query.middleware(AdminOnlyMiddleware())

# Throttle: ~20 pesan/detik (aman di bawah limit Telegram ~30/dtk)
SEND_DELAY = 0.05
PROGRESS_EVERY = 25

_running = False  # cegah broadcast ganda berjalan bersamaan


@router.message(F.text == kb.BTN_BROADCAST)
async def broadcast_start(message: Message, state: FSMContext) -> None:
    if _running:
        await message.answer("⏳ Broadcast lain sedang berjalan. Tunggu selesai dulu.")
        return
    await state.set_state(Broadcast.waiting)
    await message.answer(
        "📢 <b>BROADCAST</b>\n\n"
        "Kirim pesan yang mau disiarkan (teks, foto, atau media apa pun).\n"
        "Pesan akan disalin apa adanya ke semua pengguna.\n\n"
        "Ketik /cancel untuk batal.",
        reply_markup=kb.cancel_kb(),
    )


@router.message(Broadcast.waiting)
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    total = await users.count_active_users()
    if total == 0:
        await state.clear()
        await message.answer("Belum ada pengguna untuk disiarkan.", reply_markup=kb.main_menu())
        return
    await state.set_state(None)
    await state.update_data(bc_chat=message.chat.id, bc_msg=message.message_id)
    await message.answer(
        f"📢 Kirim pesan ini ke <b>{total}</b> pengguna?",
        reply_markup=kb.broadcast_confirm_kb(),
    )


@router.callback_query(F.data == "a:bcsend")
async def broadcast_send(cb: CallbackQuery, state: FSMContext) -> None:
    global _running
    if _running:
        await cb.answer("Broadcast lain sedang berjalan.", show_alert=True)
        return
    data = await state.get_data()
    src_chat = data.get("bc_chat")
    src_msg = data.get("bc_msg")
    await state.clear()
    if not src_chat or not src_msg:
        await cb.answer("Konten broadcast tidak ditemukan, ulangi.", show_alert=True)
        return

    await cb.answer()
    try:
        await cb.message.edit_text("📤 Memulai broadcast…", reply_markup=None)
    except TelegramBadRequest:
        pass

    _running = True
    asyncio.create_task(
        _do_broadcast(cb.bot, cb.message.chat.id, cb.message.message_id, src_chat, src_msg)
    )


async def _do_broadcast(bot: Bot, status_chat: int, status_msg: int,
                        src_chat: int, src_msg: int) -> None:
    global _running
    sent = failed = blocked = 0
    try:
        ids = await users.active_user_ids()
        total = len(ids)
        for i, uid in enumerate(ids, start=1):
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=src_chat, message_id=src_msg)
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
                try:
                    await bot.copy_message(chat_id=uid, from_chat_id=src_chat, message_id=src_msg)
                    sent += 1
                except Exception:  # noqa: BLE001
                    failed += 1
            except TelegramForbiddenError:
                blocked += 1
                await users.set_inactive(uid)
            except TelegramBadRequest:
                failed += 1
            except Exception:  # noqa: BLE001
                log.exception("Broadcast gagal kirim ke %s", uid)
                failed += 1

            if i % PROGRESS_EVERY == 0:
                await _edit_status(
                    bot, status_chat, status_msg,
                    f"📤 Broadcast berjalan…\n\n"
                    f"Progress: {i}/{total}\n✅ {sent}  ⛔ {blocked}  ⚠️ {failed}",
                )
            await asyncio.sleep(SEND_DELAY)

        await _edit_status(
            bot, status_chat, status_msg,
            f"✅ <b>Broadcast selesai!</b>\n\n"
            f"👥 Total: {total}\n✅ Terkirim: {sent}\n"
            f"⛔ Diblokir/nonaktif: {blocked}\n⚠️ Gagal: {failed}",
        )
    finally:
        _running = False


async def _edit_status(bot: Bot, chat: int, msg: int, text: str) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat, message_id=msg)
    except TelegramBadRequest:
        pass
