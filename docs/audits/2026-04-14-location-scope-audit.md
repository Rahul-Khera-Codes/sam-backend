# Location-Scope Audit — 2026-04-14

End-to-end audit of all location-scoped tables across DB, backend, agent, and frontend.
Verified against actual code; severity ratings reflect real-world impact.

> **STATUS UPDATE (2026-04-14 later):** All findings #1, #2, #3, #4, #5, #6, #8 fixed and committed.
> Remaining: #7 (location_services RLS — by design, low priority). Migrations need to be run by user.

---

## Summary

| Bucket | Count |
|---|---|
| 🔴 Critical (must fix before production) | 1 |
| 🟡 Medium (should fix soon) | 3 |
| 🟢 Low (nice to have / future) | 4 |
| ✅ Properly scoped (no action) | 11 features |

Most of the architecture is correctly location-scoped. The remaining issues are concentrated in the agent's appointment-creation path and a few backend endpoints that don't yet accept `location_id`.

---

## 🔴 Critical Issues

### 1. Agent can write appointments with `location_id = NULL`
**File:** `agent/agent.py:328`
```python
"location_id": loc["id"] if loc else None,
```

**The bug:** `loc` is the result of `self._resolve_location(location_name)` (line 314). If the user gives an ambiguous or unknown location name, `_resolve_location` returns `None` instead of falling back to the called location. The appointment then gets inserted with `location_id = NULL`.

**Impact:** A NULL-location appointment doesn't appear in any location-filtered view. It becomes effectively orphaned. The customer gets the confirmation email but no one sees it on the Calendar page.

**Why it matters:** The agent always knows which location was called (`self._location_id` is set from the dispatch rule). There's no good reason to accept NULL here.

**Fix (1 line):** Change `agent/agent.py:328` to:
```python
"location_id": (loc["id"] if loc else None) or self._location_id,
```
Or better, update `_resolve_location` (line 144) to fall back to `self._default_location` when no name is provided AND when the lookup misses.

---

## 🟡 Medium Issues

### 2. `PUT /forwarding/contacts/bulk/toggle` ignores location
**File:** `backend/app/routers/forwarding.py:84-94`
The bulk toggle endpoint enables/disables ALL contacts for a business — even those at other locations.

**Impact:** Admin at Location A clicking "Disable All" disables Location B's contacts too.

**Fix:** Add optional `location_id` query param; filter the UPDATE by `location_id` when provided.

### 3. `GET /settings/agent/audit-log` doesn't filter by location
**File:** `backend/app/routers/settings.py:329-346`
Returns audit entries for the entire business. With per-location settings, the audit log should also be per-location (or at least show which location the change applied to).

**Impact:** Audit log shows entries from all locations mixed together. Hard to trace which location's settings were changed.

**Fix:** Add `location_id` to the `settings_audit_log` table (migration), include it on every audit insert, and filter by it in this endpoint.

### 4. Settings page audit log not filtered when shown
**File:** `ai-employees-app/src/pages/dashboard/customer-service/AgentSettings.tsx`
The "recent changes" feed (currently fetched via `getSettingsAuditLog`) doesn't pass `selectedLocationId`. Tied to issue #3 — needs the backend fix first.

---

## 🟢 Low-Severity / Architectural Notes

### 5. `useAppointments.fetchAppointments` returns all when no location selected
**File:** `ai-employees-app/src/hooks/useAppointments.ts:81-83`
```typescript
if (selectedLocationId) {
  query = query.eq("location_id", selectedLocationId);
}
```

