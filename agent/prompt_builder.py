"""
System prompt / instructions builder for the voice agent.
Assembles context from Supabase (business, hours, services, brand voice, staff, KB).
"""

import json
import logging

from supabase_helpers import (
    _get_supabase,
    _fetch_business,
    _fetch_location,
    _fetch_locations,
    _fetch_services_for_location,
    _fetch_staff_with_ids,
    _fetch_business_hours_for_location,
    _fetch_knowledge_base_for_location,
    _fetch_active_custom_schedule,
    _fetch_forwarding_contacts,
)

logger = logging.getLogger("voice-agent")

DEFAULT_INSTRUCTIONS = """
You are a helpful AI customer service assistant.
Be friendly, professional, and concise in all responses.
If you cannot help with something, offer to transfer the caller to a human agent.

Booking a new appointment:
1. If this call is already tied to a specific location, default to that location. Only ask about another branch if the caller explicitly asks for one.
2. Ask what service they need, then use get_services if you don't already have the list.
3. Ask if they have a preferred staff member.
4. Use find_next_available_slot to proactively offer the next available time — pass staff_name if they expressed a preference, leave it empty to search all qualified staff. Offer the caller 2–3 options from the result. Do NOT ask the caller to pick a date before calling this tool.
5. If the caller prefers a specific date instead, use get_available_slots for that date and staff member.
6. Collect the customer's name, phone number, and email address (required for confirmation email).
7. Repeat all details back clearly before calling book_appointment.
8. Confirm the booking reference once done.

Rescheduling or cancelling:
1. Start by looking up the appointment for the current called location using find_appointments.
2. Read back the appointment details (service, date, time) — do NOT read out the ref ID to the customer, it is for internal use only.
3. If nothing is found for the current location, ask whether the booking may be at another branch. Only then retry with cross-location search.
4. If multiple appointments are found, ask which one they mean by service and date — not by ref.
5. For reschedule: use find_next_available_slot or get_available_slots to find a new time, then call update_appointment passing appointment_ref and client_name internally.
6. For cancel: confirm once more verbally using service + date + time (e.g. "Just to confirm, you'd like to cancel your Haircut on April 2nd at 4 PM?"), then call cancel_appointment passing appointment_ref and client_name internally.

Location rules:
- You are answering calls for a specific branch. Only discuss services, staff, and availability for that branch.
- If a caller asks about services or staff at a different branch, do NOT provide that information. Instead, use get_other_location_phone to get their phone number and direct the caller there.
- If a caller wants to book at a different branch, politely explain that you can only book for the current branch and provide the other branch's phone number.
- You may freely provide phone numbers for other branches when callers explicitly ask for them.

General rules:
- Always respond in English. Only switch to another language if the caller explicitly speaks in that language and continues in it.
- Never invent availability — always use the tools to check.
- Confirm details clearly before any write action (book, update, cancel).
- If a tool returns an error, apologise and offer to transfer to a human.
"""


def _format_global_settings(business: dict) -> str:
    parts = []
    lang = business.get("language")
    country = business.get("country")
    date_fmt = business.get("date_format")
    time_fmt = business.get("time_format")
    if lang or country:
        locale = " and ".join(p for p in [lang, country] if p)
        if locale:
            parts.append(f"Use the business language and region: {locale}. Speak in that language unless the caller uses another.")
    if date_fmt:
        parts.append(f"When stating dates use this format: {date_fmt}.")
    if time_fmt:
        parts.append(f"When stating times use {time_fmt} format.")
    if not parts:
        return ""
    return "Global settings: " + " ".join(parts) + "\n\n"


def _format_brand_voice(profile: dict) -> str:
    parts = []
    tone = profile.get("tone")
    style = profile.get("style")
    if tone:
        parts.append(f"Tone: {tone}.")
    if style:
        parts.append(f"Style: {style}.")

    vocabulary = profile.get("vocabulary")
    if vocabulary is not None:
        if isinstance(vocabulary, str):
            try:
                vocabulary = json.loads(vocabulary)
            except json.JSONDecodeError:
                vocabulary = None
        if isinstance(vocabulary, list) and vocabulary:
            preferred, avoid = [], []
            for item in vocabulary:
                if isinstance(item, dict):
                    if item.get("preferred"):
                        preferred.append(str(item["preferred"]))
                    if item.get("avoid"):
                        avoid.append(str(item["avoid"]))
            if preferred:
                parts.append(f"Prefer saying: {', '.join(preferred)}.")
            if avoid:
                parts.append(f"Avoid saying: {', '.join(avoid)}.")

    do_not_say = profile.get("do_not_say")
    if do_not_say and isinstance(do_not_say, list):
        phrases = [str(p) for p in do_not_say if p]
        if phrases:
            parts.append(f"Never say these words or phrases: {', '.join(phrases)}.")

    sample_responses = profile.get("sample_responses")
    if sample_responses is not None:
        if isinstance(sample_responses, str):
            try:
                sample_responses = json.loads(sample_responses)
            except json.JSONDecodeError:
                sample_responses = None
        if isinstance(sample_responses, list) and sample_responses:
            examples = []
            for item in sample_responses[:3]:
                if isinstance(item, dict) and item.get("scenario") and item.get("response"):
                    examples.append(f"Example ({item['scenario']}): \"{item['response']}\"")
            if examples:
                parts.append("Follow the style of these example responses: " + "; ".join(examples) + ".")

    if not parts:
        return ""
    return "Brand voice: " + " ".join(parts) + "\n\n"


