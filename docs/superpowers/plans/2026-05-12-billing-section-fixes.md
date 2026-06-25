# Billing Section Critical Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 3 critical issues in `feature/billing-section` before merging — wrong `.env.example` variable names, "Pro" vs "Professional" naming mismatch, and billing metric counting calls instead of minutes.

**Architecture:** All fixes are in-place edits to existing files across both repos. No DB migrations needed — the `businesses.subscription_call_limit` column already exists and will just store minute values going forward. The metrics rename flows: Pydantic schema → billing router → TypeScript interface → frontend component.

**Tech Stack:** FastAPI + Pydantic (backend), React + TypeScript (frontend), Stripe SDK

**Branch:** `feature/billing-section` in both repos

---

### Task 1: Fix `.env.example` Stripe variable names

**Files:**
- Modify: `backend/.env.example:51–53`

- [ ] **Step 1: Fix the 3 wrong variable names**

In `backend/.env.example`, change lines 51–53 from:
```
STRIPE_STARTER_PLAN_PRICE_ID=
STRIPE_STARTER_PLAN_GROWTH_ID=
STRIPE_STARTER_PLAN_PRO_ID=
```
to:
```
STRIPE_STARTER_PRICE_ID=
STRIPE_GROWTH_PRICE_ID=
STRIPE_PRO_PRICE_ID=
```
Line 54 `STRIPE_ENTERPRISE_PRICE_ID=` is already correct — leave it unchanged.

- [ ] **Step 2: Verify names match config.py**

```bash
grep "stripe_.*price_id" backend/app/core/config.py
```
Expected — all 4 fields present:
```
stripe_starter_price_id: str = ""
stripe_growth_price_id: str = ""
stripe_pro_price_id: str = ""
stripe_enterprise_price_id: str = ""
```
Pydantic-settings maps `STRIPE_STARTER_PRICE_ID` → `stripe_starter_price_id` (uppercased env var → lowercase field). All 4 now match.

- [ ] **Step 3: Commit**

```bash
git add backend/.env.example
git commit -m "fix: correct Stripe price ID variable names in .env.example"
```

---

### Task 2: Fix "Pro" → "Professional" naming

**Files:**
- Modify: `backend/app/routers/billing.py:30–35,123`
- Modify: `backend/app/schemas/billing.py:19`
- Modify: `ai-employees-app/src/pages/dashboard/Billing.tsx:36`

The `stripe_pro_price_id` config field name stays unchanged — it's an internal env var name and renaming it would require updating everyone's `.env`. Only the plan key and display name change.

- [ ] **Step 1: Rename plan key and display name in PLAN_KEY_MAP**

In `backend/app/routers/billing.py`, replace lines 30–35:
```python
PLAN_KEY_MAP = {
    "starter":    ("stripe_starter_price_id",    "Starter",    150),
    "growth":     ("stripe_growth_price_id",     "Growth",     400),
    "pro":        ("stripe_pro_price_id",        "Pro",        800),
    "enterprise": ("stripe_enterprise_price_id", "Enterprise", 1300),
}
```
with:
```python
PLAN_KEY_MAP = {
    "starter":      ("stripe_starter_price_id",    "Starter",      150),
    "growth":       ("stripe_growth_price_id",     "Growth",       400),
    "professional": ("stripe_pro_price_id",        "Professional", 800),
    "enterprise":   ("stripe_enterprise_price_id", "Enterprise",   1300),
}
```

- [ ] **Step 2: Update validation error message**

In `backend/app/routers/billing.py` line 123, change:
```python
raise HTTPException(status_code=400, detail="Invalid plan. Must be starter, growth, pro, or enterprise.")
```
to:
```python
raise HTTPException(status_code=400, detail="Invalid plan. Must be starter, growth, professional, or enterprise.")
```

- [ ] **Step 3: Update schema comment**

In `backend/app/schemas/billing.py` line 19, change:
```python
    plan: str  # "starter" | "growth" | "pro"
```
to:
```python
    plan: str  # "starter" | "growth" | "professional" | "enterprise"
```