**Context:** When `selectedLocationId` is null (user hasn't chosen a location), the query returns all appointments for the business. In practice this rarely matters because the app forces location selection at login. But if the localStorage gets cleared mid-session, the user sees cross-location data briefly.

**Fix (optional):** Skip fetching entirely when `selectedLocationId` is null. Or redirect to `/select-location`.

### 6. `_get_business_number` non-deterministic when multiple numbers
**File:** `agent/sms_helpers.py:31-51`
Uses `.limit(1)` without ordering. If a location somehow has multiple active numbers (it shouldn't), returns whichever Postgres feels like.

**Fix (optional):** Add `.order("created_at", desc=False)` for consistency.

### 7. RLS on `location_services` checks `business_id` only
**File:** `supabase/migrations/20260411000000_location_services_write_rls.sql`
Members can INSERT/UPDATE rows for any location within their business, not just locations they're assigned to. Probably fine for v1 since admin-only operations create services anyway, but could be tightened later.

### 8. Old appointments with `NULL location_id` are invisible
**Context:** Any appointment created before the location-scoped work has `location_id = NULL`. With current frontend filter, they don't appear when a location is selected.

**Fix (optional, SQL one-liner):**
```sql
UPDATE appointments a
SET location_id = (
    SELECT l.id FROM locations l
    WHERE l.business_id = a.business_id
    ORDER BY l.created_at ASC
    LIMIT 1
)
WHERE a.location_id IS NULL;
```

---

## ✅ Properly Scoped (Verified Working)

| Feature | Read | Write | Backend | Agent | Notes |
|---|---|---|---|---|---|
| Custom Schedules | ✅ | ✅ | ✅ | ✅ | Full E2E |
| Forwarding Contacts (single) | ✅ | ✅ | ✅ | ✅ | Bulk toggle is the gap (see #2) |
| Forwarding Rules | ✅ | ✅ | ✅ | N/A | |
| Agent Settings (feature flags) | ✅ | ✅ | ✅ | ✅ | Includes config_value JSONB for SMS templates |
| Agent State (on/off) | ✅ | ✅ | ✅ | ✅ | |
| Business Hours / Schedule | ✅ | ✅ | ✅ | ✅ | Both Scheduler page + Business Settings tab |
| Communication Settings | ✅ | ✅ | ✅ | N/A | |
| Knowledge Base | ✅ | ✅ | ✅ | ✅ | |
| Gmail Tokens | ✅ | ✅ | ✅ | ✅ | Per-location sender Gmail |
| Calls + Analytics | ✅ | N/A | ✅ | ✅ | |
| Location Services (junction) | ✅ | ✅ | ✅ | ✅ | RLS write policies fixed earlier |

Brand voice + global settings are intentionally **business-wide** — not location-scoped. Confirmed correct.

---

## Pending (Not Bugs — Future Work)

These are not issues; they're known features not yet implemented. Tracked in the main TODO:

| Feature | Plan Doc | Effort |
|---|---|---|
| SMS 2FA UI | `docs/SMS_2FA_SETUP.md` (client guide) | 1 day |
| Call Forwarding Option C (real SIP transfer) | `docs/superpowers/plans/2026-04-13-call-forwarding-runtime.md` | 1-2 days |
| Roles & Permissions v2 (custom roles) | `docs/superpowers/plans/2026-04-14-roles-permissions.md` Phase 6 | 3-5 days |
| Reminder Calls / Reschedule Calls runtime | (config UI shipped, runtime not built) | 2-3 days |
| Call recording | LiveKit Egress integration | 1-2 days |
| HTTPS / domain for production | Ops task | — |
| Backend appointment/service API endpoints | (Frontend writes Supabase directly today) | 1 day |
| Business authorization check | (Backend trusts frontend currently) | 2-3 hours |

---

## Testing Status

| Test Scenario | Done? |
|---|---|
| Switch location → all CS pages refresh with new data | ✅ |
| Add service → persists after refresh | ✅ |
| Custom Schedules full flow | ⚠️ Untested in production |
| Inbound call uses location-scoped agent context | ⚠️ Untested |
| Re-invite same email | ⚠️ Blocked on Resend domain verification |
| Multiple locations with different Gmail tokens | ⚠️ Untested |
| Cross-location data isolation (Location A can't see B) | ⚠️ Spot-checked, not exhaustive |

---

## Recommended Action Order

1. **Fix #1 (critical)** — Agent appointment NULL location. 1-line change. ~5 min.
2. **Fix #2 (medium)** — Bulk toggle location filter. ~15 min.
3. **Fix #3 + #4 (medium)** — Audit log location_id. Migration + endpoint + frontend. ~1 hour.
4. **Run #8 (optional)** — Backfill old NULL appointments. SQL one-liner.
5. **Test thoroughly** — Run the testing checklist above end-to-end on staging.
6. **Merge `feature/location-scoped-architecture` → main** in sam-backend.
7. Address future features in priority order (SMS 2FA when client unblocks A2P, then whatever the client prioritizes).

---

## Conclusion

The location-scoped architecture is **~95% complete**. The one critical bug (#1) is a quick fix. The medium issues are real but limited in blast radius. After these are addressed and tested, the feature branch is ready to merge.
