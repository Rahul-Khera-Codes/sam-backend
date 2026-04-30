# Location-Scoped Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the entire platform from business-scoped data display to location-scoped — every screen, API endpoint, and agent tool filters by the user's currently selected location. No fallback to business-wide defaults; each location owns its data explicitly.

**Architecture:** Every table that currently keys on `business_id` alone gains a `location_id` column. Backend endpoints require `location_id` for all location-scoped reads/writes. When a new location is created, business-wide data is **copied** as the location's initial seed (one-time copy, not a live reference). The frontend passes `selectedLocationId` (already stored in localStorage via the `useSelectedLocation` hook) to every API call. If a location has no data configured, the UI shows an actionable empty state — never silently borrows data from another source.

**Tech Stack:** FastAPI (Python), Supabase (PostgreSQL), React/TypeScript, LiveKit Agents, Twilio SIP

---

## Design Principle: No Silent Fallbacks

**The old pattern (REMOVED):**
> location-specific → business-wide default

**The new pattern:**
> Each location owns its own data. Period.

| Scenario | Old Approach | New Approach |
|---|---|---|
| No hours set for location | Silently show business hours | Empty state: "No hours configured for [Location]. Set up hours." |
| No agent settings for location | Silently show business defaults | Auto-initialized at location creation; empty state if somehow missing |
| No services mapped to location | Silently show all business services | Empty state: "No services assigned to [Location]. Assign services." |
| No KB entries for location | Silently show business KB | Empty state: "No knowledge base entries for [Location]." |
| Agent call to unconfigured location | Use business defaults (wrong data) | Agent: "This location isn't fully configured yet. Let me transfer you." |

**Why this matters:**
- Admins always see exactly what belongs to their location — no confusion
- Editing Location A data never accidentally affects Location B
- Debugging is straightforward — what you see is what's stored
- The agent never gives wrong hours/services because it silently used another location's data

**How locations get initial data:**
- When a location is created, a **seed function** copies current business-wide data (hours, settings, services, KB) into location-specific rows
- This is a one-time copy. From that point, the location's data is independent
- Existing locations (created before this migration) get seeded via a one-time backfill migration

---

## What Stays Business-Wide (NOT location-scoped)

**Global Settings** remain singular for all locations — they are NOT affected by this plan:

| Setting | Table/Field | Why Business-Wide |
|---|---|---|
| Language | `businesses.language` | Consistent brand language across all locations |
| Country/Region | `businesses.country` | Business-level identity |
| Date Format | `businesses.date_format` | Consistent display across the brand |
| Time Format | `businesses.time_format` | Consistent display across the brand |
| Business Name | `businesses.name` | One business, many locations |
| Business Type | `businesses.type` | Business-level identity |
| Brand Voice | `brand_voice_profiles` | Brand identity — tone, style, vocabulary, "do not say" phrases. Lives inside Global Settings as a tab alongside Language & Region. Same voice across all locations. |

**DO NOT** add `location_id` to the `businesses` table or `brand_voice_profiles` table.

**Frontend:** The "Global Settings" page (`/dashboard/settings/global`) — including its Brand Voice tab — and the standalone Brand Voice page (`/dashboard/settings/brand-voice`) continue to work exactly as they do today. No changes needed.

**Agent:** `_format_brand_voice()` in `prompt_builder.py` continues to read from `brand_voice_profiles` filtered by `business_id` only (no location filter). The brand voice applies to all locations equally.

---

## Current State Summary

### What's Already Location-Scoped (done)
- `appointments` table — has `location_id` column
- `calls` table — has `location_id` column
- `forwarding_contacts` table — has `location_id` column
- `business_phone_numbers` table — has `location_id` column
- Agent context — resolves location from dispatch rule metadata
- Agent appointment tools — `_apply_location_scope()` filters by `location_id`

### What's Still Business-Scoped (This Plan Fixes)
| Table | Current Key | Needs `location_id` |
|---|---|---|
| `business_hours` | `(business_id, day_of_week)` | Yes |
| `agent_settings` | `(business_id, feature_key)` | Yes |
| `agent_state` | `(business_id)` | Yes |
| `communication_settings` | `(business_id, channel, type)` | Yes |
| `services` | `(business_id)` | Yes — via junction table `location_services` |
| `forwarding_rules` | `(business_id)` | Yes |
| `knowledge_base` | `(business_id)` | Yes |

### Frontend Location Mechanism (Already Exists)
- **Hook:** `useSelectedLocation()` in `src/hooks/useLocation.ts`
- **Storage:** `localStorage.getItem("selectedLocationId")`
- **Returns:** `{ selectedLocationId, location, selectLocation, clearLocation }`
- **Business ID:** `useBusiness()` hook returns `businessId` from `roles[0]?.business_id`

### Backend API Pattern (Current)
All endpoints accept `?business_id=<uuid>` as query param. None currently accept `location_id`.

### Supabase Direct Query Pattern (Current)
Frontend hooks use `.eq("business_id", businessId)`. None filter by `location_id`.

---

## File Structure

### Database Migrations (new files)
- `supabase/migrations/20260410000000_location_scope_business_hours.sql` — add `location_id` to `business_hours`
- `supabase/migrations/20260410000001_location_scope_agent_settings.sql` — add `location_id` to `agent_settings` + `agent_state`
- `supabase/migrations/20260410000002_location_scope_communication_settings.sql` — add `location_id` to `communication_settings`
- `supabase/migrations/20260410000003_location_services.sql` — create `location_services` junction table
- `supabase/migrations/20260410000004_location_scope_forwarding_rules.sql` — add `location_id` to `forwarding_rules`
- `supabase/migrations/20260410000005_location_scope_knowledge_base.sql` — add `location_id` to `knowledge_base`
- `supabase/migrations/20260410000006_backfill_existing_locations.sql` — seed existing locations with copies of business-wide data

### Backend Files (modify)
- `backend/app/routers/calls.py` — add `location_id` param to `GET /calls`, `GET /calls/recent-activity`
- `backend/app/routers/analytics.py` — add `location_id` param to all 3 analytics endpoints
- `backend/app/routers/settings.py` — add `location_id` param to all settings endpoints; read/write location-specific only
- `backend/app/routers/forwarding.py` — add `location_id` filtering to contacts + rules
- `backend/app/routers/phone_numbers.py` — no change needed (already location-scoped)

### Backend Files (new)
- `backend/app/services/location_seed_service.py` — function to copy business-wide data into a new location

### Agent Files (modify)
- `agent/prompt_builder.py` — fetch location-specific hours, knowledge base, services (brand voice stays business-wide)
- `agent/supabase_helpers.py` — add location-scoped fetch functions (no fallback — return empty if not found)
- `agent/agent.py` — pass `location_id` to feature flag checks; handle "unconfigured location" gracefully

### Frontend Files (modify) — in `ai-employees-app/`
- `src/hooks/useAppointments.ts` — add `location_id` filter
- `src/hooks/useServices.ts` — add `location_id` filter via `location_services`
- `src/lib/voiceAgentApi.ts` — add `location_id` param to every API function
- `src/pages/dashboard/customer-service/AgentPerformance.tsx` — pass `location_id`
- `src/pages/dashboard/customer-service/CallRecordings.tsx` — pass `location_id`
- `src/pages/dashboard/customer-service/Scheduler.tsx` — pass `location_id`
- `src/pages/dashboard/customer-service/AgentSettings.tsx` — pass `location_id`
- `src/pages/dashboard/customer-service/CallForwarding.tsx` — pass `location_id`
- `src/pages/dashboard/BusinessSettings.tsx` — remove Locations tab (moved to sidebar)
- `src/components/layout/Sidebar.tsx` — add Locations under Account Settings
- `src/pages/dashboard/Calendar.tsx` — pass `location_id` to appointment queries

