"""Handler sisi buyer (model referensi).

- Angka produk = REPLY keyboard global (di-set sekali, menetap).
- Next/Prev = INLINE pada pesan daftar → di-edit di tempat (cepat, tanpa flicker).
- Pilih varian, qty, pesanan = inline. Tiap callback langsung di-answer() biar responsif.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app import config
from app.keyboards import buyer as kb
from app.notify import notify_delivery
from app.services import catalog, pakasir
from app.services import orders as orders_svc
from app.services.qr import make_qr_png
from app.utils import clamp_page, esc, fmt_dt, rupiah, total_pages

log = logging.getLogger(__name__)
router = Router(name="buyer")

PAGE_SIZE = config.PAGE_SIZE
CAP = 60  # maksimal nomor produk di reply keyboard


async def _safe_edit(cb: CallbackQuery, text: str, reply_markup=None) -> None:
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        await cb.message.answer(text, reply_markup=reply_markup)


# ============================ DAFTAR PRODUK ============================
async def _render_product_page(page: int):
    total = await catalog.count_products(active_only=True)
    page = clamp_page(page, total, PAGE_SIZE)
    tp = total_pages(total, PAGE_SIZE)
    products = await catalog.list_products(page, active_only=True)
    start_no = (page - 1) * PAGE_SIZE + 1
    lines = [f"🛍️ <b>LIST PRODUK</b> — {esc(config.STORE_NAME)}", ""]
    for i, p in enumerate(products):
        lines.append(f"[{start_no + i}]. {esc(p['name'])} ( {p['stock']} )")
    lines += ["", f"📄 Halaman {page} / {tp}", "👉 Tekan nomor produk di keyboard untuk memilih."]
    return "\n".join(lines), kb.product_nav_kb(page, tp)


async def open_browser(message: Message, state: FSMContext, greeting: str | None = None) -> None:
    """Buka panel produk: set reply keyboard angka (jika perlu) + kirim daftar inline."""
    ids = await catalog.product_ids(active_only=True, cap=CAP)
    data = await state.get_data()
    await state.update_data(product_ids=ids, page=1, ctx="buyer")

    if not ids:
        await state.update_data(kb_count=0)
        await message.answer(greeting or "🛍️ Belum ada produk tersedia saat ini.",
                             reply_markup=kb.menu_reply_kb())
        return

    # Set/refresh reply keyboard angka hanya bila jumlah produk berubah (atau ada greeting).
    if greeting or data.get("kb_count") != len(ids):
        header = greeting or "🛍️ <b>LIST PRODUK</b>\nTekan nomor produk di keyboard 👇"
        await message.answer(header, reply_markup=kb.products_reply_kb(len(ids)))
        await state.update_data(kb_count=len(ids))

    text, markup = await _render_product_page(1)
    await message.answer(text, reply_markup=markup)


@router.message(F.text == kb.BTN_PRODUK)
async def open_products(message: Message, state: FSMContext) -> None:
    await open_browser(message, state)


@router.callback_query(F.data.startswith("b:pg:"))
async def nav_products(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    page = int(cb.data.split(":")[2])
    text, markup = await _render_product_page(page)
    await state.update_data(page=page)
    await _safe_edit(cb, text, markup)


# ---- Pilih nomor produk (reply keyboard) ----
@router.message(F.text.regexp(r"^\d+$"))
async def pick_product(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ids = data.get("product_ids") or []
    if not ids:
        await message.answer("Tekan 🛍️ List Produk dulu ya.", reply_markup=kb.menu_reply_kb())
        return
    n = int(message.text)
    if not (1 <= n <= len(ids)):
        await message.answer(f"⚠️ Nomor {n} tidak ada. Pilih 1–{len(ids)}.")
        return
    text, markup = await _variants_view(ids[n - 1], data.get("page", 1))
    if text is None:
        await message.answer("Produk tidak tersedia.")
        return
    await message.answer(text, reply_markup=markup)


# ============================ VARIAN ============================
async def _variants_view(product_id: int, list_page: int):
    product = await catalog.get_product(product_id)
    if product is None or not product["is_active"]:
        return None, None
    variants = await catalog.list_variants(product_id, active_only=True)
    lines = [f"📦 <b>{esc(product['name'])}</b>"]
    if product["description"]:
        lines += ["", esc(product["description"])]
    lines.append("")
    if variants:
        for i, v in enumerate(variants, start=1):
            tag = f"stok {v['stock']}" if v["stock"] > 0 else "HABIS"
            lines.append(f"[{i}]. {esc(v['name'])} — {rupiah(v['price'])} ( {tag} )")
        lines += ["", "👉 Tekan nomor varian untuk memesan."]
    else:
        lines.append("⚠️ Belum ada varian untuk produk ini.")
    return "\n".join(lines), kb.variant_list_kb(variants, list_page)


@router.callback_query(F.data.startswith("b:vback:"))
async def variant_back(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    list_page = int(cb.data.split(":")[2])
    text, markup = await _render_product_page(list_page)
    await state.update_data(page=list_page)
    await _safe_edit(cb, text, markup)


# ============================ QTY ============================
def _qty_text(variant, qty: int) -> str:
    subtotal = int(variant["price"]) * qty
    return "\n".join([
        f"🧩 <b>{esc(variant['product_name'])}</b> — {esc(variant['name'])}",
        f"💵 Harga satuan: {rupiah(variant['price'])}",
        f"📦 Stok tersedia: {variant['stock']}",
        "",
        f"🔢 Jumlah: <b>{qty}</b>",
        f"🧮 Subtotal: <b>{rupiah(subtotal)}</b>",
        "",
        "Atur jumlah lalu tekan <b>✅ Pesan</b>.",
    ])


@router.callback_query(F.data.startswith("b:var:"))
async def open_variant(cb: CallbackQuery) -> None:
    await cb.answer()
    _, _, vid, list_page = cb.data.split(":")
    vid, list_page = int(vid), int(list_page)
    variant = await catalog.get_variant(vid)
    if variant is None or not variant["is_active"]:
        await cb.answer("Varian tidak tersedia.", show_alert=True)
        return
    if variant["stock"] <= 0:
        await cb.answer("😔 Stok habis untuk varian ini.", show_alert=True)
        return
    await _safe_edit(cb, _qty_text(variant, 1), kb.qty_kb(vid, list_page, 1, variant["stock"]))


@router.callback_query(F.data.startswith("b:qty:"))
async def change_qty(cb: CallbackQuery) -> None:
    await cb.answer()
    try:
        _, _, vid, list_page, qty = cb.data.split(":")
        vid, list_page, qty = int(vid), int(list_page), int(qty)
    except ValueError:
        log.warning("change_qty: callback tidak valid: %s", cb.data)
        await cb.answer("Tombol kedaluwarsa, buka ulang produk.", show_alert=True)
        return
    variant = await catalog.get_variant(vid)
    if variant is None or variant["stock"] <= 0:
        await cb.answer("Stok habis.", show_alert=True)
        return
    qty = max(1, min(qty, variant["stock"]))
    await _safe_edit(cb, _qty_text(variant, qty), kb.qty_kb(vid, list_page, qty, variant["stock"]))


# ============================ BUAT ORDER + QRIS ============================
@router.callback_query(F.data.startswith("b:buy:"))
async def confirm_buy(cb: CallbackQuery) -> None:
    _, _, vid, qty = cb.data.split(":")
    vid, qty = int(vid), int(qty)
    await cb.answer()
    # tampilkan status di pesan (bukan cuma toast) supaya error terlihat jelas
    await _safe_edit(cb, "⏳ Membuat pesanan & QRIS…", None)

    try:
        order = await orders_svc.create_order(
            buyer_tg_id=cb.from_user.id,
            buyer_username=cb.from_user.username,
            variant_id=vid,
            qty=qty,
        )
    except orders_svc.NotEnoughStock as e:
        await _safe_edit(cb, f"😔 Stok tidak cukup (sisa {e.available}). Coba lagi via 🛍️ List Produk.", None)
        return
    except Exception as e:  # noqa: BLE001
        log.exception("Gagal membuat order")
        await _safe_edit(
            cb,
            "❌ <b>Gagal membuat pesanan/QRIS.</b>\n\n"
            f"<code>{esc(str(e))[:300]}</code>\n\n"
            "Biasanya karena konfigurasi Pakasir (PAKASIR_PROJECT / PAKASIR_API_KEY) "
            "atau format respons API. Cek juga log terminal.",
            None,
        )
        return

    await _safe_edit(
        cb,
        f"🧾 Pesanan <code>{esc(order.order_id)}</code> dibuat.\n"
        "Silakan scan QRIS di bawah untuk membayar 👇",
        None,
    )

    biaya = order.pakasir_total - order.total_amount
    caption_lines = [
        "💳 <b>PEMBAYARAN QRIS</b>",
        "",
        f"🧾 Order: <code>{esc(order.order_id)}</code>",
        f"📦 {esc(order.product_name)} — {esc(order.variant_name)}",
        f"🔢 Jumlah: {order.qty}",
        f"🧮 Subtotal: {rupiah(order.total_amount)}",
    ]
    if biaya:
        caption_lines.append(f"➕ Biaya admin: {rupiah(biaya)}")
    caption_lines += [
        f"💰 <b>Total bayar: {rupiah(order.pakasir_total)}</b>",
        "",
        f"⏰ Bayar sebelum: {fmt_dt(order.expired_at)} WIB",
        "",
        "Scan QRIS lalu tekan <b>🔄 Cek Status Bayar</b>.\n"
        "Produk dikirim <b>otomatis</b> setelah pembayaran terkonfirmasi.",
    ]
    qr_png = make_qr_png(order.payment_number)
    await cb.message.answer_photo(
        BufferedInputFile(qr_png.read(), filename="qris.png"),
        caption="\n".join(caption_lines),
        reply_markup=kb.payment_kb(order.id),
    )


# ============================ CEK STATUS / BATAL ============================
@router.callback_query(F.data.startswith("b:chk:"))
async def check_status(cb: CallbackQuery) -> None:
    order_pk = int(cb.data.split(":")[2])
    order = await orders_svc.get_order(order_pk)
    if order is None or order["buyer_tg_id"] != cb.from_user.id:
        await cb.answer("Pesanan tidak ditemukan.", show_alert=True)
        return
    if order["status"] in ("delivered", "paid"):
        await cb.answer("✅ Pesanan ini sudah dibayar & diproses. Cek chat ya.", show_alert=True)
        return
    if order["status"] in ("expired", "cancelled"):
        await cb.answer("⌛ Pesanan ini sudah tidak aktif.", show_alert=True)
        return

    tx = await pakasir.check_status(order["order_id"], order["total_amount"])
    if pakasir.is_completed(tx):
        res = await orders_svc.deliver_order(order_pk)
        if res is not None:
            await notify_delivery(cb.bot, res)
        try:
            await cb.message.edit_caption(
                caption="✅ <b>Pembayaran diterima!</b>\nProduk sudah dikirim ke chat ini 👇",
                reply_markup=None,
            )
        except TelegramBadRequest:
            pass
        await cb.answer("✅ Pembayaran berhasil!")
    else:
        await cb.answer("⏳ Pembayaran belum masuk. Coba lagi beberapa saat.", show_alert=True)


@router.callback_query(F.data.startswith("b:cxl:"))
async def cancel_order(cb: CallbackQuery) -> None:
    order_pk = int(cb.data.split(":")[2])
    ok = await orders_svc.cancel_order(order_pk, cb.from_user.id)
    if ok:
        try:
            await cb.message.edit_caption(
                caption="❌ Pesanan dibatalkan. Stok telah dikembalikan.",
                reply_markup=None,
            )
        except TelegramBadRequest:
            pass
        await cb.answer("Pesanan dibatalkan.")
    else:
        await cb.answer("Tidak bisa dibatalkan (mungkin sudah dibayar/kedaluwarsa).", show_alert=True)


# ============================ PESANAN SAYA ============================
async def _render_orders(buyer_id: int, page: int):
    total = await orders_svc.count_buyer_orders(buyer_id)
    page = clamp_page(page, total, PAGE_SIZE)
    tp = total_pages(total, PAGE_SIZE)
    rows = await orders_svc.list_buyer_orders(buyer_id, page)
    if not rows:
        return "📦 Kamu belum punya pesanan.", None
    start_no = (page - 1) * PAGE_SIZE + 1
    lines = ["📦 <b>PESANAN SAYA</b>", ""]
    for i, o in enumerate(rows):
        lines.append(
            f"[{start_no + i}]. <code>{esc(o['order_id'])}</code> — "
            f"{esc(o['product_name_snap'])} ({o['qty']}x) — {o['status']}"
        )
    lines += ["", f"📄 Halaman {page} / {tp}", "👉 Tekan nomor untuk lihat detail."]
    return "\n".join(lines), kb.orders_kb(rows, page, tp, start_no)


@router.message(F.text == kb.BTN_PESANAN)
async def my_orders(message: Message) -> None:
    text, markup = await _render_orders(message.from_user.id, 1)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("b:olist:"))
async def nav_orders(cb: CallbackQuery) -> None:
    await cb.answer()
    page = int(cb.data.split(":")[2])
    text, markup = await _render_orders(cb.from_user.id, page)
    await _safe_edit(cb, text, markup)


@router.callback_query(F.data.startswith("b:odet:"))
async def order_detail(cb: CallbackQuery) -> None:
    await cb.answer()
    _, _, pk, page = cb.data.split(":")
    pk, page = int(pk), int(page)
    o = await orders_svc.get_order(pk)
    if o is None or o["buyer_tg_id"] != cb.from_user.id:
        await cb.answer("Pesanan tidak ditemukan.", show_alert=True)
        return
    lines = [
        f"🧾 <b>Detail Pesanan</b> <code>{esc(o['order_id'])}</code>",
        "",
        f"📦 {esc(o['product_name_snap'])} — {esc(o['variant_name_snap'])}",
        f"🔢 Jumlah: {o['qty']}",
        f"💰 Total: {rupiah(o['total_amount'])}",
        f"📌 Status: {o['status']}",
        f"🕒 Dibuat: {fmt_dt(o['created_at'])} WIB",
    ]
    if o["delivered_content"]:
        lines += ["", "🎁 <b>Produk:</b>", f"<pre>{esc(o['delivered_content'])}</pre>"]
    await _safe_edit(cb, "\n".join(lines), kb.order_detail_back_kb(page))


# ============================ CARA ORDER / INFO ============================
@router.message(F.text == kb.BTN_CARA)
async def how_to_order(message: Message) -> None:
    text = await catalog.get_setting("cara_order", "Belum diatur.")
    await message.answer(f"❓ <b>Cara Order</b>\n\n{esc(text)}")


@router.message(F.text == kb.BTN_INFO)
async def information(message: Message) -> None:
    text = await catalog.get_setting("information", "Belum diatur.")
    await message.answer(f"⚠️ <b>Information</b>\n\n{esc(text)}")
