# Custom Schedules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Custom Schedules" to the CS Scheduler page — named, toggleable, one-time or recurring schedule blocks that override weekly business hours at runtime (agent uses the custom hours, or goes offline entirely during the window).

**Architecture:** New `custom_schedules` table keyed on `(business_id, location_id)`. Admin and super_admin create/edit via a sidebar panel on the Scheduler page. The agent evaluates active custom schedules at call start — if any match today, they override the weekly hours and optionally disable the agent entirely. Existing `business_hours_overrides` data is migrated into `custom_schedules` and the old UI/table are removed.

**Tech Stack:** Supabase (PostgreSQL), React/TypeScript, FastAPI (Python), LiveKit Agents

---

## Design Decisions Locked In

| Decision | Choice | Why |
|---|---|---|
| Scope | Per-location (required `location_id`) | Matches the location-scoped pattern we established |
| Who can edit | super_admin + admin only | Client requirement |
| Overlap resolution | Higher `priority` wins; ties broken by `created_at DESC` | Predictable, admin has explicit control |
| One-time range | `start_date` + `end_date` (inclusive) | Single-day override = start==end |
| Recurring pattern | `days_of_week` text[] — no weekly/monthly/annual complexity | YAGNI, covers the shown spec ("Every Friday") |
| Agent-disabled window | `is_agent_disabled BOOLEAN` | If true, times ignored; agent responds with "we're closed" and hangs up politely |
| UI toggle state | `is_enabled BOOLEAN` | Admin can pause a schedule without deleting it |
| What happens to existing `business_hours_overrides` | Migrate into `custom_schedules` as one-time entries, then drop old table after component is removed | Clean slate, no parallel systems |
| Weekly `business_hours` — impact | None. Weekly hours stay as-is. Custom schedules only ADD overrides. | Simple, existing data preserved |

---

## File Structure

### Database Migrations (new)
- `supabase/migrations/20260413000000_custom_schedules.sql` — create table + RLS
- `supabase/migrations/20260413000001_custom_schedules_backfill.sql` — migrate `business_hours_overrides` rows
- `supabase/migrations/20260413000002_drop_business_hours_overrides.sql` — drop old table (run ONLY after confirming frontend removal is deployed)

### Backend Files (new)
- `backend/app/routers/custom_schedules.py` — GET/POST/PATCH/DELETE endpoints (admin role check)
- `backend/app/schemas/custom_schedules.py` — Pydantic request/response models

### Backend Files (modify)
- `backend/app/main.py` — register new router

### Agent Files (modify)
- `agent/supabase_helpers.py` — add `_fetch_active_custom_schedule(supabase, business_id, location_id, now)`; returns the winning schedule or None
- `agent/prompt_builder.py` — apply custom schedule hours to the formatted hours block if one is active for today
- `agent/agent.py` — at session start, check if an agent-disabled custom schedule is active. If so, respond with a "we're closed" message and end the call.

### Frontend Files (new)
- `ai-employees-app/src/hooks/useCustomSchedules.ts` — CRUD hook, direct Supabase, scoped to `selectedLocationId`
- `ai-employees-app/src/components/scheduler/CustomScheduleCard.tsx` — the card UI (matches design)
- `ai-employees-app/src/components/scheduler/CustomScheduleSidebar.tsx` — the right-side panel with cards + Add button
- `ai-employees-app/src/components/scheduler/CustomScheduleDialog.tsx` — Create/Edit modal
- `ai-employees-app/src/components/scheduler/CustomScheduleDetail.tsx` — Main-area detail view when a card is selected

### Frontend Files (modify)
- `ai-employees-app/src/pages/dashboard/customer-service/Scheduler.tsx` — split into 2-column layout (weekly grid OR selected detail on the left, sidebar on the right)

### Frontend Files (remove)
- `ai-employees-app/src/components/business/BusinessDateOverrides.tsx` — replaced by custom schedules
- `ai-employees-app/src/hooks/useBusinessHoursOverrides.ts` — no longer used
- Reference to `<BusinessDateOverrides />` in `BusinessSettings.tsx`

---

## Data Model

```sql
CREATE TABLE custom_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    location_id UUID NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,

    schedule_type TEXT NOT NULL CHECK (schedule_type IN ('one_time', 'recurring')),

    -- one_time fields (null for recurring)
    start_date DATE,
    end_date DATE,

    -- recurring fields (null for one_time)
    days_of_week TEXT[],  -- values from {'monday','tuesday',...,'sunday'}

    -- Behavior during the window
    is_agent_disabled BOOLEAN NOT NULL DEFAULT false,
    open_time TIME,
    close_time TIME,

    -- User toggle
    is_enabled BOOLEAN NOT NULL DEFAULT true,

    -- Overlap resolution
    priority INT NOT NULL DEFAULT 100,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES auth.users(id),

    -- Validity constraints
    CHECK (
        (schedule_type = 'one_time' AND start_date IS NOT NULL AND end_date IS NOT NULL AND end_date >= start_date)
        OR (schedule_type = 'recurring' AND days_of_week IS NOT NULL AND array_length(days_of_week, 1) > 0)
    ),
    CHECK (
        is_agent_disabled = true
        OR (open_time IS NOT NULL AND close_time IS NOT NULL)
    )
);
```

---

## Phase 1: Database

### Task 1: Create `custom_schedules` table