### Frontend Files (new) — in `ai-employees-app/`
- `src/pages/dashboard/Locations.tsx` — standalone Locations page
- `src/components/business/LocationServicesTab.tsx` — toggle services per location
- `src/components/ui/LocationEmptyState.tsx` — reusable empty state component for unconfigured location data

---

## Phase 1: Database Migrations

### Task 1: Add `location_id` to `business_hours`

**Files:**
- Create: `supabase/migrations/20260410000000_location_scope_business_hours.sql`

**Context:** Currently `business_hours` has unique constraint on `(business_id, day_of_week)`. We need to change this to `(location_id, day_of_week)` for location-scoped hours. The old business-wide rows (NULL `location_id`) remain for the seed/copy process but are NOT used at runtime.

- [ ] **Step 1: Write the migration SQL**

**IMPORTANT — Supabase PostgREST Upsert Limitation:**
PostgREST's `on_conflict` parameter only works with plain column-based unique constraints, NOT with functional indexes (COALESCE). All unique constraints in this plan use plain columns so upsert continues to work.

For tables where `location_id` can be NULL (legacy business-wide rows), we create TWO unique constraints:
1. One for rows WITH `location_id` (partial index: `WHERE location_id IS NOT NULL`)
2. One for rows WITHOUT `location_id` (partial index: `WHERE location_id IS NULL`)

This avoids the COALESCE issue entirely.

```sql
-- Add location_id column to business_hours
ALTER TABLE business_hours
ADD COLUMN location_id UUID REFERENCES locations(id) ON DELETE CASCADE;

-- Drop the old unique constraint
ALTER TABLE business_hours
DROP CONSTRAINT IF EXISTS business_hours_business_id_day_of_week_key;

-- Two partial unique indexes: one for location-scoped, one for legacy business-wide
CREATE UNIQUE INDEX business_hours_loc_day_unique
ON business_hours (business_id, location_id, day_of_week)
WHERE location_id IS NOT NULL;

CREATE UNIQUE INDEX business_hours_biz_day_legacy_unique
ON business_hours (business_id, day_of_week)
WHERE location_id IS NULL;

-- Index for location-scoped lookups
CREATE INDEX IF NOT EXISTS idx_business_hours_location_id
ON business_hours (location_id) WHERE location_id IS NOT NULL;
```

- [ ] **Step 2: Run migration in Supabase SQL editor**

Verify with:
```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'business_hours' AND column_name = 'location_id';
```
Expected: one row with `data_type = 'uuid'`, `is_nullable = 'YES'`

---

### Task 2: Add `location_id` to `agent_settings` and `agent_state`

**Files:**
- Create: `supabase/migrations/20260410000001_location_scope_agent_settings.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- ── agent_settings ──────────────────────────────────────────────────────────

ALTER TABLE agent_settings
ADD COLUMN location_id UUID REFERENCES locations(id) ON DELETE CASCADE;

-- Drop old unique constraint
ALTER TABLE agent_settings
DROP CONSTRAINT IF EXISTS agent_settings_business_id_feature_key_key;

-- Two partial unique indexes (same pattern as business_hours)
CREATE UNIQUE INDEX agent_settings_loc_feature_unique
ON agent_settings (business_id, location_id, feature_key)
WHERE location_id IS NOT NULL;

CREATE UNIQUE INDEX agent_settings_biz_feature_legacy_unique
ON agent_settings (business_id, feature_key)
WHERE location_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_agent_settings_location_id
ON agent_settings (location_id) WHERE location_id IS NOT NULL;

-- ── agent_state ─────────────────────────────────────────────────────────────

ALTER TABLE agent_state
ADD COLUMN location_id UUID REFERENCES locations(id) ON DELETE CASCADE;

-- Drop old unique constraint
ALTER TABLE agent_state
DROP CONSTRAINT IF EXISTS agent_state_business_id_key;

-- Two partial unique indexes
CREATE UNIQUE INDEX agent_state_loc_unique
ON agent_state (business_id, location_id)
WHERE location_id IS NOT NULL;

CREATE UNIQUE INDEX agent_state_biz_legacy_unique
ON agent_state (business_id)
WHERE location_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_agent_state_location_id
ON agent_state (location_id) WHERE location_id IS NOT NULL;
```

- [ ] **Step 2: Run migration in Supabase SQL editor**

Verify both tables have the new column.

---

### Task 3: Add `location_id` to `communication_settings`

**Files:**
- Create: `supabase/migrations/20260410000002_location_scope_communication_settings.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
ALTER TABLE communication_settings
ADD COLUMN location_id UUID REFERENCES locations(id) ON DELETE CASCADE;

ALTER TABLE communication_settings
DROP CONSTRAINT IF EXISTS communication_settings_business_id_channel_type_key;

-- Two partial unique indexes
CREATE UNIQUE INDEX communication_settings_loc_channel_type_unique
ON communication_settings (business_id, location_id, channel, type)
WHERE location_id IS NOT NULL;

CREATE UNIQUE INDEX communication_settings_biz_channel_type_legacy_unique
ON communication_settings (business_id, channel, type)
WHERE location_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_communication_settings_location_id
ON communication_settings (location_id) WHERE location_id IS NOT NULL;
```

- [ ] **Step 2: Run migration in Supabase SQL editor**

---

### Task 4: Create `location_services` junction table

**Files:**
- Create: `supabase/migrations/20260410000003_location_services.sql`

**Context:** Services stay in the `services` table (business-wide catalog). The junction table `location_services` maps which services are available at each location. If a location has NO entries in `location_services`, the UI shows an empty state prompting the admin to assign services — it does NOT silently show all business services.

- [ ] **Step 1: Write the migration SQL**

```sql
CREATE TABLE location_services (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    location_id UUID NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (location_id, service_id)
);

CREATE INDEX idx_location_services_location ON location_services (location_id);
CREATE INDEX idx_location_services_service ON location_services (service_id);
CREATE INDEX idx_location_services_business ON location_services (business_id);

-- RLS
ALTER TABLE location_services ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Members can view own business location_services"
ON location_services FOR SELECT
USING (
    business_id IN (
        SELECT business_id FROM user_roles WHERE user_id = auth.uid()
    )
);

CREATE POLICY "Service role full access on location_services"
ON location_services FOR ALL
USING (auth.role() = 'service_role');
```

- [ ] **Step 2: Run migration in Supabase SQL editor**

---

### Task 5: Add `location_id` to `forwarding_rules`

**Files:**
- Create: `supabase/migrations/20260410000004_location_scope_forwarding_rules.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
ALTER TABLE forwarding_rules
ADD COLUMN location_id UUID REFERENCES locations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_forwarding_rules_location_id
ON forwarding_rules (location_id) WHERE location_id IS NOT NULL;
```

- [ ] **Step 2: Run migration in Supabase SQL editor**

---

### Task 6: Add `location_id` to `knowledge_base`

**Files:**
- Create: `supabase/migrations/20260410000005_location_scope_knowledge_base.sql`

**Note:** `brand_voice_profiles` is NOT changed here — it stays business-wide (part of Global Settings).

- [ ] **Step 1: Write knowledge_base migration**

```sql
ALTER TABLE knowledge_base
ADD COLUMN location_id UUID REFERENCES locations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_knowledge_base_location_id
ON knowledge_base (location_id) WHERE location_id IS NOT NULL;
```

- [ ] **Step 2: Run migration in Supabase SQL editor**

---

### Task 7: Backfill Existing Locations with Business Data

**Files:**
- Create: `supabase/migrations/20260410000006_backfill_existing_locations.sql`

**Context:** Existing locations were created before location-scoping existed. They have no location-specific hours, settings, services, etc. This migration copies the current business-wide data into location-specific rows for every existing location. After this, each location has its own independent data.

- [ ] **Step 1: Write the backfill migration**

