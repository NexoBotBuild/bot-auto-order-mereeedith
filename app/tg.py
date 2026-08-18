"""Helper kecil terkait Telegram/aiogram."""
from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

# Kunci penyimpanan id "panel" (bubble bot yang di-edit terus) di FSM data.
PANEL_CHAT = "panel_chat_id"
PANEL_MSG = "panel_msg_id"


async def safe_edit(cb: CallbackQuery, text: str, reply_markup=None) -> None:
    """Edit teks pesan; abaikan error 'message is not modified'."""
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def remember_panel(state: FSMContext, message: Message) -> None:
    """Catat pesan ini sebagai panel admin yang akan di-edit selama alur berlangsung."""
    await state.update_data(**{PANEL_CHAT: message.chat.id, PANEL_MSG: message.message_id})


async def panel_update(message: Message, state: FSMContext, text: str,
                       reply_markup=None) -> None:
    """Perbarui panel admin (bubble tunggal) ketimbang mengirim pesan baru.

    Dipakai di handler yang dipicu oleh pesan teks admin (alur FSM): bot meng-EDIT
    bubble panel yang sudah ada. Jika panel tak bisa di-edit (mis. dihapus), kirim
    pesan baru lalu jadikan itu panel berikutnya.
    """
    data = await state.get_data()
    chat_id = data.get(PANEL_CHAT)
    msg_id = data.get(PANEL_MSG)
    if chat_id and msg_id:
        try:
            await message.bot.edit_message_text(
                text, chat_id=chat_id, message_id=msg_id, reply_markup=reply_markup
            )
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return
            # panel hilang → buat ulang di bawah
    sent = await message.answer(text, reply_markup=reply_markup)
    await state.update_data(**{PANEL_CHAT: sent.chat.id, PANEL_MSG: sent.message_id})
