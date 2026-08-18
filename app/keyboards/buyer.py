"""Keyboard sisi buyer (model referensi).

- ANGKA produk = REPLY keyboard persisten (global, tidak berubah tiap halaman).
- NEXT/PREV = INLINE button pada pesan daftar (di-edit di tempat).
Keduanya tampil bersamaan karena reply keyboard menetap & nomornya global.
"""
from __future__ import annotations

import asyncpg
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app import config
from app.keyboards.common import number_buttons, pagination_row

PREV = "⬅️ Sebelumnya"
NEXT = "Selanjutnya ➡️"

# ---- Tombol menu (reply keyboard) ----
BTN_PRODUK = "🛍️ List Produk"
BTN_PESANAN = "📦 Pesanan Saya"
BTN_CARA = "❓ Cara Order"
BTN_INFO = "⚠️ Information"

NUMS_PER_ROW = 5


def _menu_rows() -> list[list[KeyboardButton]]:
    return [
        [KeyboardButton(text=BTN_PRODUK), KeyboardButton(text=BTN_PESANAN)],
        [KeyboardButton(text=BTN_CARA), KeyboardButton(text=BTN_INFO)],
    ]


def products_reply_kb(count: int) -> ReplyKeyboardMarkup:
    """Reply keyboard: angka 1..count (global) + menu. Set sekali, menetap."""
    nums = [KeyboardButton(text=str(i + 1)) for i in range(count)]
    rows = [nums[i:i + NUMS_PER_ROW] for i in range(0, len(nums), NUMS_PER_ROW)]
    rows += _menu_rows()
    return ReplyKeyboardMarkup(
        keyboard=rows, resize_keyboard=True,
        input_field_placeholder="Tekan nomor produk…",
    )


def menu_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=_menu_rows(), resize_keyboard=True,
        input_field_placeholder="Pilih menu…",
    )


# ---- Inline navigasi daftar produk (di pesan list) ----
def product_nav_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav = pagination_row("b:pg:", page, total_pages, PREV, NEXT)
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="❌ Tutup", callback_data="b:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---- Inline daftar varian (di pesan varian) ----
def variant_list_kb(variants: list[asyncpg.Record], list_page: int) -> InlineKeyboardMarkup:
    cbs = [f"b:var:{v['id']}:{list_page}" for v in variants]
    rows = number_buttons(cbs, 1)
    rows.append([
        InlineKeyboardButton(text="🔙 Kembali", callback_data=f"b:vback:{list_page}"),
        InlineKeyboardButton(text="❌ Tutup", callback_data="b:close"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---- Inline pemilih jumlah (qty) ----
def qty_kb(variant_id: int, list_page: int, qty: int, max_qty: int) -> InlineKeyboardMarkup:
    dec = max(1, qty - 1)
    inc = min(max_qty, qty + 1)
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➖", callback_data=f"b:qty:{variant_id}:{list_page}:{dec}"),
            InlineKeyboardButton(text=f"{qty}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"b:qty:{variant_id}:{list_page}:{inc}"),
        ],
        [InlineKeyboardButton(text=f"✅ Pesan {qty} pcs", callback_data=f"b:buy:{variant_id}:{qty}")],
        [
            InlineKeyboardButton(text="🔙 Kembali", callback_data=f"b:vback:{list_page}"),
            InlineKeyboardButton(text="❌ Batal", callback_data="b:close"),
        ],
    ])


# ---- Inline pembayaran (di pesan foto QR) ----
def payment_kb(order_pk: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔄 Cek Status Bayar", callback_data=f"b:chk:{order_pk}")],
    ]
    if config.SANDBOX_TESTING:
        rows.append([InlineKeyboardButton(
            text="🧪 Simulasikan Bayar (Testing)", callback_data=f"b:sim:{order_pk}",
        )])
    rows.append([InlineKeyboardButton(text="❌ Batalkan Pesanan", callback_data=f"b:cxl:{order_pk}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---- Inline pesanan saya ----
def orders_kb(orders: list[asyncpg.Record], page: int,
              total_pages: int, start_no: int) -> InlineKeyboardMarkup:
    cbs = [f"b:odet:{o['id']}:{page}" for o in orders]
    rows = number_buttons(cbs, start_no)
    nav = pagination_row("b:olist:", page, total_pages, PREV, NEXT)
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="❌ Tutup", callback_data="b:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_detail_back_kb(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔙 Kembali", callback_data=f"b:olist:{page}"),
            InlineKeyboardButton(text="❌ Tutup", callback_data="b:close"),
        ],
    ])