**Files:**
- Create: `supabase/migrations/20260413000000_custom_schedules.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Custom Schedules — admin-defined schedule overrides for the agent
-- per (business_id, location_id). Overrides weekly business_hours at runtime.

CREATE TABLE custom_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    location_id UUID NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,

    schedule_type TEXT NOT NULL CHECK (schedule_type IN ('one_time', 'recurring')),

    start_date DATE,
    end_date DATE,

    days_of_week TEXT[],

    is_agent_disabled BOOLEAN NOT NULL DEFAULT false,
    open_time TIME,
    close_time TIME,

    is_enabled BOOLEAN NOT NULL DEFAULT true,
    priority INT NOT NULL DEFAULT 100,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by UUID REFERENCES auth.users(id),

    CONSTRAINT custom_schedules_fields_check CHECK (
        (schedule_type = 'one_time' AND start_date IS NOT NULL AND end_date IS NOT NULL AND end_date >= start_date)
        OR (schedule_type = 'recurring' AND days_of_week IS NOT NULL AND array_length(days_of_week, 1) > 0)
    ),
    CONSTRAINT custom_schedules_hours_check CHECK (
        is_agent_disabled = true
        OR (open_time IS NOT NULL AND close_time IS NOT NULL)
    )
);

CREATE INDEX idx_custom_schedules_business ON custom_schedules (business_id);
CREATE INDEX idx_custom_schedules_location ON custom_schedules (location_id);
CREATE INDEX idx_custom_schedules_location_enabled ON custom_schedules (location_id, is_enabled)
WHERE is_enabled = true;

-- updated_at trigger
CREATE OR REPLACE FUNCTION set_custom_schedules_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_custom_schedules_updated_at
BEFORE UPDATE ON custom_schedules
FOR EACH ROW
EXECUTE FUNCTION set_custom_schedules_updated_at();

-- RLS
ALTER TABLE custom_schedules ENABLE ROW LEVEL SECURITY;

-- Members of the business can SELECT
CREATE POLICY "Members can view own business custom_schedules"
ON custom_schedules FOR SELECT
USING (
    business_id IN (
        SELECT business_id FROM user_roles WHERE user_id = auth.uid()
    )
);

-- Admin and super_admin can INSERT/UPDATE/DELETE
CREATE POLICY "Admins can insert custom_schedules"
ON custom_schedules FOR INSERT
WITH CHECK (
    business_id IN (
        SELECT business_id FROM user_roles
        WHERE user_id = auth.uid() AND role IN ('super_admin', 'admin')
    )
);

CREATE POLICY "Admins can update custom_schedules"
ON custom_schedules FOR UPDATE
USING (
    business_id IN (
        SELECT business_id FROM user_roles
        WHERE user_id = auth.uid() AND role IN ('super_admin', 'admin')
    )
)
WITH CHECK (
    business_id IN (
        SELECT business_id FROM user_roles
        WHERE user_id = auth.uid() AND role IN ('super_admin', 'admin')
    )
);

CREATE POLICY "Admins can delete custom_schedules"
ON custom_schedules FOR DELETE
USING (
    business_id IN (
        SELECT business_id FROM user_roles
        WHERE user_id = auth.uid() AND role IN ('super_admin', 'admin')
    )
);

-- Service role (agent + backend) has full access
CREATE POLICY "Service role full access on custom_schedules"
ON custom_schedules FOR ALL
USING (auth.role() = 'service_role');
```

- [ ] **Step 2: Run migration in Supabase SQL editor**

Verify with:
```sql
SELECT table_name FROM information_schema.tables WHERE table_name = 'custom_schedules';
-- Expected: 1 row
```

---

### Task 2: Backfill `custom_schedules` from `business_hours_overrides`

**Files:**
- Create: `supabase/migrations/20260413000001_custom_schedules_backfill.sql`

**Context:** Existing `business_hours_overrides` rows have `(business_id, override_date, is_closed, open_time, close_time, reason)`. Each row becomes a one_time custom_schedule. Since the old table has no `location_id`, assign each row to the business's **first** location (oldest by `created_at`), matching the pattern we used for `gmail_tokens`.

- [ ] **Step 1: Write the backfill SQL**

```sql
INSERT INTO custom_schedules (
    business_id, location_id, name, schedule_type,
    start_date, end_date,
    is_agent_disabled, open_time, close_time,
    is_enabled, priority,
    created_at
)
SELECT
    bho.business_id,
    (
        SELECT l.id
        FROM locations l
        WHERE l.business_id = bho.business_id
        ORDER BY l.created_at ASC
        LIMIT 1
    ) AS location_id,
    COALESCE(NULLIF(bho.reason, ''), 'Date override ' || bho.override_date::text) AS name,
    'one_time',
    bho.override_date,
    bho.override_date,
    COALESCE(bho.is_closed, false),
    CASE WHEN bho.is_closed THEN NULL ELSE bho.open_time END,
    CASE WHEN bho.is_closed THEN NULL ELSE bho.close_time END,
    true,  -- is_enabled
    100,   -- priority
    COALESCE(bho.created_at, now())
FROM business_hours_overrides bho
WHERE EXISTS (
    SELECT 1 FROM locations l WHERE l.business_id = bho.business_id
);
```

- [ ] **Step 2: Run migration in Supabase SQL editor**

Verify:
```sql
SELECT COUNT(*) FROM custom_schedules WHERE schedule_type = 'one_time';
SELECT COUNT(*) FROM business_hours_overrides;
-- Both counts should match for businesses that have at least one location
```

---

## Phase 2: Backend — Custom Schedules API

### Task 3: Create Pydantic schemas

**Files:**
- Create: `backend/app/schemas/custom_schedules.py`

- [ ] **Step 1: Write the schemas**

```python
from datetime import date, time, datetime
from typing import Optional, List
from pydantic import BaseModel, field_validator


ALLOWED_DAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


class CustomScheduleBase(BaseModel):
    name: str
    schedule_type: str  # 'one_time' | 'recurring'
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days_of_week: Optional[List[str]] = None
    is_agent_disabled: bool = False
    open_time: Optional[str] = None  # "HH:MM"
    close_time: Optional[str] = None  # "HH:MM"
    is_enabled: bool = True
    priority: int = 100

    @field_validator("schedule_type")
    @classmethod
    def check_schedule_type(cls, v):
        if v not in ("one_time", "recurring"):
            raise ValueError("schedule_type must be 'one_time' or 'recurring'")
        return v

    @field_validator("days_of_week")
    @classmethod
    def check_days(cls, v):
        if v is None:
            return v
        for d in v:
            if d.lower() not in ALLOWED_DAYS:
                raise ValueError(f"Invalid day: {d}")
        return [d.lower() for d in v]


class CreateCustomScheduleRequest(CustomScheduleBase):
    location_id: str


class UpdateCustomScheduleRequest(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days_of_week: Optional[List[str]] = None
    is_agent_disabled: Optional[bool] = None
    open_time: Optional[str] = None
    close_time: Optional[str] = None
    is_enabled: Optional[bool] = None
    priority: Optional[int] = None


class CustomScheduleResponse(CustomScheduleBase):
    id: str
    business_id: str
    location_id: str
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/custom_schedules.py
git commit -m "feat: add custom_schedules Pydantic schemas"
```

---

### Task 4: Create custom_schedules router

**Files:**
- Create: `backend/app/routers/custom_schedules.py`

- [ ] **Step 1: Write the router**