```sql
-- ══════════════════════════════════════════════════════════════════════════════
-- BACKFILL: Copy business-wide data into location-specific rows for all
-- existing locations. This is a one-time seed so every location has
-- its own independent data from day one.
-- ══════════════════════════════════════════════════════════════════════════════

-- ── business_hours → per-location hours ─────────────────────────────────────
-- For each location that doesn't already have hours, copy from business-wide rows
INSERT INTO business_hours (business_id, location_id, day_of_week, is_open, open_time, close_time)
SELECT bh.business_id, l.id, bh.day_of_week, bh.is_open, bh.open_time, bh.close_time
FROM business_hours bh
JOIN locations l ON l.business_id = bh.business_id
WHERE bh.location_id IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM business_hours bh2
      WHERE bh2.business_id = bh.business_id
        AND bh2.location_id = l.id
        AND bh2.day_of_week = bh.day_of_week
  );

-- ── agent_settings → per-location settings ──────────────────────────────────
INSERT INTO agent_settings (business_id, location_id, feature_key, is_enabled, config_value, updated_by)
SELECT a.business_id, l.id, a.feature_key, a.is_enabled, a.config_value, a.updated_by
FROM agent_settings a
JOIN locations l ON l.business_id = a.business_id
WHERE a.location_id IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM agent_settings a2
      WHERE a2.business_id = a.business_id
        AND a2.location_id = l.id
        AND a2.feature_key = a.feature_key
  );

-- ── agent_state → per-location state ────────────────────────────────────────
INSERT INTO agent_state (business_id, location_id, is_active, toggled_at, toggled_by)
SELECT a.business_id, l.id, a.is_active, a.toggled_at, a.toggled_by
FROM agent_state a
JOIN locations l ON l.business_id = a.business_id
WHERE a.location_id IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM agent_state a2
      WHERE a2.business_id = a.business_id
        AND a2.location_id = l.id
  );

-- ── communication_settings → per-location comm settings ─────────────────────
INSERT INTO communication_settings (business_id, location_id, channel, type, is_enabled, days_offset, script, updated_by)
SELECT c.business_id, l.id, c.channel, c.type, c.is_enabled, c.days_offset, c.script, c.updated_by
FROM communication_settings c
JOIN locations l ON l.business_id = c.business_id
WHERE c.location_id IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM communication_settings c2
      WHERE c2.business_id = c.business_id
        AND c2.location_id = l.id
        AND c2.channel = c.channel
        AND c2.type = c.type
  );

-- ── location_services → all active services assigned to all locations ───────
INSERT INTO location_services (location_id, service_id, business_id, is_active)
SELECT l.id, s.id, s.business_id, true
FROM services s
JOIN locations l ON l.business_id = s.business_id
WHERE s.is_active = true
  AND NOT EXISTS (
      SELECT 1 FROM location_services ls
      WHERE ls.location_id = l.id
        AND ls.service_id = s.id
  );

-- ── knowledge_base → per-location KB entries ────────────────────────────────
INSERT INTO knowledge_base (business_id, location_id, title, text_content, content_type)
SELECT kb.business_id, l.id, kb.title, kb.text_content, kb.content_type
FROM knowledge_base kb
JOIN locations l ON l.business_id = kb.business_id
WHERE kb.location_id IS NULL
  AND kb.content_type = 'text'
  AND NOT EXISTS (
      SELECT 1 FROM knowledge_base kb2
      WHERE kb2.business_id = kb.business_id
        AND kb2.location_id = l.id
        AND kb2.title = kb.title
  );

-- NOTE: brand_voice_profiles is NOT backfilled — it stays business-wide (Global Settings).
```

**IMPORTANT:** Review the output row counts after running. For the test business "Mirage Banquets" (1 location), you should see rows copied for each table.

- [ ] **Step 2: Run migration in Supabase SQL editor**

Verify:
```sql
-- Check that the Mirage location now has its own hours
SELECT * FROM business_hours WHERE location_id IS NOT NULL;

-- Check that agent_settings were copied
SELECT * FROM agent_settings WHERE location_id IS NOT NULL;

-- Check location_services
SELECT * FROM location_services;
```

---

## Phase 2: Backend — Location Seed Service

### Task 8: Create Location Seed Service

**Files:**
- Create: `backend/app/services/location_seed_service.py`

**Context:** When a new location is created (via onboarding or the Locations page), we need to copy business-wide data into location-specific rows. This is the same logic as the backfill migration but for a single new location at runtime.

- [ ] **Step 1: Create the seed service**

```python
"""
Location Seed Service
=====================
When a new location is created, copies business-wide data into
location-specific rows so the location starts fully configured.

This is a ONE-TIME copy. After seeding, the location's data is
independent — changes to one location don't affect another.
"""

import logging
from app.core.supabase import supabase_admin

logger = logging.getLogger(__name__)


async def seed_location_data(business_id: str, location_id: str) -> dict:
    """
    Copy business-wide defaults into location-specific rows for a newly
    created location. Returns a summary of what was seeded.

    Call this immediately after inserting a new row into the `locations` table.
    """
    # NOTE: brand_voice_profiles is NOT seeded — it stays business-wide (Global Settings).
    summary = {
        "business_hours": 0,
        "agent_settings": 0,
        "agent_state": 0,
        "communication_settings": 0,
        "location_services": 0,
        "knowledge_base": 0,
    }

    # ── business_hours ───────────────────────────────────────────────────
    try:
        bh = (
            supabase_admin.table("business_hours")
            .select("business_id, day_of_week, is_open, open_time, close_time")
            .eq("business_id", business_id)
            .is_("location_id", "null")
            .execute()
        )
        if bh.data:
            rows = [
                {**row, "location_id": location_id}
                for row in bh.data
            ]
            # Remove 'id' if present (let DB generate new ones)
            for row in rows:
                row.pop("id", None)
            supabase_admin.table("business_hours").insert(rows).execute()
            summary["business_hours"] = len(rows)
    except Exception as e:
        logger.warning("Seed business_hours failed: %s", e)

    # ── agent_settings ───────────────────────────────────────────────────
    try:
        asettings = (
            supabase_admin.table("agent_settings")
            .select("business_id, feature_key, is_enabled, config_value, updated_by")
            .eq("business_id", business_id)
            .is_("location_id", "null")
            .execute()
        )
        if asettings.data:
            rows = [
                {**row, "location_id": location_id}
                for row in asettings.data
            ]
            for row in rows:
                row.pop("id", None)
            supabase_admin.table("agent_settings").insert(rows).execute()
            summary["agent_settings"] = len(rows)
    except Exception as e:
        logger.warning("Seed agent_settings failed: %s", e)

    # ── agent_state ──────────────────────────────────────────────────────
    try:
        astate = (
            supabase_admin.table("agent_state")
            .select("business_id, is_active, toggled_at, toggled_by")
            .eq("business_id", business_id)
            .is_("location_id", "null")
            .execute()
        )
        if astate.data:
            row = {**astate.data[0], "location_id": location_id}
            row.pop("id", None)
            supabase_admin.table("agent_state").insert(row).execute()
            summary["agent_state"] = 1
        else:
            # No business-wide state — create a default "active" state
            supabase_admin.table("agent_state").insert({
                "business_id": business_id,
                "location_id": location_id,
                "is_active": True,
            }).execute()
            summary["agent_state"] = 1
    except Exception as e:
        logger.warning("Seed agent_state failed: %s", e)

    # ── communication_settings ───────────────────────────────────────────
    try:
        cs = (
            supabase_admin.table("communication_settings")
            .select("business_id, channel, type, is_enabled, days_offset, script, updated_by")
            .eq("business_id", business_id)
            .is_("location_id", "null")
            .execute()
        )
        if cs.data:
            rows = [
                {**row, "location_id": location_id}
                for row in cs.data
            ]
            for row in rows:
                row.pop("id", None)
            supabase_admin.table("communication_settings").insert(rows).execute()
            summary["communication_settings"] = len(rows)
    except Exception as e:
        logger.warning("Seed communication_settings failed: %s", e)

    # ── location_services (copy all active services) ─────────────────────
    try:
        services = (
            supabase_admin.table("services")
            .select("id")
            .eq("business_id", business_id)
            .eq("is_active", True)
            .execute()
        )
        if services.data:
            rows = [
                {
                    "location_id": location_id,
                    "service_id": svc["id"],
                    "business_id": business_id,
                    "is_active": True,
                }
                for svc in services.data
            ]
            supabase_admin.table("location_services").insert(rows).execute()
            summary["location_services"] = len(rows)
    except Exception as e:
        logger.warning("Seed location_services failed: %s", e)

    # ── knowledge_base ───────────────────────────────────────────────────
    try:
        kb = (
            supabase_admin.table("knowledge_base")
            .select("business_id, title, text_content, content_type")
            .eq("business_id", business_id)
            .eq("content_type", "text")
            .is_("location_id", "null")
            .execute()
        )
        if kb.data:
            rows = [
                {**row, "location_id": location_id}
                for row in kb.data
            ]
            for row in rows:
                row.pop("id", None)
            supabase_admin.table("knowledge_base").insert(rows).execute()
            summary["knowledge_base"] = len(rows)
    except Exception as e:
        logger.warning("Seed knowledge_base failed: %s", e)

    logger.info(
        "Location %s seeded from business %s: %s",
        location_id, business_id, summary,
    )
    return summary
```

