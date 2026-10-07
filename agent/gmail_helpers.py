"""
Gmail sending helpers for the voice agent (async HTTP).
All functions are best-effort — failures are logged, not raised.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from constants import GOOGLE_TOKEN_URL, GMAIL_SEND_URL
from supabase_helpers import _fmt_time_12h
from token_crypto import decrypt_oauth_token, encrypt_oauth_token

logger = logging.getLogger("voice-agent")


async def _gmail_get_valid_token(
    supabase,
    business_id: str,
    location_id: str | None = None,
) -> tuple[str | None, str]:
    """
    Return (access_token, sender_email) for the business's Gmail connection.

    Gmail is one connection per business — there's no per-location connect UI,
    so location_id is accepted for call-site compatibility but ignored for
    lookup. Scoping by location let a stale row from an old reconnect attempt
    (e.g. pre-location-feature rows an April migration re-tagged with a
    specific location_id) "shadow" a working newer connection stored under a
    different location_id, even though a valid token existed for the business
    (AIE-90/AIE-99). Tries every token row for this business, newest first,
    skipping any that fail to decrypt/refresh, until one actually works.
    """
    try:
        r = (
            supabase.table("gmail_tokens")
            .select("*")
            .eq("business_id", business_id)
            .order("created_at", desc=True)
            .execute()
        )
        rows = getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to list Gmail tokens for business %s: %s", business_id, e)
        return None, ""

    for row in rows:
        resolved = await _gmail_resolve_token_row(supabase, row)
        if resolved:
            return resolved
    return None, ""


async def _gmail_resolve_token_row(supabase, row: dict) -> tuple[str, str] | None:
    """Decrypt a single gmail_tokens row and refresh it if expired. Returns
    None (rather than raising) if the row is unusable, so the caller can move
    on to the next candidate row instead of failing outright."""
    try:
        access_token = decrypt_oauth_token(row.get("access_token"))
        refresh_token = decrypt_oauth_token(row.get("refresh_token"))
        google_email = row.get("google_email", "")

        expiry_raw = row.get("token_expiry")
        if expiry_raw:
            try:
                expiry = datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00"))
            except ValueError:
                expiry = datetime.now(timezone.utc)
        else:
            expiry = datetime.now(timezone.utc)  # null expiry → treat as expired
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) < expiry:
            return access_token, google_email

        import httpx
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            return None
        async with httpx.AsyncClient() as http:
            resp = await http.post(GOOGLE_TOKEN_URL, data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            })
            if resp.status_code != 200:
                logger.warning(
                    "Gmail token refresh failed for row %s (business %s): %s %s",
                    row.get("id"), row.get("business_id"), resp.status_code, resp.text[:300],
                )
                return None
            refreshed = resp.json()
        new_expiry = datetime.now(timezone.utc) + timedelta(seconds=refreshed.get("expires_in", 3600) - 60)
        supabase.table("gmail_tokens").update({
            "access_token": encrypt_oauth_token(refreshed["access_token"]),
            "token_expiry": new_expiry.isoformat(),
        }).eq("id", row["id"]).execute()
        return refreshed["access_token"], google_email
    except Exception as e:
        logger.warning("Failed to resolve Gmail token row %s: %s", row.get("id"), e)
        return None


async def _gmail_force_expire_tokens(supabase, business_id: str) -> None:
    """Mark every gmail_tokens row for this business as already-expired, so the
    next _gmail_get_valid_token call is forced to actually refresh each one
    against Google rather than trusting a locally-stored expiry that has just
    been proven wrong (see _gmail_send_raw)."""
    try:
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        supabase.table("gmail_tokens").update({"token_expiry": past}).eq("business_id", business_id).execute()
    except Exception as e:
        logger.warning("Failed to force-expire Gmail tokens for business %s: %s", business_id, e)


async def _gmail_send_raw(supabase, business_id: str, access_token: str, raw: str) -> tuple[bool, int, str]:
    """
    POST a prepared raw MIME message to the Gmail send API.

    A token can be rejected by Gmail with 401 even when our stored
    token_expiry says it should still be valid — confirmed live 2026-10-07
    (Woyce Tech business: stored expiry ~51 min out, Gmail's own tokeninfo
    endpoint confirmed the token valid, yet the send call still got a 401).
    Rather than chase the exact cause (clock drift, a concurrent refresh
    elsewhere, external revocation), treat a live 401 as the ground truth:
    force every token row for this business to be re-checked for real against
    Google, then retry the send exactly once with whatever comes back.
    """
    import httpx

    async def _post(token: str) -> "httpx.Response":
        async with httpx.AsyncClient() as http:
            return await http.post(
                GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {token}"},
                json={"raw": raw},
            )

    resp = await _post(access_token)
    if resp.status_code == 401:
        logger.warning(
            "Gmail send got 401 with a token that looked valid (business %s) — forcing refresh and retrying once",
            business_id,
        )
        await _gmail_force_expire_tokens(supabase, business_id)
        new_token, _ = await _gmail_get_valid_token(supabase, business_id, None)
        if new_token and new_token != access_token:
            resp = await _post(new_token)

    return resp.status_code in (200, 201), resp.status_code, resp.text[:200]


async def _gmail_connection_diagnostic(
    supabase,
    business_id: str,
    location_id: str | None,
) -> str:
    """
    Build an actionable message when _gmail_get_valid_token found no usable
    token for this business. Gmail is business-wide, not per-location (see
    _gmail_get_valid_token), so this no longer reasons about location — it
    only distinguishes "nothing connected yet" from "a connection exists but
    none of it still works" (e.g. revoked access), which the old
    location-framed message couldn't express and used to misreport as a
    location mismatch (AIE-90/AIE-99).
    """
    try:
        r = (
            supabase.table("gmail_tokens")
            .select("id")
            .eq("business_id", business_id)
            .execute()
        )
        rows = getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Gmail connection diagnostic query failed for business %s: %s", business_id, e)
        rows = []

    if not rows:
        return "Gmail isn't connected for this business yet. Connect it under Settings → Business Settings → Integrations."

    return (
        "Gmail was connected before, but the connection no longer works (it may have expired "
        "or been revoked). Reconnect it under Settings → Business Settings → Integrations."
    )


async def _gmail_send_confirmation(
    supabase,
    business_id: str,
    location_id: str | None,
    business_name: str,
    business_phone: str,
    client_name: str,
    client_email: str,
    service: str,
    staff_name: str,
    location: str,
    date: str,
    time: str,
    duration_minutes: int,
    confirmation_ref: str,
    business_timezone: str = "",
) -> None:
    """Send appointment confirmation email with .ics calendar attachment (best-effort)."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    from ics_helpers import generate_ics

    access_token, sender_email = await _gmail_get_valid_token(supabase, business_id, location_id)
    if not access_token:
        logger.info("Gmail not connected for business %s — skipping email", business_id)
        return

    time_12h = _fmt_time_12h(time)
    subject = f"Appointment Confirmed — {service} on {date}"

    plain = (
        f"Hi {client_name},\n\nYour appointment is confirmed!\n\n"
        f"Service:   {service}\nWith:      {staff_name}\nLocation:  {location}\n"
        f"Date:      {date}\nTime:      {time_12h}\nDuration:  {duration_minutes} min\n"
        f"Ref:       {confirmation_ref}\n\n"
        + (f"To reschedule, call us at {business_phone}.\n\n" if business_phone else "")
        + f"Thank you,\n{business_name}"
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
body{{margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
.w{{max-width:560px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
.h{{background:#18181b;padding:28px 32px;}}.h h1{{margin:0;color:#fff;font-size:20px;}}.h p{{margin:4px 0 0;color:#a1a1aa;font-size:13px;}}
.badge{{display:inline-block;background:#22c55e;color:#fff;font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;margin-top:12px;}}
.b{{padding:28px 32px;}}.g{{font-size:16px;color:#18181b;margin:0 0 20px;}}
.card{{background:#f9f9f9;border:1px solid #e4e4e7;border-radius:8px;padding:20px 24px;margin-bottom:24px;}}
.row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #e4e4e7;}}
.row:last-child{{border-bottom:none;}}.lbl{{color:#71717a;font-size:13px;}}.val{{color:#18181b;font-size:13px;font-weight:500;}}
.ref{{background:#18181b;color:#fff;text-align:center;border-radius:8px;padding:14px;font-size:18px;letter-spacing:2px;font-weight:700;margin-bottom:24px;}}
.ref-lbl{{font-size:11px;color:#a1a1aa;margin-bottom:4px;}}
.foot{{padding:20px 32px;background:#f4f4f5;font-size:12px;color:#71717a;text-align:center;}}
</style></head>
<body><div class="w">
<div class="h"><h1>{business_name}</h1><p>Appointment Confirmation</p><span class="badge">CONFIRMED</span></div>
<div class="b">
<p class="g">Hi {client_name}, your appointment is confirmed!</p>
<div class="card">
<div class="row"><span class="lbl">Service</span><span class="val">{service}</span></div>
<div class="row"><span class="lbl">With</span><span class="val">{staff_name}</span></div>
<div class="row"><span class="lbl">Location</span><span class="val">{location}</span></div>
<div class="row"><span class="lbl">Date</span><span class="val">{date}</span></div>
<div class="row"><span class="lbl">Time</span><span class="val">{time_12h}</span></div>
<div class="row"><span class="lbl">Duration</span><span class="val">{duration_minutes} min</span></div>
</div>
<div class="ref"><div class="ref-lbl">CONFIRMATION REFERENCE</div>{confirmation_ref}</div>
{"<p style='color:#71717a;font-size:13px;margin:0'>Need to reschedule? Call us at " + business_phone + "</p>" if business_phone else ""}
</div>
<div class="foot">&copy; {business_name} &bull; Automated confirmation</div>
</div></body></html>"""

    # Build .ics calendar attachment
    ics_content = generate_ics(
        summary=f"{service} — {business_name}",
        description=f"Appointment with {staff_name} at {location}.\nRef: {confirmation_ref}",
        location=location,
        date=date,
        time=time,
        duration_minutes=duration_minutes,
        timezone=business_timezone,
        organizer_email=sender_email,
        attendee_email=client_email,
        uid=f"{confirmation_ref}@aiemployees",
    )

    # Outer: mixed (HTML body + attachment)
    msg = MIMEMultipart("mixed")
    msg["From"] = f"{business_name} <{sender_email}>"
    msg["To"] = client_email
    msg["Subject"] = subject

    # Inner: alternative (plain + html)
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(plain, "plain"))
    body_part.attach(MIMEText(html, "html"))
    msg.attach(body_part)

    # .ics attachment
    ics_part = MIMEBase("text", "calendar", method="REQUEST", name="appointment.ics")
    ics_part.set_payload(ics_content.encode("utf-8"))
    encoders.encode_base64(ics_part)
    ics_part.add_header("Content-Disposition", "attachment", filename="appointment.ics")
    msg.attach(ics_part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        sent, status, text = await _gmail_send_raw(supabase, business_id, access_token, raw)
        if sent:
            logger.info("Confirmation email with .ics sent to %s", client_email)
        else:
            logger.warning("Gmail send failed %s: %s", status, text)
    except Exception as e:
        logger.warning("Failed to send Gmail confirmation: %s", e)


async def _gmail_send_staff_notification(
    supabase,
    business_id: str,
    location_id: str | None,
    business_name: str,
    staff_user_id: str,
    staff_name: str,
    client_name: str,
    client_phone: str,
    client_email: str,
    service: str,
    location: str,
    date: str,
    time: str,
    duration_minutes: int,
    confirmation_ref: str,
) -> None:
    """Send a new-booking notification to the assigned staff member (best-effort)."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    access_token, sender_email = await _gmail_get_valid_token(supabase, business_id, location_id)
    if not access_token:
        return

    staff_email = ""
    try:
        resp = supabase.auth.admin.get_user_by_id(staff_user_id)
        user = getattr(resp, "user", None)
        if user:
            staff_email = getattr(user, "email", "") or ""
    except Exception as e:
        logger.warning("Could not fetch staff email for %s: %s", staff_user_id, e)

    if not staff_email:
        logger.info("No email found for staff %s — skipping staff notification", staff_user_id)
        return

    time_12h = _fmt_time_12h(time)
    subject = f"New Booking: {client_name} — {service} on {date}"

    plain = (
        f"Hi {staff_name},\n\nYou have a new appointment!\n\n"
        f"Customer:  {client_name}\n"
        f"Phone:     {client_phone}\n"
        + (f"Email:     {client_email}\n" if client_email else "")
        + f"Service:   {service}\n"
        f"Location:  {location}\n"
        f"Date:      {date}\n"
        f"Time:      {time_12h}\n"
        f"Duration:  {duration_minutes} min\n"
        f"Ref:       {confirmation_ref}\n\n"
        f"— {business_name}"
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
body{{margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
.w{{max-width:560px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
.h{{background:#18181b;padding:28px 32px;}}.h h1{{margin:0;color:#fff;font-size:20px;}}.h p{{margin:4px 0 0;color:#a1a1aa;font-size:13px;}}
.badge{{display:inline-block;background:#3b82f6;color:#fff;font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;margin-top:12px;}}
.b{{padding:28px 32px;}}.g{{font-size:16px;color:#18181b;margin:0 0 20px;}}
.card{{background:#f9f9f9;border:1px solid #e4e4e7;border-radius:8px;padding:20px 24px;margin-bottom:24px;}}
.section-label{{font-size:11px;font-weight:600;color:#71717a;text-transform:uppercase;letter-spacing:.8px;margin-bottom:12px;}}
.row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #e4e4e7;}}
.row:last-child{{border-bottom:none;}}.lbl{{color:#71717a;font-size:13px;}}.val{{color:#18181b;font-size:13px;font-weight:500;}}
.ref{{background:#18181b;color:#fff;text-align:center;border-radius:8px;padding:14px;font-size:18px;letter-spacing:2px;font-weight:700;margin-bottom:0;}}
.ref-lbl{{font-size:11px;color:#a1a1aa;margin-bottom:4px;}}
.foot{{padding:20px 32px;background:#f4f4f5;font-size:12px;color:#71717a;text-align:center;}}
</style></head>
<body><div class="w">
<div class="h"><h1>{business_name}</h1><p>New Appointment Notification</p><span class="badge">NEW BOOKING</span></div>
<div class="b">
<p class="g">Hi {staff_name}, you have a new appointment!</p>
<div class="card">
<div class="section-label">Customer</div>
<div class="row"><span class="lbl">Name</span><span class="val">{client_name}</span></div>
<div class="row"><span class="lbl">Phone</span><span class="val">{client_phone}</span></div>
{"<div class='row'><span class='lbl'>Email</span><span class='val'>" + client_email + "</span></div>" if client_email else ""}
</div>
<div class="card">
<div class="section-label">Appointment</div>
<div class="row"><span class="lbl">Service</span><span class="val">{service}</span></div>
<div class="row"><span class="lbl">Location</span><span class="val">{location}</span></div>
<div class="row"><span class="lbl">Date</span><span class="val">{date}</span></div>
<div class="row"><span class="lbl">Time</span><span class="val">{time_12h}</span></div>
<div class="row"><span class="lbl">Duration</span><span class="val">{duration_minutes} min</span></div>
</div>
<div class="ref"><div class="ref-lbl">CONFIRMATION REFERENCE</div>{confirmation_ref}</div>
</div>
<div class="foot">&copy; {business_name} &bull; Staff notification</div>
</div></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{business_name} <{sender_email}>"
    msg["To"] = staff_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        sent, status, text = await _gmail_send_raw(supabase, business_id, access_token, raw)
        if sent:
            logger.info("Staff notification sent to %s", staff_email)
        else:
            logger.warning("Staff Gmail notify failed %s: %s", status, text)
    except Exception as e:
        logger.warning("Failed to send staff notification email: %s", e)


async def _gmail_send_reschedule_confirmation(
    supabase,
    business_id: str,
    location_id: str | None,
    business_name: str,
    business_phone: str,
    client_name: str,
    client_email: str,
    service: str,
    staff_name: str,
    location: str,
    new_date: str,
    new_time: str,
    duration_minutes: int,
    confirmation_ref: str,
    business_timezone: str = "",
) -> None:
    """Send reschedule confirmation email with .ics attachment (best-effort)."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    from ics_helpers import generate_ics

    access_token, sender_email = await _gmail_get_valid_token(supabase, business_id, location_id)
    if not access_token:
        return

    time_12h = _fmt_time_12h(new_time)
    subject = f"Appointment Rescheduled — {service} on {new_date}"

    plain = (
        f"Hi {client_name},\n\nYour appointment has been rescheduled.\n\n"
        f"Service:   {service}\nWith:      {staff_name}\nLocation:  {location}\n"
        f"New Date:  {new_date}\nNew Time:  {time_12h}\nDuration:  {duration_minutes} min\n"
        f"Ref:       {confirmation_ref}\n\n"
        + (f"Need further changes? Call us at {business_phone}.\n\n" if business_phone else "")
        + f"Thank you,\n{business_name}"
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
body{{margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
.w{{max-width:560px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
.h{{background:#18181b;padding:28px 32px;}}.h h1{{margin:0;color:#fff;font-size:20px;}}.h p{{margin:4px 0 0;color:#a1a1aa;font-size:13px;}}
.badge{{display:inline-block;background:#f59e0b;color:#fff;font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;margin-top:12px;}}
.b{{padding:28px 32px;}}.g{{font-size:16px;color:#18181b;margin:0 0 20px;}}
.card{{background:#f9f9f9;border:1px solid #e4e4e7;border-radius:8px;padding:20px 24px;margin-bottom:24px;}}
.row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #e4e4e7;}}
.row:last-child{{border-bottom:none;}}.lbl{{color:#71717a;font-size:13px;}}.val{{color:#18181b;font-size:13px;font-weight:500;}}
.ref{{background:#18181b;color:#fff;text-align:center;border-radius:8px;padding:14px;font-size:18px;letter-spacing:2px;font-weight:700;margin-bottom:24px;}}
.ref-lbl{{font-size:11px;color:#a1a1aa;margin-bottom:4px;}}
.foot{{padding:20px 32px;background:#f4f4f5;font-size:12px;color:#71717a;text-align:center;}}
</style></head>
<body><div class="w">
<div class="h"><h1>{business_name}</h1><p>Appointment Rescheduled</p><span class="badge">RESCHEDULED</span></div>
<div class="b">
<p class="g">Hi {client_name}, your appointment has been rescheduled.</p>
<div class="card">
<div class="row"><span class="lbl">Service</span><span class="val">{service}</span></div>
<div class="row"><span class="lbl">With</span><span class="val">{staff_name}</span></div>
<div class="row"><span class="lbl">Location</span><span class="val">{location}</span></div>
<div class="row"><span class="lbl">New Date</span><span class="val">{new_date}</span></div>
<div class="row"><span class="lbl">New Time</span><span class="val">{time_12h}</span></div>
<div class="row"><span class="lbl">Duration</span><span class="val">{duration_minutes} min</span></div>
</div>
<div class="ref"><div class="ref-lbl">CONFIRMATION REFERENCE</div>{confirmation_ref}</div>
{"<p style='color:#71717a;font-size:13px;margin:0'>Need further changes? Call us at " + business_phone + "</p>" if business_phone else ""}
</div>
<div class="foot">&copy; {business_name} &bull; Automated notification</div>
</div></body></html>"""

    # .ics with updated time
    ics_content = generate_ics(
        summary=f"{service} — {business_name} (Rescheduled)",
        description=f"Rescheduled appointment with {staff_name} at {location}.\nRef: {confirmation_ref}",
        location=location,
        date=new_date,
        time=new_time,
        duration_minutes=duration_minutes,
        timezone=business_timezone,
        organizer_email=sender_email,
        attendee_email=client_email,
        uid=f"{confirmation_ref}@aiemployees",
    )

    msg = MIMEMultipart("mixed")
    msg["From"] = f"{business_name} <{sender_email}>"
    msg["To"] = client_email
    msg["Subject"] = subject

    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(plain, "plain"))
    body_part.attach(MIMEText(html, "html"))
    msg.attach(body_part)

    ics_part = MIMEBase("text", "calendar", method="REQUEST", name="appointment.ics")
    ics_part.set_payload(ics_content.encode("utf-8"))
    encoders.encode_base64(ics_part)
    ics_part.add_header("Content-Disposition", "attachment", filename="appointment.ics")
    msg.attach(ics_part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        sent, status, text = await _gmail_send_raw(supabase, business_id, access_token, raw)
        if sent:
            logger.info("Reschedule confirmation with .ics sent to %s", client_email)
        else:
            logger.warning("Gmail reschedule send failed %s: %s", status, text)
    except Exception as e:
        logger.warning("Failed to send reschedule confirmation: %s", e)


async def _gmail_send_staff_reschedule_notification(
    supabase,
    business_id: str,
    location_id: str | None,
    business_name: str,
    staff_user_id: str,
    staff_name: str,
    client_name: str,
    client_phone: str,
    client_email: str,
    service: str,
    location: str,
    new_date: str,
    new_time: str,
    duration_minutes: int,
    confirmation_ref: str,
) -> None:
    """Notify assigned staff of a rescheduled appointment (best-effort)."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    access_token, sender_email = await _gmail_get_valid_token(supabase, business_id, location_id)
    if not access_token:
        return

    staff_email = ""
    try:
        resp = supabase.auth.admin.get_user_by_id(staff_user_id)
        user = getattr(resp, "user", None)
        if user:
            staff_email = getattr(user, "email", "") or ""
    except Exception as e:
        logger.warning("Could not fetch staff email for %s: %s", staff_user_id, e)

    if not staff_email:
        return

    time_12h = _fmt_time_12h(new_time)
    subject = f"Appointment Rescheduled: {client_name} — {service} on {new_date}"

    plain = (
        f"Hi {staff_name},\n\nAn appointment has been rescheduled.\n\n"
        f"Customer:  {client_name}\nPhone:     {client_phone}\n"
        + (f"Email:     {client_email}\n" if client_email else "")
        + f"Service:   {service}\nLocation:  {location}\n"
        f"New Date:  {new_date}\nNew Time:  {time_12h}\nDuration:  {duration_minutes} min\n"
        f"Ref:       {confirmation_ref}\n\n— {business_name}"
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
body{{margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
.w{{max-width:560px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
.h{{background:#18181b;padding:28px 32px;}}.h h1{{margin:0;color:#fff;font-size:20px;}}.h p{{margin:4px 0 0;color:#a1a1aa;font-size:13px;}}
.badge{{display:inline-block;background:#f59e0b;color:#fff;font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;margin-top:12px;}}
.b{{padding:28px 32px;}}.g{{font-size:16px;color:#18181b;margin:0 0 20px;}}
.card{{background:#f9f9f9;border:1px solid #e4e4e7;border-radius:8px;padding:20px 24px;margin-bottom:24px;}}
.section-label{{font-size:11px;font-weight:600;color:#71717a;text-transform:uppercase;letter-spacing:.8px;margin-bottom:12px;}}
.row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #e4e4e7;}}
.row:last-child{{border-bottom:none;}}.lbl{{color:#71717a;font-size:13px;}}.val{{color:#18181b;font-size:13px;font-weight:500;}}
.foot{{padding:20px 32px;background:#f4f4f5;font-size:12px;color:#71717a;text-align:center;}}
</style></head>
<body><div class="w">
<div class="h"><h1>{business_name}</h1><p>Appointment Rescheduled</p><span class="badge">RESCHEDULED</span></div>
<div class="b">
<p class="g">Hi {staff_name}, an appointment has been rescheduled.</p>
<div class="card">
<div class="section-label">Customer</div>
<div class="row"><span class="lbl">Name</span><span class="val">{client_name}</span></div>
<div class="row"><span class="lbl">Phone</span><span class="val">{client_phone}</span></div>
{"<div class='row'><span class='lbl'>Email</span><span class='val'>" + client_email + "</span></div>" if client_email else ""}
</div>
<div class="card">
<div class="section-label">New Schedule</div>
<div class="row"><span class="lbl">Service</span><span class="val">{service}</span></div>
<div class="row"><span class="lbl">Location</span><span class="val">{location}</span></div>
<div class="row"><span class="lbl">New Date</span><span class="val">{new_date}</span></div>
<div class="row"><span class="lbl">New Time</span><span class="val">{time_12h}</span></div>
<div class="row"><span class="lbl">Duration</span><span class="val">{duration_minutes} min</span></div>
<div class="row"><span class="lbl">Ref</span><span class="val">{confirmation_ref}</span></div>
</div>
</div>
<div class="foot">&copy; {business_name} &bull; Staff notification</div>
</div></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{business_name} <{sender_email}>"
    msg["To"] = staff_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        sent, status, text = await _gmail_send_raw(supabase, business_id, access_token, raw)
        if sent:
            logger.info("Staff reschedule notification sent to %s", staff_email)
        else:
            logger.warning("Staff reschedule notify failed %s: %s", status, text)
    except Exception as e:
        logger.warning("Failed to send staff reschedule notification: %s", e)


async def _gmail_send_cancellation_confirmation(
    supabase,
    business_id: str,
    location_id: str | None,
    business_name: str,
    business_phone: str,
    client_name: str,
    client_email: str,
    service: str,
    staff_name: str,
    location: str,
    date: str,
    time: str,
    duration_minutes: int,
    confirmation_ref: str,
) -> None:
    """Send cancellation confirmation email to the customer (best-effort)."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    access_token, sender_email = await _gmail_get_valid_token(supabase, business_id, location_id)
    if not access_token:
        return

    time_12h = _fmt_time_12h(time)
    subject = f"Appointment Cancelled — {service} on {date}"

    plain = (
        f"Hi {client_name},\n\nYour appointment has been cancelled.\n\n"
        f"Service:   {service}\nWith:      {staff_name}\nLocation:  {location}\n"
        f"Date:      {date}\nTime:      {time_12h}\nRef:       {confirmation_ref}\n\n"
        + (f"To book a new appointment, call us at {business_phone}.\n\n" if business_phone else "")
        + f"Thank you,\n{business_name}"
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
body{{margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
.w{{max-width:560px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
.h{{background:#18181b;padding:28px 32px;}}.h h1{{margin:0;color:#fff;font-size:20px;}}.h p{{margin:4px 0 0;color:#a1a1aa;font-size:13px;}}
.badge{{display:inline-block;background:#ef4444;color:#fff;font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;margin-top:12px;}}
.b{{padding:28px 32px;}}.g{{font-size:16px;color:#18181b;margin:0 0 20px;}}
.card{{background:#f9f9f9;border:1px solid #e4e4e7;border-radius:8px;padding:20px 24px;margin-bottom:24px;}}
.row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #e4e4e7;}}
.row:last-child{{border-bottom:none;}}.lbl{{color:#71717a;font-size:13px;}}.val{{color:#18181b;font-size:13px;font-weight:500;}}
.ref{{background:#18181b;color:#fff;text-align:center;border-radius:8px;padding:14px;font-size:18px;letter-spacing:2px;font-weight:700;margin-bottom:24px;}}
.ref-lbl{{font-size:11px;color:#a1a1aa;margin-bottom:4px;}}
.foot{{padding:20px 32px;background:#f4f4f5;font-size:12px;color:#71717a;text-align:center;}}
</style></head>
<body><div class="w">
<div class="h"><h1>{business_name}</h1><p>Appointment Cancelled</p><span class="badge">CANCELLED</span></div>
<div class="b">
<p class="g">Hi {client_name}, your appointment has been cancelled.</p>
<div class="card">
<div class="row"><span class="lbl">Service</span><span class="val">{service}</span></div>
<div class="row"><span class="lbl">With</span><span class="val">{staff_name}</span></div>
<div class="row"><span class="lbl">Location</span><span class="val">{location}</span></div>
<div class="row"><span class="lbl">Date</span><span class="val">{date}</span></div>
<div class="row"><span class="lbl">Time</span><span class="val">{time_12h}</span></div>
</div>
<div class="ref"><div class="ref-lbl">CANCELLED REFERENCE</div>{confirmation_ref}</div>
{"<p style='color:#71717a;font-size:13px;margin:0'>To rebook, call us at " + business_phone + "</p>" if business_phone else ""}
</div>
<div class="foot">&copy; {business_name} &bull; Automated notification</div>
</div></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{business_name} <{sender_email}>"
    msg["To"] = client_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        sent, status, text = await _gmail_send_raw(supabase, business_id, access_token, raw)
        if sent:
            logger.info("Cancellation email sent to %s", client_email)
        else:
            logger.warning("Gmail cancel send failed %s: %s", status, text)
    except Exception as e:
        logger.warning("Failed to send cancellation email: %s", e)


async def _gmail_send_staff_cancellation_notification(
    supabase,
    business_id: str,
    location_id: str | None,
    business_name: str,
    staff_user_id: str,
    staff_name: str,
    client_name: str,
    client_phone: str,
    client_email: str,
    service: str,
    location: str,
    date: str,
    time: str,
    duration_minutes: int,
    confirmation_ref: str,
) -> None:
    """Notify assigned staff of a cancelled appointment (best-effort)."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    access_token, sender_email = await _gmail_get_valid_token(supabase, business_id, location_id)
    if not access_token:
        return

    staff_email = ""
    try:
        resp = supabase.auth.admin.get_user_by_id(staff_user_id)
        user = getattr(resp, "user", None)
        if user:
            staff_email = getattr(user, "email", "") or ""
    except Exception as e:
        logger.warning("Could not fetch staff email for %s: %s", staff_user_id, e)

    if not staff_email:
        return

    time_12h = _fmt_time_12h(time)
    subject = f"Appointment Cancelled: {client_name} — {service} on {date}"

    plain = (
        f"Hi {staff_name},\n\nAn appointment has been cancelled.\n\n"
        f"Customer:  {client_name}\nPhone:     {client_phone}\n"
        + (f"Email:     {client_email}\n" if client_email else "")
        + f"Service:   {service}\nLocation:  {location}\n"
        f"Date:      {date}\nTime:      {time_12h}\n"
        f"Ref:       {confirmation_ref}\n\n— {business_name}"
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
body{{margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
.w{{max-width:560px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
.h{{background:#18181b;padding:28px 32px;}}.h h1{{margin:0;color:#fff;font-size:20px;}}.h p{{margin:4px 0 0;color:#a1a1aa;font-size:13px;}}
.badge{{display:inline-block;background:#ef4444;color:#fff;font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;margin-top:12px;}}
.b{{padding:28px 32px;}}.g{{font-size:16px;color:#18181b;margin:0 0 20px;}}
.card{{background:#f9f9f9;border:1px solid #e4e4e7;border-radius:8px;padding:20px 24px;margin-bottom:24px;}}
.section-label{{font-size:11px;font-weight:600;color:#71717a;text-transform:uppercase;letter-spacing:.8px;margin-bottom:12px;}}
.row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #e4e4e7;}}
.row:last-child{{border-bottom:none;}}.lbl{{color:#71717a;font-size:13px;}}.val{{color:#18181b;font-size:13px;font-weight:500;}}
.foot{{padding:20px 32px;background:#f4f4f5;font-size:12px;color:#71717a;text-align:center;}}
</style></head>
<body><div class="w">
<div class="h"><h1>{business_name}</h1><p>Appointment Cancelled</p><span class="badge">CANCELLED</span></div>
<div class="b">
<p class="g">Hi {staff_name}, an appointment has been cancelled.</p>
<div class="card">
<div class="section-label">Customer</div>
<div class="row"><span class="lbl">Name</span><span class="val">{client_name}</span></div>
<div class="row"><span class="lbl">Phone</span><span class="val">{client_phone}</span></div>
{"<div class='row'><span class='lbl'>Email</span><span class='val'>" + client_email + "</span></div>" if client_email else ""}
</div>
<div class="card">
<div class="section-label">Cancelled Appointment</div>
<div class="row"><span class="lbl">Service</span><span class="val">{service}</span></div>
<div class="row"><span class="lbl">Location</span><span class="val">{location}</span></div>
<div class="row"><span class="lbl">Date</span><span class="val">{date}</span></div>
<div class="row"><span class="lbl">Time</span><span class="val">{time_12h}</span></div>
<div class="row"><span class="lbl">Ref</span><span class="val">{confirmation_ref}</span></div>
</div>
</div>
<div class="foot">&copy; {business_name} &bull; Staff notification</div>
</div></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{business_name} <{sender_email}>"
    msg["To"] = staff_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        sent, status, text = await _gmail_send_raw(supabase, business_id, access_token, raw)
        if sent:
            logger.info("Staff cancellation notification sent to %s", staff_email)
        else:
            logger.warning("Staff cancel notify failed %s: %s", status, text)
    except Exception as e:
        logger.warning("Failed to send staff cancellation notification: %s", e)


async def _gmail_send_document_notification(
    supabase,
    business_id: str,
    location_id: str | None,
    business_name: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str,
    document_name: str,
    sent_at: str,
) -> None:
    """Notify the business Gmail (self-email) when a document is sent to a customer (best-effort)."""
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    access_token, sender_email = await _gmail_get_valid_token(supabase, business_id, location_id)
    if not access_token:
        return

    subject = f"Document Sent: {document_name} → {customer_name or customer_email}"

    plain = (
        f"Hi {business_name},\n\n"
        f"A document was sent to a customer during a call.\n\n"
        f"Document:  {document_name}\n"
        f"Customer:  {customer_name or '—'}\n"
        f"Email:     {customer_email}\n"
        f"Phone:     {customer_phone or '—'}\n"
        f"Sent at:   {sent_at}\n\n"
        f"You can follow up with this customer directly.\n\n"
        f"— AI Employees"
    )

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
body{{margin:0;padding:0;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
.w{{max-width:560px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);}}
.h{{background:#18181b;padding:28px 32px;}}.h h1{{margin:0;color:#fff;font-size:20px;}}.h p{{margin:4px 0 0;color:#a1a1aa;font-size:13px;}}
.badge{{display:inline-block;background:#3b82f6;color:#fff;font-size:11px;font-weight:600;padding:3px 10px;border-radius:999px;margin-top:12px;}}
.b{{padding:28px 32px;}}.g{{font-size:16px;color:#18181b;margin:0 0 20px;}}
.card{{background:#f9f9f9;border:1px solid #e4e4e7;border-radius:8px;padding:20px 24px;margin-bottom:24px;}}
.row{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #e4e4e7;}}
.row:last-child{{border-bottom:none;}}.lbl{{color:#71717a;font-size:13px;}}.val{{color:#18181b;font-size:13px;font-weight:500;}}
.foot{{padding:20px 32px;background:#f4f4f5;font-size:12px;color:#71717a;text-align:center;}}
</style></head>
<body><div class="w">
<div class="h"><h1>{business_name}</h1><p>Document Sent Notification</p><span class="badge">DOCUMENT SENT</span></div>
<div class="b">
<p class="g">A document was sent to a customer during a call.</p>
<div class="card">
<div class="row"><span class="lbl">Document</span><span class="val">{document_name}</span></div>
<div class="row"><span class="lbl">Customer</span><span class="val">{customer_name or '—'}</span></div>
<div class="row"><span class="lbl">Email</span><span class="val">{customer_email}</span></div>
<div class="row"><span class="lbl">Phone</span><span class="val">{customer_phone or '—'}</span></div>
<div class="row"><span class="lbl">Sent at</span><span class="val">{sent_at}</span></div>
</div>
<p style="color:#71717a;font-size:13px;margin:0">You can follow up with this customer directly.</p>
</div>
<div class="foot">&copy; {business_name} &bull; AI Employees automated notification</div>
</div></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{business_name} <{sender_email}>"
    msg["To"] = sender_email
    msg["Subject"] = subject
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    try:
        sent, status, text = await _gmail_send_raw(supabase, business_id, access_token, raw)
        if sent:
            logger.info("Document notification sent to business %s", sender_email)
        else:
            logger.warning("Document notification failed %s: %s", status, text)
    except Exception as e:
        logger.warning("Failed to send document notification: %s", e)
