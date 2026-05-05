# Stripe Billing Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static Billing.tsx placeholder with a real Stripe subscription system — Checkout for sign-up, Customer Portal for self-serve management, and webhooks to keep the DB in sync.

**Architecture:** Tiered plans (Starter $99/150 calls, Growth $199/400 calls, Pro $349/800 calls) with monthly flat-rate subscriptions via Stripe. The backend exposes three billing endpoints (subscription info, create-checkout-session, customer-portal) plus a webhook receiver. The frontend fetches live data and redirects to Stripe-hosted pages for payment/management — no raw card info touches our UI.

**Tech Stack:** stripe Python SDK (backend), Stripe Checkout + Customer Portal + Webhooks, FastAPI, Supabase (PostgreSQL), React/TypeScript frontend, existing `fetchWithAuth` pattern in `voiceAgentApi.ts`.

---

## Prerequisites (manual steps before running any task)

These must be done in the Stripe dashboard BEFORE writing code:

1. Create a Stripe account (or use the client's account — they have added you to their org).
2. Create 3 products in Stripe → Products tab:
   - **Starter** — $99/month recurring → note the **price ID** (e.g. `price_xxxx`)
   - **Growth** — $199/month recurring → note the **price ID**
   - **Pro** — $349/month recurring → note the **price ID**
3. Enable Stripe Customer Portal: Stripe Dashboard → Settings → Customer Portal → Save.
4. Create a webhook endpoint pointing to `https://your-backend.com/billing/webhook` with these events:
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
   - `invoice.payment_failed`
   → note the **webhook signing secret** (`whsec_xxxx`)
5. Copy your Stripe **secret key** (`sk_live_xxxx` or `sk_test_xxxx` for testing).
6. Add to `sam-backend/.env`:
   ```
   STRIPE_SECRET_KEY=sk_test_xxxx
   STRIPE_WEBHOOK_SECRET=whsec_xxxx
   STRIPE_STARTER_PRICE_ID=price_xxxx
   STRIPE_GROWTH_PRICE_ID=price_xxxx
   STRIPE_PRO_PRICE_ID=price_xxxx
   BILLING_SUCCESS_URL=https://your-frontend.com/dashboard/billing?success=true
   BILLING_CANCEL_URL=https://your-frontend.com/dashboard/billing?canceled=true
   ```

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `ai-employees-app/supabase/migrations/20260430000001_businesses_stripe.sql` | CREATE | Add Stripe fields to businesses table |
| `ai-employees-app/src/integrations/supabase/types.ts` | MODIFY | Add Stripe fields to businesses Row/Insert/Update types |
| `sam-backend/backend/requirements.txt` | MODIFY | Add `stripe>=11.0.0` |
| `sam-backend/backend/app/core/config.py` | MODIFY | Add Stripe env vars |
| `sam-backend/backend/app/schemas/billing.py` | CREATE | Pydantic response/request models for billing endpoints |
| `sam-backend/backend/app/routers/billing.py` | CREATE | `/billing/subscription`, `/billing/create-checkout-session`, `/billing/customer-portal`, `/billing/webhook` |
| `sam-backend/backend/app/main.py` | MODIFY | Register billing router |
| `ai-employees-app/src/lib/voiceAgentApi.ts` | MODIFY | Add `getBillingSubscription`, `createCheckoutSession`, `createCustomerPortalSession` |
| `ai-employees-app/src/pages/dashboard/Billing.tsx` | REWRITE | Live Stripe data — plan selection or subscription status + usage |

---

## Task 1: Supabase Migration + TypeScript Types

**Repos:** `ai-employees-app`

**Files:**
- Create: `ai-employees-app/supabase/migrations/20260430000001_businesses_stripe.sql`
- Modify: `ai-employees-app/src/integrations/supabase/types.ts`

- [ ] **Step 1: Write the migration SQL**

Create `ai-employees-app/supabase/migrations/20260430000001_businesses_stripe.sql`:

```sql
-- Add Stripe billing fields to businesses.
-- stripe_subscription_status: active | trialing | past_due | canceled | unpaid | null (no subscription)
-- subscription_call_limit: monthly call cap from the plan (150 / 400 / 800)
-- subscription_period_start / _end: current billing period window from Stripe, updated by webhook

ALTER TABLE public.businesses
  ADD COLUMN IF NOT EXISTS stripe_customer_id         TEXT,
  ADD COLUMN IF NOT EXISTS stripe_subscription_id     TEXT,
  ADD COLUMN IF NOT EXISTS stripe_price_id            TEXT,
  ADD COLUMN IF NOT EXISTS stripe_subscription_status TEXT,
  ADD COLUMN IF NOT EXISTS subscription_call_limit    INTEGER,
  ADD COLUMN IF NOT EXISTS subscription_period_start  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS subscription_period_end    TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS businesses_stripe_customer_id_key
  ON public.businesses (stripe_customer_id)
  WHERE stripe_customer_id IS NOT NULL;
```

- [ ] **Step 2: Apply the migration**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
supabase db push
```

Expected: migration applied with no errors. If supabase CLI is not available, apply directly in the Supabase dashboard SQL editor.

- [ ] **Step 3: Update TypeScript types for businesses**

In `ai-employees-app/src/integrations/supabase/types.ts`, find the `businesses` table block (around line 374).

Add to the `Row` block (after `website: string | null`):
```typescript
          stripe_customer_id: string | null
          stripe_subscription_id: string | null
          stripe_price_id: string | null
          stripe_subscription_status: string | null
          subscription_call_limit: number | null
          subscription_period_start: string | null
          subscription_period_end: string | null
```

Add to both `Insert` and `Update` blocks (after `website?: string | null`):
```typescript
          stripe_customer_id?: string | null
          stripe_subscription_id?: string | null
          stripe_price_id?: string | null
          stripe_subscription_status?: string | null
          subscription_call_limit?: number | null
          subscription_period_start?: string | null
          subscription_period_end?: string | null
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app && npx tsc --noEmit
```

Expected: no output (zero errors).

- [ ] **Step 5: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add supabase/migrations/20260430000001_businesses_stripe.sql src/integrations/supabase/types.ts
git commit -m "feat: add Stripe billing fields to businesses table"
```

---

## Task 2: Backend — Stripe Config + Schemas + Core Endpoints

**Repo:** `sam-backend`

**Files:**
- Modify: `sam-backend/backend/requirements.txt`
- Modify: `sam-backend/backend/app/core/config.py`
- Create: `sam-backend/backend/app/schemas/billing.py`
- Create: `sam-backend/backend/app/routers/billing.py` (subscription + checkout + portal endpoints only — webhook in Task 3)

- [ ] **Step 1: Add stripe to requirements**

In `sam-backend/backend/requirements.txt`, add after the `twilio` line:

```
stripe>=11.0.0
```

- [ ] **Step 2: Add Stripe config vars**

In `sam-backend/backend/app/core/config.py`, add these fields to the `Settings` class (after the `twilio_term_domain` field):

```python
    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_starter_price_id: str = ""
    stripe_growth_price_id: str = ""
    stripe_pro_price_id: str = ""
    billing_success_url: str = "http://localhost:5173/dashboard/billing?success=true"
    billing_cancel_url: str = "http://localhost:5173/dashboard/billing?canceled=true"
```

- [ ] **Step 3: Create billing schemas**

Create `sam-backend/backend/app/schemas/billing.py`:

```python
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class SubscriptionResponse(BaseModel):
    has_subscription: bool
    status: Optional[str] = None          # active | trialing | past_due | canceled
    plan_name: Optional[str] = None       # Starter | Growth | Pro
    price_id: Optional[str] = None
    call_limit: Optional[int] = None      # monthly call cap (150 / 400 / 800)
    calls_used: Optional[int] = None      # calls made in current billing period
    period_start: Optional[str] = None    # ISO8601
    period_end: Optional[str] = None      # ISO8601


class CreateCheckoutSessionRequest(BaseModel):
    business_id: str
    price_id: str                          # one of the 3 Stripe price IDs


class CreateCheckoutSessionResponse(BaseModel):
    checkout_url: str


class CustomerPortalResponse(BaseModel):
    portal_url: str
```

- [ ] **Step 4: Create billing router (subscription, checkout, portal)**

Create `sam-backend/backend/app/routers/billing.py`:

```python
"""
Stripe billing endpoints.
- GET  /billing/subscription        → current plan + call usage
- POST /billing/create-checkout-session → Stripe Checkout redirect URL
- POST /billing/customer-portal     → Stripe Customer Portal redirect URL
- POST /billing/webhook             → Stripe webhook receiver (Task 3)
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

# Map Stripe price ID → plan metadata. Populated at import time from settings.
def _plan_map() -> dict:
    return {
        settings.stripe_starter_price_id: {"name": "Starter", "call_limit": 150},
        settings.stripe_growth_price_id:  {"name": "Growth",  "call_limit": 400},
        settings.stripe_pro_price_id:     {"name": "Pro",     "call_limit": 800},
    }


def _stripe_client() -> stripe.Stripe:
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    return stripe.Stripe(settings.stripe_secret_key)


def _get_business(business_id: str) -> dict:
    r = supabase_admin.table("businesses").select(
        "id,name,stripe_customer_id,stripe_subscription_id,stripe_price_id,"
        "stripe_subscription_status,subscription_call_limit,"
        "subscription_period_start,subscription_period_end"
    ).eq("id", business_id).limit(1).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Business not found")
    return r.data[0]


def _count_calls_in_period(business_id: str, period_start: Optional[str], period_end: Optional[str]) -> int:
    if not period_start or not period_end:
        return 0
    r = supabase_admin.table("calls").select("id", count="exact").eq(
        "business_id", business_id
    ).gte("created_at", period_start).lte("created_at", period_end).execute()
    return r.count or 0


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    biz = _get_business(business_id)

    if not biz.get("stripe_subscription_id"):
        return SubscriptionResponse(has_subscription=False)

    plan_info = _plan_map().get(biz.get("stripe_price_id", ""), {})
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


@router.post("/create-checkout-session", response_model=CreateCheckoutSessionResponse)
async def create_checkout_session(
    body: CreateCheckoutSessionRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)

    plan_map = _plan_map()
    if body.price_id not in plan_map:
        raise HTTPException(status_code=400, detail="Invalid price ID")

    sc = _stripe_client()
    biz = _get_business(body.business_id)

    # Re-use existing Stripe customer if present, else Stripe creates one.
    customer_id = biz.get("stripe_customer_id") or None

    session = sc.checkout.sessions.create(
        mode="subscription",
        payment_method_types=["card"],
        line_items=[{"price": body.price_id, "quantity": 1}],
        success_url=settings.billing_success_url,
        cancel_url=settings.billing_cancel_url,
        metadata={"business_id": body.business_id},
        **({"customer": customer_id} if customer_id else {}),
    )

    return CreateCheckoutSessionResponse(checkout_url=session.url)


@router.post("/customer-portal", response_model=CustomerPortalResponse)
async def customer_portal(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    biz = _get_business(business_id)

    customer_id = biz.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer found for this business. Subscribe to a plan first.")

    sc = _stripe_client()
    session = sc.billing_portal.sessions.create(
        customer=customer_id,
        return_url=settings.billing_cancel_url.replace("?canceled=true", ""),
    )
    return CustomerPortalResponse(portal_url=session.url)
```

- [ ] **Step 5: Register billing router in main.py**

In `sam-backend/backend/app/main.py`, add the import:

```python
from app.routers import (
    calls,
    settings as settings_router,
    forwarding,
    analytics,
    integrations,
    gmail_integrations,
    phone_numbers,
    support,
    locations,
    custom_schedules,
    roles as roles_router,
    billing as billing_router,
)
```

And add below the last `app.include_router` call:

```python
app.include_router(billing_router.router)
```

- [ ] **Step 6: Install stripe and verify import**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
pip install stripe>=11.0.0
python -c "import stripe; print('stripe OK', stripe.__version__)"
```

Expected: `stripe OK 11.x.x`

- [ ] **Step 7: Verify FastAPI startup**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend && python -c "
from backend.app.main import app
from backend.app.routers.billing import router
routes = [r.path for r in app.routes]
assert '/billing/subscription' in routes, 'missing /billing/subscription'
assert '/billing/create-checkout-session' in routes
assert '/billing/customer-portal' in routes
print('All billing routes registered OK')
"
```

Expected: `All billing routes registered OK`

- [ ] **Step 8: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add backend/requirements.txt backend/app/core/config.py backend/app/schemas/billing.py backend/app/routers/billing.py backend/app/main.py
git commit -m "feat: add Stripe billing router (subscription, checkout, portal)"
```

---

## Task 3: Backend — Stripe Webhook Handler

**Repo:** `sam-backend`

**Files:**
- Modify: `sam-backend/backend/app/routers/billing.py` (add webhook endpoint)

The webhook endpoint must receive the **raw request body** (before JSON parsing) to verify Stripe's signature. FastAPI's body parsing would consume the stream, so we inject the `Request` object directly.

- [ ] **Step 1: Add webhook endpoint to billing.py**

Add this at the end of `sam-backend/backend/app/routers/billing.py` (after the `customer_portal` function):

```python
@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
):
    """
    Receives Stripe webhook events. No JWT auth — Stripe signature verifies authenticity.
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    payload = await request.body()

    try:
        sc = stripe.Stripe(settings.stripe_secret_key)
        event = sc.webhooks.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    except Exception as e:
        logger.error("Webhook construction error: %s", e)
        raise HTTPException(status_code=400, detail="Webhook error")

    event_type = event["type"]
    logger.info("Stripe webhook received: %s", event_type)

    if event_type in ("customer.subscription.created", "customer.subscription.updated"):
        _handle_subscription_upsert(event["data"]["object"])

    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(event["data"]["object"])

    elif event_type == "invoice.payment_succeeded":
        _handle_invoice_paid(event["data"]["object"])

    elif event_type == "invoice.payment_failed":
        _handle_invoice_failed(event["data"]["object"])

    return JSONResponse(content={"received": True})


def _handle_subscription_upsert(sub: dict) -> None:
    """Store subscription state on the business matching the Stripe customer."""
    customer_id = sub.get("customer")
    if not customer_id:
        return

    price_id = None
    items = sub.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id")

    plan_info = _plan_map().get(price_id, {})
    call_limit = plan_info.get("call_limit")

    period_start = sub.get("current_period_start")
    period_end = sub.get("current_period_end")

    def _ts(unix: int | None) -> str | None:
        if unix is None:
            return None
        return datetime.fromtimestamp(unix, tz=timezone.utc).isoformat()

    update = {
        "stripe_subscription_id": sub.get("id"),
        "stripe_price_id": price_id,
        "stripe_subscription_status": sub.get("status"),
        "subscription_period_start": _ts(period_start),
        "subscription_period_end": _ts(period_end),
    }
    if call_limit is not None:
        update["subscription_call_limit"] = call_limit

    # Find the business by stripe_customer_id first; if not found, try metadata.
    r = supabase_admin.table("businesses").select("id").eq("stripe_customer_id", customer_id).limit(1).execute()
    if r.data:
        business_id = r.data[0]["id"]
    else:
        # First time — checkout.session.completed sets customer_id, so check metadata fallback.
        logger.warning("No business found for Stripe customer %s", customer_id)
        return

    supabase_admin.table("businesses").update(update).eq("id", business_id).execute()
    logger.info("Subscription upserted for business %s: %s", business_id, sub.get("status"))


def _handle_subscription_deleted(sub: dict) -> None:
    customer_id = sub.get("customer")
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


def _handle_invoice_paid(invoice: dict) -> None:
    """On successful payment, update billing period (Stripe sends updated sub in invoice)."""
    sub_id = invoice.get("subscription")
    customer_id = invoice.get("customer")
    if not sub_id or not customer_id:
        return

    # The invoice contains the subscription period — re-read from Stripe to get fresh values.
    try:
        sc = stripe.Stripe(settings.stripe_secret_key)
        sub = sc.subscriptions.retrieve(sub_id)
        _handle_subscription_upsert(sub)
    except Exception as e:
        logger.error("Failed to refresh subscription on invoice.payment_succeeded: %s", e)


def _handle_invoice_failed(invoice: dict) -> None:
    customer_id = invoice.get("customer")
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
```

**Important:** The webhook endpoint has no `Depends(get_user_id)` — it authenticates via Stripe signature instead. Make sure CORS does NOT block `POST /billing/webhook` (it won't, because the wildcard CORS in main.py allows all origins).

- [ ] **Step 2: Handle checkout.session.completed to link customer_id**

The first time a user subscribes, Stripe creates a new customer. We capture that customer ID in the `checkout.session.completed` event (which carries `metadata.business_id`). Add this event to the webhook handler in `stripe_webhook`:

After the `elif event_type == "invoice.payment_failed":` block, add:

```python
    elif event_type == "checkout.session.completed":
        _handle_checkout_completed(event["data"]["object"])
```

And add the handler function (before `_handle_subscription_upsert`):

```python
def _handle_checkout_completed(session: dict) -> None:
    """Link the new Stripe customer_id to the business after first checkout."""
    business_id = (session.get("metadata") or {}).get("business_id")
    customer_id = session.get("customer")
    if not business_id or not customer_id:
        return
    supabase_admin.table("businesses").update({
        "stripe_customer_id": customer_id
    }).eq("id", business_id).execute()
    logger.info("Linked Stripe customer %s to business %s", customer_id, business_id)
```

Also add `checkout.session.completed` to the Stripe webhook dashboard event list.

- [ ] **Step 3: Verify the webhook route is registered (no auth dependency)**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend && python -c "
from backend.app.main import app
for r in app.routes:
    if hasattr(r, 'path') and 'webhook' in r.path:
        print('webhook route:', r.path, r.methods)
"
```

Expected: `webhook route: /billing/webhook {'POST'}`

- [ ] **Step 4: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add backend/app/routers/billing.py
git commit -m "feat: add Stripe webhook handler (subscription sync, checkout link)"
```

---

## Task 4: Frontend — Billing API + Billing Page

**Repo:** `ai-employees-app`

**Files:**
- Modify: `ai-employees-app/src/lib/voiceAgentApi.ts`
- Rewrite: `ai-employees-app/src/pages/dashboard/Billing.tsx`

The Billing page has two states:
1. **No subscription** — show 3 plan cards (Starter / Growth / Pro). Clicking "Subscribe" calls `createCheckoutSession` and redirects to the returned URL.
2. **Subscribed** — show current plan, calls used/total with a progress bar, renewal date, status badge. "Manage Plan" button opens Stripe Customer Portal.

The `STRIPE_STARTER_PRICE_ID` etc. are backend config — the frontend doesn't hardcode price IDs. Instead, the no-subscription view fetches a public plan list endpoint. We keep it simple: hardcode the 3 plan definitions in the frontend (name, price, features, price_id read from `import.meta.env.VITE_STRIPE_STARTER_PRICE_ID` etc.).

- [ ] **Step 1: Add env vars to frontend**

In `ai-employees-app/.env` (and `.env.local`), add:

```
VITE_STRIPE_STARTER_PRICE_ID=price_xxxx
VITE_STRIPE_GROWTH_PRICE_ID=price_xxxx
VITE_STRIPE_PRO_PRICE_ID=price_xxxx
```

(Same price IDs as in the backend `.env`.)

- [ ] **Step 2: Add billing API functions to voiceAgentApi.ts**

At the end of `ai-employees-app/src/lib/voiceAgentApi.ts`, add:

```typescript
// ── Billing ───────────────────────────────────────────────────────────────────

export interface BillingSubscription {
  has_subscription: boolean;
  status?: string;
  plan_name?: string;
  price_id?: string;
  call_limit?: number;
  calls_used?: number;
  period_start?: string;
  period_end?: string;
}

export async function getBillingSubscription(
  token: string,
  businessId: string
): Promise<BillingSubscription> {
  const q = new URLSearchParams({ business_id: businessId });
  const res = await fetchWithAuth(`/billing/subscription?${q}`, token);
  if (!res.ok) throw new Error(`Failed to fetch subscription: ${res.status}`);
  return res.json();
}

export async function createCheckoutSession(
  token: string,
  businessId: string,
  priceId: string
): Promise<{ checkout_url: string }> {
  const res = await fetchWithAuth("/billing/create-checkout-session", token, {
    method: "POST",
    body: JSON.stringify({ business_id: businessId, price_id: priceId }),
  });
  if (!res.ok) throw new Error(`Failed to create checkout session: ${res.status}`);
  return res.json();
}

export async function createCustomerPortalSession(
  token: string,
  businessId: string
): Promise<{ portal_url: string }> {
  const q = new URLSearchParams({ business_id: businessId });
  const res = await fetchWithAuth(`/billing/customer-portal?${q}`, token, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to create portal session: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 3: Rewrite Billing.tsx**

Replace the entire content of `ai-employees-app/src/pages/dashboard/Billing.tsx` with:

```tsx
import { useEffect, useState } from "react";
import { CheckCircle, AlertCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { useAuth } from "@/contexts/AuthContext";
import {
  getBillingSubscription,
  createCheckoutSession,
  createCustomerPortalSession,
  type BillingSubscription,
} from "@/lib/voiceAgentApi";

const PLANS = [
  {
    name: "Starter",
    price: "$99",
    period: "/month",
    callLimit: 150,
    locations: 1,
    users: 5,
    overage: "$0.35/call",
    priceId: import.meta.env.VITE_STRIPE_STARTER_PRICE_ID as string,
    features: [
      "150 calls/month",
      "1 location",
      "Up to 5 team members",
      "Inbound + outbound calling",
      "SMS + email confirmations",
      "Google Calendar sync",
      "Call recordings & transcripts",
      "Brand voice customization",
    ],
  },
  {
    name: "Growth",
    price: "$199",
    period: "/month",
    callLimit: 400,
    locations: 3,
    users: 15,
    overage: "$0.30/call",
    priceId: import.meta.env.VITE_STRIPE_GROWTH_PRICE_ID as string,
    highlight: true,
    features: [
      "400 calls/month",
      "3 locations",
      "Up to 15 team members",
      "Everything in Starter",
      "Multi-location scheduling",
      "Priority support",
    ],
  },
  {
    name: "Pro",
    price: "$349",
    period: "/month",
    callLimit: 800,
    locations: 5,
    users: 30,
    overage: "$0.25/call",
    priceId: import.meta.env.VITE_STRIPE_PRO_PRICE_ID as string,
    features: [
      "800 calls/month",
      "5 locations",
      "Up to 30 team members",
      "Everything in Growth",
      "Lowest overage rate",
      "Dedicated support",
    ],
  },
];

function usagePercent(used: number, limit: number) {
  return Math.min(Math.round((used / limit) * 100), 100);
}

function formatDate(iso?: string) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" });
}

function statusBadge(status?: string) {
  if (status === "active") return <Badge className="bg-green-500/10 text-green-600">Active</Badge>;
  if (status === "past_due") return <Badge className="bg-red-500/10 text-red-600">Past Due</Badge>;
  if (status === "trialing") return <Badge className="bg-blue-500/10 text-blue-600">Trial</Badge>;
  if (status === "canceled") return <Badge className="bg-gray-500/10 text-gray-500">Canceled</Badge>;
  return <Badge variant="outline">{status}</Badge>;
}

const Billing = () => {
  const { session, businessId } = useAuth();
  const token = session?.access_token ?? null;

  const [sub, setSub] = useState<BillingSubscription | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [subscribing, setSubscribing] = useState<string | null>(null);
  const [openingPortal, setOpeningPortal] = useState(false);

  useEffect(() => {
    if (!token || !businessId) return;
    setLoading(true);
    getBillingSubscription(token, businessId)
      .then(setSub)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [token, businessId]);

  const handleSubscribe = async (priceId: string) => {
    if (!token || !businessId) return;
    setSubscribing(priceId);
    try {
      const { checkout_url } = await createCheckoutSession(token, businessId, priceId);
      window.location.href = checkout_url;
    } catch (e: any) {
      setError(e.message);
      setSubscribing(null);
    }
  };

  const handleManagePlan = async () => {
    if (!token || !businessId) return;
    setOpeningPortal(true);
    try {
      const { portal_url } = await createCustomerPortalSession(token, businessId);
      window.location.href = portal_url;
    } catch (e: any) {
      setError(e.message);
      setOpeningPortal(false);
    }
  };

  if (loading) {
    return (
      <div className="animate-fade-in flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-muted-foreground" size={32} />
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <h1 className="text-3xl font-bold text-foreground mb-2">Billing</h1>
      <p className="text-muted-foreground mb-8">Manage your subscription and usage.</p>

      {error && (
        <div className="flex items-center gap-2 text-red-600 bg-red-50 border border-red-200 rounded-lg p-3 mb-6 text-sm">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {/* ── No subscription: plan selection ─────────────────────────── */}
      {(!sub || !sub.has_subscription || sub.status === "canceled") && (
        <div>
          <h2 className="text-xl font-semibold text-foreground mb-6">Choose a plan</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {PLANS.map((plan) => (
              <div
                key={plan.name}
                className={`bg-card rounded-xl border p-6 shadow-card flex flex-col ${
                  plan.highlight ? "border-accent ring-1 ring-accent" : "border-border"
                }`}
              >
                {plan.highlight && (
                  <div className="text-xs font-semibold uppercase tracking-wide text-accent mb-3">Most popular</div>
                )}
                <h3 className="text-xl font-bold text-foreground">{plan.name}</h3>
                <div className="mt-2 mb-4">
                  <span className="text-3xl font-bold text-foreground">{plan.price}</span>
                  <span className="text-muted-foreground text-sm">{plan.period}</span>
                </div>
                <ul className="space-y-2 flex-1 mb-6">
                  {plan.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-muted-foreground">
                      <CheckCircle size={14} className="text-green-500 mt-0.5 shrink-0" />
                      {f}
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground mb-4">Overage: {plan.overage}</p>
                <Button
                  className="w-full"
                  variant={plan.highlight ? "default" : "outline"}
                  disabled={!!subscribing}
                  onClick={() => handleSubscribe(plan.priceId)}
                >
                  {subscribing === plan.priceId ? (
                    <Loader2 size={16} className="animate-spin mr-2" />
                  ) : null}
                  Subscribe
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Active subscription ──────────────────────────────────────── */}
      {sub?.has_subscription && sub.status !== "canceled" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: usage */}
          <div className="lg:col-span-2 space-y-6">
            <div className="bg-card rounded-xl border border-border p-6 shadow-card">
              <h2 className="text-lg font-semibold text-foreground mb-4">Usage this period</h2>
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-muted-foreground">AI Calls</span>
                  <span className="font-medium">
                    {sub.calls_used?.toLocaleString() ?? 0} / {sub.call_limit?.toLocaleString() ?? "—"}
                  </span>
                </div>
                <Progress value={usagePercent(sub.calls_used ?? 0, sub.call_limit ?? 1)} className="h-2" />
                {(sub.calls_used ?? 0) >= (sub.call_limit ?? Infinity) && (
                  <p className="text-xs text-amber-600 flex items-center gap-1">
                    <AlertCircle size={12} /> You've reached your monthly call limit. Additional calls will be billed as overage.
                  </p>
                )}
                {(sub.calls_used ?? 0) >= (sub.call_limit ?? Infinity) * 0.8 &&
                  (sub.calls_used ?? 0) < (sub.call_limit ?? Infinity) && (
                  <p className="text-xs text-amber-500 flex items-center gap-1">
                    <AlertCircle size={12} /> You've used 80% of your monthly calls.
                  </p>
                )}
              </div>
              <div className="mt-4 pt-4 border-t border-border grid grid-cols-2 gap-4 text-sm">
                <div>
                  <p className="text-muted-foreground">Period start</p>
                  <p className="font-medium">{formatDate(sub.period_start)}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">Renews</p>
                  <p className="font-medium">{formatDate(sub.period_end)}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Right: plan card */}
          <div className="space-y-6">
            <div className="bg-card rounded-xl border border-border p-6 shadow-card">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-foreground">Your Plan</h2>
                {statusBadge(sub.status)}
              </div>
              <p className="text-2xl font-bold text-foreground mb-1">{sub.plan_name} Plan</p>
              <p className="text-muted-foreground text-sm mb-6">
                {sub.call_limit?.toLocaleString()} calls/month
              </p>
              <div className="flex flex-col gap-2">
                <Button onClick={handleManagePlan} disabled={openingPortal} variant="outline">
                  {openingPortal && <Loader2 size={14} className="animate-spin mr-2" />}
                  Manage Plan
                </Button>
              </div>
              <p className="text-xs text-muted-foreground mt-4">
                Change plan, update payment method, or cancel from the billing portal.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Billing;
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app && npx tsc --noEmit
```

Expected: no output (zero errors). If there are errors about `Progress` component not existing, check that `@/components/ui/progress` exists:

```bash
ls /home/lap-68/Documents/gt-rahul/ai-employees-app/src/components/ui/progress.tsx 2>/dev/null || echo "MISSING — install shadcn progress"
```

If missing, run: `npx shadcn-ui@latest add progress` from the ai-employees-app directory.

- [ ] **Step 5: Check AuthContext exports businessId**

```bash
grep -n "businessId" /home/lap-68/Documents/gt-rahul/ai-employees-app/src/contexts/AuthContext.tsx | head -10
```

If `businessId` is not exported from `useAuth()`, find how it's exposed (may be `currentBusinessId`, or derived from `businesses[0].id`). Adjust the `useAuth()` destructure in `Billing.tsx` to match.

- [ ] **Step 6: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/lib/voiceAgentApi.ts src/pages/dashboard/Billing.tsx
git commit -m "feat: replace static billing with live Stripe subscription UI"
```

---

## Task 5: Docker Rebuild + End-to-End Smoke Test

**Repos:** both

- [ ] **Step 1: Add stripe to requirements.txt and rebuild**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
docker compose build sam-backend
docker compose up -d
```

Expected: container starts without import errors. Check logs:

```bash
docker logs sam-backend-sam-backend-1 2>&1 | tail -20
```

Expected: `Application startup complete.` with no `ModuleNotFoundError`.

- [ ] **Step 2: Test subscription endpoint (no subscription state)**

```bash
# Replace TOKEN with a real Supabase JWT (from browser devtools → Application → localStorage → supabase token)
# Replace BUSINESS_ID with da9fc4fb-2b16-48ab-8856-696870d0a18a (test business)
curl -s -H "Authorization: Bearer TOKEN" \
  "http://localhost:8000/billing/subscription?business_id=BUSINESS_ID" | python3 -m json.tool
```

Expected response:
```json
{"has_subscription": false}
```

- [ ] **Step 3: Test checkout session creation (test mode)**

First ensure your Stripe keys are test mode (`sk_test_...`). Then:

```bash
curl -s -X POST \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"business_id": "da9fc4fb-2b16-48ab-8856-696870d0a18a", "price_id": "YOUR_STARTER_PRICE_ID"}' \
  "http://localhost:8000/billing/create-checkout-session" | python3 -m json.tool
```

Expected: `{"checkout_url": "https://checkout.stripe.com/..."}`. Copy the URL and open it in browser — should show Stripe test checkout.

- [ ] **Step 4: Test webhook locally with Stripe CLI**

Install the Stripe CLI, then forward events to localhost:

```bash
stripe listen --forward-to localhost:8000/billing/webhook
```

In another terminal, trigger a test event:

```bash
stripe trigger checkout.session.completed
```

Expected in backend logs: `Stripe webhook received: checkout.session.completed`.

- [ ] **Step 5: Verify the Billing page renders both states**

Start the frontend dev server and navigate to the Billing page:
- Before subscribing: plan cards should show (Starter / Growth / Pro)
- After subscribing (or in Supabase, manually set `stripe_subscription_status = 'active'`, `subscription_call_limit = 150`, `subscription_period_start`, `subscription_period_end` on the test business): refresh → should show usage view.

---

## Self-Review Checklist

- [ ] Migration adds all 7 Stripe fields; unique index on `stripe_customer_id`
- [ ] Config has all 6 Stripe env vars with safe empty string defaults (so backend doesn't crash without Stripe configured)
- [ ] Billing schemas defined in separate `schemas/billing.py` (follows existing pattern like `schemas/roles.py`)
- [ ] Webhook endpoint uses raw `request.body()` — not `body: dict = Body(...)` — so Stripe signature verification works
- [ ] `checkout.session.completed` links `stripe_customer_id` to business before subscription events fire
- [ ] `subscription.deleted` clears all Stripe fields cleanly
- [ ] `invoice.payment_succeeded` refreshes the period window from Stripe
- [ ] Frontend shows progress bar at 80% warning and at-limit warning
- [ ] Frontend "Manage Plan" opens Stripe Customer Portal (handles cancel, change plan, update payment)
- [ ] `businessId` in Billing.tsx matches what `useAuth()` actually exports
- [ ] `Progress` component exists or is installed via shadcn