```python
"""
Custom Schedules API — admin/super_admin only.

CRUD for agent custom schedules per (business_id, location_id).
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_user_id, get_current_user
from app.core.supabase import supabase_admin
from app.schemas.custom_schedules import (
    CreateCustomScheduleRequest,
    UpdateCustomScheduleRequest,
    CustomScheduleResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/custom-schedules", tags=["custom-schedules"])


def _require_admin(user_id: str) -> str:
    """Verify user is admin/super_admin and return their business_id."""
    role_row = (
        supabase_admin.table("user_roles")
        .select("business_id, role")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not role_row.data:
        raise HTTPException(status_code=403, detail="User has no role assigned")
    if role_row.data[0]["role"] not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only admins can manage custom schedules")
    return role_row.data[0]["business_id"]


def _verify_location(business_id: str, location_id: str) -> None:
    result = (
        supabase_admin.table("locations")
        .select("id")
        .eq("id", location_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Location not found for this business")


# ── GET /custom-schedules ─────────────────────────────────────────────────────

@router.get("", response_model=List[CustomScheduleResponse])
async def list_custom_schedules(
    location_id: str,
    current_user: dict = Depends(get_current_user),
    user_id: str = Depends(get_user_id),
):
    business_id = _require_admin(user_id)
    _verify_location(business_id, location_id)

    result = (
        supabase_admin.table("custom_schedules")
        .select("*")
        .eq("business_id", business_id)
        .eq("location_id", location_id)
        .order("priority", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


# ── POST /custom-schedules ────────────────────────────────────────────────────

@router.post("", response_model=CustomScheduleResponse, status_code=201)
async def create_custom_schedule(
    body: CreateCustomScheduleRequest,
    user_id: str = Depends(get_user_id),
):
    business_id = _require_admin(user_id)
    _verify_location(business_id, body.location_id)

    row = body.model_dump()
    row["business_id"] = business_id
    row["created_by"] = user_id
    if row["start_date"]:
        row["start_date"] = row["start_date"].isoformat()
    if row["end_date"]:
        row["end_date"] = row["end_date"].isoformat()

    result = supabase_admin.table("custom_schedules").insert(row).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create custom schedule")
    return result.data[0]


# ── PATCH /custom-schedules/{id} ──────────────────────────────────────────────

@router.patch("/{schedule_id}", response_model=CustomScheduleResponse)
async def update_custom_schedule(
    schedule_id: str,
    body: UpdateCustomScheduleRequest,
    user_id: str = Depends(get_user_id),
):
    business_id = _require_admin(user_id)

    # Verify row exists and belongs to this business
    existing = (
        supabase_admin.table("custom_schedules")
        .select("id, business_id")
        .eq("id", schedule_id)
        .limit(1)
        .execute()
    )
    if not existing.data or existing.data[0]["business_id"] != business_id:
        raise HTTPException(status_code=404, detail="Custom schedule not found")

    updates = body.model_dump(exclude_unset=True)
    if "start_date" in updates and updates["start_date"]:
        updates["start_date"] = updates["start_date"].isoformat()
    if "end_date" in updates and updates["end_date"]:
        updates["end_date"] = updates["end_date"].isoformat()

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        supabase_admin.table("custom_schedules")
        .update(updates)
        .eq("id", schedule_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update custom schedule")
    return result.data[0]


# ── DELETE /custom-schedules/{id} ─────────────────────────────────────────────

@router.delete("/{schedule_id}")
async def delete_custom_schedule(
    schedule_id: str,
    user_id: str = Depends(get_user_id),
):
    business_id = _require_admin(user_id)

    existing = (
        supabase_admin.table("custom_schedules")
        .select("id, business_id")
        .eq("id", schedule_id)
        .limit(1)
        .execute()
    )
    if not existing.data or existing.data[0]["business_id"] != business_id:
        raise HTTPException(status_code=404, detail="Custom schedule not found")

    supabase_admin.table("custom_schedules").delete().eq("id", schedule_id).execute()
    return {"deleted": True}
```

- [ ] **Step 2: Register router in `backend/app/main.py`**

Add import:
```python
from app.routers import calls, settings as settings_router, forwarding, analytics, integrations, gmail_integrations, phone_numbers, support, locations, custom_schedules
```

Add registration after the other `include_router` calls:
```python
app.include_router(custom_schedules.router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/custom_schedules.py backend/app/main.py
git commit -m "feat: add custom_schedules CRUD endpoints (admin only)"
```

---

## Phase 3: Agent — Runtime Custom Schedule Evaluation

### Task 5: Add custom schedule fetch + evaluator

**Files:**
- Modify: `agent/supabase_helpers.py`

- [ ] **Step 1: Add `_fetch_active_custom_schedule` helper**

Add to the end of `agent/supabase_helpers.py`:

```python
def _fetch_active_custom_schedule(
    supabase,
    business_id: str,
    location_id: str | None,
    now: datetime | None = None,
) -> dict | None:
    """
    Return the single custom_schedule that applies to the given moment, or None.
    Rules:
      - is_enabled = true
      - type one_time: start_date <= today <= end_date
      - type recurring: today's day-of-week in days_of_week
    If multiple match, highest priority wins; ties broken by created_at desc.
    """
    if not supabase or not business_id or not location_id:
        return None

    now = now or datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    dow = now.strftime("%A").lower()  # 'monday' etc.

    try:
        r = (
            supabase.table("custom_schedules")
            .select("*")
            .eq("business_id", business_id)
            .eq("location_id", location_id)
            .eq("is_enabled", True)
            .order("priority", desc=True)
            .order("created_at", desc=True)
            .execute()
        )
        rows = getattr(r, "data", None) or []
    except Exception as e:
        logger.warning("Failed to fetch custom schedules: %s", e)
        return None

    for row in rows:
        stype = row.get("schedule_type")
        if stype == "one_time":
            sd = row.get("start_date")
            ed = row.get("end_date")
            if sd and ed and sd <= today_str <= ed:
                return row
        elif stype == "recurring":
            days = row.get("days_of_week") or []
            if dow in [d.lower() for d in days]:
                return row

    return None
```

- [ ] **Step 2: Commit**

```bash
git add agent/supabase_helpers.py
git commit -m "feat: add _fetch_active_custom_schedule helper"
```

---

### Task 6: Apply custom schedule to prompt builder hours block

**Files:**
- Modify: `agent/prompt_builder.py`

