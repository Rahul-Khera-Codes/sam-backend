from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import require_business_access
from app.core.supabase import supabase_admin

router = APIRouter(prefix="/reports", tags=["reports"])

MONEY_QUANT = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def _parse_date_range(start_date: str, end_date: str) -> tuple[str, str]:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="start_date/end_date must be in YYYY-MM-DD format")
    if end < start:
        raise HTTPException(status_code=422, detail="end_date must be on or after start_date")
    start_iso = f"{start.isoformat()}T00:00:00+00:00"
    end_iso_exclusive = f"{(end + timedelta(days=1)).isoformat()}T00:00:00+00:00"
    return start_iso, end_iso_exclusive


def _empty_bucket() -> dict:
    return {"subtotal": Decimal("0.00"), "tax": Decimal("0.00"), "tip": Decimal("0.00"), "payment_count": 0}


def _add_to_bucket(bucket: dict, entry_subtotal: Decimal, entry_tax: Decimal, entry_tip: Decimal) -> None:
    bucket["subtotal"] += entry_subtotal
    bucket["tax"] += entry_tax
    bucket["tip"] += entry_tip
    bucket["payment_count"] += 1


def _serialize_bucket(bucket: dict) -> dict:
    subtotal = _money(bucket["subtotal"])
    tax = _money(bucket["tax"])
    tip = _money(bucket["tip"])
    return {
        "subtotal": float(subtotal),
        "tax": float(tax),
        "tip": float(tip),
        "total": float((subtotal + tax + tip).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)),
        "payment_count": bucket["payment_count"],
    }


def _fetch_profile_names(user_ids: set[str]) -> dict[str, str]:
    ids = [uid for uid in user_ids if uid]
    if not ids:
        return {}
    result = (
        supabase_admin.table("profiles")
        .select("id, first_name, last_name")
        .in_("id", ids)
        .execute()
    )
    names: dict[str, str] = {}
    for row in result.data or []:
        name = f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip()
        names[row["id"]] = name or "Unnamed"
    return names