- [ ] **Step 4: Update PLAN_ACTIONS in Billing.tsx**

In `ai-employees-app/src/pages/dashboard/Billing.tsx` line 36, change:
```tsx
  { label: "Subscribe", plan: "pro" },
```
to:
```tsx
  { label: "Subscribe", plan: "professional" },
```

- [ ] **Step 5: Verify backend syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('backend/app/routers/billing.py').read()); print('billing.py OK')"
python -c "import ast; ast.parse(open('backend/app/schemas/billing.py').read()); print('schemas OK')"
```
Expected: both print `OK`.

- [ ] **Step 6: Commit both repos**

```bash
# Backend
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add backend/app/routers/billing.py backend/app/schemas/billing.py
git commit -m "fix: rename plan key 'pro' to 'professional' for display consistency"

# Frontend
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/pages/dashboard/Billing.tsx
git commit -m "fix: update PLAN_ACTIONS to send 'professional' instead of 'pro'"
```

---

### Task 3: Fix billing metric — minutes instead of call count

**Files:**
- Modify: `backend/app/routers/billing.py:30–35,62–109` — PLAN_KEY_MAP limits + new minute counter + updated field names
- Modify: `backend/app/schemas/billing.py:6–14` — rename `calls_used`/`call_limit` → `minutes_used`/`minute_limit`
- Modify: `ai-employees-app/src/lib/voiceAgentApi.ts:912–921` — update `BillingSubscription` interface
- Modify: `ai-employees-app/src/pages/dashboard/Billing.tsx:207–257` — field references + labels

**Context:** The `calls` table has a `duration_seconds` column (added in migration `20260417000000`). Summing this and dividing by 60 gives actual agent minutes used. The `businesses.subscription_call_limit` DB column stays as-is — no migration needed; we just store minute values (200/600/1500/4000) instead of call counts.

- [ ] **Step 1: Update PLAN_KEY_MAP limits to minute values**

In `backend/app/routers/billing.py`, update the PLAN_KEY_MAP (after Task 2 it already has the right keys). Change the 3rd element of each tuple from call counts to minute values:

```python
PLAN_KEY_MAP = {
    "starter":      ("stripe_starter_price_id",    "Starter",      200),
    "growth":       ("stripe_growth_price_id",     "Growth",       600),
    "professional": ("stripe_pro_price_id",        "Professional", 1500),
    "enterprise":   ("stripe_enterprise_price_id", "Enterprise",   4000),
}
```

- [ ] **Step 2: Replace `_count_calls_in_period` with `_count_minutes_in_period`**

In `backend/app/routers/billing.py`, replace lines 62–77:
```python
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
```
with:
```python
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
        .execute()
    )
    total_seconds = sum((row.get("duration_seconds") or 0) for row in (r.data or []))
    return total_seconds // 60
```

- [ ] **Step 3: Update `get_subscription` to use new function and field names**

In `backend/app/routers/billing.py`, replace lines 94–109:
```python
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
```
with:
```python
    minutes_used = _count_minutes_in_period(
        business_id,
        biz.get("subscription_period_start"),
        biz.get("subscription_period_end"),
    )

    return SubscriptionResponse(
        has_subscription=True,
        status=biz.get("stripe_subscription_status"),
        plan_name=plan_info.get("name"),
        price_id=biz.get("stripe_price_id"),
        minute_limit=biz.get("subscription_call_limit") or plan_info.get("call_limit"),
        minutes_used=minutes_used,
        period_start=biz.get("subscription_period_start"),
        period_end=biz.get("subscription_period_end"),
    )
```

- [ ] **Step 4: Update `SubscriptionResponse` schema**

In `backend/app/schemas/billing.py`, replace lines 6–14:
```python
class SubscriptionResponse(BaseModel):
    has_subscription: bool
    status: Optional[str] = None
    plan_name: Optional[str] = None
    price_id: Optional[str] = None
    call_limit: Optional[int] = None
    calls_used: Optional[int] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