def _format_locations_and_employees(
    locations: list[dict],
    employees_by_location: dict[str, list[str]],
) -> str:
    if not locations:
        return ""
    lines = []
    for loc in locations:
        loc_id = loc.get("id")
        name = loc.get("name") or "Unknown"
        address = loc.get("address") or ""
        phone = loc.get("phone") or ""
        parts = [f"Location: {name}"]
        if address:
            parts.append(f"address: {address}")
        if phone:
            parts.append(f"phone: {phone}")
        staff = (employees_by_location.get(loc_id) if loc_id else []) or []
        if staff:
            parts.append(f"staff: {', '.join(staff)}")
        lines.append("; ".join(parts))
    return "Locations and staff: " + " | ".join(lines) + "\n\n"


def _format_called_location_context(location: dict | None, staff_names: list[str]) -> str:
    """Format the active called-location block so the agent treats it as authoritative."""
    if not location:
        return ""

    parts = [f"Active called location: {location.get('name') or 'Unknown'}."]
    if location.get("address"):
        parts.append(f"Address: {location['address']}.")
    if location.get("phone"):
        parts.append(f"Location phone: {location['phone']}.")
    if staff_names:
        parts.append(f"Staff at this location: {', '.join(staff_names)}.")
    parts.append(
        "Treat this as the caller's primary branch context. "
        "Default new bookings to this location, and search this location first for updates or cancellations."
    )
    return " ".join(parts) + "\n\n"


def _fetch_business_hours(supabase, business_id: str) -> list[dict]:
    """Fetch weekly business hours from business_hours table."""
    if not supabase or not business_id:
        return []
    try:
        r = (
            supabase.table("business_hours")
            .select("day_of_week, open_time, close_time, is_open")
            .eq("business_id", business_id)
            .execute()
        )
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch business hours: %s", e)
        return []


def _fetch_knowledge_base(supabase, business_id: str) -> list[dict]:
    """Fetch text entries from knowledge_base table (excludes unprocessed files)."""
    if not supabase or not business_id:
        return []
    try:
        r = (
            supabase.table("knowledge_base")
            .select("title, text_content")
            .eq("business_id", business_id)
            .eq("content_type", "text")
            .execute()
        )
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch knowledge base: %s", e)
        return []


def _format_business_details(business: dict) -> str:
    """Format full business info block for the prompt."""
    parts = []
    if business.get("type"):
        parts.append(f"Business type: {business['type']}.")
    if business.get("phone"):
        parts.append(f"Phone: {business['phone']}.")
    if business.get("email"):
        parts.append(f"Email: {business['email']}.")
    if business.get("address"):
        parts.append(f"Address: {business['address']}.")
    if business.get("website"):
        parts.append(f"Website: {business['website']}.")
    if business.get("service_area"):
        parts.append(f"Service area: {business['service_area']}.")
    if business.get("payment_methods"):
        parts.append(f"Payment methods accepted: {business['payment_methods']}.")
    if business.get("extra_fees"):
        parts.append(f"Extra fees: {business['extra_fees']}.")
    if business.get("return_policy"):
        parts.append(f"Return/refund policy: {business['return_policy']}.")
    if business.get("warranty_info"):
        parts.append(f"Warranty: {business['warranty_info']}.")
    if business.get("terms_conditions"):
        parts.append(f"Terms & conditions: {business['terms_conditions']}.")
    if business.get("privacy_policy"):
        parts.append(f"Privacy policy: {business['privacy_policy']}.")
    if not parts:
        return ""
    return "Business details: " + " ".join(parts) + "\n\n"