@router.get("/payment-summary")
async def get_payment_summary_report(
    business_id: str,
    start_date: str,
    end_date: str,
    location_id: Optional[str] = None,
    employee_ids: Optional[str] = None,
    _: str = Depends(require_business_access()),
):
    """Revenue report over appointment_payment_entries for a date range.

    Filtering by `employee_ids` (comma-separated user ids) scopes to
    appointments whose `assigned_user_id` is in the set — that's the
    "employee who made the appointment" per the source ticket, and unlike
    `collected_by_user_id` it's always populated regardless of whether a
    business has AIE-28 payment codes turned on. The by_assigned_employee /
    by_collected_employee breakdowns are then both computed over that same
    scoped set.

    Tip/tax are invoice-level (`appointment_payments.tip_amount`/`tax_total`),
    not per payment entry, so a single payment entry's amount is split into
    subtotal/tax/tip portions using the parent invoice's own ratios
    (subtotal:tax:tip out of grand_total) — this handles split/partial
    payments correctly without needing to guess which entry "gets" the tip.
    """
    start_iso, end_iso_exclusive = _parse_date_range(start_date, end_date)
    employee_id_filter = {e for e in (employee_ids or "").split(",") if e}

    invoices_query = (
        supabase_admin.table("appointment_payments")
        .select("id, appointment_id, subtotal, tax_total, tip_amount, grand_total, location_id, refunded_at")
        .eq("business_id", business_id)
        .is_("refunded_at", "null")
    )
    if location_id:
        invoices_query = invoices_query.eq("location_id", location_id)
    invoices = invoices_query.execute().data or []
    if not invoices:
        return _empty_report(start_date, end_date)

    appointment_ids = list({inv["appointment_id"] for inv in invoices if inv.get("appointment_id")})
    appointments = (
        supabase_admin.table("appointments")
        .select("id, assigned_user_id")
        .in_("id", appointment_ids)
        .execute()
        .data
        or []
    )
    assigned_by_appointment = {a["id"]: a.get("assigned_user_id") for a in appointments}

    if employee_id_filter:
        invoices = [
            inv for inv in invoices
            if assigned_by_appointment.get(inv["appointment_id"]) in employee_id_filter
        ]
    if not invoices:
        return _empty_report(start_date, end_date)

    invoices_by_id = {inv["id"]: inv for inv in invoices}
    entries = (
        supabase_admin.table("appointment_payment_entries")
        .select("id, payment_type, amount, paid_at, collected_by_user_id, collected_by_code, appointment_payment_id")
        .eq("business_id", business_id)
        .gte("paid_at", start_iso)
        .lt("paid_at", end_iso_exclusive)
        .in_("appointment_payment_id", list(invoices_by_id.keys()))
        .execute()
        .data
        or []
    )

    totals = _empty_bucket()
    by_date: dict[str, dict] = defaultdict(_empty_bucket)
    by_payment_type: dict[str, dict] = defaultdict(_empty_bucket)
    by_assigned_employee: dict[Optional[str], dict] = defaultdict(_empty_bucket)
    by_collected_employee: dict[Optional[str], dict] = defaultdict(_empty_bucket)
    collected_codes: dict[Optional[str], set[str]] = defaultdict(set)

    for entry in entries:
        invoice = invoices_by_id.get(entry["appointment_payment_id"])
        if not invoice:
            continue
        grand_total = _money(invoice.get("grand_total"))
        amount = _money(entry.get("amount"))
        if grand_total > 0:
            entry_tax = (amount * _money(invoice.get("tax_total")) / grand_total).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
            entry_tip = (amount * _money(invoice.get("tip_amount")) / grand_total).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
            entry_subtotal = (amount - entry_tax - entry_tip).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        else:
            entry_tax = Decimal("0.00")
            entry_tip = Decimal("0.00")
            entry_subtotal = amount

        _add_to_bucket(totals, entry_subtotal, entry_tax, entry_tip)

        paid_date = (entry.get("paid_at") or "")[:10]
        if paid_date:
            _add_to_bucket(by_date[paid_date], entry_subtotal, entry_tax, entry_tip)

        _add_to_bucket(by_payment_type[entry.get("payment_type") or "other"], entry_subtotal, entry_tax, entry_tip)

        assigned_user_id = assigned_by_appointment.get(invoice.get("appointment_id"))
        _add_to_bucket(by_assigned_employee[assigned_user_id], entry_subtotal, entry_tax, entry_tip)

        collected_user_id = entry.get("collected_by_user_id")
        _add_to_bucket(by_collected_employee[collected_user_id], entry_subtotal, entry_tax, entry_tip)
        collected_code = entry.get("collected_by_code")
        if collected_code:
            collected_codes[collected_user_id].add(collected_code)

    profile_names = _fetch_profile_names(
        set(by_assigned_employee.keys()) | set(by_collected_employee.keys())
    )

    def _employee_breakdown(buckets: dict[Optional[str], dict], codes: dict[Optional[str], set[str]] | None = None) -> list[dict]:
        rows = []
        for user_id, bucket in buckets.items():
            row = {
                "user_id": user_id,
                "name": profile_names.get(user_id, "Unnamed") if user_id else "Unattributed",
                **_serialize_bucket(bucket),
            }
            if codes is not None:
                # Immutable per-transaction snapshots (appointment_payment_entries.collected_by_code),
                # not the employee's live user_roles.check_in_code — that stays write-only per AIE-28.
                row["codes"] = sorted(codes.get(user_id, set()))
            rows.append(row)
        rows.sort(key=lambda r: r["total"], reverse=True)
        return rows

    return {
        "start_date": start_date,
        "end_date": end_date,
        "totals": _serialize_bucket(totals),
        "by_date": [
            {"date": d, **_serialize_bucket(b)}
            for d, b in sorted(by_date.items())
        ],
        "by_payment_type": [
            {"payment_type": t, **_serialize_bucket(b)}
            for t, b in sorted(by_payment_type.items())
        ],
        "by_assigned_employee": _employee_breakdown(by_assigned_employee),
        "by_collected_employee": _employee_breakdown(by_collected_employee, collected_codes),
    }


def _empty_report(start_date: str, end_date: str) -> dict:
    return {
        "start_date": start_date,
        "end_date": end_date,
        "totals": _serialize_bucket(_empty_bucket()),
        "by_date": [],
        "by_payment_type": [],
        "by_assigned_employee": [],
        "by_collected_employee": [],
    }
