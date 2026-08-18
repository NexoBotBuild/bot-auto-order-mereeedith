"""Handler admin: Kelola Produk (CRUD produk & varian, paginate)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import config
from app.keyboards import admin as kb
from app.middlewares import AdminOnlyMiddleware, IsAdmin, NotInContext
from app.services import catalog
from app.states import AddProduct, AddVariant, EditProduct, EditVariant
from app.tg import panel_update, remember_panel, safe_edit
from app.utils import clamp_page, esc, rupiah, total_pages

router = Router(name="admin_products")
router.message.middleware(AdminOnlyMiddleware())
router.callback_query.middleware(AdminOnlyMiddleware())

PAGE_SIZE = config.PAGE_SIZE
ADMIN_CAP = 60


# ============================ DAFTAR PRODUK ============================
async def _render_products(page: int):
    total = await catalog.count_products(active_only=False)
    page = clamp_page(page, total, PAGE_SIZE)
    tp = total_pages(total, PAGE_SIZE)
    products = await catalog.list_products(page, active_only=False)
    start_no = (page - 1) * PAGE_SIZE + 1
    if not products:
        text = "📦 <b>KELOLA PRODUK</b>\n\nBelum ada produk. Tekan ➕ Tambah Produk."
    else:
        lines = [f"📦 <b>KELOLA PRODUK</b> — total {total} produk", ""]
        for idx, p in enumerate(products):
            flag = "" if p["is_active"] else "🚫 "
            lines.append(
                f"[{start_no + idx}]. {flag}{esc(p['name'])} — {p['variant_count']} varian"
            )
        lines.append("")
        lines.append("👉 Tekan nomor produk di keyboard untuk mengelola.")
        text = "\n".join(lines)
    return text, kb.product_list_nav_kb(page, tp)


async def _enter_kelola(state: FSMContext) -> list[int]:
    """Set konteks Kelola Produk & ambil daftar id produk untuk pemetaan nomor."""
    ids = await catalog.product_ids(active_only=False, cap=ADMIN_CAP)
    await state.update_data(ctx="kelola", aids=ids)
    return ids


@router.message(F.text == kb.BTN_KELOLA)
async def open_kelola(message: Message, state: FSMContext) -> None:
    await state.clear()
    ids = await _enter_kelola(state)
    await message.answer(
        "📦 <b>KELOLA PRODUK</b>\nTekan nomor produk di keyboard 👇",
        reply_markup=kb.products_reply_kb(len(ids)),
    )
    text, markup = await _render_products(1)
    await message.answer(text, reply_markup=markup)


@router.message(F.text.regexp(r"^\d+$"), StateFilter(None), IsAdmin(), NotInContext("buyer"))
async def pick_product(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ids = data.get("aids")
    if not ids:  # konteks hilang (mis. setelah CRUD) → ambil ulang
        ids = await _enter_kelola(state)
    if not ids:
        await message.answer("Belum ada produk. Tekan ➕ Tambah Produk via 📦 Kelola Produk.")
        return
    n = int(message.text)
    if not (1 <= n <= len(ids)):
        await message.answer(f"⚠️ Nomor {n} tidak ada. Pilih 1–{len(ids)}.")
        return
    text, markup = await _render_product_manage(ids[n - 1], 1)
    if text is None:
        await message.answer("Produk tidak ada.")
        return
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("a:plist:"))
async def nav_products(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await _enter_kelola(state)
    page = int(cb.data.split(":")[2])
    text, markup = await _render_products(page)
    await safe_edit(cb, text, markup)
    await cb.answer()


# ============================ DETAIL / KELOLA PRODUK ============================
async def _render_product_manage(pid: int, page: int):
    product = await catalog.get_product(pid)
    if product is None:
        return None, None
    variants = await catalog.list_variants(pid, active_only=False)
    lines = [
        f"📦 <b>{esc(product['name'])}</b>",
        ("✅ Aktif" if product["is_active"] else "🚫 Nonaktif"),
    ]
    if product["description"]:
        lines += ["", esc(product["description"])]
    lines.append("")
    if variants:
        lines.append(f"<b>Varian ({len(variants)}):</b>")
        for idx, v in enumerate(variants, start=1):
            flag = "" if v["is_active"] else "🚫 "
            lines.append(
                f"<b>{idx}.</b> {flag}{esc(v['name'])} — {rupiah(v['price'])} (stok {v['stock']})"
            )
        lines.append("")
        lines.append("Tekan nomor untuk kelola varian, atau pakai tombol di bawah.")
    else:
        lines.append("Belum ada varian. Tekan ➕ Tambah Varian.")
    return "\n".join(lines), kb.product_manage_kb(pid, variants, page)


@router.callback_query(F.data.startswith("a:prod:"))
async def open_product(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    _, _, pid, page = cb.data.split(":")
    text, markup = await _render_product_manage(int(pid), int(page))
    if text is None:
        await cb.answer("Produk tidak ada.", show_alert=True)
        return
    await safe_edit(cb, text, markup)
    await cb.answer()


# ============================ TAMBAH PRODUK (FSM) ============================
@router.callback_query(F.data == "a:padd")
async def add_product_start(cb: CallbackQuery, state: FSMContext) -> None:
    await remember_panel(state, cb.message)
    await state.set_state(AddProduct.name)
    await safe_edit(cb, "➕ <b>Tambah Produk</b>\n\nKetik <b>nama produk</b>:", kb.cancel_kb())
    await cb.answer()


@router.message(AddProduct.name)
async def add_product_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(AddProduct.description)
    await panel_update(
        message, state,
        "Ketik <b>deskripsi produk</b> (atau kirim <code>-</code> untuk kosong):",
        kb.cancel_kb(),
    )


@router.message(AddProduct.description)
async def add_product_desc(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    desc = "" if message.text.strip() == "-" else message.text.strip()
    pid = await catalog.create_product(data["name"], desc)
    text, markup = await _render_product_manage(pid, 1)
    await panel_update(message, state, f"✅ Produk <b>{esc(data['name'])}</b> dibuat.\n\n" + text, markup)
    await state.clear()


# ============================ EDIT PRODUK (FSM) ============================
@router.callback_query(F.data.startswith("a:pedit:"))
async def edit_product_start(cb: CallbackQuery, state: FSMContext) -> None:
    pid = int(cb.data.split(":")[2])
    await remember_panel(state, cb.message)
    await state.set_state(EditProduct.name)
    await state.update_data(pid=pid)
    await safe_edit(
        cb,
        "✏️ <b>Edit Produk</b>\n\nKetik <b>nama baru</b> "
        "(atau <code>-</code> untuk tidak mengubah):",
        kb.cancel_kb(),
    )
    await cb.answer()


@router.message(EditProduct.name)
async def edit_product_name(message: Message, state: FSMContext) -> None:
    name = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(name=name)
    await state.set_state(EditProduct.description)
    await panel_update(
        message, state,
        "Ketik <b>deskripsi baru</b> (atau <code>-</code> untuk tidak mengubah):",
        kb.cancel_kb(),
    )


@router.message(EditProduct.description)
async def edit_product_desc(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    desc = None if message.text.strip() == "-" else message.text.strip()
    await catalog.update_product(data["pid"], name=data["name"], description=desc)
    text, markup = await _render_product_manage(data["pid"], 1)
    await panel_update(message, state, "✅ Produk diperbarui.\n\n" + text, markup)
    await state.clear()


# ============================ HAPUS PRODUK ============================
@router.callback_query(F.data.startswith("a:pdel:"))
async def del_product_confirm(cb: CallbackQuery) -> None:
    _, _, pid, page = cb.data.split(":")
    await safe_edit(
        cb,
        "🗑️ Yakin hapus produk ini beserta <b>semua varian & stoknya</b>?\n"
        "Tindakan tidak bisa dibatalkan.",
        kb.confirm_kb(f"a:pdelc:{pid}:{page}", f"a:prod:{pid}:{page}"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("a:pdelc:"))
async def del_product_do(cb: CallbackQuery) -> None:
    _, _, pid, page = cb.data.split(":")
    await catalog.delete_product(int(pid))
    text, markup = await _render_products(int(page))
    await safe_edit(cb, "✅ Produk dihapus.\n\n" + text, markup)
    await cb.answer("Dihapus.")


# ============================ TAMBAH VARIAN (FSM) ============================
@router.callback_query(F.data.startswith("a:vadd:"))
async def add_variant_start(cb: CallbackQuery, state: FSMContext) -> None:
    pid = int(cb.data.split(":")[2])
    await remember_panel(state, cb.message)
    await state.set_state(AddVariant.name)
    await state.update_data(pid=pid)
    await safe_edit(
        cb,
        "➕ <b>Tambah Varian</b>\n\nKetik <b>nama varian</b> (mis. <i>1 Bulan</i>):",
        kb.cancel_kb(),
    )
    await cb.answer()


@router.message(AddVariant.name)
async def add_variant_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await state.set_state(AddVariant.price)
    await panel_update(message, state,
                       "Ketik <b>harga</b> (angka saja, mis. <code>10000</code>):",
                       kb.cancel_kb())


@router.message(AddVariant.price)
async def add_variant_price(message: Message, state: FSMContext) -> None:
    price = _parse_price(message.text)
    if price is None:
        await panel_update(message, state, "⚠️ Harga harus angka. Coba lagi:", kb.cancel_kb())
        return
    data = await state.get_data()
    await catalog.create_variant(data["pid"], data["name"], price)
    text, markup = await _render_product_manage(data["pid"], 1)
    await panel_update(
        message, state,
        f"✅ Varian <b>{esc(data['name'])}</b> ({rupiah(price)}) ditambahkan.\n\n" + text,
        markup,
    )
    await state.clear()


# ============================ KELOLA VARIAN ============================
async def _render_variant_manage(vid: int, pid: int, page: int):
    v = await catalog.get_variant(vid)
    if v is None:
        return None, None
    text = "\n".join([
        f"⚙️ <b>Varian:</b> {esc(v['name'])}",
        f"📦 Produk: {esc(v['product_name'])}",
        f"💵 Harga: {rupiah(v['price'])}",
        f"📊 Stok tersedia: {v['stock']}",
    ])
    return text, kb.variant_manage_kb(vid, pid, page)


@router.callback_query(F.data.startswith("a:var:"))
async def open_variant(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    _, _, vid, pid, page = cb.data.split(":")
    text, markup = await _render_variant_manage(int(vid), int(pid), int(page))
    if text is None:
        await cb.answer("Varian tidak ada.", show_alert=True)
        return
    await safe_edit(cb, text, markup)
    await cb.answer()


# Kembali ke varian dari tampilan lihat-stok (butuh pid; ambil dari DB)
@router.callback_query(F.data.startswith("a:varback:"))
async def variant_back(cb: CallbackQuery) -> None:
    vid = int(cb.data.split(":")[2])
    v = await catalog.get_variant(vid)
    if v is None:
        await cb.answer("Varian tidak ada.", show_alert=True)
        return
    text, markup = await _render_variant_manage(vid, v["product_id"], 1)
    await safe_edit(cb, text, markup)
    await cb.answer()


# ============================ EDIT VARIAN (FSM) ============================
@router.callback_query(F.data.startswith("a:vedit:"))
async def edit_variant_start(cb: CallbackQuery, state: FSMContext) -> None:
    vid = int(cb.data.split(":")[2])
    v = await catalog.get_variant(vid)
    if v is None:
        await cb.answer("Varian tidak ada.", show_alert=True)
        return
    await remember_panel(state, cb.message)
    await state.set_state(EditVariant.name)
    await state.update_data(vid=vid, pid=v["product_id"])
    await safe_edit(
        cb,
        "✏️ <b>Edit Varian</b>\n\nKetik <b>nama baru</b> "
        "(atau <code>-</code> untuk tidak mengubah):",
        kb.cancel_kb(),
    )
    await cb.answer()


@router.message(EditVariant.name)
async def edit_variant_name(message: Message, state: FSMContext) -> None:
    name = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(name=name)
    await state.set_state(EditVariant.price)
    await panel_update(
        message, state,
        "Ketik <b>harga baru</b> (angka, atau <code>-</code> untuk tidak mengubah):",
        kb.cancel_kb(),
    )


@router.message(EditVariant.price)
async def edit_variant_price(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    price = None
    if raw != "-":
        price = _parse_price(raw)
        if price is None:
            await panel_update(message, state, "⚠️ Harga harus angka. Coba lagi:", kb.cancel_kb())
            return
    data = await state.get_data()
    await catalog.update_variant(data["vid"], name=data["name"], price=price)
    text, markup = await _render_variant_manage(data["vid"], data["pid"], 1)
    await panel_update(message, state, "✅ Varian diperbarui.\n\n" + text, markup)
    await state.clear()


# ============================ HAPUS VARIAN ============================
@router.callback_query(F.data.startswith("a:vdel:"))
async def del_variant_confirm(cb: CallbackQuery) -> None:
    _, _, vid, pid, page = cb.data.split(":")
    await safe_edit(
        cb,
        "🗑️ Yakin hapus varian ini beserta <b>semua stoknya</b>?",
        kb.confirm_kb(f"a:vdelc:{vid}:{pid}:{page}", f"a:var:{vid}:{pid}:{page}"),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("a:vdelc:"))
async def del_variant_do(cb: CallbackQuery) -> None:
    _, _, vid, pid, page = cb.data.split(":")
    await catalog.delete_variant(int(vid))
    text, markup = await _render_product_manage(int(pid), int(page))
    if text is None:
        text, markup = await _render_products(int(page))
    await safe_edit(cb, "✅ Varian dihapus.\n\n" + text, markup)
    await cb.answer("Dihapus.")


# ============================ BATAL (FSM) ============================
@router.callback_query(F.data == "a:cancel")
async def cancel_fsm(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text, markup = await _render_products(1)
    await safe_edit(cb, "✅ Dibatalkan.\n\n" + text, markup)
    await cb.answer()


def _parse_price(raw: str) -> int | None:
    cleaned = raw.strip().replace(".", "").replace(",", "").replace("Rp", "").replace("rp", "").strip()
    if not cleaned.isdigit():
        return None
    return int(cleaned)
