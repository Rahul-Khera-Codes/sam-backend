"""
Pre-signup email validation. Public endpoint — called before an account exists,
so no auth dependency here.
"""

import logging

from disposable_email_domains import blocklist
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


class CheckSignupEmailRequest(BaseModel):
    email: str


def _normalize_gmail_local_part(local_part: str) -> str:
    return local_part.replace(".", "").lower()


@router.post("/check-signup-email")
async def check_signup_email(body: CheckSignupEmailRequest):
    email = body.email.strip().lower()
    if "@" not in email:
        return {"blocked": False}

    local_part, _, domain = email.rpartition("@")

    if "+" in local_part:
        return {
            "blocked": True,
            "reason": "Email aliases (using a '+' in your address) aren't allowed. Please sign up with your primary email address.",
        }

    if domain in blocklist:
        return {
            "blocked": True,
            "reason": "This email provider isn't allowed for signup. Please use a permanent email address.",
        }

    if domain in GMAIL_DOMAINS:
        normalized_target = _normalize_gmail_local_part(local_part)
        existing = (
            supabase_admin.table("profiles")
            .select("email")
            .or_(",".join(f"email.ilike.%@{d}" for d in GMAIL_DOMAINS))
            .execute()
        )
        for row in existing.data or []:
            existing_email = (row.get("email") or "").strip().lower()
            existing_local, _, existing_domain = existing_email.rpartition("@")
            if existing_domain not in GMAIL_DOMAINS:
                continue
            normalized_existing = _normalize_gmail_local_part(existing_local)
            if normalized_existing and normalized_target.startswith(normalized_existing):
                return {
                    "blocked": True,
                    "reason": "An account already exists for this email address. Please log in instead.",
                }

    return {"blocked": False}
