import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_user_id, verify_business_access, require_business_access
from app.core.supabase import supabase_admin
from app.schemas.appointments import (
    CreateAppointmentRequest,
    UpdateAppointmentRequest,
    UpdateAppointmentStatusRequest,
    AppointmentResponse,
    CancelAppointmentResponse,
    VALID_APPOINTMENT_STATUSES,
    AppointmentPaymentResponse,
    SaveAppointmentPaymentRequest,
)
from app.services import booking_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/appointments", tags=["appointments"])

MONEY_QUANT = Decimal("0.01")


def _money(value: float | int | str | Decimal | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _get_appointment_for_business(appointment_id: str, business_id: str) -> dict:
    result = (
        supabase_admin.table("appointments")
        .select("id, business_id, location_id")
        .eq("id", appointment_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return result.data[0]


def _unique_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in ids:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _fetch_tax_snapshots(business_id: str, tax_config_ids: list[str], subtotal: Decimal) -> tuple[list[dict], Decimal]:
    unique_tax_ids = _unique_ids(tax_config_ids)
    if not unique_tax_ids:
        return [], Decimal("0.00")

    result = (
        supabase_admin.table("business_tax_configs")
        .select("id, name, rate_percent, registration_number")
        .eq("business_id", business_id)
        .in_("id", unique_tax_ids)
        .execute()
    )
    rows = result.data or []
    if len(rows) != len(unique_tax_ids):
        raise HTTPException(status_code=400, detail="One or more selected taxes are invalid")

    rows_by_id = {row["id"]: row for row in rows}
    snapshots: list[dict] = []
    tax_total = Decimal("0.00")
    for tax_id in unique_tax_ids:
        row = rows_by_id[tax_id]
        rate = Decimal(str(row.get("rate_percent") or 0))
        amount = (subtotal * (rate / Decimal("100"))).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        tax_total += amount
        snapshots.append({
            "tax_config_id": row["id"],
            "name": row["name"],
            "rate_percent": float(rate),
            "registration_number": row.get("registration_number"),
            "amount": float(amount),
        })

    return snapshots, tax_total.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _build_payment_snapshot(body: SaveAppointmentPaymentRequest) -> tuple[list[dict], list[dict], Decimal, Decimal, Decimal, Decimal]:
    line_items: list[dict] = []
    subtotal = Decimal("0.00")
    for item in body.line_items:
        if item.quantity < 1:
            raise HTTPException(status_code=400, detail="Line item quantity must be at least 1")
        if not item.service_name.strip():
            raise HTTPException(status_code=400, detail="Line item service name is required")
        if item.price is None:
            if body.status == "paid":
                raise HTTPException(status_code=400, detail="All service prices are required before marking payment paid")
            price = None
            line_total = Decimal("0.00")
        else:
            price_decimal = _money(item.price)
            if price_decimal < 0:
                raise HTTPException(status_code=400, detail="Line item prices cannot be negative")
            price = float(price_decimal)
            line_total = (price_decimal * item.quantity).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
            subtotal += line_total

        line_items.append({
            "service_id": item.service_id,
            "service_name": item.service_name.strip(),
            "price": price,
            "quantity": item.quantity,
            "line_total": float(line_total),
        })

    tip_amount = _money(body.tip_amount)
    if tip_amount < 0:
        raise HTTPException(status_code=400, detail="Tip amount cannot be negative")

    selected_taxes, tax_total = _fetch_tax_snapshots(body.business_id, body.tax_config_ids, subtotal)
    grand_total = (subtotal + tax_total + tip_amount).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    return line_items, selected_taxes, subtotal, tax_total, tip_amount, grand_total


@router.post("", response_model=AppointmentResponse)
async def create_appointment(
    body: CreateAppointmentRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    return await booking_service.create_appointment(body, created_by=user_id)


@router.put("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    appointment_id: str,
    body: UpdateAppointmentRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    return await booking_service.update_appointment(appointment_id, body)


@router.patch("/{appointment_id}/status")
async def update_appointment_status(
    appointment_id: str,
    body: UpdateAppointmentStatusRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    if body.status not in VALID_APPOINTMENT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_APPOINTMENT_STATUSES))}",
        )
    result = (
        supabase_admin.table("appointments")
        .update({"status": body.status})
        .eq("id", appointment_id)
        .eq("business_id", body.business_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return result.data[0]


@router.delete("/{appointment_id}", response_model=CancelAppointmentResponse)
async def cancel_appointment(
    appointment_id: str,
    business_id: str,
    _: str = Depends(require_business_access()),
    user_id: str = Depends(get_user_id),
):
    return await booking_service.cancel_appointment(appointment_id, business_id)


@router.get("/{appointment_id}/payment", response_model=AppointmentPaymentResponse | None)
async def get_appointment_payment(
    appointment_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    _get_appointment_for_business(appointment_id, business_id)
    result = (
        supabase_admin.table("appointment_payments")
        .select("*")
        .eq("appointment_id", appointment_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]


@router.put("/{appointment_id}/payment", response_model=AppointmentPaymentResponse)
async def save_appointment_payment(
    appointment_id: str,
    body: SaveAppointmentPaymentRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    appointment = _get_appointment_for_business(appointment_id, body.business_id)
    if body.status == "paid" and not body.payment_type:
        raise HTTPException(status_code=400, detail="Payment type is required before marking payment paid")

    line_items, selected_taxes, subtotal, tax_total, tip_amount, grand_total = _build_payment_snapshot(body)
    existing = (
        supabase_admin.table("appointment_payments")
        .select("id, paid_at")
        .eq("appointment_id", appointment_id)
        .eq("business_id", body.business_id)
        .limit(1)
        .execute()
    )

    paid_at = None
    if body.status == "paid":
        paid_at = (existing.data or [{}])[0].get("paid_at") or datetime.now(timezone.utc).isoformat()

    row = {
        "appointment_id": appointment_id,
        "business_id": body.business_id,
        "location_id": body.location_id or appointment.get("location_id"),
        "status": body.status,
        "payment_type": body.payment_type,
        "line_items": line_items,
        "selected_taxes": selected_taxes,
        "subtotal": float(subtotal),
        "tax_total": float(tax_total),
        "tip_amount": float(tip_amount),
        "grand_total": float(grand_total),
        "paid_at": paid_at,
        "updated_by": user_id,
    }

    if existing.data:
        result = (
            supabase_admin.table("appointment_payments")
            .update(row)
            .eq("id", existing.data[0]["id"])
            .execute()
        )
    else:
        result = (
            supabase_admin.table("appointment_payments")
            .insert({**row, "created_by": user_id})
            .execute()
        )

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to save payment details")
    return result.data[0]
