"""Klien Pakasir: buat transaksi QRIS & cek status."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import aiohttp

from app import config

log = logging.getLogger(__name__)

_session: aiohttp.ClientSession | None = None


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        )
    return _session


async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


@dataclass
class QrisTransaction:
    payment_number: str          # string QRIS untuk dirender jadi QR
    total_payment: int           # nominal yang harus dibayar (incl fee)
    expired_at: datetime | None
    payment_method: str | None


def _parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


async def create_qris(order_id: str, amount: int) -> QrisTransaction:
    """Buat transaksi QRIS di Pakasir untuk satu order."""
    url = f"{config.PAKASIR_BASE_URL}/api/transactioncreate/qris"
    payload = {
        "project": config.PAKASIR_PROJECT,
        "order_id": order_id,
        "amount": amount,
        "api_key": config.PAKASIR_API_KEY,
    }
    session = _get_session()

    # Coba JSON dulu; bila ditolak (4xx), ulangi sebagai form-encoded — format
    # request Pakasir tidak dijabarkan eksplisit, jadi dukung keduanya.
    last_status, last_text = None, ""
    for kwargs in ({"json": payload}, {"data": payload}):
        async with session.post(url, **kwargs) as resp:
            text = await resp.text()
            if resp.status < 400:
                data = await _safe_json(resp, text)
                break
            last_status, last_text = resp.status, text
            log.error("Pakasir create_qris gagal (%s) [%s]: %s",
                      resp.status, "json" if "json" in kwargs else "form", text)
    else:
        raise RuntimeError(f"Pakasir error {last_status}: {last_text}")

    # Pakasir membungkus data di key 'payment' (atau 'transaction'); ambil yang ada.
    tx = _unwrap(data)
    payment_number = tx.get("payment_number") or tx.get("qris") or tx.get("qr_string")
    if not payment_number:
        log.error("Respon Pakasir tanpa payment_number: %s", data)
        raise RuntimeError("Respon Pakasir tidak mengandung payment_number.")

    total = tx.get("total_payment") or tx.get("amount") or amount
    return QrisTransaction(
        payment_number=str(payment_number),
        total_payment=int(total),
        expired_at=_parse_dt(tx.get("expired_at")),
        payment_method=tx.get("payment_method"),
    )


async def simulate_payment(order_id: str, amount: int) -> bool:
    """Trigger Pakasir Payment Simulation (khusus project Sandbox). Testing only."""
    url = f"{config.PAKASIR_BASE_URL}/api/paymentsimulation"
    payload = {
        "project": config.PAKASIR_PROJECT,
        "order_id": order_id,
        "amount": amount,
        "api_key": config.PAKASIR_API_KEY,
    }
    session = _get_session()
    async with session.post(url, json=payload) as resp:
        text = await resp.text()
        if resp.status >= 400:
            log.warning("Pakasir simulate_payment (%s): %s", resp.status, text)
            return False
    return True


async def check_status(order_id: str, amount: int) -> dict:
    """Cek detail/status transaksi. Mengembalikan dict mentah Pakasir."""
    url = f"{config.PAKASIR_BASE_URL}/api/transactiondetail"
    params = {
        "project": config.PAKASIR_PROJECT,
        "amount": amount,
        "order_id": order_id,
        "api_key": config.PAKASIR_API_KEY,
    }
    session = _get_session()
    async with session.get(url, params=params) as resp:
        text = await resp.text()
        if resp.status >= 400:
            log.warning("Pakasir check_status (%s): %s", resp.status, text)
            return {}
        data = await _safe_json(resp, text)
    return _unwrap(data)


def _unwrap(data) -> dict:
    """Ambil objek transaksi dari respons Pakasir (dibungkus 'payment'/'transaction')."""
    if not isinstance(data, dict):
        return {}
    inner = data.get("payment") or data.get("transaction")
    return inner if isinstance(inner, dict) else data


def is_completed(tx: dict) -> bool:
    return str(tx.get("status", "")).lower() == "completed"


async def _safe_json(resp: aiohttp.ClientResponse, text: str):
    try:
        return await resp.json(content_type=None)
    except Exception:  # noqa: BLE001
        log.error("Respon Pakasir bukan JSON valid: %s", text)
        raise RuntimeError("Respon Pakasir tidak valid.")
