"""
Gmail API email service.

Sends transactional emails (appointment confirmations, reminders) via a business's
connected Gmail account using the Gmail REST API.

Token storage: gmail_tokens table (business_id unique key).
Token refresh is automatic before every send.
"""

import base64
import logging
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/userinfo.email openid"


# ── OAuth URL ─────────────────────────────────────────────────────────────────

def build_gmail_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GMAIL_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return f"{GOOGLE_AUTH_BASE}?{params}"


# ── Token exchange / refresh ──────────────────────────────────────────────────

async def exchange_code_for_tokens(
    code: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(
    refresh_token: str, client_id: str, client_secret: str
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def revoke_token(token: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(GOOGLE_REVOKE_URL, params={"token": token})


def token_expiry_from_response(token_data: dict) -> datetime:
    expires_in = int(token_data.get("expires_in", 3600))
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)


def is_token_expired(expiry_str: str) -> bool:
    try:
        expiry = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) >= expiry
    except Exception:
        return True


# ── Token row helpers ─────────────────────────────────────────────────────────

def get_token_row(supabase, business_id: str) -> Optional[dict]:
    result = (
        supabase.table("gmail_tokens")
        .select("*")
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


async def get_valid_access_token(
    supabase, business_id: str, client_id: str, client_secret: str
) -> Optional[str]:
    """Return a valid access token, refreshing if needed."""
    row = get_token_row(supabase, business_id)
    if not row:
        return None

    if is_token_expired(row["token_expiry"]):
        try:
            refreshed = await refresh_access_token(
                row["refresh_token"], client_id, client_secret
            )
            new_expiry = token_expiry_from_response(refreshed)
            supabase.table("gmail_tokens").update({
                "access_token": refreshed["access_token"],
                "token_expiry": new_expiry.isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("business_id", business_id).execute()
            return refreshed["access_token"]
        except Exception as e:
            logger.error("Gmail token refresh failed: %s", e)
            return None

    return row["access_token"]


# ── Email sending ─────────────────────────────────────────────────────────────

def _build_mime_message(
    sender: str,
    to: str,
    subject: str,
    html_body: str,
    plain_body: str = "",
) -> str:
    """Build a base64url-encoded MIME message ready for the Gmail API."""
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject

    if plain_body:
        msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return raw


async def send_email(
    access_token: str,
    sender: str,
    to: str,
    subject: str,
    html_body: str,
    plain_body: str = "",
) -> bool:
    """Send an email via the Gmail API. Returns True on success."""
    raw = _build_mime_message(sender, to, subject, html_body, plain_body)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
        )
        if resp.status_code not in (200, 201):
            logger.error("Gmail send failed %s: %s", resp.status_code, resp.text)
            return False
        return True


# ── Email templates ───────────────────────────────────────────────────────────

def _fmt_time_12h(time_24: str) -> str:
    try:
        h, m = map(int, time_24.split(":"))
        period = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {period}"
    except Exception:
        return time_24


def build_appointment_confirmation_email(
    client_name: str,
    client_email: str,
    service: str,
    staff_name: str,
    location: str,
    date: str,
    time: str,
    duration_minutes: int,
    confirmation_ref: str,
    business_name: str,
    business_phone: str = "",
) -> tuple[str, str, str]:
    """
    Returns (subject, html_body, plain_body) for an appointment confirmation email.
    """
    time_display = _fmt_time_12h(time)
    subject = f"Appointment Confirmed — {service} on {date}"

    plain = (
        f"Hi {client_name},\n\n"
        f"Your appointment has been confirmed!\n\n"
        f"Details:\n"
        f"  Service:   {service}\n"
        f"  With:      {staff_name}\n"
        f"  Location:  {location}\n"
        f"  Date:      {date}\n"
        f"  Time:      {time_display}\n"
        f"  Duration:  {duration_minutes} minutes\n"
        f"  Ref:       {confirmation_ref}\n\n"
        f"If you need to reschedule or cancel, please contact us"
        + (f" at {business_phone}" if business_phone else "") + ".\n\n"
        f"Thank you,\n{business_name}"
    )

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {{ margin: 0; padding: 0; background: #f4f4f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
    .wrapper {{ max-width: 560px; margin: 32px auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.08); }}
    .header {{ background: #18181b; padding: 28px 32px; }}
    .header h1 {{ margin: 0; color: #ffffff; font-size: 20px; font-weight: 600; }}
    .header p {{ margin: 4px 0 0; color: #a1a1aa; font-size: 13px; }}
    .badge {{ display: inline-block; background: #22c55e; color: #fff; font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 999px; letter-spacing: .5px; margin-top: 12px; }}
    .body {{ padding: 28px 32px; }}
    .greeting {{ font-size: 16px; color: #18181b; margin: 0 0 20px; }}
    .card {{ background: #f9f9f9; border: 1px solid #e4e4e7; border-radius: 8px; padding: 20px 24px; margin-bottom: 24px; }}
    .row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e4e4e7; }}
    .row:last-child {{ border-bottom: none; }}
    .label {{ color: #71717a; font-size: 13px; }}
    .value {{ color: #18181b; font-size: 13px; font-weight: 500; text-align: right; max-width: 60%; }}
    .ref-box {{ background: #18181b; color: #ffffff; text-align: center; border-radius: 8px; padding: 14px; font-size: 18px; letter-spacing: 2px; font-weight: 700; margin-bottom: 24px; }}
    .ref-label {{ font-size: 11px; color: #a1a1aa; margin-bottom: 4px; }}
    .footer {{ padding: 20px 32px; background: #f4f4f5; font-size: 12px; color: #71717a; text-align: center; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>{business_name}</h1>
      <p>Appointment Confirmation</p>
      <span class="badge">CONFIRMED</span>
    </div>
    <div class="body">
      <p class="greeting">Hi {client_name}, your appointment is confirmed!</p>
      <div class="card">
        <div class="row"><span class="label">Service</span><span class="value">{service}</span></div>
        <div class="row"><span class="label">With</span><span class="value">{staff_name}</span></div>
        <div class="row"><span class="label">Location</span><span class="value">{location}</span></div>
        <div class="row"><span class="label">Date</span><span class="value">{date}</span></div>
        <div class="row"><span class="label">Time</span><span class="value">{time_display}</span></div>
        <div class="row"><span class="label">Duration</span><span class="value">{duration_minutes} minutes</span></div>
      </div>
      <div class="ref-box">
        <div class="ref-label">CONFIRMATION REFERENCE</div>
        {confirmation_ref}
      </div>
      <p style="color:#71717a;font-size:13px;margin:0;">
        Need to reschedule or cancel?{"Contact us at " + business_phone + "." if business_phone else "Please contact us."}
      </p>
    </div>
    <div class="footer">&copy; {business_name} &bull; This is an automated confirmation email.</div>
  </div>
</body>
</html>"""

    return subject, html, plain


async def send_appointment_confirmation(
    supabase,
    business_id: str,
    client_name: str,
    client_email: str,
    service: str,
    staff_name: str,
    location: str,
    date: str,
    time: str,
    duration_minutes: int,
    confirmation_ref: str,
    business_name: str,
    business_phone: str = "",
    client_id: str = "",
    client_secret: str = "",
) -> bool:
    """
    High-level helper: get token, build email, send.
    Returns True if sent, False if Gmail not connected or send failed.
    """
    access_token = await get_valid_access_token(supabase, business_id, client_id, client_secret)
    if not access_token:
        logger.info("Gmail not connected for business %s — skipping confirmation email", business_id)
        return False

    token_row = get_token_row(supabase, business_id)
    sender = token_row["google_email"] if token_row else "noreply@example.com"

    subject, html_body, plain_body = build_appointment_confirmation_email(
        client_name=client_name,
        client_email=client_email,
        service=service,
        staff_name=staff_name,
        location=location,
        date=date,
        time=time,
        duration_minutes=duration_minutes,
        confirmation_ref=confirmation_ref,
        business_name=business_name,
        business_phone=business_phone,
    )

    try:
        sent = await send_email(
            access_token=access_token,
            sender=f"{business_name} <{sender}>",
            to=client_email,
            subject=subject,
            html_body=html_body,
            plain_body=plain_body,
        )
        if sent:
            logger.info("Appointment confirmation sent to %s", client_email)
        return sent
    except Exception as e:
        logger.error("Failed to send confirmation email: %s", e)
        return False
