# ADR 0001: Billing Add-On Line Items + Two-Layer Access Gating

**Date:** 2026-07-02
**Status:** Accepted
**Deciders:** Rahul Khera

---

## Context

Sam asked "where is the toggle to add-on the Executive Assistant?" in billing. Verifying the current code turned up two separate problems, not one:

1. **No add-on concept exists at all.** Billing today is one Stripe subscription per business, one plan, one price. There's no mechanism for a second, optional, separately-toggleable charge.
2. **No subscription enforcement exists anywhere outside the Billing page's display.** Searching the whole backend for `has_subscription`/`stripe_subscription_status`/`subscription_call_limit` found them referenced only in the Billing page itself. A business with a canceled or nonexistent subscription can use every feature today — the usage-limit warnings on the Billing page are cosmetic text, not an enforced block. This predates this work and is a whole-product gap, not something introduced here (see "Consequences" below — it is *not* being fixed as part of this ADR).

This ADR covers the *narrow* decision: how the Executive Agent add-on specifically should work, end to end. It does not resolve the whole-product gap — that's tracked separately (`TODO.md`, `memory/project_blockers.md`) and deliberately deferred.

---

## Decision

### 1. Add-ons are additional Stripe subscription items, not separate subscriptions

The Executive Agent add-on is added as a second line item on the business's *existing* Stripe subscription (`stripe.SubscriptionItem.create(subscription=existing_sub_id, price=addon_price_id)`), not as a new, separate Stripe subscription. This is Stripe's own recommended pattern for add-ons — one invoice, one payment method, line items can be added/removed independently.

We store the returned **subscription item ID** (not the price ID) on `businesses.stripe_exec_agent_item_id`, so it can be deleted individually later without touching the base plan.

### 2. The actual dollar price is a deploy-time config value, not a code constant

`STRIPE_EXEC_AGENT_PRICE_ID` is an environment variable, mirroring the existing pattern for the four base-plan prices. The Stripe Price object itself is created manually in the Stripe dashboard whenever Sam names a number — the code never needs to know or store the dollar amount. Until it's configured, toggling the add-on on fails with a clear "not configured" error (503), not a silent no-op.

### 3. Access is gated in two independent layers — both required, neither optional

- **Frontend (UX layer):** `AuthContext.tsx` already does a single bootstrap fetch on login/full-page-refresh that loads `profile`, `roles`, and `permittedPaths` once — every page reads from this instead of re-checking permissions itself (`canAccess(path)`). We extend this *same* bootstrap to also carry the add-on's enabled/disabled state. This means a locked-out business never even sees the Executive Agent nav item light up or gets partway into the page before being blocked — consistent with how role-based gating already behaves.
- **Backend (enforcement layer):** `POST /executive/session` (and any other endpoint that would let someone actually use Remi) independently checks `businesses.stripe_exec_agent_item_id IS NOT NULL` server-side and rejects with 403 if the add-on isn't active — regardless of what the frontend thinks or shows. This is the layer that actually matters; the frontend layer alone is bypassable by anyone calling the API directly, so it's a UX nicety, not security.

### 4. Cascading cancellation

If the business's *entire* base subscription is canceled (not just the add-on), Stripe cancels every line item on it automatically, including the add-on. The existing `customer.subscription.deleted` webhook handler is extended to also clear `stripe_exec_agent_item_id`, so our DB doesn't retain a stale reference to a subscription item Stripe has already deleted.

---

## Alternatives Considered

**Separate Stripe subscription for the add-on**, instead of a line item on the existing one. Rejected — means a second invoice, a second payment-method dependency, and doesn't match Stripe's own guidance for add-ons.

**Per-page/incremental fetch of billing state**, instead of extending the login bootstrap. Rejected — billing/add-on state doesn't change often enough (only when someone toggles it, or once per billing cycle) to need per-page freshness, and it would create two different gating mechanisms behaving two different ways (bootstrap-once for roles, per-page for billing) instead of one consistent model.

**Frontend-only gating**, skipping the backend check. Rejected outright — not a real security boundary. Included here only to record that it was explicitly considered and ruled out, not overlooked.

---

## Consequences

- Building this requires touching 3 layers (Stripe line-item logic, `AuthContext` bootstrap extension, backend endpoint guard) — not a single-file change, but each piece is small and independently testable.
- The whole-product billing-enforcement gap (item 2 under Context) is now written down and tracked, but is explicitly **not** part of this decision or its implementation. When that work happens, it should follow the same two-layer pattern established here (bootstrap extension + mandatory backend check per endpoint) rather than inventing a new one — but it is a much larger surface (every feature, every endpoint) and needs its own careful scoping and testing pass, separate from this add-on.
- Until `STRIPE_EXEC_AGENT_PRICE_ID` is set, the add-on toggle is visible but non-functional (clear error, not hidden) — this is intentional so the UI/toggle can be built and tested end-to-end before Sam names a price.