- [ ] **Step 2: Wire seed into location creation**

The frontend creates locations via direct Supabase insert (`LocationsTab.tsx` and `Onboarding.tsx`). We need to call `seed_location_data` after location creation. Two options:

**Option A (recommended):** Add a backend endpoint `POST /locations/{location_id}/seed` that the frontend calls after creating a location.

**Option B:** Use a Supabase database trigger (function + trigger on `locations` INSERT). This is cleaner but harder to debug.

For Option A, add a new route. This can go in a new file or in an existing router. Simplest: add to `phone_numbers.py` or create a small `locations.py` router:

```python
# backend/app/routers/locations.py (NEW FILE — minimal)
import logging
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_user_id
from app.core.supabase import supabase_admin
from app.services import location_seed_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/locations", tags=["locations"])


@router.post("/{location_id}/seed")
async def seed_location(
    location_id: str,
    user_id: str = Depends(get_user_id),
):
    """
    Seed a newly created location with business-wide default data.
    Call this immediately after creating a location.
    """
    # Verify the location exists and user has access
    role_row = (
        supabase_admin.table("user_roles")
        .select("business_id, role")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not role_row.data:
        raise HTTPException(status_code=403, detail="User has no role assigned")

    business_id = role_row.data[0]["business_id"]

    loc = (
        supabase_admin.table("locations")
        .select("id")
        .eq("id", location_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not loc.data:
        raise HTTPException(status_code=404, detail="Location not found")

    summary = await location_seed_service.seed_location_data(business_id, location_id)
    return {"seeded": True, "summary": summary}
```

Register in `main.py`:
```python
from app.routers import locations  # ADD
app.include_router(locations.router)  # ADD
```

- [ ] **Step 3: Add `seedLocation` to frontend API**

In `voiceAgentApi.ts`:
```typescript
export async function seedLocation(token: string, locationId: string) {
  const response = await fetch(`${API_BASE}/locations/${locationId}/seed`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) throw new Error("Failed to seed location");
  return response.json();
}
```

Then call it in `LocationsTab.tsx` after successful location insert. Note: `LocationsTab` doesn't have a `token` variable — get it from auth context:
```typescript
import { seedLocation } from "@/lib/voiceAgentApi";
import { useAuth } from "@/contexts/AuthContext";

const { session } = useAuth();

// After: const { data } = await supabase.from("locations").insert({...}).select().single();
if (data && session?.access_token) {
  await seedLocation(session.access_token, data.id);
}
```

And in `Onboarding.tsx` after `createBusinessWithLocation`:
```typescript
import { seedLocation } from "@/lib/voiceAgentApi";
import { useAuth } from "@/contexts/AuthContext";

const { session } = useAuth();

// After: const result = await createBusinessWithLocation(businessData, data);
if (result && session?.access_token) {
  await seedLocation(session.access_token, result.location_id);
}
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/location_seed_service.py backend/app/routers/locations.py backend/app/main.py
git commit -m "feat: add location seed service to copy business defaults on location creation"
```

---

## Phase 3: Backend API — Location Filtering (No Fallback)

### Task 9: Add `location_id` to Calls Endpoints

**Files:**
- Modify: `backend/app/routers/calls.py`

- [ ] **Step 1: Update `GET /calls` to accept and filter by `location_id`**

```python
@router.get("", response_model=List[CallResponse])
async def list_calls(
    business_id: str,
    location_id: Optional[str] = None,
    status: Optional[str] = None,
    direction: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    query = (
        supabase_admin.table("calls")
        .select("*")
        .eq("business_id", business_id)
        .order("created_at", desc=True)
        .range((page - 1) * limit, page * limit - 1)
    )

    if location_id:
        query = query.eq("location_id", location_id)
    if status:
        query = query.eq("status", status)
    if direction:
        query = query.eq("direction", direction)
    if search:
        query = query.ilike("caller_name", f"%{search}%")

    result = query.execute()

    if result.data is None:
        raise HTTPException(status_code=500, detail="Failed to fetch calls")

    return result.data
```

- [ ] **Step 2: Update `GET /calls/recent-activity`**

Add `location_id: Optional[str] = None` parameter. Filter query when provided:
```python
    if location_id:
        query = query.eq("location_id", location_id)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/calls.py
git commit -m "feat: add location_id filter to calls endpoints"
```

---

### Task 10: Add `location_id` to Analytics Endpoints

**Files:**
- Modify: `backend/app/routers/analytics.py`

- [ ] **Step 1: Add `Optional` import and `location_id` param to all 3 endpoints**

Add to the top:
```python
from typing import Optional
```

For each of `get_summary`, `call_volume_trends`, `call_distribution`:
- Add `location_id: Optional[str] = None` to the function signature
- After building the base query with `.eq("business_id", business_id)`, add:
```python
    if location_id:
        query = query.eq("location_id", location_id)
```

Apply this to EVERY query in each function (e.g., `get_summary` has both a current-period and previous-period query — add the filter to both).

- [ ] **Step 2: Commit**

```bash
git add backend/app/routers/analytics.py
git commit -m "feat: add location_id filter to analytics endpoints"
```

---

### Task 11: Update Settings Endpoints — Location-Specific Only (No Fallback)

**Files:**
- Modify: `backend/app/routers/settings.py`
- Modify: `backend/app/schemas/settings.py`

**Context:** When `location_id` is provided, read/write ONLY that location's data. If none exists, return empty — the frontend shows an empty state. No merging with business defaults.

- [ ] **Step 1: Update `GET /settings/agent`**

```python
@router.get("/agent")
async def get_agent_settings(
    business_id: str,
    location_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    query = (
        supabase_admin.table("agent_settings")
        .select("*")
        .eq("business_id", business_id)
        .order("feature_key")
    )
    if location_id:
        query = query.eq("location_id", location_id)
    else:
        query = query.is_("location_id", "null")

    result = query.execute()

    return {
        "business_id": business_id,
        "location_id": location_id,
        "settings": result.data or [],
    }
```

- [ ] **Step 2: Update `PUT /settings/agent`**

