"""Penyimpanan pengguna bot (untuk broadcast)."""
from __future__ import annotations

from app.db import get_pool


async def upsert_user(tg_id: int, username: str | None, first_name: str | None) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO users (tg_id, username, first_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (tg_id) DO UPDATE
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                is_active = TRUE,
                last_seen = now()
        """,
        tg_id, username, first_name,
    )


async def count_active_users() -> int:
    pool = get_pool()
    return await pool.fetchval("SELECT count(*) FROM users WHERE is_active")


async def active_user_ids() -> list[int]:
    pool = get_pool()
    rows = await pool.fetch("SELECT tg_id FROM users WHERE is_active ORDER BY tg_id")
    return [r["tg_id"] for r in rows]


async def set_inactive(tg_id: int) -> None:
    pool = get_pool()
    await pool.execute("UPDATE users SET is_active = FALSE WHERE tg_id = $1", tg_id)
