"""Logika order: buat + reserve stok (anti-oversell), deliver, expire, riwayat."""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import asyncpg

from app import config
from app.db import get_pool
from app.services import catalog, pakasir

log = logging.getLogger(__name__)


class NotEnoughStock(Exception):
    def __init__(self, available: int):
        self.available = available
        super().__init__(f"Stok tidak cukup (tersisa {available}).")


@dataclass
class CreatedOrder:
    id: int
    order_id: str
    payment_number: str
    pakasir_total: int
    total_amount: int
    expired_at: datetime
    product_name: str
    variant_name: str
    qty: int


@dataclass
class DeliveryResult:
    delivered: bool          # True jika semua qty terkirim
    content: str             # konten yang dikirim ke buyer
    shortage: int            # berapa unit yang gagal dikirim (kurang stok)
    order_row: asyncpg.Record


def _gen_order_id() -> str:
    return f"ORD{int(time.time())}{secrets.token_hex(3).upper()}"


# ============================ BUAT ORDER ============================
async def create_order(buyer_tg_id: int, buyer_username: str | None,
                       variant_id: int, qty: int) -> CreatedOrder:
    """Reserve stok + buat order + transaksi QRIS Pakasir.

    Stok di-reserve dulu (atomic, FOR UPDATE SKIP LOCKED) supaya dua buyer
    tidak bisa merebut unit yang sama.
    """
    pool = get_pool()
    order_id = _gen_order_id()

    async with pool.acquire() as conn:
        async with conn.transaction():
            variant = await conn.fetchrow(
                """
                SELECT v.id, v.name, v.price, p.name AS product_name
                FROM variants v JOIN products p ON p.id = v.product_id
                WHERE v.id = $1
                FOR UPDATE OF v
                """,
                variant_id,
            )
            if variant is None:
                raise NotEnoughStock(0)

            # Ambil & kunci stok yang tersedia
            stock_rows = await conn.fetch(
                """
                SELECT id FROM stock_items
                WHERE variant_id = $1 AND status = 'available'
                ORDER BY id
                FOR UPDATE SKIP LOCKED
                LIMIT $2
                """,
                variant_id, qty,
            )
            if len(stock_rows) < qty:
                raise NotEnoughStock(len(stock_rows))

            unit_price = int(variant["price"])
            total_amount = unit_price * qty

            order_pk = await conn.fetchval(
                """
                INSERT INTO orders
                    (order_id, buyer_tg_id, buyer_username, variant_id,
                     product_name_snap, variant_name_snap, qty, unit_price,
                     total_amount, pakasir_total, status)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$9,'pending')
                RETURNING id
                """,
                order_id, buyer_tg_id, buyer_username, variant_id,
                variant["product_name"], variant["name"], qty, unit_price,
                total_amount,
            )

            stock_ids = [r["id"] for r in stock_rows]
            await conn.execute(
                "UPDATE stock_items SET status='reserved', order_id=$1 WHERE id = ANY($2::bigint[])",
                order_pk, stock_ids,
            )

    catalog.invalidate_cache()  # stok available berkurang → segarkan tampilan

    # Panggil Pakasir di luar transaksi DB
    try:
        tx = await pakasir.create_qris(order_id, total_amount)
    except Exception:
        log.exception("Gagal membuat QRIS, melepas reservasi order %s", order_id)
        await _release_and_cancel(order_pk)
        raise

    expired_at = tx.expired_at or (
        datetime.now(timezone.utc) + timedelta(seconds=config.ORDER_EXPIRE_SECONDS)
    )
    await pool.execute(
        """
        UPDATE orders
        SET payment_number=$2, pakasir_total=$3, expired_at=$4, payment_method=$5
        WHERE id = $1
        """,
        order_pk, tx.payment_number, tx.total_payment, expired_at, tx.payment_method,
    )

    return CreatedOrder(
        id=order_pk,
        order_id=order_id,
        payment_number=tx.payment_number,
        pakasir_total=tx.total_payment,
        total_amount=total_amount,
        expired_at=expired_at,
        product_name=variant["product_name"],
        variant_name=variant["name"],
        qty=qty,
    )