```
with:
```python
class SubscriptionResponse(BaseModel):
    has_subscription: bool
    status: Optional[str] = None
    plan_name: Optional[str] = None
    price_id: Optional[str] = None
    minute_limit: Optional[int] = None
    minutes_used: Optional[int] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None
```

- [ ] **Step 5: Verify backend syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('backend/app/routers/billing.py').read()); print('billing.py OK')"
python -c "import ast; ast.parse(open('backend/app/schemas/billing.py').read()); print('schemas OK')"
```
Expected: both print `OK`.

- [ ] **Step 6: Update `BillingSubscription` TypeScript interface**

In `ai-employees-app/src/lib/voiceAgentApi.ts`, replace lines 912–921:
```ts
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
```
with:
```ts
export interface BillingSubscription {
  has_subscription: boolean;
  status?: string;
  plan_name?: string;
  price_id?: string;
  minute_limit?: number;
  minutes_used?: number;
  period_start?: string;
  period_end?: string;
}
```

- [ ] **Step 7: Update field references and labels in `Billing.tsx`**

Apply the following changes in `ai-employees-app/src/pages/dashboard/Billing.tsx`:

**Line 207** — usage label:
```tsx
<span className="text-muted-foreground">AI Calls</span>
```
→
```tsx
<span className="text-muted-foreground">AI Minutes Used</span>
```

**Lines 209–210** — used/limit display:
```tsx
                    {(sub!.calls_used ?? 0).toLocaleString()} /{" "}
                    {(sub!.call_limit ?? 0).toLocaleString()}
```
→
```tsx
                    {(sub!.minutes_used ?? 0).toLocaleString()} /{" "}
                    {(sub!.minute_limit ?? 0).toLocaleString()}
```

**Line 214** — progress bar value:
```tsx
                  value={usagePercent(sub!.calls_used ?? 0, sub!.call_limit ?? 1)}
```
→
```tsx
                  value={usagePercent(sub!.minutes_used ?? 0, sub!.minute_limit ?? 1)}
```

**Line 217** — overage warning condition:
```tsx
                {(sub!.calls_used ?? 0) >= (sub!.call_limit ?? Infinity) && (
```
→
```tsx
                {(sub!.minutes_used ?? 0) >= (sub!.minute_limit ?? Infinity) && (
```

**Line 218** — overage warning text:
```tsx
                    Call limit reached — additional calls are billed as overage.
```
→
```tsx
                    Minute limit reached — contact support to upgrade your plan.
```

**Lines 223–224** — 80% warning condition:
```tsx
                {(sub!.calls_used ?? 0) >= (sub!.call_limit ?? Infinity) * 0.8 &&
                  (sub!.calls_used ?? 0) < (sub!.call_limit ?? Infinity) && (
```
→
```tsx
                {(sub!.minutes_used ?? 0) >= (sub!.minute_limit ?? Infinity) * 0.8 &&
                  (sub!.minutes_used ?? 0) < (sub!.minute_limit ?? Infinity) && (
```

**Line 226** — 80% warning text:
```tsx
                      You've used 80% of your monthly calls.
```
→
```tsx
                      You've used 80% of your monthly minutes.
```

**Line 257** — plan card subtitle:
```tsx
              {(sub!.call_limit ?? 0).toLocaleString()} calls/month
```
→
```tsx
              {(sub!.minute_limit ?? 0).toLocaleString()} minutes/month
```

- [ ] **Step 8: TypeScript check**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx tsc --noEmit 2>&1 | grep -E "calls_used|call_limit|minute"
```
Expected: no output (no errors on those field names).

- [ ] **Step 9: Commit both repos**

```bash
# Backend
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add backend/app/routers/billing.py backend/app/schemas/billing.py
git commit -m "fix: switch billing metric from call count to minutes; update PLAN_KEY_MAP limits"

# Frontend
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/lib/voiceAgentApi.ts src/pages/dashboard/Billing.tsx
git commit -m "fix: update billing UI to use minutes_used/minute_limit fields and labels"
```
