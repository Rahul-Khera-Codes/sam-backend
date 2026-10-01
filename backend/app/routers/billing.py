"""
Stripe billing endpoints.
- GET  /billing/subscription             → current plan + minute usage
- POST /billing/create-checkout-session  → Stripe Checkout redirect URL
- POST /billing/customer-portal          → Stripe Customer Portal redirect URL
- POST /billing/webhook                  → Stripe webhook receiver
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import JSONResponse

from app.core.auth import get_user_id, verify_business_access
from app.core.billing_gate import get_access_status, is_platform_admin_business
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.billing import (
    SubscriptionResponse,
    CreateCheckoutSessionRequest,
    CreateCheckoutSessionResponse,
    CustomerPortalResponse,
    ExecutiveAgentAddonResponse,
    ChangePlanRequest,
    ChangePlanResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

# Minute limits are read from Settings (not a literal here) so they're tunable
# via .env without a code change — see docs/features/billing-pricing-page.md.
# Enterprise is a fixed $999/mo self-serve plan with plan_enterprise_minute_limit=None
# (unlimited) by default — same mechanics as Starter/Growth otherwise.
PLAN_KEY_MAP = {
    "starter":    ("stripe_starter_price_id",    "Starter",    "plan_starter_minute_limit"),
    "growth":     ("stripe_growth_price_id",     "Growth",     "plan_growth_minute_limit"),
    "enterprise": ("stripe_enterprise_price_id", "Enterprise", "plan_enterprise_minute_limit"),
}


def _plan_by_price_id(price_id: str) -> dict:
    for plan_key, (attr, name, limit_attr) in PLAN_KEY_MAP.items():
        if getattr(settings, attr, "") == price_id:
            return {"name": name, "minute_limit": getattr(settings, limit_attr, 0)}
    return {}


def _init_stripe() -> None:
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    stripe.api_key = settings.stripe_secret_key


def _get_business(business_id: str) -> dict:
    r = supabase_admin.table("businesses").select(
        "id,name,stripe_customer_id,stripe_subscription_id,stripe_price_id,"
        "stripe_subscription_status,subscription_call_limit,"
        "subscription_period_start,subscription_period_end,stripe_exec_agent_item_id"
    ).eq("id", business_id).limit(1).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Business not found")
    return r.data[0]


def _count_minutes_in_period(
    business_id: str,
    period_start: Optional[str],
    period_end: Optional[str],
) -> int:
    if not period_start or not period_end:
        return 0
    r = (
        supabase_admin.table("calls")
        .select("duration_seconds")
        .eq("business_id", business_id)
        .gte("created_at", period_start)
        .lte("created_at", period_end)
        .range(0, 9999)
        .execute()
    )
    total_seconds = sum((row.get("duration_seconds") or 0) for row in (r.data or []))
    return total_seconds // 60


# ── GET /billing/subscription ─────────────────────────────────────────────────

@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    biz = _get_business(business_id)

    if is_platform_admin_business(business_id):
        # Platform staff's own testing/demo business — always free Enterprise,
        # regardless of whatever (if anything) is actually in Stripe for it.
        # Shown as Enterprise/active/unlimited so the Billing page UI matches
        # what billing_gate actually grants, rather than looking "unsubscribed"
        # while every feature silently works.
        minutes_used = _count_minutes_in_period(
            business_id, biz.get("subscription_period_start"), biz.get("subscription_period_end")
        )
        return SubscriptionResponse(
            has_subscription=True,
            status="active",
            plan_name="Enterprise",
            price_id=biz.get("stripe_price_id"),
            minute_limit=None,
            minutes_used=minutes_used,
            period_start=biz.get("subscription_period_start"),
            period_end=biz.get("subscription_period_end"),
            executive_agent_addon_enabled=bool(biz.get("stripe_exec_agent_item_id")),
            executive_agent_addon_required=settings.exec_agent_addon_enforced,
            access_status="ok",
            grace_days_remaining=None,
            is_trial=False,
            is_platform_admin=True,
        )

    if not biz.get("stripe_subscription_id"):
        return SubscriptionResponse(has_subscription=False, access_status="blocked")

    access_status, grace_days_remaining = get_access_status(business_id)
    status = biz.get("stripe_subscription_status")
    plan_info = _plan_by_price_id(biz.get("stripe_price_id") or "")
    minutes_used = _count_minutes_in_period(
        business_id,
        biz.get("subscription_period_start"),
        biz.get("subscription_period_end"),
    )

    # Trial rides on the real Starter price (see create_checkout_session), so
    # _plan_by_price_id alone would report "Starter" + Starter's full minute
    # limit during a trial. Override at read time — no extra write path, no
    # stale-state window once Stripe flips trialing -> active.
    is_trial = status == "trialing"
    plan_name = "Free Trial" if is_trial else plan_info.get("name")
    minute_limit = (
        settings.plan_trial_minute_limit if is_trial
        else (biz.get("subscription_call_limit") or plan_info.get("minute_limit"))
    )

    return SubscriptionResponse(
        has_subscription=True,
        status=status,
        plan_name=plan_name,
        price_id=biz.get("stripe_price_id"),
        minute_limit=minute_limit,
        minutes_used=minutes_used,
        period_start=biz.get("subscription_period_start"),
        period_end=biz.get("subscription_period_end"),
        executive_agent_addon_enabled=bool(biz.get("stripe_exec_agent_item_id")),
        # Lets the frontend gate stay in sync with the backend's actual
        # enforcement switch instead of guessing (ADR 0001) — both driven by
        # the same settings.exec_agent_addon_enforced flag.
        executive_agent_addon_required=settings.exec_agent_addon_enforced,
        access_status=access_status,
        grace_days_remaining=grace_days_remaining,
        is_trial=is_trial,
        # For a trialing subscription, current_period_end IS the trial end
        # (the first "period" is the trial) — no separate Stripe field needed.
        trial_end=biz.get("subscription_period_end") if is_trial else None,
    )


# ── POST /billing/create-checkout-session ────────────────────────────────────

@router.post("/create-checkout-session", response_model=CreateCheckoutSessionResponse)
async def create_checkout_session(
    body: CreateCheckoutSessionRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)

    plan_key = body.plan.lower()
    # Trial rides on the real Starter price with trial_period_days attached —
    # not a separate $0 product — so it auto-converts to paid Starter when the
    # trial ends, with no extra webhook/sync logic needed for that transition.
    is_trial = plan_key == "trial"
    lookup_key = "starter" if is_trial else plan_key
    if lookup_key not in PLAN_KEY_MAP:
        raise HTTPException(status_code=400, detail="Invalid plan. Must be starter, growth, enterprise, or trial.")

    price_attr, plan_name, _minute_limit_attr = PLAN_KEY_MAP[lookup_key]
    price_id = getattr(settings, price_attr, "")
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Stripe price ID for {plan_name} is not configured")

    _init_stripe()
    biz = _get_business(body.business_id)

    if is_trial and biz.get("stripe_customer_id"):
        # A Stripe customer only ever gets linked once a checkout actually
        # completes (see _handle_checkout_completed) — so this blocks repeat
        # trials for a business that already subscribed (and possibly
        # canceled) before, not first-time signups.
        raise HTTPException(status_code=400, detail="Free trial already used for this business.")

    customer_id = biz.get("stripe_customer_id") or None

    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=settings.billing_success_url,
        cancel_url=settings.billing_cancel_url,
        metadata={"business_id": body.business_id},
        **({"customer": customer_id} if customer_id else {}),
        **({"subscription_data": {"trial_period_days": settings.trial_period_days}} if is_trial else {}),
    )

    return CreateCheckoutSessionResponse(checkout_url=session.url)


# ── POST /billing/customer-portal ────────────────────────────────────────────

@router.post("/customer-portal", response_model=CustomerPortalResponse)
async def customer_portal(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    biz = _get_business(business_id)

    customer_id = biz.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(
            status_code=400,
            detail="No Stripe customer found. Subscribe to a plan first.",
        )

    _init_stripe()
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=settings.billing_cancel_url,
    )
    return CustomerPortalResponse(portal_url=session.url)


# ── POST /billing/change-plan ────────────────────────────────────────────────
# Existing subscriber switching between Starter/Growth/Enterprise via
# Stripe::Subscription.modify with proration. Deliberately does NOT write to
# `businesses` itself: Subscription.modify
# fires customer.subscription.updated, and the existing webhook handler
# (_handle_subscription_upsert below) already re-syncs the row from that event —
# duplicating that sync here would be two write paths for the same data.
# See docs/features/billing-pricing-page.md for the webhook-ordering caveat this
# implies for callers (a GET /subscription right after this may briefly be stale).

@router.post("/change-plan", response_model=ChangePlanResponse)
async def change_plan(
    body: ChangePlanRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    biz = _get_business(body.business_id)

    sub_id = biz.get("stripe_subscription_id")
    if not sub_id or biz.get("stripe_subscription_status") in (None, "canceled"):
        raise HTTPException(status_code=400, detail="No active subscription to change. Subscribe to a plan first.")

    target_key = body.plan.lower()
    if target_key not in PLAN_KEY_MAP:
        raise HTTPException(status_code=400, detail="Invalid target plan. Must be starter, growth, or enterprise.")

    price_attr, plan_name, _minute_limit_attr = PLAN_KEY_MAP[target_key]
    new_price_id = getattr(settings, price_attr, "")
    if not new_price_id:
        raise HTTPException(status_code=503, detail=f"Stripe price ID for {plan_name} is not configured")

    current_price_id = biz.get("stripe_price_id")
    if current_price_id == new_price_id:
        raise HTTPException(status_code=400, detail=f"Already on the {plan_name} plan.")

    _init_stripe()
    try:
        sub = stripe.Subscription.retrieve(sub_id)
    except stripe.InvalidRequestError:
        raise HTTPException(status_code=404, detail="Stripe subscription not found")

    items_data = sub["items"]["data"]
    if not items_data:
        raise HTTPException(status_code=500, detail="Subscription has no base plan item to modify")

    # Match the base-plan item by its current price (robust against item
    # ordering); fall back to the first item, which is the only ordering
    # that's ever existed so far (base item created at checkout time, the
    # exec-agent add-on item always created after, as a second item).
    base_item = next(
        (it for it in items_data if it.get("price", {}).get("id") == current_price_id),
        items_data[0],
    )

    try:
        stripe.Subscription.modify(
            sub_id,
            items=[{"id": base_item["id"], "price": new_price_id}],
            proration_behavior="create_prorations",
        )
    except stripe.InvalidRequestError as e:
        raise HTTPException(status_code=400, detail=f"Stripe rejected the plan change: {e.user_message or str(e)}")

    return ChangePlanResponse(status="ok", price_id=new_price_id)


# ── Executive Agent add-on ───────────────────────────────────────────────────
# Per docs/adr/0001-billing-addon-access-gating.md — a second Stripe
# subscription item on the business's existing subscription, not a separate
# subscription. We store the subscription ITEM id (not the price id) so it
# can be removed individually without touching the base plan.

@router.post("/addons/executive-agent", response_model=ExecutiveAgentAddonResponse)
async def enable_executive_agent_addon(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    biz = _get_business(business_id)

    sub_id = biz.get("stripe_subscription_id")
    if not sub_id:
        raise HTTPException(status_code=400, detail="Subscribe to a plan first.")
    if biz.get("stripe_exec_agent_item_id"):
        return ExecutiveAgentAddonResponse(executive_agent_addon_enabled=True)

    price_id = settings.stripe_exec_agent_price_id
    if not price_id:
        raise HTTPException(status_code=503, detail="Executive Agent add-on price is not configured yet")

    _init_stripe()
    item = stripe.SubscriptionItem.create(subscription=sub_id, price=price_id)

    supabase_admin.table("businesses").update({
        "stripe_exec_agent_item_id": item.id
    }).eq("id", business_id).execute()

    return ExecutiveAgentAddonResponse(executive_agent_addon_enabled=True)


@router.delete("/addons/executive-agent", response_model=ExecutiveAgentAddonResponse)
async def disable_executive_agent_addon(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    biz = _get_business(business_id)

    item_id = biz.get("stripe_exec_agent_item_id")
    if item_id:
        _init_stripe()
        try:
            stripe.SubscriptionItem.delete(item_id)
        except stripe.InvalidRequestError:
            # Already removed on Stripe's side (e.g. base subscription was
            # canceled, which cancels every item on it) — clear our record anyway.
            pass

    supabase_admin.table("businesses").update({
        "stripe_exec_agent_item_id": None
    }).eq("id", business_id).execute()

    return ExecutiveAgentAddonResponse(executive_agent_addon_enabled=False)


# ── POST /billing/webhook ─────────────────────────────────────────────────────

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
):
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    except Exception as e:
        logger.error("Webhook construction error: %s", e)
        raise HTTPException(status_code=400, detail="Webhook error")

    event_type = event["type"]
    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(event["data"]["object"])

    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        _handle_subscription_upsert(event["data"]["object"])

    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(event["data"]["object"])

    elif event_type == "invoice.payment_succeeded":
        _handle_invoice_paid(event["data"]["object"])

    elif event_type == "invoice.payment_failed":
        _handle_invoice_failed(event["data"]["object"])

    return JSONResponse(content={"received": True})


# ── Webhook helpers ───────────────────────────────────────────────────────────

def _attr(obj, key, default=None):
    """Read a field from a Stripe SDK object (attribute access) or plain dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _handle_checkout_completed(session) -> None:
    metadata = _attr(session, "metadata") or {}
    business_id = metadata.get("business_id") if isinstance(metadata, dict) else _attr(metadata, "business_id")
    customer_id = _attr(session, "customer")
    if not business_id or not customer_id:
        return
    supabase_admin.table("businesses").update({
        "stripe_customer_id": customer_id
    }).eq("id", business_id).execute()
    logger.info("Linked Stripe customer %s to business %s", customer_id, business_id)