async def _release_and_cancel(order_pk: int) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE stock_items SET status='available', order_id=NULL "
                "WHERE order_id=$1 AND status='reserved'",
                order_pk,
            )
            await conn.execute(
                "UPDATE orders SET status='cancelled' WHERE id=$1 AND status='pending'",
                order_pk,
            )
    catalog.invalidate_cache()


# ============================ DELIVER ============================
async def deliver_order(order_pk: int, payment_method: str | None = None) -> DeliveryResult | None:
    """Tandai order dibayar lalu kirim stok. Idempotent: aman dipanggil berkali-kali.

    Mengembalikan None jika order tidak ada / sudah delivered sebelumnya (tidak ada
    aksi baru). Jika baru delivered, kembalikan DeliveryResult.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT * FROM orders WHERE id=$1 FOR UPDATE", order_pk
            )
            if order is None:
                return None
            if order["status"] == "delivered":
                return None  # sudah dikirim, jangan dobel
            if order["status"] in ("expired", "cancelled"):
                # Order kadung batal tapi pembayaran masuk — tetap usahakan kirim.
                pass

            qty = order["qty"]
            variant_id = order["variant_id"]

            # Stok yang sudah direservasi untuk order ini
            reserved = await conn.fetch(
                "SELECT id, content FROM stock_items WHERE order_id=$1 AND status='reserved' ORDER BY id",
                order_pk,
            )

            # Kalau kurang (mis. reservasi sempat dilepas saat expired), coba ambil lagi
            if len(reserved) < qty and variant_id is not None:
                need = qty - len(reserved)
                extra = await conn.fetch(
                    """
                    SELECT id, content FROM stock_items
                    WHERE variant_id=$1 AND status='available'
                    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT $2
                    """,
                    variant_id, need,
                )
                if extra:
                    await conn.execute(
                        "UPDATE stock_items SET status='reserved', order_id=$1 "
                        "WHERE id = ANY($2::bigint[])",
                        order_pk, [r["id"] for r in extra],
                    )
                    reserved = list(reserved) + list(extra)

            delivered_rows = reserved[:qty]
            shortage = qty - len(delivered_rows)
            content = "\n".join(r["content"] for r in delivered_rows)

            now = datetime.now(timezone.utc)
            if delivered_rows:
                await conn.execute(
                    "UPDATE stock_items SET status='sold', sold_at=$2 "
                    "WHERE id = ANY($1::bigint[])",
                    [r["id"] for r in delivered_rows], now,
                )

            new_status = "delivered" if shortage == 0 else "paid"
            await conn.execute(
                """
                UPDATE orders
                SET status=$2,
                    paid_at=COALESCE(paid_at, $3),
                    delivered_at=CASE WHEN $2='delivered' THEN $3 ELSE delivered_at END,
                    delivered_content=$4,
                    payment_method=COALESCE($5, payment_method)
                WHERE id=$1
                """,
                order_pk, new_status, now, content, payment_method,
            )
            order = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", order_pk)

    catalog.invalidate_cache()  # stok jadi sold → segarkan tampilan
    return DeliveryResult(
        delivered=(shortage == 0),
        content=content,
        shortage=shortage,
        order_row=order,
    )


# ============================ EXPIRE ============================
async def expire_due_orders() -> list[asyncpg.Record]:
    """Tandai order pending yang lewat waktu jadi expired & lepas stoknya.
    Mengembalikan daftar order yang baru saja di-expire (untuk notifikasi)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            due = await conn.fetch(
                """
                SELECT id, buyer_tg_id FROM orders
                WHERE status='pending' AND expired_at IS NOT NULL AND expired_at < now()
                FOR UPDATE SKIP LOCKED
                """
            )
            if not due:
                return []
            ids = [r["id"] for r in due]
            await conn.execute(
                "UPDATE stock_items SET status='available', order_id=NULL "
                "WHERE order_id = ANY($1::bigint[]) AND status='reserved'",
                ids,
            )
            await conn.execute(
                "UPDATE orders SET status='expired' WHERE id = ANY($1::bigint[])", ids
            )
    catalog.invalidate_cache()  # stok kembali available
    return due


