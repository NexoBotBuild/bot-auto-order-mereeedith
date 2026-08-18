"""Middleware: gate handler khusus admin."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from app import config


class IsAdmin(Filter):
    """Filter handler: hanya cocok bila pengirim adalah admin."""

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user is not None and config.is_admin(event.from_user.id)


class NotInContext(Filter):
    """Filter: cocok bila 'ctx' di FSM data BUKAN nilai tertentu.

    Dipakai pada handler angka admin agar TIDAK aktif saat admin sedang mode buyer
    (ctx='buyer') — sehingga angka diteruskan ke router buyer (perilaku buyer).
    """

    def __init__(self, ctx_value: str):
        self.ctx_value = ctx_value

    async def __call__(self, event: Message, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("ctx") != self.ctx_value


class UserTrackingMiddleware(BaseMiddleware):
    """Rekam pengguna (untuk broadcast). Pakai cache memori agar tidak menulis DB
    di tiap update — cukup sekali per user selama proses berjalan."""

    def __init__(self):
        self._seen: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None and not user.is_bot and user.id not in self._seen:
            self._seen.add(user.id)
            # Tulis di latar belakang — jangan menunda pemrosesan handler.
            asyncio.create_task(self._record(user))
        return await handler(event, data)

    async def _record(self, user) -> None:
        from app.services import users  # impor lokal untuk hindari siklus
        try:
            await users.upsert_user(user.id, user.username, user.first_name)
        except Exception:  # noqa: BLE001
            self._seen.discard(user.id)  # coba lagi lain kali


class AdminOnlyMiddleware(BaseMiddleware):
    """Pasang di router admin. Tolak user non-admin secara senyap/aman."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None or not config.is_admin(user.id):
            if isinstance(event, CallbackQuery):
                await event.answer("Akses khusus admin.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("⛔ Menu ini khusus admin.")
            return None
        return await handler(event, data)
