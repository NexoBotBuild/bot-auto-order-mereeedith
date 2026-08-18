"""Handler admin: Riwayat Penjualan, Pengaturan, mode lihat-sebagai-buyer."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import config
from app.handlers.buyer import open_browser
from app.keyboards import admin as kb
from app.middlewares import AdminOnlyMiddleware
from app.services import catalog
from app.services import orders as orders_svc
from app.states import EditSetting
from app.tg import panel_update, remember_panel, safe_edit
from app.utils import clamp_page, esc, fmt_dt, rupiah, total_pages

router = Router(name="admin_orders")
router.message.middleware(AdminOnlyMiddleware())
router.callback_query.middleware(AdminOnlyMiddleware())

PAGE_SIZE = config.PAGE_SIZE
_RANGE_LABEL = {"today": "Hari ini", "7d": "7 hari terakhir", "all": "Semua"}


# ============================ RIWAYAT PENJUALAN ============================
async def _render_sales(range_key: str, page: int):
    n, omzet = await orders_svc.sales_summary(range_key)
    total = await orders_svc.count_sales(range_key)
    page = clamp_page(page, total, PAGE_SIZE)
    tp = total_pages(total, PAGE_SIZE)
    rows = await orders_svc.list_sales(range_key, page)
    start_no = (page - 1) * PAGE_SIZE + 1

    lines = [
        "📊 <b>RIWAYAT PENJUALAN</b>",
        f"🗓️ {_RANGE_LABEL.get(range_key, 'Semua')}",
        f"🧾 {n} transaksi • 💰 Omzet {rupiah(omzet)}",
        "",
    ]
    if not rows:
        lines.append("Belum ada penjualan pada rentang ini.")
    else:
        for idx, o in enumerate(rows):
            uname = f"@{o['buyer_username']}" if o["buyer_username"] else str(o["buyer_tg_id"])
            lines.append(
                f"<b>{start_no + idx}.</b> {fmt_dt(o['created_at'])} — {esc(o['product_name_snap'])}"
                f" ({o['qty']}x) — {rupiah(o['total_amount'])} — {esc(uname)}"
            )
        lines.append("")
        lines.append("Tekan nomor untuk lihat detail transaksi.")
    return "\n".join(lines), kb.sales_list_kb(rows, range_key, page, tp, start_no)


@router.message(F.text == kb.BTN_RIWAYAT)
async def open_riwayat(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _render_sales("today", 1)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("a:slist:"))
async def nav_sales(cb: CallbackQuery) -> None:
    _, _, range_key, page = cb.data.split(":")
    text, markup = await _render_sales(range_key, int(page))
    await safe_edit(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data.startswith("a:sdet:"))
async def sales_detail(cb: CallbackQuery) -> None:
    _, _, pk, range_key, page = cb.data.split(":")
    o = await orders_svc.get_order(int(pk))
    if o is None:
        await cb.answer("Order tidak ada.", show_alert=True)
        return
    uname = f"@{o['buyer_username']}" if o["buyer_username"] else "-"
    biaya = o["pakasir_total"] - o["total_amount"]
    lines = [
        f"🧾 <b>Detail Penjualan</b> <code>{esc(o['order_id'])}</code>",
        "",
        f"📦 {esc(o['product_name_snap'])} — {esc(o['variant_name_snap'])}",
        f"🔢 Jumlah: {o['qty']}",
        f"💵 Harga satuan: {rupiah(o['unit_price'])}",
        f"🧮 Subtotal: {rupiah(o['total_amount'])}",
        f"➕ Biaya admin: {rupiah(biaya)}",
        f"💰 Total bayar: {rupiah(o['pakasir_total'])}",
        f"📌 Status: {o['status']}",
        f"💳 Metode: {esc(o['payment_method']) or '-'}",
        "",
        f"👤 Buyer: <code>{o['buyer_tg_id']}</code> ({esc(uname)})",
        f"🕒 Dibuat: {fmt_dt(o['created_at'])} WIB",
        f"✅ Dibayar: {fmt_dt(o['paid_at'])} WIB",
        f"📤 Dikirim: {fmt_dt(o['delivered_at'])} WIB",
    ]
    if o["delivered_content"]:
        lines += ["", "🎁 <b>Konten terkirim:</b>", f"<pre>{esc(o['delivered_content'])}</pre>"]
    await safe_edit(cb, "\n".join(lines), kb.sales_detail_kb(range_key, int(page)))
    await cb.answer()


# ============================ PENGATURAN ============================
@router.message(F.text == kb.BTN_PENGATURAN)
async def open_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "⚙️ <b>PENGATURAN</b>\nEdit teks yang dilihat buyer:",
        reply_markup=kb.settings_kb(),
    )


@router.callback_query(F.data.startswith("a:set:"))
async def edit_setting_start(cb: CallbackQuery, state: FSMContext) -> None:
    key = cb.data.split(":", 2)[2]
    current = await catalog.get_setting(key, "(kosong)")
    await remember_panel(state, cb.message)
    await state.set_state(EditSetting.value)
    await state.update_data(key=key)
    await safe_edit(
        cb,
        f"✏️ Kirim teks baru untuk <b>{esc(key)}</b>.\n\nSaat ini:\n<pre>{esc(current)}</pre>",
        kb.cancel_kb(),
    )
    await cb.answer()


@router.message(EditSetting.value)
async def edit_setting_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await catalog.set_setting(data["key"], message.text)
    await panel_update(message, state, "✅ Teks diperbarui.", kb.settings_kb())
    await state.clear()


# ============================ MODE LIHAT SEBAGAI BUYER ============================
@router.message(F.text == kb.BTN_MODE_BUYER)
async def mode_buyer(message: Message, state: FSMContext) -> None:
    await state.clear()
    await open_browser(message, state,
                       greeting="👁️ Mode tampilan buyer. Ketik /admin untuk kembali ke panel admin.")