```python
@router.put("/agent")
async def update_agent_settings(
    business_id: str,
    body: UpdateAgentSettingsRequest,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
):
    # Get current values for audit log
    current_query = (
        supabase_admin.table("agent_settings")
        .select("feature_key, is_enabled")
        .eq("business_id", business_id)
    )
    if location_id:
        current_query = current_query.eq("location_id", location_id)
    else:
        current_query = current_query.is_("location_id", "null")
    current = current_query.execute()
    current_map = {s["feature_key"]: s["is_enabled"] for s in (current.data or [])}

    audit_entries = []
    for setting in body.settings:
        row = {
            "business_id": business_id,
            "feature_key": setting.feature_key,
            "is_enabled": setting.is_enabled,
            "config_value": setting.config_value or {},
            "updated_by": user_id,
        }
        if location_id:
            row["location_id"] = location_id

        # Cannot use upsert with partial unique indexes — use SELECT + INSERT/UPDATE
        existing = current_query_copy = (
            supabase_admin.table("agent_settings")
            .select("id")
            .eq("business_id", business_id)
            .eq("feature_key", setting.feature_key)
        )
        if location_id:
            existing = existing.eq("location_id", location_id)
        else:
            existing = existing.is_("location_id", "null")
        existing_result = existing.limit(1).execute()

        if existing_result.data:
            supabase_admin.table("agent_settings").update(
                {"is_enabled": setting.is_enabled, "config_value": setting.config_value or {}, "updated_by": user_id}
            ).eq("id", existing_result.data[0]["id"]).execute()
        else:
            supabase_admin.table("agent_settings").insert(row).execute()

        old_val = current_map.get(setting.feature_key)
        if old_val != setting.is_enabled:
            audit_entries.append({
                "business_id": business_id,
                "feature_key": setting.feature_key,
                "old_value": old_val,
                "new_value": setting.is_enabled,
                "changed_by": user_id,
            })

    if audit_entries:
        supabase_admin.table("settings_audit_log").insert(audit_entries).execute()

    return {"success": True, "updated": len(body.settings)}
```

- [ ] **Step 3: Update agent state endpoints**

```python
@router.get("/agent/state", response_model=AgentStateResponse)
async def get_agent_state(
    business_id: str,
    location_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    query = (
        supabase_admin.table("agent_state")
        .select("*")
        .eq("business_id", business_id)
    )
    if location_id:
        query = query.eq("location_id", location_id)
    else:
        query = query.is_("location_id", "null")
    result = query.limit(1).execute()

    if not result.data:
        # No state found for this location — return inactive with a flag
        return {"business_id": business_id, "location_id": location_id, "is_active": False, "toggled_at": None}

    return result.data[0]


@router.put("/agent/state", response_model=AgentStateResponse)
async def toggle_agent_state(
    business_id: str,
    body: ToggleAgentStateRequest,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
):
    row = {
        "business_id": business_id,
        "is_active": body.is_active,
        "toggled_at": datetime.now(timezone.utc).isoformat(),
        "toggled_by": user_id,
    }
    if location_id:
        row["location_id"] = location_id

    # SELECT + INSERT/UPDATE instead of upsert (partial unique indexes)
    existing = supabase_admin.table("agent_state").select("id").eq("business_id", business_id)
    if location_id:
        existing = existing.eq("location_id", location_id)
    else:
        existing = existing.is_("location_id", "null")
    existing_result = existing.limit(1).execute()

    if existing_result.data:
        result = supabase_admin.table("agent_state").update(
            {"is_active": body.is_active, "toggled_at": row["toggled_at"], "toggled_by": user_id}
        ).eq("id", existing_result.data[0]["id"]).execute()
    else:
        result = supabase_admin.table("agent_state").insert(row).execute()

    return result.data[0]
```

- [ ] **Step 4: Update schedule endpoints**

```python
@router.get("/agent/schedule", response_model=AgentScheduleResponse)
async def get_agent_schedule(
    business_id: str,
    location_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    query = (
        supabase_admin.table("business_hours")
        .select("day_of_week, is_open, open_time, close_time")
        .eq("business_id", business_id)
    )
    if location_id:
        query = query.eq("location_id", location_id)
    else:
        query = query.is_("location_id", "null")

    result = query.execute()

    return {
        "business_id": business_id,
        "location_id": location_id,
        "schedule": _serialize_schedule_rows(result.data or []),
    }


@router.put("/agent/schedule", response_model=AgentScheduleResponse)
async def update_agent_schedule(
    business_id: str,
    body: UpdateAgentScheduleRequest,
    location_id: Optional[str] = None,
    user_id: str = Depends(get_user_id),
):
    seen_days = set()
    for item in body.schedule:
        day = item.day_of_week.lower()
        if day not in DAY_ORDER:
            raise HTTPException(status_code=400, detail=f"Invalid day_of_week: {item.day_of_week}")
        if day in seen_days:
            raise HTTPException(status_code=400, detail=f"Duplicate day_of_week: {item.day_of_week}")
        seen_days.add(day)
        if item.is_open and (not item.open_time or not item.close_time):
            raise HTTPException(
                status_code=400,
                detail=f"Open days must include both open_time and close_time: {item.day_of_week}",
            )

        row = {
            "business_id": business_id,
            "day_of_week": day,
            "is_open": item.is_open,
            "open_time": item.open_time if item.is_open else None,
            "close_time": item.close_time if item.is_open else None,
        }
        if location_id:
            row["location_id"] = location_id

        # SELECT + INSERT/UPDATE instead of upsert (partial unique indexes)
        existing = supabase_admin.table("business_hours").select("id").eq("business_id", business_id).eq("day_of_week", day)
        if location_id:
            existing = existing.eq("location_id", location_id)
        else:
            existing = existing.is_("location_id", "null")
        existing_result = existing.limit(1).execute()

        if existing_result.data:
            supabase_admin.table("business_hours").update({
                "is_open": row["is_open"], "open_time": row["open_time"], "close_time": row["close_time"],
            }).eq("id", existing_result.data[0]["id"]).execute()
        else:
            supabase_admin.table("business_hours").insert(row).execute()

    # Re-read
    read_query = (
        supabase_admin.table("business_hours")
        .select("day_of_week, is_open, open_time, close_time")
        .eq("business_id", business_id)
    )
    if location_id:
        read_query = read_query.eq("location_id", location_id)
    else:
        read_query = read_query.is_("location_id", "null")
    result = read_query.execute()

    return {
        "business_id": business_id,
        "location_id": location_id,
        "schedule": _serialize_schedule_rows(result.data or []),
    }
```

- [ ] **Step 5: Update communication settings endpoints**

Same pattern — add `location_id: Optional[str] = None` param, filter by it or filter `is_("location_id", "null")` when absent.

- [ ] **Step 6: Update schema response models**

In `backend/app/schemas/settings.py`:

```python
class AgentSettingsResponse(BaseModel):
    business_id: str
    location_id: Optional[str] = None
    settings: List[AgentSettingItem]

class AgentStateResponse(BaseModel):
    business_id: str
    location_id: Optional[str] = None
    is_active: bool
    toggled_at: Optional[datetime]

class AgentScheduleResponse(BaseModel):
    business_id: str
    location_id: Optional[str] = None
    schedule: List[AgentScheduleDayItem]
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/settings.py backend/app/schemas/settings.py
git commit -m "feat: location-scoped settings endpoints — no fallback, location data only"
```

---

### Task 12: Add `location_id` to Forwarding Endpoints

**Files:**
- Modify: `backend/app/routers/forwarding.py`
- Modify: `backend/app/schemas/settings.py`

- [ ] **Step 1: Update contacts and rules list endpoints**

Add `location_id: Optional[str] = None` to `list_contacts` and `list_rules`. Filter when provided:
```python
    if location_id:
        query = query.eq("location_id", location_id)
```

- [ ] **Step 2: Add `location_id` to `CreateForwardingRuleRequest` and `ForwardingRuleResponse`**

