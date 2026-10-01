"""
Subscription access gate — two independent checks:
  1. Payment status (get_access_status / require_active_subscription): is this
     business currently paid up at all? Blocks "new work" dashboard/back-office
     actions (Marketing post creation, Sales research runs, HR screening/interviews)
     once past_due beyond the grace period, or canceled/never-subscribed.
  2. Plan-tier feature gating (require_plan_feature): does THIS business's
     CURRENT plan include this specific feature at all, regardless of payment
     status? E.g. Sales/HR require Growth or higher; a paid-up Starter business
     is still blocked from them. Matches the Billing page's comparison table exactly.

Deliberately NEVER used to gate phone calls or any customer-service/voice-agent
path — a business falling behind on payment (or being on a lower tier) must
never strand a real caller.
See docs/features/billing-pricing-page.md for the full design rationale.
"""
from datetime import datetime, timezone
from typing import Literal, Optional, Tuple

from fastapi import HTTPException

from app.core.config import settings
from app.core.supabase import supabase_admin

AccessStatus = Literal["ok", "grace", "blocked"]

_BLOCKED_DETAIL = "Your subscription needs attention before you can do this. Update your billing to continue."

# Tier rank per plan — mirrors the Billing page's comparison table exactly.
# Trial rides on the Starter price (see billing.py::create_checkout_session),
# so it naturally resolves to the same rank 0 as Starter — matching the
# comparison table, where Free Trial and Starter both get "Customer Service + Marketing" only.
_GROWTH_TIER = 1
_ENTERPRISE_TIER = 2

# Minimum tier required per feature. Anything not listed defaults to 0 (every paid plan).
FEATURE_MIN_TIER = {
    "marketing": 0,
    "sales": _GROWTH_TIER,
    "hr": _GROWTH_TIER,
    "executive_agent": _ENTERPRISE_TIER,
}

_TIER_NAME = {0: "any plan", _GROWTH_TIER: "the Growth or Enterprise plan", _ENTERPRISE_TIER: "the Enterprise plan"}


def _resolve_plan_tier(stripe_price_id: Optional[str]) -> int:
    if stripe_price_id and stripe_price_id == settings.stripe_enterprise_price_id:
        return _ENTERPRISE_TIER
    if stripe_price_id and stripe_price_id == settings.stripe_growth_price_id:
        return _GROWTH_TIER
    return 0  # Starter, trial (rides on the Starter price), or unrecognized


def is_platform_admin_business(business_id: str) -> bool:
    """True if any super_admin on this business also holds platform-super-admin
    status (a super_admin role on the fixed "AI Employees Inc. Platform"
    business, type="platform") — i.e. this is a platform staff member's own
    testing/demo business (Sam/Charles/Rahul today, automatically covers
    anyone else granted platform-super-admin later). These get free, permanent
    Enterprise access — see docs/features/billing-pricing-page.md. Reused by
    billing.py::get_subscription so the Billing page UI reflects this
    consistently, not just the backend gate."""
    owners = (
        supabase_admin.table("user_roles")
        .select("user_id")
        .eq("business_id", business_id)
        .eq("role", "super_admin")
        .execute()
    )
    if not owners.data:
        return False
    owner_ids = [o["user_id"] for o in owners.data]

    platform_biz = supabase_admin.table("businesses").select("id").eq("type", "platform").limit(1).execute()
    if not platform_biz.data:
        return False
    platform_business_id = platform_biz.data[0]["id"]

    admin_check = (
        supabase_admin.table("user_roles")
        .select("user_id")
        .eq("business_id", platform_business_id)
        .eq("role", "super_admin")
        .in_("user_id", owner_ids)
        .limit(1)
        .execute()
    )
    return bool(admin_check.data)


def get_access_status(business_id: str) -> Tuple[AccessStatus, Optional[int]]:
    """Returns (status, grace_days_remaining). grace_days_remaining is only
    meaningful when status == "grace" (None otherwise)."""
    if is_platform_admin_business(business_id):
        return "ok", None

    r = (
        supabase_admin.table("businesses")
        .select("stripe_subscription_status,subscription_past_due_since")
        .eq("id", business_id)
        .limit(1)
        .execute()
    )
    if not r.data:
        return "blocked", None

    status = r.data[0].get("stripe_subscription_status")
    if status in ("active", "trialing"):
        return "ok", None

    if status == "past_due":
        since_raw = r.data[0].get("subscription_past_due_since")
        if not since_raw:
            # Webhook hasn't landed yet, or just flipped this instant — don't
            # punish the gap between Stripe's event and our own DB catching up.
            return "ok", None
        since = datetime.fromisoformat(since_raw)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        elapsed_days = (datetime.now(timezone.utc) - since).days
        remaining = settings.subscription_grace_period_days - elapsed_days
        if remaining > 0:
            return "grace", remaining
        return "blocked", 0

    # canceled, or no subscription at all (status is None)
    return "blocked", None


def require_active_subscription(business_id: str) -> None:
    """Call at the top of a gated endpoint (after any auth/business-access
    check), before doing the expensive/billable work. Raises 402 if blocked;
    does nothing during "ok" or "grace"."""
    status, _ = get_access_status(business_id)
    if status == "blocked":
        raise HTTPException(status_code=402, detail=_BLOCKED_DETAIL)


def require_plan_feature(business_id: str, feature: str) -> None:
    """Combined gate: payment status first (require_active_subscription), then
    whether the business's CURRENT plan tier actually includes this feature —
    e.g. a paid-up Starter business is still blocked from Sales/HR, which
    need Growth or higher. Call this instead of require_active_subscription
    on any endpoint that's plan-tier-specific, not just payment-specific."""
    require_active_subscription(business_id)

    min_tier = FEATURE_MIN_TIER.get(feature, 0)
    if min_tier == 0:
        return
    if is_platform_admin_business(business_id):
        return  # Platform staff's own business — always treated as Enterprise tier.

    r = (
        supabase_admin.table("businesses")
        .select("stripe_price_id")
        .eq("id", business_id)
        .limit(1)
        .execute()
    )
    price_id = r.data[0].get("stripe_price_id") if r.data else None
    tier = _resolve_plan_tier(price_id)
    if tier < min_tier:
        raise HTTPException(
            status_code=402,
            detail=f"This feature requires {_TIER_NAME[min_tier]}. Upgrade your plan to continue.",
        )
