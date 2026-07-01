"""
Gmail sending helpers for the voice agent (async HTTP).
All functions are best-effort — failures are logged, not raised.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from constants import GOOGLE_TOKEN_URL, GMAIL_SEND_URL
from supabase_helpers import _fmt_time_12h

logger = logging.getLogger("voice-agent")


async def _gmail_get_valid_token(
    supabase,
    business_id: str,
    location_id: str | None = None,
) -> tuple[str | None, str]:
    """
    Return (access_token, sender_email) for the business+location Gmail account.
    Refreshes the token if expired. No fallback — if the location has no token,
    returns (None, "") and the caller should skip sending.
    """
    try:
        query = supabase.table("gmail_tokens").select("*").eq("business_id", business_id)
        if location_id:
            query = query.eq("location_id", location_id)
        else:
            query = query.is_("location_id", "null")
        r = query.limit(1).execute()
        data = getattr(r, "data", None) or []
        if not data:
            return None, ""
        row = data[0]

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
        if datetime.now(timezone.utc) >= expiry:
                import httpx
                client_id = os.getenv("GOOGLE_CLIENT_ID", "")
                client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
                if not client_id or not client_secret:
                    return None, ""
                async with httpx.AsyncClient() as http:
                    resp = await http.post(GOOGLE_TOKEN_URL, data={
                        "refresh_token": row["refresh_token"],
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "grant_type": "refresh_token",
                    })
                    if resp.status_code != 200:
                        logger.warning(
                            "Gmail token refresh failed for business %s loc %s: %s %s",
                            business_id, location_id, resp.status_code, resp.text[:300],
                        )
                        return None, ""
                    refreshed = resp.json()
                new_expiry = datetime.now(timezone.utc) + timedelta(seconds=refreshed.get("expires_in", 3600) - 60)
                supabase.table("gmail_tokens").update({
                    "access_token": refreshed["access_token"],
                    "token_expiry": new_expiry.isoformat(),
                }).eq("id", row["id"]).execute()
                return refreshed["access_token"], row.get("google_email", "")

        return row["access_token"], row.get("google_email", "")
    except Exception as e:
        logger.warning("Failed to get Gmail token for business %s loc %s: %s", business_id, location_id, e)
        return None, ""


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
    import httpx
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
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
            if resp.status_code in (200, 201):
                logger.info("Confirmation email with .ics sent to %s", client_email)
            else:
                logger.warning("Gmail send failed %s: %s", resp.status_code, resp.text[:200])
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
    import httpx

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
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
            if resp.status_code in (200, 201):
                logger.info("Staff notification sent to %s", staff_email)
            else:
                logger.warning("Staff Gmail notify failed %s: %s", resp.status_code, resp.text[:200])
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
    import httpx
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
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
            if resp.status_code in (200, 201):
                logger.info("Reschedule confirmation with .ics sent to %s", client_email)
            else:
                logger.warning("Gmail reschedule send failed %s: %s", resp.status_code, resp.text[:200])
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
    import httpx

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
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
            if resp.status_code in (200, 201):
                logger.info("Staff reschedule notification sent to %s", staff_email)
            else:
                logger.warning("Staff reschedule notify failed %s: %s", resp.status_code, resp.text[:200])
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
    import httpx

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
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
            if resp.status_code in (200, 201):
                logger.info("Cancellation email sent to %s", client_email)
            else:
                logger.warning("Gmail cancel send failed %s: %s", resp.status_code, resp.text[:200])
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
    import httpx

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
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
            if resp.status_code in (200, 201):
                logger.info("Staff cancellation notification sent to %s", staff_email)
            else:
                logger.warning("Staff cancel notify failed %s: %s", resp.status_code, resp.text[:200])
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
    import httpx

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
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                GMAIL_SEND_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )
            if resp.status_code in (200, 201):
                logger.info("Document notification sent to business %s", sender_email)
            else:
                logger.warning("Document notification failed %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Failed to send document notification: %s", e)
