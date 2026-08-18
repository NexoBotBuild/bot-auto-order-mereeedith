"""Helper pembuatan keyboard yang dipakai bersama."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton

NOOP = "noop"  # callback untuk tombol indikator halaman (tidak melakukan apa-apa)


def number_buttons(callback_datas: list[str], start_no: int,
                   per_row: int = 5) -> list[list[InlineKeyboardButton]]:
    """Bikin tombol angka (1,2,3,…) — datanya ada di teks, tombol hanya pemilih.

    `callback_datas` urut sesuai item di teks; `start_no` nomor item pertama
    (untuk penomoran berkelanjutan antar halaman).
    """
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i, data in enumerate(callback_datas):
        row.append(InlineKeyboardButton(text=str(start_no + i), callback_data=data))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def pagination_row(prefix: str, page: int, total_pages: int,
                   prev_text: str = "◀️", next_text: str = "▶️",
                   page_text: str | None = None) -> list[InlineKeyboardButton]:
    """Baris navigasi: prev  Hal x/y  next.

    `prefix` adalah awalan callback; halaman ditambahkan jadi f"{prefix}{page}".
    Tombol prev/next tidak muncul jika sudah di ujung (tetap ada indikator halaman).
    """
    row: list[InlineKeyboardButton] = []
    if page > 1:
        row.append(InlineKeyboardButton(text=prev_text, callback_data=f"{prefix}{page - 1}"))
    label = page_text or f"Hal {page}/{total_pages}"
    row.append(InlineKeyboardButton(text=label, callback_data=NOOP))
    if page < total_pages:
        row.append(InlineKeyboardButton(text=next_text, callback_data=f"{prefix}{page + 1}"))
    return row
