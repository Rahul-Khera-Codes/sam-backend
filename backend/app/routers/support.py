"""
Support and feature request routes.
"""

import html
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_user_id, verify_business_access
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.services import email_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["support"])

WISHLIST_RECIPIENT = "sam@aiemployeesinc.com"


class WishlistSubmissionRequest(BaseModel):
    business_id: str
    location_id: str | None = None
    name: str
    email: str
    subject: str
    message: str


def _build_wishlist_email_html(
    *,
    business_name: str,
    requester_name: str,
    requester_email: str,
    subject: str,
    message: str,
) -> str:
    escaped_business_name = html.escape(business_name)
    escaped_requester_name = html.escape(requester_name)
    escaped_requester_email = html.escape(requester_email)
    escaped_subject = html.escape(subject)
    escaped_message = html.escape(message).replace("\n", "<br />")
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
</head>
<body style="margin:0;padding:24px;background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:640px;margin:0 auto;background:#ffffff;border:1px solid #e4e4e7;border-radius:12px;overflow:hidden;">
    <div style="padding:24px 28px;background:#18181b;color:#ffffff;">
      <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#a1a1aa;">Wish List Submission</div>
      <h1 style="margin:8px 0 0;font-size:22px;font-weight:700;">{escaped_subject}</h1>
    </div>
    <div style="padding:28px;">
      <p style="margin:0 0 20px;font-size:14px;color:#52525b;">
        A new feature request was submitted from <strong>{escaped_business_name}</strong>.
      </p>
      <table style="width:100%;border-collapse:collapse;margin-bottom:24px;">
        <tr>
          <td style="padding:8px 0;color:#71717a;font-size:13px;width:140px;">Business</td>
          <td style="padding:8px 0;color:#18181b;font-size:13px;font-weight:600;">{escaped_business_name}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#71717a;font-size:13px;">Submitted by</td>
          <td style="padding:8px 0;color:#18181b;font-size:13px;font-weight:600;">{escaped_requester_name}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#71717a;font-size:13px;">Email</td>
          <td style="padding:8px 0;color:#18181b;font-size:13px;font-weight:600;">{escaped_requester_email}</td>
        </tr>
      </table>
      <div style="border:1px solid #e4e4e7;border-radius:10px;padding:20px;background:#fafafa;">
        <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#71717a;margin-bottom:10px;">Message</div>
        <div style="font-size:14px;line-height:1.6;color:#18181b;">{escaped_message}</div>
      </div>
    </div>
  </div>
</body>
</html>"""


@router.post("/wishlist")
async def submit_wishlist(
    body: WishlistSubmissionRequest,
    user_id: str = Depends(get_user_id),
):
    requester_name = body.name.strip()
    requester_email = body.email.strip()
    subject = body.subject.strip()
    message = body.message.strip()
    if not requester_name or not requester_email or not subject or not message:
        raise HTTPException(status_code=400, detail="All fields are required.")

    verify_business_access(user_id, body.business_id)

    business_row = (
        supabase_admin.table("businesses")
        .select("name")
        .eq("id", body.business_id)
        .limit(1)
        .execute()
    )
    business_name = business_row.data[0]["name"] if business_row.data else "AI Employees Business"

    access_token = await email_service.get_valid_access_token(
        supabase_admin,
        body.business_id,
        settings.google_client_id,
        settings.google_client_secret,
        body.location_id,
    )
    if not access_token:
        raise HTTPException(
            status_code=409,
            detail="Gmail is not connected for this business. Connect Gmail before sending Wish List requests.",
        )

    token_row = email_service.get_token_row(supabase_admin, body.business_id, body.location_id)
    if not token_row or not token_row.get("google_email"):
        raise HTTPException(
            status_code=409,
            detail="Connected Gmail account is missing the sender email. Reconnect Gmail and try again.",
        )

    if not await email_service.has_gmail_send_scope(access_token):
        raise HTTPException(
            status_code=409,
            detail=(
                "This Gmail connection is missing mail-sending permission. "
                "Disconnect Gmail, reconnect it, and approve send access before retrying."
            ),
        )

    plain_body = (
        f"Wish List submission from {business_name}\n\n"
        f"Submitted by: {requester_name}\n"
        f"Email: {requester_email}\n\n"
        f"Message:\n{message}\n"
    )
    html_body = _build_wishlist_email_html(
        business_name=business_name,
        requester_name=requester_name,
        requester_email=requester_email,
        subject=subject,
        message=message,
    )

    sent = await email_service.send_email(
        access_token=access_token,
        sender=f"{business_name} <{token_row['google_email']}>",
        to=WISHLIST_RECIPIENT,
        subject=f"[Wish List] {subject}",
        html_body=html_body,
        plain_body=plain_body,
    )
    if not sent:
        logger.error("Wish List email send failed for business %s", body.business_id)
        raise HTTPException(status_code=502, detail="Failed to send Wish List email.")

    return {"sent": True}
