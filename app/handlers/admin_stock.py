"""Handler admin: Tambah Stok (bulk), Lihat Stok, Laporan Stok."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import config
from app.handlers.admin_products import _render_variant_manage
from app.keyboards import admin as kb
from app.middlewares import AdminOnlyMiddleware
from app.services import catalog
from app.states import Stocking
from app.tg import panel_update, remember_panel, safe_edit
from app.utils import clamp_page, esc, total_pages

router = Router(name="admin_stock")
router.message.middleware(AdminOnlyMiddleware())
router.callback_query.middleware(AdminOnlyMiddleware())

PAGE_SIZE = config.PAGE_SIZE
LOW_STOCK = 3


# ============ PILIH VARIAN UNTUK STOCKING (dari level produk) ============
@router.callback_query(F.data.startswith("a:stkpick:"))
async def stocking_pick(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    _, _, pid, page = cb.data.split(":")
    pid, page = int(pid), int(page)
    product = await catalog.get_product(pid)
    if product is None:
        await cb.answer("Produk tidak ada.", show_alert=True)
        return
    variants = await catalog.list_variants(pid, active_only=False)
    if not variants:
        await cb.answer("Belum ada varian. Tambah varian dulu.", show_alert=True)
        return
    lines = [f"📥 <b>Tambah Stok</b> — {esc(product['name'])}", ""]
    for idx, v in enumerate(variants, start=1):
        lines.append(f"<b>{idx}.</b> {esc(v['name'])} (stok {v['stock']})")
    lines.append("")
    lines.append("Tekan nomor varian yang mau ditambah stok.")
    await safe_edit(cb, "\n".join(lines), kb.stocking_pick_kb(pid, variants, page))
    await cb.answer()


# ============================ STOCKING (FSM, bulk per baris) ============================
@router.callback_query(F.data.startswith("a:stk:"))
async def stocking_start(cb: CallbackQuery, state: FSMContext) -> None:
    vid = int(cb.data.split(":")[2])
    v = await catalog.get_variant(vid)
    if v is None:
        await cb.answer("Varian tidak ada.", show_alert=True)
        return
    await remember_panel(state, cb.message)
    await state.set_state(Stocking.collecting)
    await state.update_data(vid=vid, pid=v["product_id"], added=0)
    await safe_edit(
        cb,
        f"📥 <b>Tambah Stok</b> — {esc(v['product_name'])} / {esc(v['name'])}\n\n"
        "Kirim stok sekarang. <b>Pisahkan tiap akun dengan baris baru (Enter)</b>.\n"
        "Satu baris = satu stok. Boleh kirim beberapa pesan.\n\n"
        "Tekan <b>✅ Selesai</b> bila sudah.",
        kb.stocking_done_kb(),
    )
    await cb.answer()


@router.message(Stocking.collecting)
async def stocking_collect(message: Message, state: FSMContext) -> None:
    raw = message.text or message.caption or ""
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    data = await state.get_data()
    if not lines:
        await panel_update(message, state,
                           "⚠️ Tidak ada baris terbaca. Kirim stok (1 baris = 1 stok).",
                           kb.stocking_done_kb())
        return
    n = await catalog.add_stock_bulk(data["vid"], lines)
    total = data.get("added", 0) + n
    await state.update_data(added=total)
    await panel_update(
        message, state,
        f"✅ +{n} stok ditambahkan (total sesi ini: <b>{total}</b>).\n"
        "Kirim lagi atau tekan <b>✅ Selesai</b>.",
        kb.stocking_done_kb(),
    )


@router.callback_query(F.data == "a:stkdone")
async def stocking_done(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    vid = data.get("vid")
    pid = data.get("pid")
    added = data.get("added", 0)
    if vid is None:
        await safe_edit(cb, f"✅ Selesai. {added} stok ditambahkan.", None)
        await cb.answer()
        return
    text, markup = await _render_variant_manage(vid, pid, 1)
    await safe_edit(cb, f"✅ Selesai menambah <b>{added}</b> stok.\n\n" + text, markup)
    await cb.answer()


# ============================ LIHAT STOK (paginate + hapus) ============================
async def _render_stock_view(vid: int, page: int):
    v = await catalog.get_variant(vid)
    if v is None:
        return None, None
    total = await catalog.available_stock_count(vid)
    page = clamp_page(page, total, PAGE_SIZE)
    tp = total_pages(total, PAGE_SIZE)
    items = await catalog.list_stock(vid, page)
    start_no = (page - 1) * PAGE_SIZE + 1
    lines = [
        f"📋 <b>Stok:</b> {esc(v['product_name'])} / {esc(v['name'])}",
        f"Tersedia: {total}",
        "",
    ]
    if items:
        for idx, s in enumerate(items):
            preview = (s["content"][:60] + "…") if len(s["content"]) > 61 else s["content"]
            lines.append(f"<b>{start_no + idx}.</b> <code>{esc(preview)}</code>")
        lines.append("")
        lines.append("Tekan nomor untuk <b>menghapus</b> stok itu.")
    else:
        lines.append("(kosong)")
    return "\n".join(lines), kb.stock_view_kb(items, vid, page, tp, start_no)


@router.callback_query(F.data.startswith("a:vstk:"))
async def view_stock(cb: CallbackQuery) -> None:
    _, _, vid, page = cb.data.split(":")
    text, markup = await _render_stock_view(int(vid), int(page))
    if text is None:
        await cb.answer("Varian tidak ada.", show_alert=True)
        return
    await safe_edit(cb, text, markup)
    await cb.answer()


@router.callback_query(F.data.startswith("a:sdel:"))
async def delete_stock(cb: CallbackQuery) -> None:
    _, _, sid, vid, page = cb.data.split(":")
    await catalog.delete_stock_item(int(sid))
    text, markup = await _render_stock_view(int(vid), int(page))
    await safe_edit(cb, text, markup)
    await cb.answer("Stok dihapus.")


# ============================ LAPORAN STOK ============================
async def _render_report(page: int):
    total = await catalog.count_all_variants()
    page = clamp_page(page, total, PAGE_SIZE)
    tp = total_pages(total, PAGE_SIZE)
    rows = await catalog.stock_report(page)
    lines = ["📈 <b>LAPORAN STOK</b>", ""]
    if not rows:
        lines.append("Belum ada varian.")
    for r in rows:
        mark = "⚠️" if r["stock"] <= LOW_STOCK else "✅"
        lines.append(
            f"{mark} {esc(r['product_name'])} / {esc(r['variant_name'])}: <b>{r['stock']}</b>"
        )
    return "\n".join(lines), kb.stock_report_kb(page, tp)


@router.message(F.text == kb.BTN_LAPORAN)
async def open_laporan(message: Message, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _render_report(1)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("a:rep:"))
async def nav_report(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[2])
    text, markup = await _render_report(page)
    await safe_edit(cb, text, markup)
    await cb.answer()
