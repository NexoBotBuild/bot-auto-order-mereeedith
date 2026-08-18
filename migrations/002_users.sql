-- =====================================================================
-- Tabel pengguna bot (untuk fitur broadcast)
-- Jalankan di Supabase: SQL Editor > New query > Run
-- =====================================================================

CREATE TABLE IF NOT EXISTS users (
    tg_id       BIGINT      PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,   -- FALSE jika user blokir bot
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);

-- Seed dari pembeli yang sudah ada (agar broadcast pertama menjangkau mereka)
INSERT INTO users (tg_id, username)
SELECT DISTINCT buyer_tg_id, buyer_username
FROM orders
ON CONFLICT (tg_id) DO NOTHING;
