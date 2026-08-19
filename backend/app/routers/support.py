"""
Support and feature request routes.
"""

import html
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import get_current_user, get_user_id, verify_business_access
from app.core.supabase import supabase_admin
from app.services.resend_email_service import send_via_resend

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["support"])

WISHLIST_RECIPIENT = "sam@aiemployeesinc.com"
SUPPORT_RECIPIENT = "support@aiemployeesinc.com"
WISHLIST_SENDER_ADDRESS = "wishlist-requests@aiemployeesinc.com"
SUPPORT_SENDER_ADDRESS = "support-requests@aiemployeesinc.com"
ANONYMOUS_REQUESTER_EMAIL = "anonymous@aiemployeesinc.com"


class SupportSubmissionRequest(BaseModel):
    business_id: str
    location_id: str | None = None
    name: str
    subject: str
    message: str


class WishlistSubmissionRequest(BaseModel):
    business_id: str
    location_id: str | None = None
    name: str
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
    current_user: dict = Depends(get_current_user),
):
    requester_name = body.name.strip()
    subject = body.subject.strip()
    message = body.message.strip()
    if not requester_name or not subject or not message:
        raise HTTPException(status_code=400, detail="All fields are required.")

    login_email = current_user.get("email")
    requester_email = login_email or ANONYMOUS_REQUESTER_EMAIL

    verify_business_access(user_id, body.business_id)

    business_row = (
        supabase_admin.table("businesses")
        .select("name")
        .eq("id", body.business_id)
        .limit(1)
        .execute()
    )
    business_name = business_row.data[0]["name"] if business_row.data else "AI Employees Business"

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

    sent = await send_via_resend(
        from_email=f"{business_name} <{WISHLIST_SENDER_ADDRESS}>",
        to=WISHLIST_RECIPIENT,
        subject=f"[Wish List] {subject}",
        html_body=html_body,
        plain_body=plain_body,
        reply_to=login_email,
    )
    if not sent:
        logger.error("Wish List email send failed for business %s", body.business_id)
        raise HTTPException(status_code=502, detail="Failed to send Wish List email.")

    return {"sent": True}


def _build_support_email_html(
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
      <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#a1a1aa;">Support Request</div>
      <h1 style="margin:8px 0 0;font-size:22px;font-weight:700;">{escaped_subject}</h1>
    </div>
    <div style="padding:28px;">
      <p style="margin:0 0 20px;font-size:14px;color:#52525b;">
        A new support request was submitted from <strong>{escaped_business_name}</strong>.
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


@router.post("/submit")
async def submit_support(
    body: SupportSubmissionRequest,
    user_id: str = Depends(get_user_id),
    current_user: dict = Depends(get_current_user),
):
    requester_name = body.name.strip()
    subject = body.subject.strip()
    message = body.message.strip()
    if not requester_name or not subject or not message:
        raise HTTPException(status_code=400, detail="All fields are required.")

    login_email = current_user.get("email")
    requester_email = login_email or ANONYMOUS_REQUESTER_EMAIL

    verify_business_access(user_id, body.business_id)

    business_row = (
        supabase_admin.table("businesses")
        .select("name")
        .eq("id", body.business_id)
        .limit(1)
        .execute()
    )
    business_name = business_row.data[0]["name"] if business_row.data else "AI Employees Business"

    plain_body = (
        f"Support request from {business_name}\n\n"
        f"Submitted by: {requester_name}\n"
        f"Email: {requester_email}\n\n"
        f"Message:\n{message}\n"
    )
    html_body = _build_support_email_html(
        business_name=business_name,
        requester_name=requester_name,
        requester_email=requester_email,
        subject=subject,
        message=message,
    )

    sent = await send_via_resend(
        from_email=f"{business_name} <{SUPPORT_SENDER_ADDRESS}>",
        to=SUPPORT_RECIPIENT,
        subject=f"[Support] {subject}",
        html_body=html_body,
        plain_body=plain_body,
        reply_to=login_email,
    )
    if not sent:
        logger.error("Support email send failed for business %s", body.business_id)
        raise HTTPException(status_code=502, detail="Failed to send support request.")

    return {"sent": True}
