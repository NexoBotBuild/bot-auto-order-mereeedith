"""Keyboard sisi admin."""
from __future__ import annotations

import asyncpg
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.keyboards.common import number_buttons, pagination_row

# ---- Menu utama admin (reply keyboard) ----
BTN_KELOLA = "📦 Kelola Produk"
BTN_RIWAYAT = "📊 Riwayat Penjualan"
BTN_LAPORAN = "📈 Laporan Stok"
BTN_PENGATURAN = "⚙️ Pengaturan"
BTN_BROADCAST = "📢 Broadcast"
BTN_MODE_BUYER = "👁️ Lihat sebagai Buyer"

PREV = "⬅️ Sebelumnya"
NEXT = "Selanjutnya ➡️"

NUMS_PER_ROW = 5


def _menu_rows() -> list[list[KeyboardButton]]:
    return [
        [KeyboardButton(text=BTN_KELOLA)],
        [KeyboardButton(text=BTN_LAPORAN), KeyboardButton(text=BTN_RIWAYAT)],
        [KeyboardButton(text=BTN_BROADCAST), KeyboardButton(text=BTN_PENGATURAN)],
        [KeyboardButton(text=BTN_MODE_BUYER)],
    ]


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Kirim sekarang", callback_data="a:bcsend")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="a:cancel")],
    ])


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=_menu_rows(), resize_keyboard=True,
        input_field_placeholder="Menu admin…",
    )


def products_reply_kb(count: int) -> ReplyKeyboardMarkup:
    """Reply keyboard Kelola Produk: angka 1..count (pilih produk) + menu admin."""
    nums = [KeyboardButton(text=str(i + 1)) for i in range(count)]
    rows = [nums[i:i + NUMS_PER_ROW] for i in range(0, len(nums), NUMS_PER_ROW)]
    rows += _menu_rows()
    return ReplyKeyboardMarkup(
        keyboard=rows, resize_keyboard=True,
        input_field_placeholder="Tekan nomor produk…",
    )


def cancel_kb() -> InlineKeyboardMarkup:
    """Tombol batal untuk alur FSM."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Batal", callback_data="a:cancel")]
    ])


# ============================ KELOLA PRODUK ============================
def product_list_nav_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Inline pada pesan daftar produk: navigasi + tambah. Pilih produk via angka keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    nav = pagination_row("a:plist:", page, total_pages, PREV, NEXT)
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="➕ Tambah Produk", callback_data="a:padd")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_manage_kb(product_id: int, variants: list[asyncpg.Record],
                      page: int) -> InlineKeyboardMarkup:
    # angka = pilih varian (datanya di teks)
    cbs = [f"a:var:{v['id']}:{product_id}:{page}" for v in variants]
    rows = number_buttons(cbs, 1)
    rows.append([
        InlineKeyboardButton(text="➕ Tambah Varian", callback_data=f"a:vadd:{product_id}"),
        InlineKeyboardButton(text="📥 Tambah Stok", callback_data=f"a:stkpick:{product_id}:{page}"),
    ])
    rows.append([
        InlineKeyboardButton(text="✏️ Edit Produk", callback_data=f"a:pedit:{product_id}"),
        InlineKeyboardButton(text="🗑️ Hapus Produk", callback_data=f"a:pdel:{product_id}:{page}"),
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 Kembali", callback_data=f"a:plist:{page}"),
        InlineKeyboardButton(text="❌ Tutup", callback_data="a:close"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stocking_pick_kb(product_id: int, variants: list[asyncpg.Record],
                     page: int) -> InlineKeyboardMarkup:
    """Pilih varian mana yang mau ditambah stok (angka = pemilih, data di teks)."""
    cbs = [f"a:stk:{v['id']}" for v in variants]
    rows = number_buttons(cbs, 1)
    rows.append([
        InlineKeyboardButton(text="🔙 Kembali", callback_data=f"a:prod:{product_id}:{page}"),
        InlineKeyboardButton(text="❌ Tutup", callback_data="a:close"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def variant_manage_kb(variant_id: int, product_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Edit Harga/Nama", callback_data=f"a:vedit:{variant_id}"),
        ],
        [
            InlineKeyboardButton(text="📥 Tambah Stok", callback_data=f"a:stk:{variant_id}"),
            InlineKeyboardButton(text="📋 Lihat Stok", callback_data=f"a:vstk:{variant_id}:1"),
        ],
        [InlineKeyboardButton(text="🗑️ Hapus Varian", callback_data=f"a:vdel:{variant_id}:{product_id}:{page}")],
        [
            InlineKeyboardButton(text="🔙 Kembali", callback_data=f"a:prod:{product_id}:{page}"),
            InlineKeyboardButton(text="❌ Tutup", callback_data="a:close"),
        ],
    ])


def confirm_kb(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ya, hapus", callback_data=yes_cb),
            InlineKeyboardButton(text="❌ Batal", callback_data=no_cb),
        ]
    ])


# ---- Lihat stok varian (paginate). Angka = hapus item bernomor itu (data di teks) ----
def stock_view_kb(items: list[asyncpg.Record], variant_id: int, page: int,
                  total_pages: int, start_no: int) -> InlineKeyboardMarkup:
    cbs = [f"a:sdel:{s['id']}:{variant_id}:{page}" for s in items]
    rows = number_buttons(cbs, start_no)
    nav = pagination_row(f"a:vstk:{variant_id}:", page, total_pages, PREV, NEXT)
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔙 Kembali", callback_data=f"a:varback:{variant_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---- Selesai stocking ----
def stocking_done_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Selesai", callback_data="a:stkdone")],
        [InlineKeyboardButton(text="❌ Batal", callback_data="a:cancel")],
    ])


# ============================ LAPORAN STOK ============================
def stock_report_kb(page: int, total_pages: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav = pagination_row("a:rep:", page, total_pages, PREV, NEXT)
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="❌ Tutup", callback_data="a:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================ RIWAYAT PENJUALAN ============================
_RANGES = [("today", "Hari ini"), ("7d", "7 Hari"), ("all", "Semua")]


def sales_list_kb(orders: list[asyncpg.Record], range_key: str, page: int,
                  total_pages: int, start_no: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    # baris filter rentang
    rows.append([
        InlineKeyboardButton(
            text=("• " if rk == range_key else "") + label,
            callback_data=f"a:slist:{rk}:1",
        )
        for rk, label in _RANGES
    ])
    # angka = buka detail transaksi bernomor itu (data di teks)
    cbs = [f"a:sdet:{o['id']}:{range_key}:{page}" for o in orders]
    rows.extend(number_buttons(cbs, start_no))
    nav = pagination_row(f"a:slist:{range_key}:", page, total_pages, PREV, NEXT)
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="❌ Tutup", callback_data="a:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sales_detail_kb(range_key: str, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Kembali", callback_data=f"a:slist:{range_key}:{page}")],
        [InlineKeyboardButton(text="❌ Tutup", callback_data="a:close")],
    ])


# ============================ PENGATURAN ============================
def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit teks 'Cara Order'", callback_data="a:set:cara_order")],
        [InlineKeyboardButton(text="✏️ Edit teks 'Information'", callback_data="a:set:information")],
        [InlineKeyboardButton(text="❌ Tutup", callback_data="a:close")],
    ])
