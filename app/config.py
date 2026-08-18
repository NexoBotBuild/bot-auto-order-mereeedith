"""Konfigurasi terpusat — dibaca dari environment variable."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Environment variable '{key}' wajib diisi. Lihat .env.example")
    return val


def _parse_admin_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return ids


# ---- Telegram ----
BOT_TOKEN: str = _require("BOT_TOKEN")
ADMIN_IDS: set[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

# ---- Database ----
DATABASE_URL: str = _require("DATABASE_URL")

# ---- Pakasir ----
PAKASIR_PROJECT: str = _require("PAKASIR_PROJECT")
PAKASIR_API_KEY: str = _require("PAKASIR_API_KEY")
PAKASIR_BASE_URL: str = os.getenv("PAKASIR_BASE_URL", "https://app.pakasir.com").rstrip("/")

# Tombol "Simulasikan Bayar" di chat buyer — HANYA untuk project Pakasir Sandbox.
# WAJIB false/hapus sebelum project Pakasir di-set ke Production.
SANDBOX_TESTING: bool = os.getenv("SANDBOX_TESTING", "false").strip().lower() == "true"

# ---- Web server ----
PORT: int = int(os.getenv("PORT", "8080"))
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# ---- Toko / lain-lain ----
STORE_NAME: str = os.getenv("STORE_NAME", "Auto Order Bot")
ORDER_EXPIRE_SECONDS: int = int(os.getenv("ORDER_EXPIRE_SECONDS", "1800"))

# Ukuran halaman pagination
PAGE_SIZE: int = 8


def is_admin(tg_id: int | None) -> bool:
    return tg_id is not None and tg_id in ADMIN_IDS