**Context:** When a custom schedule is active for today, the agent's prompt should mention those hours for today instead of the normal weekly hours for today. If the schedule is agent-disabled, the prompt should say "the agent is temporarily unavailable due to {name}."

- [ ] **Step 1: Update imports**

Add to the import block:
```python
from supabase_helpers import (
    # ... existing imports ...
    _fetch_active_custom_schedule,
)
```

- [ ] **Step 2: Apply custom schedule in `build_instructions`**

In `build_instructions()`, after fetching `biz_hours` and BEFORE formatting, add:

```python
    # Apply an active custom schedule (if any) for the called location
    active_custom = None
    if business_id:
        active_custom = _fetch_active_custom_schedule(supabase, business_id, location_id)

    if active_custom:
        if active_custom.get("is_agent_disabled"):
            # Override the entire hours block with a closed message
            hours_block = (
                f"Special notice: The agent is temporarily unavailable due to "
                f"'{active_custom.get('name') or 'a scheduled closure'}'. "
                f"Apologise to the caller, tell them the business is currently closed, "
                f"and offer to take a message or suggest calling back later.\n\n"
            )
        else:
            # Override today's row in biz_hours with the custom times
            from datetime import datetime as _dt
            today_dow = _dt.now().strftime("%A").lower()
            new_hours = []
            found = False
            for row in biz_hours:
                if row.get("day_of_week") == today_dow:
                    new_hours.append({
                        "day_of_week": today_dow,
                        "is_open": True,
                        "open_time": active_custom["open_time"],
                        "close_time": active_custom["close_time"],
                    })
                    found = True
                else:
                    new_hours.append(row)
            if not found:
                new_hours.append({
                    "day_of_week": today_dow,
                    "is_open": True,
                    "open_time": active_custom["open_time"],
                    "close_time": active_custom["close_time"],
                })
            biz_hours = new_hours
            hours_block = (
                _format_business_hours(biz_hours)
                + f"Today's hours are affected by the active schedule '{active_custom.get('name')}'.\n\n"
            )
    else:
        hours_block = _format_business_hours(biz_hours)
```

Remove the existing standalone `hours_block = _format_business_hours(biz_hours)` line (the new block replaces it).

- [ ] **Step 3: Commit**

```bash
git add agent/prompt_builder.py
git commit -m "feat: prompt builder applies active custom schedule"
```

---

### Task 7: Agent hangs up when `is_agent_disabled` is active

**Files:**
- Modify: `agent/agent.py`

**Context:** Currently the agent always starts the session. With a custom schedule active AND `is_agent_disabled=true`, the agent should answer, play a short "we're closed" message, and end the call. The prompt change from Task 6 already instructs the agent to do this verbally, but we also want to proactively end the call after a short reply so we don't hold open a no-op SIP session.

- [ ] **Step 1: Add imports**

In the existing import block of `agent/agent.py`:
```python
from supabase_helpers import (
    # ... existing imports ...
    _fetch_active_custom_schedule,
)
```

- [ ] **Step 2: Check active schedule right after context is resolved**

In the `voice_agent()` function, AFTER the section where `business_id` and `location_id` are resolved and `supabase` is initialized, and BEFORE `build_instructions()` is called, add:

```python
    # Check for agent-disabled custom schedule
    disabled_by_schedule = None
    if business_id and location_id and supabase is not None:
        _cs = _fetch_active_custom_schedule(supabase, business_id, location_id)
        if _cs and _cs.get("is_agent_disabled"):
            disabled_by_schedule = _cs
            logger.info(
                "Custom schedule '%s' is disabling the agent for this call",
                _cs.get("name"),
            )
```

Then after `session.start(...)` but before `await caller_left.wait()`, add:

```python
    if disabled_by_schedule:
        # Short closure message — the prompt already instructs the agent to say
        # we're closed, so just kick off one reply and then end the session.
        await session.generate_reply(
            instructions=(
                f"Immediately tell the caller: 'Thank you for calling. We are currently closed "
                f"due to {disabled_by_schedule.get('name') or 'scheduled unavailability'}. "
                f"Please call back during our regular hours.' Then do not say anything else."
            )
        )
        # Give the TTS ~4 seconds to speak before ending
        await asyncio.sleep(6)
        await ctx.room.disconnect()
        return
```

- [ ] **Step 3: Commit**

```bash
git add agent/agent.py
git commit -m "feat: agent ends call gracefully when disabled by custom schedule"
```

---

## Phase 4: Frontend — Custom Schedules Hook

### Task 8: Create `useCustomSchedules` hook

**Files:**
- Create: `ai-employees-app/src/hooks/useCustomSchedules.ts`

- [ ] **Step 1: Write the hook**