In schemas:
```python
class CreateForwardingRuleRequest(BaseModel):
    name: str
    condition_type: str
    condition_value: Optional[Dict[str, Any]] = {}
    action: Optional[Dict[str, Any]] = {}
    priority_order: int = 0
    location_id: Optional[str] = None

class ForwardingRuleResponse(BaseModel):
    id: str
    business_id: str
    location_id: Optional[str] = None
    # ... rest unchanged
```

Update `create_rule` to pass `body.location_id`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/forwarding.py backend/app/schemas/settings.py
git commit -m "feat: add location_id filtering to forwarding endpoints"
```

---

## Phase 4: Agent — Location-Specific Data (No Fallback)

### Task 13: Add Location-Scoped Fetch Functions to Agent

**Files:**
- Modify: `agent/supabase_helpers.py`

**Context:** The agent fetches hours, services, settings for the called location. With no fallback, if a location has no data, these return empty results — and the agent handles it gracefully.

- [ ] **Step 1: Add location-specific business hours fetch**

```python
def _fetch_business_hours_for_location(
    supabase,
    business_id: str,
    location_id: str | None,
) -> list[dict]:
    """Fetch business hours for a specific location. Returns empty if none configured."""
    if not supabase or not business_id:
        return []
    try:
        query = (
            supabase.table("business_hours")
            .select("day_of_week, open_time, close_time, is_open")
            .eq("business_id", business_id)
        )
        if location_id:
            query = query.eq("location_id", location_id)
        else:
            query = query.is_("location_id", "null")
        r = query.execute()
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch business hours: %s", e)
        return []
```

- [ ] **Step 2: Add location-specific feature flag check**

```python
def _is_feature_enabled_for_location(
    supabase,
    business_id: str,
    location_id: str | None,
    feature_key: str,
    default: bool = True,
) -> bool:
    """Check feature flag for a specific location. No fallback to business level."""
    if not supabase or not business_id:
        return default
    try:
        query = (
            supabase.table("agent_settings")
            .select("is_enabled")
            .eq("business_id", business_id)
            .eq("feature_key", feature_key)
        )
        if location_id:
            query = query.eq("location_id", location_id)
        else:
            query = query.is_("location_id", "null")
        r = query.limit(1).execute()
        data = getattr(r, "data", None) or []
        if data:
            return bool(data[0].get("is_enabled", default))
    except Exception as e:
        logger.warning("Could not check feature flag %s: %s", feature_key, e)
    return default
```

- [ ] **Step 3: Add location-specific services fetch**

```python
def _fetch_services_for_location(
    supabase,
    business_id: str,
    location_id: str | None,
) -> list[dict]:
    """Fetch services mapped to a location via location_services. Returns empty if none mapped."""
    if not supabase or not business_id:
        return []

    if location_id:
        try:
            r = (
                supabase.table("location_services")
                .select("service_id")
                .eq("location_id", location_id)
                .eq("is_active", True)
                .execute()
            )
            service_ids = [row["service_id"] for row in (getattr(r, "data", None) or [])]
            if not service_ids:
                return []  # No services mapped — return empty, not all business services
            sr = (
                supabase.table("services")
                .select("id, name, description, duration_minutes, price")
                .eq("business_id", business_id)
                .eq("is_active", True)
                .in_("id", service_ids)
                .execute()
            )
            return getattr(sr, "data", None) or []
        except Exception as e:
            logger.warning("Failed to fetch location services: %s", e)
            return []

    # No location_id — return all business services (legacy web call without location)
    return _fetch_services(supabase, business_id)
```

- [ ] **Step 4: Add location-specific knowledge base fetch**

**Note:** Brand voice is NOT location-scoped — it stays business-wide (Global Settings). The existing `_fetch_brand_voice()` in `prompt_builder.py` is unchanged.

```python
def _fetch_knowledge_base_for_location(
    supabase,
    business_id: str,
    location_id: str | None,
) -> list[dict]:
    """Fetch KB entries for a specific location only."""
    if not supabase or not business_id:
        return []
    try:
        query = (
            supabase.table("knowledge_base")
            .select("title, text_content")
            .eq("business_id", business_id)
            .eq("content_type", "text")
        )
        if location_id:
            query = query.eq("location_id", location_id)
        else:
            query = query.is_("location_id", "null")
        r = query.execute()
        return getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch knowledge base: %s", e)
        return []
```

- [ ] **Step 5: Commit**

```bash
git add agent/supabase_helpers.py
git commit -m "feat: add location-scoped agent data fetches — no fallback"
```

---

### Task 14: Update Prompt Builder to Use Location-Scoped Fetches

**Files:**
- Modify: `agent/prompt_builder.py`

- [ ] **Step 1: Update imports**

Add the new location-scoped imports (brand voice is NOT here — it stays business-wide):
```python
from supabase_helpers import (
    _get_supabase,
    _fetch_business,
    _fetch_location,
    _fetch_locations,
    _fetch_services_for_location,
    _fetch_staff_with_ids,
    _fetch_business_hours_for_location,
    _fetch_knowledge_base_for_location,
)
```

- [ ] **Step 2: Update `build_instructions()` to call location-scoped functions**

Replace the fetch calls in `build_instructions()`:

```python
    # Replace these lines:
    #   biz_hours = _fetch_business_hours(supabase, business_id)
    #   services = _fetch_services(supabase, business_id)
    #   brand = _fetch_brand_voice(supabase, business_id)
    #   kb_entries = _fetch_knowledge_base(supabase, business_id)
    # With:
    biz_hours    = _fetch_business_hours_for_location(supabase, business_id, location_id) if business_id else []
    hours_block  = _format_business_hours(biz_hours)

    services       = _fetch_services_for_location(supabase, business_id, location_id) if business_id else []
    services_block = _format_services_for_prompt(services)

    # Brand voice stays BUSINESS-WIDE — do NOT change this line:
    brand       = _fetch_brand_voice(supabase, business_id) if business_id else None
    brand_block = _format_brand_voice(brand) if brand else ""

    kb_entries = _fetch_knowledge_base_for_location(supabase, business_id, location_id) if business_id else []
    kb_block   = _format_knowledge_base(kb_entries)
```

Remove the now-unused local `_fetch_business_hours()` and `_fetch_knowledge_base()` functions from `prompt_builder.py` since we're importing the location-aware versions from `supabase_helpers`. Keep `_fetch_brand_voice()` — it remains business-wide.

- [ ] **Step 3: Commit**

```bash
git add agent/prompt_builder.py
git commit -m "feat: prompt builder uses location-scoped data fetches"
```

---

### Task 15: Update Agent Feature Flag Checks + Unconfigured Location Handling

**Files:**
- Modify: `agent/agent.py`

- [ ] **Step 1: Update imports**

```python
from supabase_helpers import (
    # ... existing imports ...
    _is_feature_enabled_for_location,
)
```

- [ ] **Step 2: Replace `_is_feature_enabled` calls with `_is_feature_enabled_for_location`**

In `book_appointment` (SMS check):
```python
                if client_phone and _is_feature_enabled_for_location(
                    self._supabase, self._business_id, self._location_id,
                    "send_texts_during_after_calls",
                ):
```

In `_finalize_call` (missed-call SMS):
```python
        if _is_feature_enabled_for_location(supabase, business_id, location_id, "missed_call_text_back"):
```

- [ ] **Step 3: Add unconfigured location handling**

In the `voice_agent()` function, after building instructions and loading data, add a check:

```python
    if business_id and location_id:
        # Check if location has basic configuration (hours + services)
        if not services:
            logger.warning(
                "Location %s has no services configured — agent will inform caller",
                location_id,
            )
        if not biz_hours:
            logger.warning(
                "Location %s has no business hours configured",
                location_id,
            )
