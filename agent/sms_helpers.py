"""
SMS helpers for the voice agent.
Uses Twilio to send SMS from the business's provisioned phone number.

All functions are fire-and-forget — callers should wrap in try/except
so a failed SMS never blocks a booking or call finalization.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger("voice-agent")


def _get_twilio():
    """Return a Twilio REST client, or None if credentials are missing."""
    try:
        from twilio.rest import Client
        sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        token = os.getenv("TWILIO_AUTH_TOKEN", "")
        if not sid or not token:
            logger.warning("[SMS] TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN not set — SMS disabled")
            return None
        return Client(sid, token)
    except ImportError:
        logger.warning("[SMS] twilio package not installed — SMS disabled")
        return None


def _get_business_number(supabase, business_id: str) -> Optional[str]:
    """Look up the active Twilio phone number for a business (used as From)."""
    try:
        result = (
            supabase.table("business_phone_numbers")
            .select("phone_number")
            .eq("business_id", business_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["phone_number"]
    except Exception as e:
        logger.warning("[SMS] Could not fetch business phone number: %s", e)
    return None


def _send_sms(from_number: str, to_number: str, body: str) -> bool:
    """Low-level send. Returns True on success."""
    twilio = _get_twilio()
    if not twilio:
        return False
    try:
        msg = twilio.messages.create(from_=from_number, to=to_number, body=body)
        logger.info("[SMS] Sent %s → %s sid=%s", from_number, to_number, msg.sid)
        return True
    except Exception as e:
        logger.error("[SMS] Send failed from=%s to=%s: %s", from_number, to_number, e)
        return False


# ── Public send functions ─────────────────────────────────────────────────────

def send_appointment_confirmation_sms(
    supabase,
    business_id: str,
    business_name: str,
    client_phone: str,
    client_name: str,
    service: str,
    date: str,
    time_str: str,
    confirmation_ref: str,
) -> None:
    """
    Send a booking confirmation SMS to the customer.
    Fires after book_appointment when send_texts_during_after_calls is enabled.
    """
    from_number = _get_business_number(supabase, business_id)
    if not from_number or not client_phone:
        return

    body = (
        f"Hi {client_name}, your {service} at {business_name} is confirmed.\n"
        f"Date: {date}  Time: {time_str}\n"
        f"Ref: {confirmation_ref}\n"
        f"Questions? Reply or call {from_number}"
    )
    _send_sms(from_number, client_phone, body)


def send_appointment_reminder_sms(
    supabase,
    business_id: str,
    business_name: str,
    client_phone: str,
    client_name: str,
    service: str,
    date: str,
    time_str: str,
) -> None:
    """
    Send a reminder SMS. Called by a scheduler N days before the appointment.
    """
    from_number = _get_business_number(supabase, business_id)
    if not from_number or not client_phone:
        return

    body = (
        f"Reminder: {client_name}, you have {service} at {business_name} "
        f"on {date} at {time_str}.\n"
        f"Need to reschedule? Call {from_number}"
    )
    _send_sms(from_number, client_phone, body)


def send_missed_call_sms(
    supabase,
    business_id: str,
    business_name: str,
    caller_phone: str,
) -> None:
    """
    Send a text-back when a caller hangs up before the agent could help.
    Fires from _finalize_call when missed_call_text_back is enabled.
    """
    from_number = _get_business_number(supabase, business_id)
    if not from_number or not caller_phone:
        return

    body = (
        f"Hi! You recently called {business_name} and we missed you.\n"
        f"Reply here or call us back at {from_number} — we'd love to help!"
    )
    _send_sms(from_number, caller_phone, body)