```typescript
import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/integrations/supabase/client";
import { useBusiness } from "@/hooks/useBusiness";
import { useSelectedLocation } from "@/hooks/useLocation";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";

export type ScheduleType = "one_time" | "recurring";

export interface CustomSchedule {
  id: string;
  business_id: string;
  location_id: string;
  name: string;
  schedule_type: ScheduleType;
  start_date: string | null;
  end_date: string | null;
  days_of_week: string[] | null;
  is_agent_disabled: boolean;
  open_time: string | null;
  close_time: string | null;
  is_enabled: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
  created_by: string | null;
}

export interface CreateCustomScheduleInput {
  name: string;
  schedule_type: ScheduleType;
  start_date?: string;
  end_date?: string;
  days_of_week?: string[];
  is_agent_disabled?: boolean;
  open_time?: string;
  close_time?: string;
  is_enabled?: boolean;
  priority?: number;
}

export function useCustomSchedules() {
  const { businessId } = useBusiness();
  const { selectedLocationId } = useSelectedLocation();
  const { user } = useAuth();
  const [schedules, setSchedules] = useState<CustomSchedule[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const fetchSchedules = useCallback(async () => {
    if (!businessId || !selectedLocationId) {
      setSchedules([]);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    const { data, error } = await supabase
      .from("custom_schedules")
      .select("*")
      .eq("business_id", businessId)
      .eq("location_id", selectedLocationId)
      .order("priority", { ascending: false })
      .order("created_at", { ascending: false });

    if (error) {
      console.error("Failed to fetch custom schedules:", error);
      toast.error("Failed to load custom schedules");
      setSchedules([]);
    } else {
      setSchedules((data as CustomSchedule[]) || []);
    }
    setIsLoading(false);
  }, [businessId, selectedLocationId]);

  useEffect(() => {
    fetchSchedules();
  }, [fetchSchedules]);

  const createSchedule = async (input: CreateCustomScheduleInput) => {
    if (!businessId || !selectedLocationId || !user) {
      toast.error("Missing business or location");
      return { error: new Error("Missing context") };
    }

    const row = {
      business_id: businessId,
      location_id: selectedLocationId,
      created_by: user.id,
      name: input.name,
      schedule_type: input.schedule_type,
      start_date: input.start_date ?? null,
      end_date: input.end_date ?? null,
      days_of_week: input.days_of_week ?? null,
      is_agent_disabled: input.is_agent_disabled ?? false,
      open_time: input.open_time ?? null,
      close_time: input.close_time ?? null,
      is_enabled: input.is_enabled ?? true,
      priority: input.priority ?? 100,
    };

    const { data, error } = await supabase
      .from("custom_schedules")
      .insert(row)
      .select()
      .single();

    if (error) {
      console.error("Create custom schedule error:", error);
      toast.error(`Failed to create: ${error.message}`);
      return { error };
    }

    setSchedules((prev) => [data as CustomSchedule, ...prev]);
    toast.success("Custom schedule created");
    return { data: data as CustomSchedule };
  };

  const updateSchedule = async (id: string, updates: Partial<CustomSchedule>) => {
    const { data, error } = await supabase
      .from("custom_schedules")
      .update(updates)
      .eq("id", id)
      .select()
      .single();

    if (error) {
      toast.error(`Failed to update: ${error.message}`);
      return { error };
    }
    setSchedules((prev) => prev.map((s) => (s.id === id ? (data as CustomSchedule) : s)));
    return { data: data as CustomSchedule };
  };

  const toggleEnabled = async (id: string, is_enabled: boolean) => {
    return updateSchedule(id, { is_enabled });
  };

  const deleteSchedule = async (id: string) => {
    const { error } = await supabase.from("custom_schedules").delete().eq("id", id);
    if (error) {
      toast.error(`Failed to delete: ${error.message}`);
      return { error };
    }
    setSchedules((prev) => prev.filter((s) => s.id !== id));
    toast.success("Custom schedule deleted");
    return { error: null };
  };

  return {
    schedules,
    isLoading,
    refetch: fetchSchedules,
    createSchedule,
    updateSchedule,
    toggleEnabled,
    deleteSchedule,
  };
}

// ── Helper used by UI to compute status badge ────────────────────────────────

export function deriveStatus(s: CustomSchedule): "Active" | "Scheduled" | "Ended" | "Disabled" {
  if (!s.is_enabled) return "Disabled";
  const today = new Date().toISOString().slice(0, 10);
  if (s.schedule_type === "one_time") {
    if (s.end_date && s.end_date < today) return "Ended";
    if (s.start_date && s.start_date > today) return "Scheduled";
    return "Active";
  }
  // recurring
  return "Active";
}
```

- [ ] **Step 2: Commit**

```bash
git add src/hooks/useCustomSchedules.ts
git commit -m "feat: add useCustomSchedules hook"
```

---

## Phase 5: Frontend — Card, Sidebar, Dialog, Detail

### Task 9: Create `CustomScheduleCard`

**Files:**
- Create: `ai-employees-app/src/components/scheduler/CustomScheduleCard.tsx`

- [ ] **Step 1: Write the component**

```typescript
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { CustomSchedule } from "@/hooks/useCustomSchedules";
import { deriveStatus } from "@/hooks/useCustomSchedules";

interface Props {
  schedule: CustomSchedule;
  isSelected: boolean;
  onSelect: () => void;
  onToggle: (next: boolean) => void;
}

function formatDateRange(s: CustomSchedule): string {
  if (s.schedule_type === "one_time") {
    if (s.start_date && s.end_date) {
      if (s.start_date === s.end_date) {
        return new Date(s.start_date).toLocaleDateString(undefined, {
          month: "short", day: "numeric", year: "numeric",
        });
      }
      const start = new Date(s.start_date).toLocaleDateString(undefined, { month: "short", day: "numeric" });
      const end = new Date(s.end_date).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
      return `${start}–${end}`;
    }
    return "—";
  }
  // recurring
  const days = s.days_of_week ?? [];
  if (days.length === 7) return "Every day";
  if (days.length === 1) return `Every ${capitalize(days[0])}`;
  return days.map(capitalize).join(", ");
}

function formatTimeRange(s: CustomSchedule): string {
  if (s.is_agent_disabled) return "Agent Disabled";
  if (s.open_time && s.close_time) {
    return `${formatTime(s.open_time)} – ${formatTime(s.close_time)}`;
  }
  return "—";
}

function formatTime(t: string): string {
  const [h, m] = t.split(":");
  const hour = parseInt(h, 10);
  const ampm = hour < 12 ? "AM" : "PM";
  const h12 = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour;
  return `${h12}:${m} ${ampm}`;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function CustomScheduleCard({ schedule, isSelected, onSelect, onToggle }: Props) {
  const status = deriveStatus(schedule);
  const badgeColor = {
    Active: "bg-green-500/10 text-green-600 border-green-600/20",
    Scheduled: "bg-amber-500/10 text-amber-600 border-amber-600/20",
    Ended: "bg-muted text-muted-foreground",
    Disabled: "bg-muted text-muted-foreground",
  }[status];

  return (
    <div
      onClick={onSelect}
      className={cn(
        "cursor-pointer rounded-lg border p-4 transition-colors",
        isSelected ? "border-accent bg-accent/5" : "border-border hover:border-accent/50"
      )}
    >
      <div className="flex items-start justify-between mb-1">
        <h4 className="font-semibold text-sm text-foreground">{schedule.name}</h4>
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <Badge variant="outline" className={cn("text-xs", badgeColor)}>
            {status}
          </Badge>
          <Switch
            checked={schedule.is_enabled}
            onCheckedChange={onToggle}
            className="scale-75"
          />
        </div>
      </div>
      <p className="text-xs text-muted-foreground mb-1">{formatDateRange(schedule)}</p>
      <p className="text-xs flex items-center gap-1.5">
        <span
          className={cn(
            "inline-block w-1.5 h-1.5 rounded-full",
            schedule.is_agent_disabled ? "bg-muted-foreground" : "bg-green-500"
          )}
        />
        {formatTimeRange(schedule)}
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/scheduler/CustomScheduleCard.tsx
git commit -m "feat: add CustomScheduleCard component"
```

