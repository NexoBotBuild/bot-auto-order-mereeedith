"""Query katalog: produk, varian, stok — semuanya berpaginasi.

Hasil baca untuk browsing (daftar produk/varian + hitungannya) di-cache singkat
di memori supaya geser halaman & buka produk terasa instan (tidak nembak DB tiap
kali). Cache otomatis dibersihkan saat admin mengubah produk/varian/stok.
"""
from __future__ import annotations

import time

from app import config
from app.db import get_pool

# ---- Cache TTL singkat untuk read browsing ----
_CACHE: dict = {}
# TTL panjang aman karena setiap perubahan (order/stok/admin) langsung clear cache.
_CACHE_TTL = 120.0


def _cache_get(key):
    hit = _CACHE.get(key)
    if hit is not None:
        if hit[0] > time.monotonic():
            return hit[1]
        _CACHE.pop(key, None)
    return None


def _cache_put(key, value):
    _CACHE[key] = (time.monotonic() + _CACHE_TTL, value)
    return value


def invalidate_cache() -> None:
    """Dipanggil setiap ada perubahan produk/varian/stok oleh admin."""
    _CACHE.clear()


# ============================ PRODUK ============================
async def count_products(active_only: bool = True) -> int:
    key = ("count_products", active_only)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    pool = get_pool()
    where = "WHERE is_active" if active_only else ""
    return _cache_put(key, await pool.fetchval(f"SELECT count(*) FROM products {where}"))


async def list_products(page: int, active_only: bool = True, page_size: int | None = None):
    """Daftar produk satu halaman. Setiap baris menyertakan jumlah varian & stok."""
    page_size = page_size or config.PAGE_SIZE
    key = ("list_products", page, active_only, page_size)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    pool = get_pool()
    offset = (page - 1) * page_size
    where = "WHERE p.is_active" if active_only else ""
    variant_filter = "AND v.is_active" if active_only else ""
    rows = await pool.fetch(
        f"""
        SELECT p.id, p.name, p.description, p.is_active,
               (SELECT count(*) FROM variants v
                 WHERE v.product_id = p.id {variant_filter}) AS variant_count,
               (SELECT count(*) FROM stock_items s
                  JOIN variants vs ON vs.id = s.variant_id
                 WHERE vs.product_id = p.id AND s.status = 'available') AS stock
        FROM products p
        {where}
        ORDER BY p.sort_order, p.id
        LIMIT $1 OFFSET $2
        """,
        page_size, offset,
    )
    return _cache_put(key, rows)


async def get_product(product_id: int):
    key = ("get_product", product_id)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    pool = get_pool()
    return _cache_put(key, await pool.fetchrow("SELECT * FROM products WHERE id = $1", product_id))


async def product_ids(active_only: bool = True, cap: int = 60) -> list[int]:
    """Daftar id produk terurut (untuk memetakan nomor keyboard → produk)."""
    key = ("product_ids", active_only, cap)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    pool = get_pool()
    where = "WHERE is_active" if active_only else ""
    rows = await pool.fetch(
        f"SELECT id FROM products {where} ORDER BY sort_order, id LIMIT $1", cap
    )
    return _cache_put(key, [r["id"] for r in rows])


async def create_product(name: str, description: str) -> int:
    pool = get_pool()
    pid = await pool.fetchval(
        "INSERT INTO products (name, description) VALUES ($1, $2) RETURNING id",
        name, description,
    )
    invalidate_cache()
    return pid


async def update_product(product_id: int, *, name: str | None = None,
                         description: str | None = None) -> None:
    pool = get_pool()
    if name is not None:
        await pool.execute("UPDATE products SET name = $2 WHERE id = $1", product_id, name)
    if description is not None:
        await pool.execute(
            "UPDATE products SET description = $2 WHERE id = $1", product_id, description
        )
    invalidate_cache()


async def delete_product(product_id: int) -> None:
    pool = get_pool()
    await pool.execute("DELETE FROM products WHERE id = $1", product_id)
    invalidate_cache()


# ============================ VARIAN ============================
async def list_variants(product_id: int, active_only: bool = True):
    """Semua varian satu produk + stok available. Jumlah varian per produk kecil,
    jadi tidak dipaginasi (cukup ditampilkan dalam satu pesan)."""
    key = ("list_variants", product_id, active_only)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    pool = get_pool()
    where = "AND v.is_active" if active_only else ""
    rows = await pool.fetch(
        f"""
        SELECT v.id, v.name, v.price, v.is_active,
               (SELECT count(*) FROM stock_items s
                 WHERE s.variant_id = v.id AND s.status = 'available') AS stock
        FROM variants v
        WHERE v.product_id = $1 {where}
        ORDER BY v.sort_order, v.id
        """,
        product_id,
    )
    return _cache_put(key, rows)


