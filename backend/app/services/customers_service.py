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


def resolve_or_create_customer(
    supabase,
    business_id: str,
    location_id: Optional[str],
    client_name: str,
    client_phone: Optional[str],
    client_email: Optional[str],
    do_not_contact: bool = False,
) -> Optional[str]:
    """Looks up an existing customer for this business by phone (or email if no
    phone), creates one if not found, and returns its id. Returns None if there's
    not enough identity info (no phone and no email) to resolve or create one.
    """
    phone = _normalize_phone_e164(client_phone) if client_phone else None
    email = (client_email or "").strip().lower() or None

    if not phone and not email:
        return None

    query = supabase.table("customers").select("id").eq("business_id", business_id)
    if phone:
        query = query.eq("phone", phone)
    else:
        query = query.eq("email", email)
    existing = query.limit(1).execute()
    if existing.data:
        return existing.data[0]["id"]

    first_name, last_name = _split_name(client_name)
    row = {
        "business_id": business_id,
        "location_id": location_id,
        "first_name": first_name or "Unknown",
        "last_name": last_name,
        "phone": phone,
        "email": email,
        "do_not_contact": do_not_contact,
    }
    created = supabase.table("customers").insert(row).execute()
    if created.data:
        return created.data[0]["id"]
    return None