---

### Task 10: Create `CustomScheduleDialog` (Add/Edit modal)

**Files:**
- Create: `ai-employees-app/src/components/scheduler/CustomScheduleDialog.tsx`

- [ ] **Step 1: Write the dialog**

```typescript
import { useEffect, useState } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import type { CustomSchedule, CreateCustomScheduleInput, ScheduleType } from "@/hooks/useCustomSchedules";

interface Props {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  existing?: CustomSchedule | null;
  onCreate?: (input: CreateCustomScheduleInput) => Promise<void>;
  onUpdate?: (id: string, updates: Partial<CustomSchedule>) => Promise<void>;
}

const DAYS = [
  { value: "monday", label: "Mon" },
  { value: "tuesday", label: "Tue" },
  { value: "wednesday", label: "Wed" },
  { value: "thursday", label: "Thu" },
  { value: "friday", label: "Fri" },
  { value: "saturday", label: "Sat" },
  { value: "sunday", label: "Sun" },
];

const blank = {
  name: "",
  schedule_type: "one_time" as ScheduleType,
  start_date: "",
  end_date: "",
  days_of_week: [] as string[],
  is_agent_disabled: false,
  open_time: "09:00",
  close_time: "17:00",
};

export function CustomScheduleDialog({ open, onOpenChange, existing, onCreate, onUpdate }: Props) {
  const [form, setForm] = useState(blank);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (existing) {
      setForm({
        name: existing.name,
        schedule_type: existing.schedule_type,
        start_date: existing.start_date ?? "",
        end_date: existing.end_date ?? "",
        days_of_week: existing.days_of_week ?? [],
        is_agent_disabled: existing.is_agent_disabled,
        open_time: existing.open_time ?? "09:00",
        close_time: existing.close_time ?? "17:00",
      });
    } else {
      setForm(blank);
    }
  }, [existing, open]);

  const toggleDay = (d: string) => {
    setForm((f) => ({
      ...f,
      days_of_week: f.days_of_week.includes(d)
        ? f.days_of_week.filter((x) => x !== d)
        : [...f.days_of_week, d],
    }));
  };

  const valid = () => {
    if (!form.name.trim()) return false;
    if (form.schedule_type === "one_time") {
      if (!form.start_date || !form.end_date) return false;
      if (form.end_date < form.start_date) return false;
    } else {
      if (form.days_of_week.length === 0) return false;
    }
    if (!form.is_agent_disabled) {
      if (!form.open_time || !form.close_time) return false;
    }
    return true;
  };

  const handleSave = async () => {
    if (!valid()) return;
    setSaving(true);
    try {
      const payload: CreateCustomScheduleInput = {
        name: form.name.trim(),
        schedule_type: form.schedule_type,
        is_agent_disabled: form.is_agent_disabled,
      };
      if (form.schedule_type === "one_time") {
        payload.start_date = form.start_date;
        payload.end_date = form.end_date;
      } else {
        payload.days_of_week = form.days_of_week;
      }
      if (!form.is_agent_disabled) {
        payload.open_time = form.open_time;
        payload.close_time = form.close_time;
      }
      if (existing && onUpdate) {
        await onUpdate(existing.id, payload as Partial<CustomSchedule>);
      } else if (onCreate) {
        await onCreate(payload);
      }
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{existing ? "Edit Custom Schedule" : "Add Custom Schedule"}</DialogTitle>
          <DialogDescription>
            Override the weekly schedule for a specific date range or recurring day.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div>
            <Label>Name</Label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. Holiday Hours"
            />
          </div>

          <div>
            <Label>Type</Label>
            <RadioGroup
              value={form.schedule_type}
              onValueChange={(v) => setForm({ ...form, schedule_type: v as ScheduleType })}
              className="flex gap-6 mt-1"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="one_time" id="st-one" />
                <Label htmlFor="st-one" className="font-normal cursor-pointer">One-time</Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="recurring" id="st-rec" />
                <Label htmlFor="st-rec" className="font-normal cursor-pointer">Recurring</Label>
              </div>
            </RadioGroup>
          </div>

          {form.schedule_type === "one_time" ? (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Start date</Label>
                <Input type="date" value={form.start_date}
                  onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
              </div>
              <div>
                <Label>End date</Label>
                <Input type="date" value={form.end_date}
                  onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
              </div>
            </div>
          ) : (
            <div>
              <Label>Days of week</Label>
              <div className="flex flex-wrap gap-2 mt-1">
                {DAYS.map((d) => (
                  <label key={d.value}
                    className="flex items-center gap-1.5 border rounded-md px-2.5 py-1.5 cursor-pointer text-sm">
                    <Checkbox
                      checked={form.days_of_week.includes(d.value)}
                      onCheckedChange={() => toggleDay(d.value)}
                    />
                    {d.label}
                  </label>
                ))}
              </div>
            </div>
          )}

          <div className="flex items-center justify-between border rounded-lg p-3">
            <div>
              <Label className="cursor-pointer">Disable agent during this window</Label>
              <p className="text-xs text-muted-foreground">
                When on, the agent answers but immediately tells callers we're closed.
              </p>
            </div>
            <Switch
              checked={form.is_agent_disabled}
              onCheckedChange={(v) => setForm({ ...form, is_agent_disabled: v })}
            />
          </div>

          {!form.is_agent_disabled && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Open time</Label>
                <Input type="time" value={form.open_time}
                  onChange={(e) => setForm({ ...form, open_time: e.target.value })} />
              </div>
              <div>
                <Label>Close time</Label>
                <Input type="time" value={form.close_time}
                  onChange={(e) => setForm({ ...form, close_time: e.target.value })} />
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave} disabled={!valid() || saving}>
            {saving ? "Saving..." : (existing ? "Save" : "Create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/scheduler/CustomScheduleDialog.tsx
git commit -m "feat: add CustomScheduleDialog for create/edit"
```

---

### Task 11: Create `CustomScheduleDetail`

**Files:**
- Create: `ai-employees-app/src/components/scheduler/CustomScheduleDetail.tsx`

- [ ] **Step 1: Write the detail view**

