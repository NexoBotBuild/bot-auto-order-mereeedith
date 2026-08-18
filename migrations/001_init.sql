-- =====================================================================
-- Bot Auto-Order — Skema database (Supabase / PostgreSQL)
-- Jalankan seluruh isi file ini di Supabase: SQL Editor > New query > Run
-- =====================================================================

-- ---------- PRODUK ----------
CREATE TABLE IF NOT EXISTS products (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT        NOT NULL,
    description TEXT        NOT NULL DEFAULT '',
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    sort_order  INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- VARIAN (durasi/paket dengan harga & stok sendiri) ----------
CREATE TABLE IF NOT EXISTS variants (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id  BIGINT      NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    price       BIGINT      NOT NULL CHECK (price >= 0),   -- rupiah, integer
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    sort_order  INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_variants_product ON variants(product_id);

-- ---------- ORDER ----------
CREATE TABLE IF NOT EXISTS orders (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id           TEXT        NOT NULL UNIQUE,          -- id unik untuk Pakasir
    buyer_tg_id        BIGINT      NOT NULL,
    buyer_username     TEXT,
    variant_id         BIGINT      REFERENCES variants(id) ON DELETE SET NULL,
    product_name_snap  TEXT        NOT NULL,
    variant_name_snap  TEXT        NOT NULL,
    qty                INTEGER     NOT NULL CHECK (qty > 0),
    unit_price         BIGINT      NOT NULL,
    total_amount       BIGINT      NOT NULL,                 -- qty * unit_price (sebelum fee)
    pakasir_total      BIGINT      NOT NULL,                 -- nominal yang ditagih (incl fee)
    status             TEXT        NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','paid','delivered','expired','cancelled')),
    payment_number     TEXT,                                 -- string QRIS dari Pakasir
    payment_method     TEXT,
    expired_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at            TIMESTAMPTZ,
    delivered_at       TIMESTAMPTZ,
    delivered_content  TEXT                                  -- snapshot konten yang dikirim
);
CREATE INDEX IF NOT EXISTS idx_orders_buyer   ON orders(buyer_tg_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);

-- ---------- STOK (1 baris = 1 unit yang bisa dikirim) ----------
CREATE TABLE IF NOT EXISTS stock_items (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    variant_id  BIGINT      NOT NULL REFERENCES variants(id) ON DELETE CASCADE,
    content     TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'available'
                CHECK (status IN ('available','reserved','sold')),
    order_id    BIGINT      REFERENCES orders(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    sold_at     TIMESTAMPTZ
);
-- Index utama untuk hitung stok available & ambil cepat (anti-oversell)
CREATE INDEX IF NOT EXISTS idx_stock_variant_status ON stock_items(variant_id, status);
CREATE INDEX IF NOT EXISTS idx_stock_order ON stock_items(order_id);

-- ---------- SETTINGS (teks yang bisa diedit admin) ----------
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO settings (key, value) VALUES
    ('cara_order', E'Cara order:\n1. Tekan 🛍️ List Produk\n2. Pilih produk lalu pilih varian\n3. Tentukan jumlah, tekan ✅ Pesan\n4. Scan QRIS yang muncul & bayar\n5. Produk otomatis dikirim ke chat ini setelah pembayaran berhasil.'),
    ('information', E'ℹ️ Toko digital otomatis 24 jam. Semua transaksi diproses oleh bot. Stok dikirim instan setelah pembayaran terkonfirmasi.')
ON CONFLICT (key) DO NOTHING;