def _ts(unix: Optional[int]) -> Optional[str]:
    if unix is None:
        return None
    return datetime.fromtimestamp(unix, tz=timezone.utc).isoformat()


def _handle_subscription_upsert(sub) -> None:
    customer_id = _attr(sub, "customer")
    if not customer_id:
        return

    price_id = None
    period_start = None
    period_end = None
    items_obj = _attr(sub, "items")
    items_data = _attr(items_obj, "data") or [] if items_obj else []
    if items_data:
        first_item = items_data[0]
        price_obj = _attr(first_item, "price")
        price_id = _attr(price_obj, "id") if price_obj else None
        # Stripe API 2026+ moved period dates from subscription root to items
        period_start = _attr(first_item, "current_period_start") or _attr(sub, "current_period_start")
        period_end = _attr(first_item, "current_period_end") or _attr(sub, "current_period_end")

    plan_info = _plan_by_price_id(price_id or "")

    update: dict = {
        "stripe_subscription_id": _attr(sub, "id"),
        "stripe_price_id": price_id,
        "stripe_subscription_status": _attr(sub, "status"),
        "subscription_period_start": _ts(period_start),
        "subscription_period_end": _ts(period_end),
    }
    if plan_info.get("minute_limit"):
        update["subscription_call_limit"] = plan_info["minute_limit"]

    r = (
        supabase_admin.table("businesses")
        .select("id,subscription_past_due_since")
        .eq("stripe_customer_id", customer_id)
        .limit(1)
        .execute()
    )
    if not r.data:
        logger.warning("No business found for Stripe customer %s", customer_id)
        return

    business_id = r.data[0]["id"]
    new_status = _attr(sub, "status")
    if new_status == "past_due":
        # Stamp only the first time we see it go past_due — a webhook retry
        # or an unrelated update while still past_due must not reset the
        # grace-period clock (see app/core/billing_gate.py).
        if not r.data[0].get("subscription_past_due_since"):
            update["subscription_past_due_since"] = datetime.now(timezone.utc).isoformat()
    else:
        update["subscription_past_due_since"] = None

    supabase_admin.table("businesses").update(update).eq("id", business_id).execute()
    logger.info("Subscription upserted for business %s: %s", business_id, _attr(sub, "status"))