```typescript
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Pencil, Trash2 } from "lucide-react";
import type { CustomSchedule } from "@/hooks/useCustomSchedules";
import { deriveStatus } from "@/hooks/useCustomSchedules";

interface Props {
  schedule: CustomSchedule;
  onEdit: () => void;
  onDelete: () => void;
}

function formatTime(t: string | null): string {
  if (!t) return "—";
  const [h, m] = t.split(":");
  const hour = parseInt(h, 10);
  const ampm = hour < 12 ? "AM" : "PM";
  const h12 = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour;
  return `${h12}:${m} ${ampm}`;
}

export function CustomScheduleDetail({ schedule, onEdit, onDelete }: Props) {
  const status = deriveStatus(schedule);
  return (
    <div className="bg-card border border-border rounded-xl p-6">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h2 className="text-xl font-semibold text-foreground">{schedule.name}</h2>
          <Badge variant="outline" className="mt-2">{status}</Badge>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={onEdit}>
            <Pencil className="h-4 w-4 mr-1" /> Edit
          </Button>
          <Button variant="outline" size="sm" onClick={onDelete}
            className="text-destructive hover:text-destructive">
            <Trash2 className="h-4 w-4 mr-1" /> Delete
          </Button>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <dt className="text-muted-foreground">Type</dt>
          <dd className="font-medium capitalize">{schedule.schedule_type.replace("_", "-")}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Enabled</dt>
          <dd className="font-medium">{schedule.is_enabled ? "Yes" : "No"}</dd>
        </div>
        {schedule.schedule_type === "one_time" ? (
          <>
            <div>
              <dt className="text-muted-foreground">Start</dt>
              <dd className="font-medium">{schedule.start_date ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">End</dt>
              <dd className="font-medium">{schedule.end_date ?? "—"}</dd>
            </div>
          </>
        ) : (
          <div className="col-span-2">
            <dt className="text-muted-foreground">Days</dt>
            <dd className="font-medium capitalize">
              {(schedule.days_of_week ?? []).join(", ") || "—"}
            </dd>
          </div>
        )}
        <div className="col-span-2 border-t pt-3">
          {schedule.is_agent_disabled ? (
            <>
              <dt className="text-muted-foreground">Agent</dt>
              <dd className="font-medium text-destructive">Disabled during this window</dd>
            </>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <dt className="text-muted-foreground">Open</dt>
                <dd className="font-medium">{formatTime(schedule.open_time)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Close</dt>
                <dd className="font-medium">{formatTime(schedule.close_time)}</dd>
              </div>
            </div>
          )}
        </div>
      </dl>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/scheduler/CustomScheduleDetail.tsx
git commit -m "feat: add CustomScheduleDetail view"
```

---

### Task 12: Create `CustomScheduleSidebar`

**Files:**
- Create: `ai-employees-app/src/components/scheduler/CustomScheduleSidebar.tsx`

- [ ] **Step 1: Write the sidebar**

```typescript
import { Button } from "@/components/ui/button";
import { Plus, CalendarDays } from "lucide-react";
import { CustomScheduleCard } from "./CustomScheduleCard";
import type { CustomSchedule } from "@/hooks/useCustomSchedules";

interface Props {
  schedules: CustomSchedule[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onAdd: () => void;
  isLoading: boolean;
}

export function CustomScheduleSidebar({
  schedules, selectedId, onSelect, onToggle, onAdd, isLoading,
}: Props) {
  return (
    <div className="bg-card border border-border rounded-xl p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-semibold text-foreground">Custom Schedules</h3>
          <p className="text-xs text-muted-foreground">Special date overrides</p>
        </div>
      </div>

      {isLoading ? (
        <div className="animate-pulse space-y-2">
          {[0, 1].map((i) => (
            <div key={i} className="h-20 bg-secondary rounded-lg" />
          ))}
        </div>
      ) : schedules.length === 0 ? (
        <div className="text-center py-8 border border-dashed border-border rounded-lg mb-3">
          <CalendarDays className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">No custom schedules yet.</p>
        </div>
      ) : (
        <div className="space-y-2 mb-3">
          {schedules.map((s) => (
            <CustomScheduleCard
              key={s.id}
              schedule={s}
              isSelected={selectedId === s.id}
              onSelect={() => onSelect(s.id)}
              onToggle={(next) => onToggle(s.id, next)}
            />
          ))}
        </div>
      )}

      <Button variant="outline" className="w-full" onClick={onAdd}>
        <Plus className="h-4 w-4 mr-2" /> Add Custom Schedule
      </Button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/scheduler/CustomScheduleSidebar.tsx
git commit -m "feat: add CustomScheduleSidebar component"
```

---

### Task 13: Wire sidebar into Scheduler page

**Files:**
- Modify: `ai-employees-app/src/pages/dashboard/customer-service/Scheduler.tsx`

**Context:** Turn the current single-column layout into a 2-column grid. Left column: the existing weekly grid OR the detail view of a selected custom schedule. Right column: the new sidebar.

- [ ] **Step 1: Add imports + hook at the top of the component**

Add imports near the top:
```typescript
import { useCustomSchedules } from "@/hooks/useCustomSchedules";
import { CustomScheduleSidebar } from "@/components/scheduler/CustomScheduleSidebar";
import { CustomScheduleDialog } from "@/components/scheduler/CustomScheduleDialog";
import { CustomScheduleDetail } from "@/components/scheduler/CustomScheduleDetail";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
```

Inside the component body, after the existing hooks:
```typescript
  const {
    schedules: customSchedules,
    isLoading: csLoading,
    createSchedule,
    updateSchedule,
    toggleEnabled,
    deleteSchedule,
  } = useCustomSchedules();

  const [selectedScheduleId, setSelectedScheduleId] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<typeof customSchedules[number] | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  const selectedSchedule = customSchedules.find((s) => s.id === selectedScheduleId) ?? null;
```

- [ ] **Step 2: Replace the page's outer container with a 2-column grid**

Find the current JSX return. Wrap the weekly schedule grid + existing content in a left column, and add the sidebar as a right column:

