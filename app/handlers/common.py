"""Handler umum: /start, /cancel, /admin, fallback, dan callback NOOP."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import config
from app.handlers.buyer import open_browser
from app.keyboards import admin as admin_kb
from app.keyboards.common import NOOP

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    name = message.from_user.first_name or "kak"
    if config.is_admin(message.from_user.id):
        await message.answer(
            f"👋 Halo admin <b>{name}</b>!\nPilih menu di bawah untuk mengelola <b>{config.STORE_NAME}</b>.",
            reply_markup=admin_kb.main_menu(),
        )
    else:
        await open_browser(message, state,
                           greeting=f"👋 Selamat datang di <b>{config.STORE_NAME}</b>, {name}!")


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not config.is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("🛠️ Panel admin:", reply_markup=admin_kb.main_menu())


@router.message(Command("cancel"))
@router.message(F.text.casefold() == "batal")
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    if config.is_admin(message.from_user.id):
        await message.answer("✅ Dibatalkan.", reply_markup=admin_kb.main_menu())
    else:
        await open_browser(message, state, greeting="✅ Dibatalkan. Silakan pilih produk:")


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    if config.is_admin(message.from_user.id):
        await message.answer("🛠️ Panel admin:", reply_markup=admin_kb.main_menu())
    else:
        await open_browser(message, state, greeting="🏠 Menu utama:")


# Tombol indikator halaman — tidak melakukan apa-apa
@router.callback_query(F.data == NOOP)
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()


# Tombol Tutup (buyer & admin) — hapus pesan inline
@router.callback_query(F.data.in_({"b:close", "a:close"}))
async def close_msg(cb: CallbackQuery) -> None:
    try:
        await cb.message.delete()
    except Exception:  # noqa: BLE001
        await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer()