def _handle_subscription_deleted(sub) -> None:
    customer_id = _attr(sub, "customer")
    if not customer_id:
        return
    r = supabase_admin.table("businesses").select("id").eq("stripe_customer_id", customer_id).limit(1).execute()
    if not r.data:
        return
    business_id = r.data[0]["id"]
    supabase_admin.table("businesses").update({
        "stripe_subscription_id": None,
        "stripe_price_id": None,
        "stripe_subscription_status": "canceled",
        "subscription_call_limit": None,
        "subscription_period_start": None,
        "subscription_period_end": None,
        "subscription_past_due_since": None,
        # Canceling the base subscription cancels every item on it, including
        # the exec-agent add-on — clear our record so it doesn't go stale.
        "stripe_exec_agent_item_id": None,
    }).eq("id", business_id).execute()
    logger.info("Subscription deleted for business %s", business_id)


def _handle_invoice_paid(invoice) -> None:
    sub_id = _attr(invoice, "subscription")
    if not sub_id:
        return
    try:
        _init_stripe()
        sub = stripe.Subscription.retrieve(sub_id)
        _handle_subscription_upsert(sub)
    except Exception as e:
        logger.error("Failed to refresh subscription on invoice.payment_succeeded: %s", e)


def _handle_invoice_failed(invoice) -> None:
    customer_id = _attr(invoice, "customer")
    if not customer_id:
        return
    r = supabase_admin.table("businesses").select("id").eq("stripe_customer_id", customer_id).limit(1).execute()
    if not r.data:
        return
    business_id = r.data[0]["id"]
    supabase_admin.table("businesses").update({
        "stripe_subscription_status": "past_due"
    }).eq("id", business_id).execute()
    logger.warning("Invoice payment failed for business %s", business_id)
