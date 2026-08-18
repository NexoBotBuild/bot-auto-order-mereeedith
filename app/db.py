"""Pool koneksi asyncpg ke Postgres (Supabase)."""
from __future__ import annotations

import logging

import asyncpg

from app import config

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    """Buat pool koneksi. Dipanggil sekali saat startup."""
    global _pool
    if _pool is None:
        # Transaction pooler (port 6543) tidak mendukung prepared statement →
        # cache harus 0. Session pooler / direct (5432) mendukung → aktifkan
        # cache supaya query jauh lebih cepat (tidak prepare ulang tiap kali).
        is_txn_pooler = ":6543" in config.DATABASE_URL
        if is_txn_pooler:
            log.warning(
                "DATABASE_URL pakai TRANSACTION pooler (port 6543) → lebih lambat "
                "(prepared-statement cache dimatikan). Untuk kecepatan, ganti ke "
                "SESSION pooler port 5432."
            )
        _pool = await asyncpg.create_pool(
            dsn=config.DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=30,
            max_inactive_connection_lifetime=300,
            statement_cache_size=0 if is_txn_pooler else 256,
        )
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Pool belum diinisialisasi. Panggil init_pool() dulu.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