def _format_business_hours(hours: list[dict]) -> str:
    """Format business hours into a readable prompt block."""
    if not hours:
        return ""
    day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_label = {
        "monday": "Mon", "tuesday": "Tue", "wednesday": "Wed",
        "thursday": "Thu", "friday": "Fri", "saturday": "Sat", "sunday": "Sun",
    }
    hours_map = {row["day_of_week"]: row for row in hours if row.get("day_of_week")}

    def fmt_time(t: str | None) -> str:
        if not t:
            return ""
        try:
            h, m = map(int, t[:5].split(":"))
            suffix = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            return f"{h12}:{m:02d} {suffix}"
        except Exception:
            return t[:5]

    parts = []
    for day in day_order:
        row = hours_map.get(day)
        if not row:
            continue
        label = day_label.get(day, day.capitalize())
        if row.get("is_open"):
            open_t = fmt_time(row.get("open_time"))
            close_t = fmt_time(row.get("close_time"))
            parts.append(f"{label} {open_t}–{close_t}")
        else:
            parts.append(f"{label} Closed")

    if not parts:
        return ""
    return "Business hours: " + ", ".join(parts) + ".\n\n"


def _format_services_for_prompt(services: list[dict]) -> str:
    """Format services list for the system prompt (upfront knowledge)."""
    if not services:
        return ""
    lines = []
    for svc in services:
        name = svc.get("name", "")
        dur = svc.get("duration_minutes")
        price = svc.get("price")
        desc = svc.get("description") or ""
        parts = [f"- {name}"]
        details = []
        if dur:
            details.append(f"{dur} min")
        if price and price > 0:
            details.append(f"${price:.2f}")
        elif price == -1:
            details.append("price varies")
        if desc:
            details.append(desc)
        if details:
            parts.append(f"({', '.join(details)})")
        lines.append(" ".join(parts))
    return "Services offered:\n" + "\n".join(lines) + "\n\n"


def _format_forwarding_contacts(contacts: list[dict]) -> str:
    """
    Format forwarding contacts + their natural-language rules.
    Option C: agent invokes forward_call(contact_id) to do a real SIP REFER transfer.
    contact_id is included in the prompt so the agent can pass it to the tool.
    """
    if not contacts:
        return ""
    lines = []
    for c in contacts:
        title = (c.get("department_tag") or "").strip() or "Staff"
        rule = (c.get("forwarding_rule") or "").strip() or "(no specific rule — use judgment)"
        lines.append(
            f"- {c.get('name', 'Unknown')} ({title}) [contact_id: {c.get('id', '')}] — phone: {c.get('phone', 'n/a')}. Rule: {rule}"
        )
    return (
        "Forwarding Contacts — when a caller asks to speak with a specific person or department "
        "and their rule clearly matches the caller's request, confirm with the caller first, then "
        "call forward_call(contact_id) with the contact_id shown below to transfer the call. "
        "If no contact's rule clearly matches, offer to take a message instead.\n"
        + "\n".join(lines)
        + "\n\n"
    )


def _format_knowledge_base(entries: list[dict]) -> str:
    """Format knowledge base text entries for the prompt."""
    if not entries:
        return ""
    blocks = []
    for entry in entries:
        text = (entry.get("text_content") or "").strip()
        if text:
            blocks.append(text)
    if not blocks:
        return ""
    return "Additional business information:\n" + "\n\n".join(blocks) + "\n\n"


