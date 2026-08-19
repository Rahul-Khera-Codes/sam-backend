"""
Resend-based transactional email sending (Support + Wish List only).

Unlike email_service.py (Gmail, per-business OAuth), this sends from a fixed
platform sender via Resend's HTTP API — no business-level connection required.
"""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_SEND_URL = "https://api.resend.com/emails"


async def send_via_resend(
    *,
    from_email: str,
    to: str,
    subject: str,
    html_body: str,
    plain_body: str,
    reply_to: str | None = None,
) -> bool:
    payload = {
        "from": from_email,
        "to": [to],
        "subject": subject,
        "html": html_body,
        "text": plain_body,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.post(
                RESEND_SEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError:
            logger.exception("Resend request failed for subject=%r to=%s", subject, to)
            return False

    if response.status_code >= 300:
        logger.error(
            "Resend send failed (%s) for subject=%r to=%s: %s",
            response.status_code,
            subject,
            to,
            response.text,
        )
        return False

    return True