async def cancel_order(order_pk: int, buyer_tg_id: int) -> bool:
    """Buyer membatalkan order pending miliknya sendiri. True jika berhasil."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT id, status FROM orders WHERE id=$1 AND buyer_tg_id=$2 FOR UPDATE",
                order_pk, buyer_tg_id,
            )
            if order is None or order["status"] != "pending":
                return False
            await conn.execute(
                "UPDATE stock_items SET status='available', order_id=NULL "
                "WHERE order_id=$1 AND status='reserved'",
                order_pk,
            )
            await conn.execute("UPDATE orders SET status='cancelled' WHERE id=$1", order_pk)
    catalog.invalidate_cache()  # stok kembali available
    return True


async def get_order(order_pk: int):
    pool = get_pool()
    return await pool.fetchrow("SELECT * FROM orders WHERE id=$1", order_pk)


async def get_order_by_orderid(order_id: str):
    pool = get_pool()
    return await pool.fetchrow("SELECT * FROM orders WHERE order_id=$1", order_id)


async def list_pending_orders():
    pool = get_pool()
    return await pool.fetch(
        "SELECT id, order_id, total_amount FROM orders WHERE status='pending'"
    )


# ============================ RIWAYAT ============================
_RANGE_SQL = {
    "today": "AND created_at >= date_trunc('day', now())",
    "7d": "AND created_at >= now() - interval '7 days'",
    "all": "",
}
# Hanya order yang menghasilkan uang dihitung pada riwayat penjualan
_PAID_STATUSES = "('paid','delivered')"


async def count_sales(range_key: str) -> int:
    pool = get_pool()
    rng = _RANGE_SQL.get(range_key, "")
    return await pool.fetchval(
        f"SELECT count(*) FROM orders WHERE status IN {_PAID_STATUSES} {rng}"
    )


async def sales_summary(range_key: str) -> tuple[int, int]:
    """(jumlah transaksi, total omzet) untuk rentang waktu."""
    pool = get_pool()
    rng = _RANGE_SQL.get(range_key, "")
    row = await pool.fetchrow(
        f"""SELECT count(*) AS n, COALESCE(sum(total_amount),0) AS omzet
            FROM orders WHERE status IN {_PAID_STATUSES} {rng}"""
    )
    return int(row["n"]), int(row["omzet"])


async def list_sales(range_key: str, page: int, page_size: int | None = None):
    pool = get_pool()
    page_size = page_size or config.PAGE_SIZE
    offset = (page - 1) * page_size
    rng = _RANGE_SQL.get(range_key, "")
    return await pool.fetch(
        f"""
        SELECT id, order_id, buyer_tg_id, buyer_username, product_name_snap,
               variant_name_snap, qty, total_amount, status, created_at, paid_at
        FROM orders
        WHERE status IN {_PAID_STATUSES} {rng}
        ORDER BY created_at DESC
        LIMIT $1 OFFSET $2
        """,
        page_size, offset,
    )


# Riwayat order milik buyer (semua status)
async def count_buyer_orders(buyer_tg_id: int) -> int:
    pool = get_pool()
    return await pool.fetchval(
        "SELECT count(*) FROM orders WHERE buyer_tg_id=$1", buyer_tg_id
    )


async def list_buyer_orders(buyer_tg_id: int, page: int, page_size: int | None = None):
    pool = get_pool()
    page_size = page_size or config.PAGE_SIZE
    offset = (page - 1) * page_size
    return await pool.fetch(
        """
        SELECT id, order_id, product_name_snap, variant_name_snap, qty,
               total_amount, status, created_at
        FROM orders
        WHERE buyer_tg_id=$1
        ORDER BY created_at DESC
        LIMIT $2 OFFSET $3
        """,
        buyer_tg_id, page_size, offset,
    )