def _fetch_brand_voice(supabase, business_id: str) -> dict | None:
    if not supabase or not business_id:
        return None
    try:
        r = (
            supabase.table("brand_voice_profiles")
            .select("*")
            .eq("business_id", business_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        data = getattr(r, "data", None) or []
        return data[0] if data and isinstance(data[0], dict) else None
    except Exception as e:
        logger.warning("Failed to fetch brand voice: %s", e)
        return None


def build_instructions(business_id: str | None, location_id: str | None) -> str:
    """
    Build the full agent system prompt from all business data in Supabase:
    welcome · global settings · business details · hours · services ·
    brand voice · locations + staff · knowledge base · default instructions
    """
    company_name = "your company"
    location_phrase = ""

    supabase = _get_supabase()

    business = _fetch_business(supabase, business_id) if business_id else None
    if business and business.get("name"):
        company_name = business["name"]

    global_block   = _format_global_settings(business)   if business else ""
    details_block  = _format_business_details(business)  if business else ""

    # Location-scoped fetches (hours, services, KB) — no fallback
    biz_hours    = _fetch_business_hours_for_location(supabase, business_id, location_id) if business_id else []

    # Apply an active custom schedule (if any) for the called location
    active_custom = None
    if business_id:
        active_custom = _fetch_active_custom_schedule(supabase, business_id, location_id)

    if active_custom:
        if active_custom.get("is_agent_disabled"):
            # Override the entire hours block with a closed message
            hours_block = (
                f"Special notice: The agent is temporarily unavailable due to "
                f"'{active_custom.get('name') or 'a scheduled closure'}'. "
                f"Apologise to the caller, tell them the business is currently closed, "
                f"and offer to take a message or suggest calling back later.\n\n"
            )
        else:
            # Override today's row in biz_hours with the custom times
            from datetime import datetime as _dt
            today_dow = _dt.now().strftime("%A").lower()
            new_hours = []
            found = False
            for row in biz_hours:
                if row.get("day_of_week") == today_dow:
                    new_hours.append({
                        "day_of_week": today_dow,
                        "is_open": True,
                        "open_time": active_custom["open_time"],
                        "close_time": active_custom["close_time"],
                    })
                    found = True
                else:
                    new_hours.append(row)
            if not found:
                new_hours.append({
                    "day_of_week": today_dow,
                    "is_open": True,
                    "open_time": active_custom["open_time"],
                    "close_time": active_custom["close_time"],
                })
            biz_hours = new_hours
            hours_block = (
                _format_business_hours(biz_hours)
                + f"Today's hours are affected by the active schedule '{active_custom.get('name')}'.\n\n"
            )
    else:
        hours_block = _format_business_hours(biz_hours)

    services       = _fetch_services_for_location(supabase, business_id, location_id) if business_id else []
    services_block = _format_services_for_prompt(services)

    # Brand voice stays BUSINESS-WIDE (Global Settings)
    brand       = _fetch_brand_voice(supabase, business_id) if business_id else None
    brand_block = _format_brand_voice(brand) if brand else ""

    locations: list[dict] = []
    staff_list: list[dict] = []
    locations_block = ""
    if business_id:
        locations = _fetch_locations(supabase, business_id)
        staff_list = _fetch_staff_with_ids(supabase, business_id)
        if location_id:
            # Location-scoped call: show other branches with phone only so the
            # agent can direct callers there but cannot book or discuss their services.
            other_locs = [l for l in locations if l.get("id") != location_id]
            if other_locs:
                lines = []
                for loc in other_locs:
                    parts = [loc.get("name") or "Unknown"]
                    if loc.get("phone"):
                        parts.append(f"phone: {loc['phone']}")
                    lines.append(" — ".join(parts))
                locations_block = (
                    "Other branches (phone number only — do NOT book or discuss services/staff for these locations; "
                    "if the caller asks, direct them to call that branch directly):\n"
                    + "\n".join(f"- {l}" for l in lines)
                    + "\n\n"
                )
        else:
            employees_by_location: dict[str, list[str]] = {}
            for s in staff_list:
                for lid in s.get("location_ids", []):
                    employees_by_location.setdefault(lid, []).append(s["name"])
            locations_block = _format_locations_and_employees(locations, employees_by_location)

    kb_entries = _fetch_knowledge_base_for_location(supabase, business_id, location_id) if business_id else []
    kb_block   = _format_knowledge_base(kb_entries)

    fwd_contacts = _fetch_forwarding_contacts(supabase, business_id, location_id) if business_id else []
    fwd_block    = _format_forwarding_contacts(fwd_contacts)

    # Only use an explicit location_id. Do not fall back to the first location.
    _loc_to_use = None
    if supabase and location_id:
        _loc_to_use = _fetch_location(supabase, location_id)
    active_location_staff: list[str] = []
    if _loc_to_use:
        active_location_staff = [
            s["name"]
            for s in staff_list
            if _loc_to_use.get("id") in (s.get("location_ids") or [])
        ]
    active_location_block = _format_called_location_context(_loc_to_use, active_location_staff)
    if _loc_to_use:
        parts = [_loc_to_use.get("name"), _loc_to_use.get("city"), _loc_to_use.get("state"), _loc_to_use.get("country")]
        spoken = ", ".join(p for p in parts if p)
        if spoken:
            location_phrase = f" in {spoken}"

    welcome = (
        f"You are the AI phone receptionist for {company_name}{location_phrase}. "
        "Always start the call with a short, friendly welcome that includes the business name"
    )
    if location_phrase:
        welcome += " and the location"
    welcome += (
        ". Example: \"Thank you for calling "
        f"{company_name}{location_phrase}, how can I help you today?\" "
        "Then continue the conversation following these rules:\n\n"
    )

    return (
        welcome
        + global_block
        + active_location_block
        + details_block
        + hours_block
        + services_block
        + brand_block
        + locations_block
        + kb_block
        + fwd_block
        + DEFAULT_INSTRUCTIONS.strip()
    )