```tsx
return (
  <div className="animate-fade-in">
    <h1 className="text-3xl font-bold text-foreground mb-2">Customer Service Agent Scheduler</h1>
    <p className="text-muted-foreground mb-6">Set when your agent operates — plus custom overrides.</p>

    <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-6">
      {/* LEFT: weekly grid or selected-schedule detail */}
      <div className="space-y-6">
        {selectedSchedule ? (
          <CustomScheduleDetail
            schedule={selectedSchedule}
            onEdit={() => {
              setEditingSchedule(selectedSchedule);
              setDialogOpen(true);
            }}
            onDelete={() => setDeleteConfirmId(selectedSchedule.id)}
          />
        ) : (
          <>
            {/* EXISTING WEEKLY GRID + ON/OFF TOGGLE JSX GOES HERE (unchanged) */}
          </>
        )}
      </div>

      {/* RIGHT: sidebar */}
      <CustomScheduleSidebar
        schedules={customSchedules}
        selectedId={selectedScheduleId}
        onSelect={(id) => setSelectedScheduleId(selectedScheduleId === id ? null : id)}
        onToggle={(id, enabled) => toggleEnabled(id, enabled)}
        onAdd={() => {
          setEditingSchedule(null);
          setDialogOpen(true);
        }}
        isLoading={csLoading}
      />
    </div>

    <CustomScheduleDialog
      open={dialogOpen}
      onOpenChange={setDialogOpen}
      existing={editingSchedule}
      onCreate={async (input) => {
        await createSchedule(input);
      }}
      onUpdate={async (id, updates) => {
        await updateSchedule(id, updates);
      }}
    />

    <AlertDialog open={!!deleteConfirmId} onOpenChange={(open) => !open && setDeleteConfirmId(null)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this custom schedule?</AlertDialogTitle>
          <AlertDialogDescription>
            This cannot be undone. The agent will stop using this override immediately.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={async () => {
              if (deleteConfirmId) {
                await deleteSchedule(deleteConfirmId);
                if (selectedScheduleId === deleteConfirmId) setSelectedScheduleId(null);
                setDeleteConfirmId(null);
              }
            }}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            Delete
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
);
```

Leave the existing weekly grid markup untouched — it goes into the placeholder `{/* EXISTING WEEKLY GRID... */}` block.

- [ ] **Step 3: Commit**

```bash
git add src/pages/dashboard/customer-service/Scheduler.tsx
git commit -m "feat: Scheduler page integrates custom schedules sidebar"
```

---

## Phase 6: Cleanup

### Task 14: Remove old BusinessDateOverrides

**Files:**
- Modify: `ai-employees-app/src/pages/dashboard/BusinessSettings.tsx`
- Delete: `ai-employees-app/src/components/business/BusinessDateOverrides.tsx`
- Delete: `ai-employees-app/src/hooks/useBusinessHoursOverrides.ts`

- [ ] **Step 1: Remove the import + usage from BusinessSettings.tsx**

Search for `BusinessDateOverrides` in BusinessSettings.tsx and delete:
- The import line
- The JSX `<BusinessDateOverrides />` tag wherever it's rendered

- [ ] **Step 2: Delete the now-unused files**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
rm src/components/business/BusinessDateOverrides.tsx
rm src/hooks/useBusinessHoursOverrides.ts
```

- [ ] **Step 3: Typecheck to make sure nothing else imported them**

```bash
npx tsc --noEmit
```
Expected: exit code 0, no errors.

- [ ] **Step 4: Commit**

```bash
git add src/pages/dashboard/BusinessSettings.tsx
git add -u    # picks up the deletions
git commit -m "refactor: remove BusinessDateOverrides (replaced by custom_schedules)"
```

---

### Task 15: Drop `business_hours_overrides` table

**Files:**
- Create: `supabase/migrations/20260413000002_drop_business_hours_overrides.sql`

**Context:** Only run this migration AFTER Task 14 is deployed. The frontend no longer reads/writes this table, and the backfill migration (Task 2) copied all data into `custom_schedules`.

- [ ] **Step 1: Write the migration**

```sql
-- Safe to run after the frontend no longer references this table.
-- All data was migrated to custom_schedules by 20260413000001_custom_schedules_backfill.sql.
DROP TABLE IF EXISTS business_hours_overrides CASCADE;
```

- [ ] **Step 2: Run migration in Supabase SQL editor**

Verify:
```sql
SELECT table_name FROM information_schema.tables WHERE table_name = 'business_hours_overrides';
-- Expected: 0 rows
```

---

### Task 16: Regenerate Supabase TS types

**Files:**
- Modify: `ai-employees-app/src/integrations/supabase/types.ts`

- [ ] **Step 1: Regenerate**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx supabase gen types typescript --linked > src/integrations/supabase/types.ts
```

- [ ] **Step 2: Typecheck**

```bash
npx tsc --noEmit
```
Expected: exit code 0.

- [ ] **Step 3: Commit**

```bash
git add src/integrations/supabase/types.ts
git commit -m "chore: regenerate Supabase types (custom_schedules table)"
```

---

## Execution Order Summary

| Phase | Tasks | Description |
|---|---|---|
| **Phase 1** | 1-2 | DB migrations: create table + backfill |
| **Phase 2** | 3-4 | Backend schemas + router |
| **Phase 3** | 5-7 | Agent runtime custom schedule handling |
| **Phase 4** | 8 | Frontend hook |
| **Phase 5** | 9-13 | Frontend card, dialog, detail, sidebar, page wiring |
| **Phase 6** | 14-16 | Cleanup: remove old component, drop old table, regen types |

## Testing Checklist

After implementation:

- [ ] Create one-time schedule "Holiday Hours" Dec 24-26, 10 AM – 2 PM → shows as Scheduled, then Active on Dec 24, then Ended Dec 27
- [ ] Create recurring "Every Friday" 8 AM – 8 PM → shows Active year-round
- [ ] Create "Maintenance" one-time with Agent Disabled on Jan 15 → shows "Agent Disabled" on card
- [ ] Toggle a schedule off → status badge becomes Disabled, agent no longer applies it
- [ ] Delete a schedule → card disappears, detail pane clears
- [ ] Agent call during active Agent-Disabled schedule → agent says closed message, hangs up within ~6s
- [ ] Agent call during active custom-hours schedule → prompt's hours block reflects the override for today
- [ ] Agent call outside any active schedule → weekly hours unchanged, normal behavior
- [ ] Two overlapping schedules — priority 200 vs priority 100 → priority 200 wins
- [ ] Non-admin user tries to create a custom schedule → RLS blocks (or the endpoint returns 403)
- [ ] Switch selected location → sidebar refreshes with that location's schedules only
- [ ] Old `business_hours_overrides` rows appear as one-time custom_schedules after backfill
- [ ] Business Settings → Business Hours tab no longer shows the Date Overrides section
