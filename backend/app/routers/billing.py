"""
Stripe billing endpoints.
- GET  /billing/subscription             → current plan + call usage
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
from app.core.config import settings
from app.core.supabase import supabase_admin
from app.schemas.billing import (
    SubscriptionResponse,
    CreateCheckoutSessionRequest,
    CreateCheckoutSessionResponse,
    CustomerPortalResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_KEY_MAP = {
    "starter": ("stripe_starter_price_id", "Starter", 150),
    "growth":  ("stripe_growth_price_id",  "Growth",  400),
    "pro":     ("stripe_pro_price_id",     "Pro",     800),
}


def _plan_by_price_id(price_id: str) -> dict:
    for plan_key, (attr, name, limit) in PLAN_KEY_MAP.items():
        if getattr(settings, attr, "") == price_id:
            return {"name": name, "call_limit": limit}
    return {}


def _init_stripe() -> None:
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    stripe.api_key = settings.stripe_secret_key


def _get_business(business_id: str) -> dict:
    r = supabase_admin.table("businesses").select(
        "id,name,stripe_customer_id,stripe_subscription_id,stripe_price_id,"
        "stripe_subscription_status,subscription_call_limit,"
        "subscription_period_start,subscription_period_end"
    ).eq("id", business_id).limit(1).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Business not found")
    return r.data[0]


def _count_calls_in_period(
    business_id: str,
    period_start: Optional[str],
    period_end: Optional[str],
) -> int:
    if not period_start or not period_end:
        return 0
    r = (
        supabase_admin.table("calls")
        .select("id", count="exact")
        .eq("business_id", business_id)
        .gte("created_at", period_start)
        .lte("created_at", period_end)
        .execute()
    )
    return r.count or 0


# ── GET /billing/subscription ─────────────────────────────────────────────────

@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    biz = _get_business(business_id)

    if not biz.get("stripe_subscription_id"):
        return SubscriptionResponse(has_subscription=False)

    plan_info = _plan_by_price_id(biz.get("stripe_price_id") or "")
    calls_used = _count_calls_in_period(
        business_id,
        biz.get("subscription_period_start"),
        biz.get("subscription_period_end"),
    )

    return SubscriptionResponse(
        has_subscription=True,
        status=biz.get("stripe_subscription_status"),
        plan_name=plan_info.get("name"),
        price_id=biz.get("stripe_price_id"),
        call_limit=biz.get("subscription_call_limit") or plan_info.get("call_limit"),
        calls_used=calls_used,
        period_start=biz.get("subscription_period_start"),
        period_end=biz.get("subscription_period_end"),
    )


# ── POST /billing/create-checkout-session ────────────────────────────────────

@router.post("/create-checkout-session", response_model=CreateCheckoutSessionResponse)
async def create_checkout_session(
    body: CreateCheckoutSessionRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)

    plan_key = body.plan.lower()
    if plan_key not in PLAN_KEY_MAP:
        raise HTTPException(status_code=400, detail="Invalid plan. Must be starter, growth, or pro.")

    price_attr, plan_name, call_limit = PLAN_KEY_MAP[plan_key]
    price_id = getattr(settings, price_attr, "")
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Stripe price ID for {plan_name} is not configured")

    _init_stripe()
    biz = _get_business(body.business_id)
    customer_id = biz.get("stripe_customer_id") or None

    session = stripe.checkout.Session.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=settings.billing_success_url,
        cancel_url=settings.billing_cancel_url,
        metadata={"business_id": body.business_id},
        **({"customer": customer_id} if customer_id else {}),
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
    if plan_info.get("call_limit"):
        update["subscription_call_limit"] = plan_info["call_limit"]

    r = supabase_admin.table("businesses").select("id").eq("stripe_customer_id", customer_id).limit(1).execute()
    if not r.data:
        logger.warning("No business found for Stripe customer %s", customer_id)
        return

    business_id = r.data[0]["id"]
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
