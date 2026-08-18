# Auto Order Bot — Auto-Order Telegram

Bot Telegram untuk jualan produk digital **otomatis**: admin masukkan produk, harga, dan stok; buyer browse → pesan → bayar **QRIS (Pakasir)** → stok **terkirim otomatis**. Dua sisi (admin & buyer), pagination di semua daftar, tombol cancel/back jelas di tiap langkah.

## Fitur

**Buyer**
- 🛍️ List Produk — navigasi produk & varian (inline, paginate, edit-in-place tanpa flicker)
- Pilih varian → atur jumlah → bayar QRIS → produk dikirim otomatis
- 📦 Pesanan Saya — riwayat order + lihat konten yang diterima
- ❓ Cara Order, ⚠️ Information (teksnya bisa diedit admin)

**Admin** (dikenali via `ADMIN_IDS`)
- 📦 Kelola Produk — CRUD produk & varian (paginate). Di tiap produk ada tombol **Tambah Varian / Tambah Stok / Edit Produk / Hapus** sejajar. **Tambah Stok** bulk: **pisahkan tiap stok dengan baris baru (Enter)**, 1 baris = 1 stok
- 📈 Laporan Stok — jumlah stok tiap varian (tanda ⚠️ untuk stok menipis)
- 📊 Riwayat Penjualan — paginate, filter Hari ini / 7 hari / Semua, ringkasan omzet, detail per transaksi
- 📢 Broadcast — kirim pesan (teks/foto/media) ke semua pengguna, throttled & jalan di background (handle flood + skip yang blokir bot)
- ⚙️ Pengaturan — edit teks "Cara Order" & "Information"

## Stack
Python 3.11+ · aiogram 3 · asyncpg (Supabase Postgres) · aiohttp (webhook) · qrcode/Pillow · Pakasir (QRIS)

## Struktur
```
app/
  main.py          entrypoint (web server + polling + background task)
  config.py db.py states.py middlewares.py utils.py tg.py notify.py tasks.py webhook.py
  keyboards/       buyer.py admin.py common.py
  handlers/        common.py buyer.py admin_products.py admin_stock.py admin_orders.py
  services/        catalog.py orders.py pakasir.py qr.py
migrations/001_init.sql
```

## Setup

### 1. Supabase (database)
1. Buat project di [supabase.com](https://supabase.com).
2. Buka **SQL Editor → New query**, tempel seluruh isi `migrations/001_init.sql`, **Run**.
   Lalu jalankan juga `migrations/002_users.sql` (tabel pengguna untuk fitur broadcast).
3. **Project Settings → Database → Connection string → Transaction pooler** (port `6543`).
   Salin sebagai `DATABASE_URL` (ganti `[YOUR-PASSWORD]` dengan password DB).

### 2. Pakasir (pembayaran QRIS)
1. Daftar & buat project di [pakasir.com](https://pakasir.com).
2. Ambil **slug project** → `PAKASIR_PROJECT` dan **API key** → `PAKASIR_API_KEY`.
3. Setelah deploy, pasang **Webhook URL** di dashboard Pakasir ke:
   `https://<domain-railway-kamu>/pakasir/webhook`

### 3. Telegram
1. Buat bot via [@BotFather](https://t.me/BotFather) → `BOT_TOKEN`.
2. Cari Telegram ID kamu via [@userinfobot](https://t.me/userinfobot) → `ADMIN_IDS`.

### 4. Jalankan lokal
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # lalu isi semua nilainya
python -m app.main
```
Lokal: webhook Pakasir tidak akan masuk (tidak ada domain publik), tapi tombol **🔄 Cek Status Bayar** dan **polling cadangan** tetap mengonfirmasi pembayaran.

### 5. Deploy Railway
1. Push repo ke GitHub, lalu **New Project → Deploy from GitHub** di Railway.
2. Tab **Variables**: isi `BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL`, `PAKASIR_PROJECT`, `PAKASIR_API_KEY`, `PUBLIC_BASE_URL` (= domain Railway), `STORE_NAME`.
   `PORT` diisi otomatis oleh Railway.
3. Start command sudah ada di `Procfile`/`railway.json`: `python -m app.main`.
4. Generate domain (Settings → Networking), lalu pasang webhook Pakasir ke `https://<domain>/pakasir/webhook`.

## Cara kerja anti-oversell
Saat buyer membuat order, stok langsung **di-reserve** (`SELECT ... FOR UPDATE SKIP LOCKED`) sehingga dua buyer tak bisa merebut unit yang sama. Bayar → stok jadi `sold` & dikirim. Batal/kedaluwarsa → stok kembali `available`. Pengiriman bersifat **idempotent** (aman walau webhook + polling + tombol cek jalan bersamaan).

## Catatan integrasi Pakasir
Field respons API Pakasir bisa sedikit berbeda antar versi. `app/services/pakasir.py` sudah menoleransi beberapa nama field (`payment_number`/`qris`/`qr_string`, `total_payment`/`amount`). Jika QR tidak muncul atau status tak terbaca, cek log dan sesuaikan parsing di file itu.
