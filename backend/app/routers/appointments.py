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
    CreatePaymentEntryRequest,
    UpdatePaymentEntryRequest,
    RefundPaymentRequest,
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


def _get_business_code_flags(business_id: str) -> dict:
    result = (
        supabase_admin.table("businesses")
        .select("require_checkin_employee_code, require_payment_employee_code")
        .eq("id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return {"require_checkin_employee_code": False, "require_payment_employee_code": False}
    return result.data[0]


def _resolve_employee_code(business_id: str, code: str | None) -> str:
    if not code:
        raise HTTPException(status_code=422, detail="Employee code required")
    result = (
        supabase_admin.table("user_roles")
        .select("user_id")
        .eq("business_id", business_id)
        .eq("check_in_code", code)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=422, detail="Invalid employee code")
    return result.data[0]["user_id"]


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


def _fetch_payment_entries(appointment_payment_id: str) -> list[dict]:
    result = (
        supabase_admin.table("appointment_payment_entries")
        .select("*")
        .eq("appointment_payment_id", appointment_payment_id)
        .order("paid_at")
        .execute()
    )
    return result.data or []


def _get_payment_row_or_404(appointment_id: str, business_id: str) -> dict:
    result = (
        supabase_admin.table("appointment_payments")
        .select("*")
        .eq("appointment_id", appointment_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Save payment details before recording a payment")
    return result.data[0]


def _build_full_payment_response(payment_row: dict) -> dict:
    entries = _fetch_payment_entries(payment_row["id"])
    grand_total = _money(payment_row.get("grand_total"))

    paid_amount = Decimal("0.00")
    fully_paid_at: str | None = None
    for entry in entries:
        paid_amount += _money(entry.get("amount"))
        if fully_paid_at is None and paid_amount >= grand_total and grand_total > 0:
            fully_paid_at = entry.get("paid_at")

    owing_amount = (grand_total - paid_amount).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)

    refunded_at = payment_row.get("refunded_at")
    if refunded_at:
        status = "refunded"
    elif paid_amount <= 0:
        status = "unpaid"
    elif paid_amount < grand_total:
        status = "partially_paid"
    else:
        status = "paid"

    return {
        **payment_row,
        "entries": entries,
        "paid_amount": float(paid_amount),
        "owing_amount": float(owing_amount),
        "status": status,
        "paid_at": fully_paid_at,
    }


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

    update_row: dict = {"status": body.status}
    if body.status in {"checked_in", "no_show", "cancelled"}:
        if _get_business_code_flags(body.business_id)["require_checkin_employee_code"]:
            # Shared front-desk login case: the code identifies which employee actually performed
            # the action, since the authenticated session may not be theirs.
            attributed_user_id = _resolve_employee_code(body.business_id, body.employee_code)
            # Immutable snapshot of the code actually entered — distinct from user_roles.check_in_code,
            # which may be reset later. This one never changes after the fact.
            employee_code = body.employee_code
        else:
            # No code required for this business — attribute to whoever is actually logged in
            # rather than leaving the record unattributed.
            attributed_user_id = user_id
            employee_code = None
        now = datetime.now(timezone.utc).isoformat()
        if body.status == "checked_in":
            update_row["checked_in_by_user_id"] = attributed_user_id
            update_row["checked_in_by_code"] = employee_code
            update_row["checked_in_at"] = now
        elif body.status == "no_show":
            update_row["no_show_by_user_id"] = attributed_user_id
            update_row["no_show_by_code"] = employee_code
            update_row["no_show_at"] = now
        elif body.status == "cancelled":
            update_row["cancelled_by_user_id"] = attributed_user_id
            update_row["cancelled_by_code"] = employee_code
            update_row["cancelled_at"] = now

    result = (
        supabase_admin.table("appointments")
        .update(update_row)
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
    return _build_full_payment_response(result.data[0])


@router.put("/{appointment_id}/payment", response_model=AppointmentPaymentResponse)
async def save_appointment_payment(
    appointment_id: str,
    body: SaveAppointmentPaymentRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    appointment = _get_appointment_for_business(appointment_id, body.business_id)

    line_items, selected_taxes, subtotal, tax_total, tip_amount, grand_total = _build_payment_snapshot(body)
    existing = (
        supabase_admin.table("appointment_payments")
        .select("id")
        .eq("appointment_id", appointment_id)
        .eq("business_id", body.business_id)
        .limit(1)
        .execute()
    )

    row = {
        "appointment_id": appointment_id,
        "business_id": body.business_id,
        "location_id": body.location_id or appointment.get("location_id"),
        "line_items": line_items,
        "selected_taxes": selected_taxes,
        "subtotal": float(subtotal),
        "tax_total": float(tax_total),
        "tip_amount": float(tip_amount),
        "grand_total": float(grand_total),
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
    return _build_full_payment_response(result.data[0])


@router.post("/{appointment_id}/payment/entries", response_model=AppointmentPaymentResponse)
async def add_payment_entry(
    appointment_id: str,
    body: CreatePaymentEntryRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    payment_row = _get_payment_row_or_404(appointment_id, body.business_id)

    line_items = payment_row.get("line_items") or []
    if any(item.get("price") is None for item in line_items):
        raise HTTPException(status_code=400, detail="Enter a price for every service before recording a payment")

    amount = _money(body.amount)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")

    entry_row = {
        "appointment_payment_id": payment_row["id"],
        "business_id": body.business_id,
        "payment_type": body.payment_type,
        "amount": float(amount),
        "note": body.note,
        "created_by": user_id,
        "updated_by": user_id,
    }
    if _get_business_code_flags(body.business_id)["require_payment_employee_code"]:
        entry_row["collected_by_user_id"] = _resolve_employee_code(body.business_id, body.employee_code)
        # Immutable snapshot of the code actually entered — see checked_in_by_code for rationale.
        entry_row["collected_by_code"] = body.employee_code
    if body.paid_at:
        entry_row["paid_at"] = body.paid_at

    result = supabase_admin.table("appointment_payment_entries").insert(entry_row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to record payment")

    return _build_full_payment_response(payment_row)


@router.patch("/{appointment_id}/payment/entries/{entry_id}", response_model=AppointmentPaymentResponse)
async def update_payment_entry(
    appointment_id: str,
    entry_id: str,
    body: UpdatePaymentEntryRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    payment_row = _get_payment_row_or_404(appointment_id, body.business_id)

    updates: dict = {"updated_by": user_id}
    if body.payment_type is not None:
        updates["payment_type"] = body.payment_type
    if body.amount is not None:
        amount = _money(body.amount)
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero")
        updates["amount"] = float(amount)
    if body.note is not None:
        updates["note"] = body.note

    result = (
        supabase_admin.table("appointment_payment_entries")
        .update(updates)
        .eq("id", entry_id)
        .eq("appointment_payment_id", payment_row["id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Payment entry not found")

    return _build_full_payment_response(payment_row)


@router.delete("/{appointment_id}/payment/entries/{entry_id}", response_model=AppointmentPaymentResponse)
async def delete_payment_entry(
    appointment_id: str,
    entry_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    payment_row = _get_payment_row_or_404(appointment_id, business_id)

    result = (
        supabase_admin.table("appointment_payment_entries")
        .delete()
        .eq("id", entry_id)
        .eq("appointment_payment_id", payment_row["id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Payment entry not found")

    return _build_full_payment_response(payment_row)


@router.post("/{appointment_id}/payment/refund", response_model=AppointmentPaymentResponse)
async def refund_appointment_payment(
    appointment_id: str,
    body: RefundPaymentRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    payment_row = _get_payment_row_or_404(appointment_id, body.business_id)

    result = (
        supabase_admin.table("appointment_payments")
        .update({"refunded_at": datetime.now(timezone.utc).isoformat(), "updated_by": user_id})
        .eq("id", payment_row["id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to mark payment refunded")
    return _build_full_payment_response(result.data[0])


@router.delete("/{appointment_id}/payment/refund", response_model=AppointmentPaymentResponse)
async def unrefund_appointment_payment(
    appointment_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    payment_row = _get_payment_row_or_404(appointment_id, business_id)

    result = (
        supabase_admin.table("appointment_payments")
        .update({"refunded_at": None, "updated_by": user_id})
        .eq("id", payment_row["id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to clear refund status")
    return _build_full_payment_response(result.data[0])