```

The agent's system prompt already says "If you cannot help with something, offer to transfer the caller to a human agent." With no services returned, the `get_services` tool will return "No services are currently configured" and the agent will naturally suggest contacting staff directly.

- [ ] **Step 4: Commit**

```bash
git add agent/agent.py
git commit -m "feat: agent uses location-scoped feature flags, handles unconfigured locations"
```

---

## Phase 5: Frontend — Pass `location_id` Everywhere

### Task 16: Update `voiceAgentApi.ts`

**Files:**
- Modify: `ai-employees-app/src/lib/voiceAgentApi.ts`

**Context:** Every API function passes `business_id`. Add optional `locationId` parameter to each. The pattern is identical across all functions.

- [ ] **Step 1: Add `locationId` to all API functions**

For every function that takes `businessId` and builds a URLSearchParams, add:
```typescript
  locationId?: string | null
```
to the signature, and:
```typescript
  if (locationId) params.set("location_id", locationId);
```
after setting `business_id`.

**Functions to update (all follow same pattern):**
- `getAnalyticsSummary`
- `getCallVolumeTrends`
- `getCallDistribution`
- `getCalls` (add `locationId` to the options object)
- `getRecentActivity`
- `getAgentSettings`
- `updateAgentSettings`
- `resetAgentSettings`
- `getAgentState`
- `updateAgentState`
- `getAgentSchedule`
- `updateAgentSchedule`
- `getCommunicationSettings`
- `getForwardingContacts`
- `getForwardingRules`

Also add the `seedLocation` function:
```typescript
export async function seedLocation(token: string, locationId: string) {
  const response = await fetch(`${API_BASE}/locations/${locationId}/seed`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  });
  if (!response.ok) throw new Error("Failed to seed location");
  return response.json();
}
```

- [ ] **Step 2: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/lib/voiceAgentApi.ts
git commit -m "feat: add locationId parameter to all API functions"
```

---

### Task 17: Update Frontend Hooks to Filter by Location

**Files:**
- Modify: `ai-employees-app/src/hooks/useAppointments.ts`
- Modify: `ai-employees-app/src/hooks/useServices.ts`

- [ ] **Step 1: Update `useAppointments.ts`**

```typescript
import { useSelectedLocation } from "./useLocation";

// Inside the hook:
const { selectedLocationId } = useSelectedLocation();

// In fetchAppointments, add filter:
let query = supabase
  .from("appointments")
  .select("*")
  .eq("business_id", businessId)
  .neq("status", "cancelled")
  .order("appointment_date", { ascending: true });

if (selectedLocationId) {
  query = query.eq("location_id", selectedLocationId);
}

const { data, error } = await query;
```

Add `selectedLocationId` to the `useCallback` dependency for `fetchAppointments` (currently depends on `businessId`). Since the `useEffect` depends on `[fetchAppointments]`, adding `selectedLocationId` to the callback's deps will automatically trigger a refetch when location changes.

- [ ] **Step 2: Update `useServices.ts`**

```typescript
import { useSelectedLocation } from "./useLocation";

const { selectedLocationId } = useSelectedLocation();

// In fetchServices:
if (selectedLocationId) {
  // Fetch only services mapped to this location
  const { data: locServices } = await supabase
    .from("location_services")
    .select("service_id")
    .eq("location_id", selectedLocationId)
    .eq("is_active", true);

  const serviceIds = (locServices || []).map((r) => r.service_id);
  if (serviceIds.length === 0) {
    setServices([]);
    return; // No services mapped — show empty state
  }

  const { data } = await supabase
    .from("services")
    .select("*")
    .eq("business_id", businessId)
    .in("id", serviceIds)
    .order("name");
  setServices(data || []);
} else {
  // No location selected — show all business services
  const { data } = await supabase
    .from("services")
    .select("*")
    .eq("business_id", businessId)
    .order("name");
  setServices(data || []);
}
```

- [ ] **Step 3: Commit**

```bash
git add src/hooks/useAppointments.ts src/hooks/useServices.ts
git commit -m "feat: filter appointments and services by selected location"
```

---

### Task 18: Create Reusable Location Empty State Component

**Files:**
- Create: `ai-employees-app/src/components/ui/LocationEmptyState.tsx`

**Context:** When a location has no data for a section, we show an actionable empty state instead of silently showing wrong data.

- [ ] **Step 1: Create the component**