async def get_variant(variant_id: int):
    """Varian + nama produk + stok available (cache singkat untuk stepper qty)."""
    key = ("get_variant", variant_id)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT v.*, p.name AS product_name,
               (SELECT count(*) FROM stock_items s
                 WHERE s.variant_id = v.id AND s.status = 'available') AS stock
        FROM variants v
        JOIN products p ON p.id = v.product_id
        WHERE v.id = $1
        """,
        variant_id,
    )
    return _cache_put(key, row)


async def create_variant(product_id: int, name: str, price: int) -> int:
    pool = get_pool()
    vid = await pool.fetchval(
        "INSERT INTO variants (product_id, name, price) VALUES ($1, $2, $3) RETURNING id",
        product_id, name, price,
    )
    invalidate_cache()
    return vid


async def update_variant(variant_id: int, *, name: str | None = None,
                         price: int | None = None) -> None:
    pool = get_pool()
    if name is not None:
        await pool.execute("UPDATE variants SET name = $2 WHERE id = $1", variant_id, name)
    if price is not None:
        await pool.execute("UPDATE variants SET price = $2 WHERE id = $1", variant_id, price)
    invalidate_cache()


async def delete_variant(variant_id: int) -> None:
    pool = get_pool()
    await pool.execute("DELETE FROM variants WHERE id = $1", variant_id)
    invalidate_cache()


# ============================ STOK ============================
async def add_stock_bulk(variant_id: int, contents: list[str]) -> int:
    """Tambah banyak stok sekaligus. Mengembalikan jumlah yang ditambahkan."""
    if not contents:
        return 0
    pool = get_pool()
    rows = [(variant_id, c) for c in contents]
    await pool.executemany(
        "INSERT INTO stock_items (variant_id, content) VALUES ($1, $2)", rows
    )
    invalidate_cache()
    return len(rows)


async def available_stock_count(variant_id: int) -> int:
    pool = get_pool()
    return await pool.fetchval(
        "SELECT count(*) FROM stock_items WHERE variant_id = $1 AND status = 'available'",
        variant_id,
    )


async def list_stock(variant_id: int, page: int, page_size: int | None = None):
    """Lihat stok available satu varian (berpaginasi)."""
    pool = get_pool()
    page_size = page_size or config.PAGE_SIZE
    offset = (page - 1) * page_size
    return await pool.fetch(
        """
        SELECT id, content FROM stock_items
        WHERE variant_id = $1 AND status = 'available'
        ORDER BY id
        LIMIT $2 OFFSET $3
        """,
        variant_id, page_size, offset,
    )


async def delete_stock_item(stock_id: int) -> None:
    pool = get_pool()
    await pool.execute(
        "DELETE FROM stock_items WHERE id = $1 AND status = 'available'", stock_id
    )
    invalidate_cache()


# =================== LAPORAN STOK (paginate global) ===================
async def count_all_variants() -> int:
    pool = get_pool()
    return await pool.fetchval("SELECT count(*) FROM variants")


async def stock_report(page: int, page_size: int | None = None):
    """Laporan stok semua varian (produk + varian + jumlah available)."""
    pool = get_pool()
    page_size = page_size or config.PAGE_SIZE
    offset = (page - 1) * page_size
    return await pool.fetch(
        """
        SELECT v.id, v.name AS variant_name, p.name AS product_name,
               (SELECT count(*) FROM stock_items s
                 WHERE s.variant_id = v.id AND s.status = 'available') AS stock
        FROM variants v
        JOIN products p ON p.id = v.product_id
        ORDER BY p.sort_order, p.id, v.sort_order, v.id
        LIMIT $1 OFFSET $2
        """,
        page_size, offset,
    )


# ============================ SETTINGS ============================
async def get_setting(key: str, default: str = "") -> str:
    ck = ("setting", key)
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    pool = get_pool()
    val = await pool.fetchval("SELECT value FROM settings WHERE key = $1", key)
    return _cache_put(ck, val if val is not None else default)


async def set_setting(key: str, value: str) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO settings (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        key, value,
    )
    invalidate_cache()
