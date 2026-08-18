"""Helper kecil yang dipakai lintas modul."""
from __future__ import annotations

import html
import math
from datetime import datetime, timezone, timedelta

# Zona waktu WIB untuk tampilan
WIB = timezone(timedelta(hours=7))


def rupiah(amount: int | float) -> str:
    """Format angka jadi 'Rp10.000'."""
    return "Rp" + f"{int(amount):,}".replace(",", ".")


def esc(text: str | None) -> str:
    """Escape untuk parse_mode HTML."""
    return html.escape(str(text)) if text is not None else ""


def total_pages(total_items: int, page_size: int) -> int:
    return max(1, math.ceil(total_items / page_size)) if total_items else 1


def clamp_page(page: int, total: int, page_size: int) -> int:
    tp = total_pages(total, page_size)
    return min(max(1, page), tp)


def fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(WIB).strftime("%d/%m/%Y %H:%M")
