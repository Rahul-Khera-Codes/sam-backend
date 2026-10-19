"""
Resolve-or-create customer records at appointment-booking time (AIE-61).
Matches an existing `customers` row by phone (falling back to email), or creates
one, so every new appointment links back to a durable customer record.
"""
from typing import Optional


def _normalize_phone_e164(phone: str) -> str:
    """Same normalization as agent/agent.py's _normalize_phone_e164 (duplicated —
    backend/ and agent/ are separate deployables with no shared module)."""
    if not phone:
        return phone
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    elif len(digits) > 7:
        return f"+{digits}"
    return phone


def _split_name(client_name: str) -> tuple[str, str]:
    parts = (client_name or "").strip().split(maxsplit=1)
    if not parts:
        return "Unknown", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _same_name(row: dict, first_name: str, last_name: str) -> bool:
    return (
        (row.get("first_name") or "").strip().lower() == first_name.strip().lower()
        and (row.get("last_name") or "").strip().lower() == last_name.strip().lower()
    )


def resolve_or_create_customer(
    supabase,
    business_id: str,
    location_id: Optional[str],
    client_name: str,
    client_phone: Optional[str],
    client_email: Optional[str],
    do_not_contact: bool = False,
) -> Optional[str]:
    """Finds this business's customer for a booking, or creates one, and returns its id.

    A customer matches only when the name AND (phone or email) agree. Phone/email
    alone is not enough — family members and coworkers share them, and a different
    name on a known phone is a different person who belongs in the list (AIE-105).
    With no phone or email, the name alone matches only a customer that also has no
    phone or email on file, so name-only bookings still create a customer.
    Returns None only if there is no name at all.
    """
    first_name, last_name = _split_name(client_name)
    if not (client_name or "").strip():
        return None

    phone = _normalize_phone_e164(client_phone) if client_phone else None
    email = (client_email or "").strip().lower() or None

    candidates: list[dict] = []
    if phone or email:
        for col, val in (("phone", phone), ("email", email)):
            if val:
                found = (
                    supabase.table("customers")
                    .select("id, first_name, last_name")
                    .eq("business_id", business_id)
                    .eq(col, val)
                    .execute()
                )
                candidates.extend(found.data or [])
    else:
        found = (
            supabase.table("customers")
            .select("id, first_name, last_name")
            .eq("business_id", business_id)
            .is_("phone", "null")
            .is_("email", "null")
            .ilike("first_name", first_name)
            .execute()
        )
        candidates.extend(found.data or [])

    for row in candidates:
        if _same_name(row, first_name, last_name):
            return row["id"]

    created = supabase.table("customers").insert({
        "business_id": business_id,
        "location_id": location_id,
        "first_name": first_name or "Unknown",
        "last_name": last_name,
        "phone": phone,
        "email": email,
        "do_not_contact": do_not_contact,
    }).execute()
    if created.data:
        return created.data[0]["id"]
    return None