```typescript
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface LocationEmptyStateProps {
  locationName: string;
  dataType: string;       // e.g. "business hours", "services", "agent settings"
  actionLabel?: string;   // e.g. "Set Up Hours", "Assign Services"
  onAction?: () => void;
  description?: string;
}

export function LocationEmptyState({
  locationName,
  dataType,
  actionLabel,
  onAction,
  description,
}: LocationEmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="rounded-full bg-amber-50 p-3 mb-4">
        <AlertCircle className="h-6 w-6 text-amber-500" />
      </div>
      <h3 className="text-lg font-semibold mb-1">
        No {dataType} configured
      </h3>
      <p className="text-sm text-muted-foreground max-w-md mb-4">
        {description ||
          `${locationName} doesn't have ${dataType} set up yet. Configure them to enable this feature for this location.`}
      </p>
      {actionLabel && onAction && (
        <Button onClick={onAction}>{actionLabel}</Button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/ui/LocationEmptyState.tsx
git commit -m "feat: add reusable LocationEmptyState component"
```

---

### Task 19: Update Customer Service Pages to Pass `location_id`

**Files:**
- Modify: `ai-employees-app/src/pages/dashboard/customer-service/AgentPerformance.tsx`
- Modify: `ai-employees-app/src/pages/dashboard/customer-service/CallRecordings.tsx`
- Modify: `ai-employees-app/src/pages/dashboard/customer-service/Scheduler.tsx`
- Modify: `ai-employees-app/src/pages/dashboard/customer-service/AgentSettings.tsx`
- Modify: `ai-employees-app/src/pages/dashboard/customer-service/CallForwarding.tsx`

**Context:** Each page calls `voiceAgentApi` functions with `businessId`. Add `selectedLocationId`. When empty data is returned, show `LocationEmptyState`.

- [ ] **Step 1: Pattern for every page**

Add to every CS page:
```typescript
import { useSelectedLocation } from "@/hooks/useLocation";
import { LocationEmptyState } from "@/components/ui/LocationEmptyState";

const { selectedLocationId, location } = useSelectedLocation();
```

Pass `selectedLocationId` to every API call. Add `selectedLocationId` to `useEffect` dependency arrays.

- [ ] **Step 2: AgentPerformance.tsx**

```typescript
const data = await getAnalyticsSummary(token, businessId, period, selectedLocationId);
const trends = await getCallVolumeTrends(token, businessId, chartPeriod, selectedLocationId);
const dist = await getCallDistribution(token, businessId, period, selectedLocationId);
const activity = await getRecentActivity(token, businessId, 10, selectedLocationId);
```

- [ ] **Step 3: CallRecordings.tsx**

```typescript
const data = await getCalls(token, businessId, { ...options, locationId: selectedLocationId });
```

- [ ] **Step 4: Scheduler.tsx**

```typescript
const data = await getAgentSchedule(token, businessId, selectedLocationId);
await updateAgentSchedule(token, businessId, schedule, selectedLocationId);
```

If `data.schedule` is empty, show:
```typescript
<LocationEmptyState
  locationName={location?.name || "This location"}
  dataType="business hours"
  actionLabel="Set Up Hours"
  onAction={() => {/* open schedule editor */}}
/>
```

- [ ] **Step 5: AgentSettings.tsx**

```typescript
const data = await getAgentSettings(token, businessId, selectedLocationId);
await updateAgentSettings(token, businessId, settings, selectedLocationId);
const state = await getAgentState(token, businessId, selectedLocationId);
await updateAgentState(token, businessId, isActive, selectedLocationId);
```

If `data.settings` is empty, show:
```typescript
<LocationEmptyState
  locationName={location?.name || "This location"}
  dataType="agent settings"
  description="This location's agent settings haven't been initialized. This usually means the location was created before the location-scoped update."
  actionLabel="Initialize Settings"
  onAction={() => seedLocation(token, selectedLocationId)}
/>
```

- [ ] **Step 6: CallForwarding.tsx**

```typescript
const contacts = await getForwardingContacts(token, businessId, selectedLocationId);
const rules = await getForwardingRules(token, businessId, selectedLocationId);
```

- [ ] **Step 7: Commit**

```bash
git add src/pages/dashboard/customer-service/*.tsx
git commit -m "feat: pass selectedLocationId to all CS pages with empty states"
```

---

## Phase 6: Frontend — Navigation & UI Restructure

### Task 20: Move Locations to Sidebar

**Files:**
- Modify: `ai-employees-app/src/components/layout/Sidebar.tsx`
- Create: `ai-employees-app/src/pages/dashboard/Locations.tsx`
- Modify: `ai-employees-app/src/App.tsx`
- Modify: `ai-employees-app/src/pages/dashboard/BusinessSettings.tsx`

- [ ] **Step 1: Add Locations to sidebar under Account Settings**

In `Sidebar.tsx`, add to settings items (after Account Settings):
```typescript
{ label: "Locations", path: "/dashboard/settings/locations", icon: MapPin }
```

Import `MapPin` from `lucide-react`.

- [ ] **Step 2: Create standalone Locations page**

```typescript
// src/pages/dashboard/Locations.tsx
import { LocationsTab } from "@/components/business/LocationsTab";

export default function LocationsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Locations</h1>
        <p className="text-muted-foreground">
          Manage your business locations. Each location has its own hours, services, and settings.
        </p>
      </div>
      <LocationsTab />
    </div>
  );
}
```

- [ ] **Step 3: Add route in App.tsx**

```typescript
import LocationsPage from "@/pages/dashboard/Locations";
// In router:
<Route path="/dashboard/settings/locations" element={<LocationsPage />} />
```

- [ ] **Step 4: Remove Locations tab from BusinessSettings.tsx**

Remove the `LocationsTab` import and its tab entry from the tabs array.

- [ ] **Step 5: Wire seed call into LocationsTab**

Already handled in Task 8 Step 3 — `LocationsTab.tsx` and `Onboarding.tsx` both call `seedLocation(session.access_token, locationId)` after creation.

- [ ] **Step 6: Commit**

```bash
git add src/components/layout/Sidebar.tsx src/pages/dashboard/Locations.tsx src/App.tsx src/pages/dashboard/BusinessSettings.tsx src/components/business/LocationsTab.tsx
git commit -m "feat: move Locations to sidebar, wire seed on creation"
```

---

### Task 21: Location Services Management UI

**Files:**
- Create: `ai-employees-app/src/components/business/LocationServicesTab.tsx`
- Modify: `ai-employees-app/src/hooks/useServices.ts`

- [ ] **Step 1: Add `useLocationServices` hook**

```typescript
export function useLocationServices(locationId: string | null) {
  const { businessId } = useBusiness();
  // NOTE: import supabase from "@/integrations/supabase/client" (module singleton, not hook)
  const [locationServiceIds, setLocationServiceIds] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const fetchLocationServices = async () => {
    if (!locationId) return;
    setIsLoading(true);
    const { data } = await supabase
      .from("location_services")
      .select("service_id")
      .eq("location_id", locationId)
      .eq("is_active", true);
    setLocationServiceIds((data || []).map((r) => r.service_id));
    setIsLoading(false);
  };

  const toggleServiceForLocation = async (serviceId: string, enabled: boolean) => {
    if (!locationId || !businessId) return;
    if (enabled) {
      await supabase.from("location_services").upsert({
        location_id: locationId,
        service_id: serviceId,
        business_id: businessId,
        is_active: true,
      }, { onConflict: "location_id,service_id" });
    } else {
      await supabase
        .from("location_services")
        .update({ is_active: false })
        .eq("location_id", locationId)
        .eq("service_id", serviceId);
    }
    await fetchLocationServices();
  };

  useEffect(() => { fetchLocationServices(); }, [locationId]);

  return { locationServiceIds, isLoading, toggleServiceForLocation, refetch: fetchLocationServices };
}
```

- [ ] **Step 2: Create LocationServicesTab component**

```typescript
import { useServices } from "@/hooks/useServices";
import { useLocationServices } from "@/hooks/useServices";
import { useSelectedLocation } from "@/hooks/useLocation";
import { Switch } from "@/components/ui/switch";
import { LocationEmptyState } from "@/components/ui/LocationEmptyState";

export function LocationServicesTab() {
  const { selectedLocationId, location } = useSelectedLocation();
  const { services } = useServices(); // All business services (catalog)
  const { locationServiceIds, toggleServiceForLocation } = useLocationServices(selectedLocationId);

  if (!services.length) {
    return (
      <LocationEmptyState
        locationName={location?.name || "This location"}
        dataType="services"
        description="No services exist in the business catalog yet. Create services first in Business Settings."
      />
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Toggle which services are available at {location?.name || "this location"}.
      </p>
      {services.map((service) => (
        <div key={service.id} className="flex items-center justify-between p-3 border rounded-lg">
          <div>
            <p className="font-medium">{service.name}</p>
            <p className="text-sm text-muted-foreground">
              {service.duration_minutes} min
              {service.price > 0 ? ` — $${service.price}` : ""}
            </p>
          </div>
          <Switch
            checked={locationServiceIds.includes(service.id)}
            onCheckedChange={(checked) => toggleServiceForLocation(service.id, checked)}
          />
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add src/hooks/useServices.ts src/components/business/LocationServicesTab.tsx
git commit -m "feat: add location services toggle UI"
```

---

## Execution Order Summary

| Phase | Tasks | Description |
|---|---|---|
| **Phase 1** | Tasks 1-7 | DB migrations + backfill existing locations |
| **Phase 2** | Task 8 | Backend seed service for new locations |
| **Phase 3** | Tasks 9-12 | Backend APIs — location filtering, no fallback |
| **Phase 4** | Tasks 13-15 | Agent — location-scoped data + feature flags |
| **Phase 5** | Tasks 16-19 | Frontend — pass `locationId`, empty states |
| **Phase 6** | Tasks 20-21 | Frontend — navigation restructure + services UI |

## Key Architecture Rules

1. **No silent fallbacks.** If a location has no data, return empty. The UI shows an actionable empty state.
2. **Seed on creation.** Every new location gets a copy of business-wide data at creation time.
3. **Backfill migration.** Existing locations get seeded by Task 7's migration.
4. **Independence after seed.** Once seeded, each location's data is fully independent. Editing Location A never affects Location B.
5. **Agent graceful degradation.** If the agent encounters a location with no services/hours, it informs the caller and offers to transfer to a human.

## Testing Checklist

- [ ] Select Location A → Call Recordings shows only Location A calls
- [ ] Select Location A → Analytics shows only Location A metrics
- [ ] Select Location A → Agent Settings shows Location A's settings (not business defaults)
- [ ] Select Location A → Scheduler shows Location A hours
- [ ] Select Location A → Calendar shows only Location A appointments
- [ ] Select Location A → Call Forwarding shows only Location A contacts/rules
- [ ] Switch to Location B → all above now show Location B data
- [ ] Create new location → seed runs → location has hours, settings, services copied
- [ ] Location with no services → empty state shown, not all business services
- [ ] Location with no hours → empty state shown, not business hours
- [ ] Agent call to seeded location → correct hours, services, brand voice used
- [ ] Agent call to unconfigured location → graceful message, no wrong data
- [ ] Edit Location A agent settings → Location B settings unchanged
- [ ] Edit Location A hours → Location B hours unchanged
