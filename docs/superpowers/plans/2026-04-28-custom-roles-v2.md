# Custom Roles & Permissions v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make page-level permissions per role editable by business admins — replacing the hardcoded static `RESTRICTED_PAGES` map with DB-driven per-business permission rows that admins can toggle in the UI.

**Architecture:** Add `custom_roles` (one row per base role per business, `is_system=true` for the 3 defaults; can add named custom roles) and `role_page_permissions` (one row per role+page). On login the frontend fetches the user's role's permissions and stores them in a context. `ProtectedRoute` and `Sidebar` use the fetched map instead of the static constant. The R&P page matrix becomes editable via toggle checkboxes; "New Role" creates a new `custom_roles` row with a full default permission set. Custom role assignment to users is NOT in this plan — roles created here are visible in the UI but user assignment is a follow-up task.

**Tech Stack:** FastAPI (new `roles.py` router), Supabase PostgreSQL, React/TypeScript, existing `require_role` dependency, existing `supabase_admin` pattern.

**Repos:**
- Backend: `/home/lap-68/Documents/gt-rahul/sam-backend` (branch `feature/custom-roles-v2`)
- Frontend: `/home/lap-68/Documents/gt-rahul/ai-employees-app` (branch `feature/custom-roles-v2`)

---

## File Structure

### New Files
- `ai-employees-app/supabase/migrations/20260428000001_custom_roles.sql` — DB schema + seed
- `sam-backend/backend/app/routers/roles.py` — CRUD API
- `sam-backend/backend/app/schemas/roles.py` — Pydantic schemas
- `ai-employees-app/src/hooks/useRolePermissions.ts` — fetch + cache DB permissions

### Modified Files
- `sam-backend/backend/app/main.py` — register roles router
- `ai-employees-app/src/contexts/AuthContext.tsx` — expose `permittedPaths` derived from DB
- `ai-employees-app/src/components/auth/ProtectedRoute.tsx` — use `permittedPaths`
- `ai-employees-app/src/components/layout/Sidebar.tsx` — use `permittedPaths`
- `ai-employees-app/src/pages/dashboard/RolesPermissions.tsx` — editable matrix + New Role dialog

---

## Task 1: DB Migration — custom_roles + role_page_permissions

**Files:**
- Create: `ai-employees-app/supabase/migrations/20260428000001_custom_roles.sql`

The static `RESTRICTED_PAGES` default (from `roles.ts`) defines which pages require restriction. Pages NOT in this map are accessible to all roles. This seeding logic mirrors that map.

- [ ] **Step 1: Write the migration**

```sql
-- =====================================================================
-- custom_roles: one row per (business, base_role) for system roles;
--               admins can add named custom roles (is_system=false).
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.custom_roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    base_role   TEXT NOT NULL CHECK (base_role IN ('super_admin', 'admin', 'user')),
    is_system   BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (business_id, name)
);

-- =====================================================================
-- role_page_permissions: page-level access per role per business.
-- page_key matches route path strings from roles.ts RESTRICTED_PAGES.
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.role_page_permissions (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id    UUID NOT NULL REFERENCES public.custom_roles(id) ON DELETE CASCADE,
    page_key   TEXT NOT NULL,
    is_allowed BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (role_id, page_key)
);

-- RLS
ALTER TABLE public.custom_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.role_page_permissions ENABLE ROW LEVEL SECURITY;

-- custom_roles: members of the business can read; only admins write
CREATE POLICY "Business members can read custom_roles"
    ON public.custom_roles FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles ur
            WHERE ur.user_id = auth.uid()
              AND ur.business_id = custom_roles.business_id
        )
    );

CREATE POLICY "Admins can insert custom_roles"
    ON public.custom_roles FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.user_roles ur
            WHERE ur.user_id = auth.uid()
              AND ur.business_id = custom_roles.business_id
              AND ur.role IN ('super_admin', 'admin')
        )
    );

CREATE POLICY "Admins can update custom_roles"
    ON public.custom_roles FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles ur
            WHERE ur.user_id = auth.uid()
              AND ur.business_id = custom_roles.business_id
              AND ur.role IN ('super_admin', 'admin')
        )
    );

CREATE POLICY "Admins can delete non-system custom_roles"
    ON public.custom_roles FOR DELETE
    USING (
        is_system = false
        AND EXISTS (
            SELECT 1 FROM public.user_roles ur
            WHERE ur.user_id = auth.uid()
              AND ur.business_id = custom_roles.business_id
              AND ur.role IN ('super_admin', 'admin')
        )
    );

-- role_page_permissions: readable by business members; writable by admins
CREATE POLICY "Business members can read role_page_permissions"
    ON public.role_page_permissions FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.custom_roles cr
            JOIN public.user_roles ur ON ur.business_id = cr.business_id
            WHERE cr.id = role_page_permissions.role_id
              AND ur.user_id = auth.uid()
        )
    );

CREATE POLICY "Admins can write role_page_permissions"
    ON public.role_page_permissions FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.custom_roles cr
            JOIN public.user_roles ur ON ur.business_id = cr.business_id
            WHERE cr.id = role_page_permissions.role_id
              AND ur.user_id = auth.uid()
              AND ur.role IN ('super_admin', 'admin')
        )
    );

-- =====================================================================
-- Seed system roles for every existing business.
-- One row per base_role, is_system=true.
-- =====================================================================
INSERT INTO public.custom_roles (business_id, name, description, base_role, is_system)
SELECT
    b.id,
    CASE r.base_role
        WHEN 'super_admin' THEN 'Admin'
        WHEN 'admin'       THEN 'Manager'
        WHEN 'user'        THEN 'Team Member'
    END,
    CASE r.base_role
        WHEN 'super_admin' THEN 'Full access to all pages and settings.'
        WHEN 'admin'       THEN 'Can manage business settings, team, and daily operations.'
        WHEN 'user'        THEN 'Can access operational pages and personal settings.'
    END,
    r.base_role,
    true
FROM public.businesses b
CROSS JOIN (VALUES ('super_admin'), ('admin'), ('user')) AS r(base_role)
ON CONFLICT (business_id, name) DO NOTHING;

-- =====================================================================
-- Seed default page permissions per system role.
-- Mirrors RESTRICTED_PAGES in roles.ts:
--   super_admin: all pages
--   admin: all except global, locations, phone-numbers, billing, roles-permissions
--   user: all except any RESTRICTED_PAGES entry
-- Restricted pages and their allowed roles (from roles.ts):
--   /dashboard/settings/global          → super_admin
--   /dashboard/settings/locations       → super_admin
--   /dashboard/settings/phone-numbers   → super_admin
--   /dashboard/settings/billing         → super_admin
--   /dashboard/roles-permissions        → super_admin
--   /dashboard/settings/business        → super_admin, admin
--   /dashboard/team                     → super_admin, admin
-- All other pages in ALL_PAGES are unrestricted (all roles allowed).
-- =====================================================================
INSERT INTO public.role_page_permissions (role_id, page_key, is_allowed)
SELECT cr.id, p.page_key, p.is_allowed
FROM public.custom_roles cr
CROSS JOIN (
    VALUES
    -- super_admin: all pages allowed
    ('super_admin', '/dashboard',                                    true),
    ('super_admin', '/dashboard/calendar',                           true),
    ('super_admin', '/dashboard/customer-service/dashboard',         true),
    ('super_admin', '/dashboard/marketing',                          true),
    ('super_admin', '/dashboard/sales',                              true),
    ('super_admin', '/dashboard/hr',                                 true),
    ('super_admin', '/dashboard/executive',                          true),
    ('super_admin', '/dashboard/support',                            true),
    ('super_admin', '/dashboard/tutorials',                          true),
    ('super_admin', '/dashboard/settings/global',                    true),
    ('super_admin', '/dashboard/settings/business',                  true),
    ('super_admin', '/dashboard/settings/locations',                 true),
    ('super_admin', '/dashboard/settings/account',                   true),
    ('super_admin', '/dashboard/team',                               true),
    ('super_admin', '/dashboard/roles-permissions',                  true),
    ('super_admin', '/dashboard/settings/phone-numbers',             true),
    ('super_admin', '/dashboard/settings/billing',                   true),
    -- admin: restricted pages blocked
    ('admin', '/dashboard',                                          true),
    ('admin', '/dashboard/calendar',                                 true),
    ('admin', '/dashboard/customer-service/dashboard',               true),
    ('admin', '/dashboard/marketing',                                true),
    ('admin', '/dashboard/sales',                                    true),
    ('admin', '/dashboard/hr',                                       true),
    ('admin', '/dashboard/executive',                                true),
    ('admin', '/dashboard/support',                                  true),
    ('admin', '/dashboard/tutorials',                                true),
    ('admin', '/dashboard/settings/global',                          false),
    ('admin', '/dashboard/settings/business',                        true),
    ('admin', '/dashboard/settings/locations',                       false),
    ('admin', '/dashboard/settings/account',                         true),
    ('admin', '/dashboard/team',                                     true),
    ('admin', '/dashboard/roles-permissions',                        false),
    ('admin', '/dashboard/settings/phone-numbers',                   false),
    ('admin', '/dashboard/settings/billing',                         false),
    -- user: only operational pages
    ('user', '/dashboard',                                           true),
    ('user', '/dashboard/calendar',                                  true),
    ('user', '/dashboard/customer-service/dashboard',                true),
    ('user', '/dashboard/marketing',                                 true),
    ('user', '/dashboard/sales',                                     true),
    ('user', '/dashboard/hr',                                        true),
    ('user', '/dashboard/executive',                                 true),
    ('user', '/dashboard/support',                                   true),
    ('user', '/dashboard/tutorials',                                 true),
    ('user', '/dashboard/settings/global',                           false),
    ('user', '/dashboard/settings/business',                         false),
    ('user', '/dashboard/settings/locations',                        false),
    ('user', '/dashboard/settings/account',                          true),
    ('user', '/dashboard/team',                                      false),
    ('user', '/dashboard/roles-permissions',                         false),
    ('user', '/dashboard/settings/phone-numbers',                    false),
    ('user', '/dashboard/settings/billing',                          false)
) AS p(base_role, page_key, is_allowed)
WHERE cr.base_role = p.base_role
  AND cr.is_system = true
ON CONFLICT (role_id, page_key) DO NOTHING;
```

- [ ] **Step 2: Push migration**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx supabase db push
```

Expected: "Remote database updated successfully" or similar.

- [ ] **Step 3: Verify tables exist**

```bash
curl -s "https://hdnwxonrwcnaodjxipll.supabase.co/rest/v1/custom_roles?select=id,name,base_role,is_system&limit=5" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imhkbnd4b25yd2NuYW9kanhpcGxsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2NTc4MjgxMiwiZXhwIjoyMDgxMzU4ODEyfQ.C3QeozTwRBVaOgP1ADezkQ66tq1euRwXbb2yvwFvG1o" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imhkbnd4b25yd2NuYW9kanhpcGxsIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2NTc4MjgxMiwiZXhwIjoyMDgxMzU4ODEyfQ.C3QeozTwRBVaOgP1ADezkQ66tq1euRwXbb2yvwFvG1o"
```

Expected: JSON array with 3+ rows (Admin, Manager, Team Member per business).

- [ ] **Step 4: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add supabase/migrations/20260428000001_custom_roles.sql
git commit -m "feat: add custom_roles + role_page_permissions migration with seed"
```

---

## Task 2: Backend Roles Router

**Files:**
- Create: `sam-backend/backend/app/schemas/roles.py`
- Create: `sam-backend/backend/app/routers/roles.py`
- Modify: `sam-backend/backend/app/main.py`

The backend must use `supabase_admin` for all reads (bypasses RLS). Auth is still enforced via `Depends(get_user_id)` or `Depends(require_role(...))`.

- [ ] **Step 1: Create schemas**

File: `sam-backend/backend/app/schemas/roles.py`

```python
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CustomRoleResponse(BaseModel):
    id: str
    business_id: str
    name: str
    description: Optional[str] = None
    base_role: str
    is_system: bool
    created_at: datetime


class CreateCustomRoleRequest(BaseModel):
    name: str
    description: Optional[str] = None
    base_role: str  # 'super_admin' | 'admin' | 'user'


class PagePermission(BaseModel):
    page_key: str
    is_allowed: bool


class RolePermissionsResponse(BaseModel):
    role_id: str
    permissions: list[PagePermission]


class UpdatePermissionsRequest(BaseModel):
    permissions: list[PagePermission]
```

- [ ] **Step 2: Create roles router**

File: `sam-backend/backend/app/routers/roles.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_user_id, verify_business_access, require_role
from app.core.supabase import supabase_admin
from app.schemas.roles import (
    CustomRoleResponse, CreateCustomRoleRequest,
    RolePermissionsResponse, PagePermission, UpdatePermissionsRequest,
)

router = APIRouter(prefix="/roles", tags=["roles"])


def _get_role_business_id(role_id: str) -> str:
    r = supabase_admin.table("custom_roles").select("business_id").eq("id", role_id).limit(1).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Role not found")
    return r.data[0]["business_id"]


@router.get("", response_model=list[CustomRoleResponse])
async def list_roles(business_id: str, user_id: str = Depends(get_user_id)):
    verify_business_access(user_id, business_id)
    r = supabase_admin.table("custom_roles").select("*").eq("business_id", business_id).order("created_at").execute()
    return r.data or []


@router.post("", response_model=CustomRoleResponse, status_code=201)
async def create_role(
    business_id: str,
    body: CreateCustomRoleRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    # Only admins can create roles
    role_row = supabase_admin.table("user_roles").select("role").eq("user_id", user_id).eq("business_id", business_id).limit(1).execute()
    if not role_row.data or role_row.data[0]["role"] not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only admins can create roles")

    if body.base_role not in ("super_admin", "admin", "user"):
        raise HTTPException(status_code=400, detail="base_role must be super_admin, admin, or user")

    r = supabase_admin.table("custom_roles").insert({
        "business_id": business_id,
        "name": body.name,
        "description": body.description,
        "base_role": body.base_role,
        "is_system": False,
    }).execute()

    if not r.data:
        raise HTTPException(status_code=500, detail="Failed to create role")

    role = r.data[0]

    # Seed permissions from the system role with the same base_role
    system_role = supabase_admin.table("custom_roles").select("id").eq("business_id", business_id).eq("base_role", body.base_role).eq("is_system", True).limit(1).execute()
    if system_role.data:
        src_id = system_role.data[0]["id"]
        src_perms = supabase_admin.table("role_page_permissions").select("page_key, is_allowed").eq("role_id", src_id).execute()
        if src_perms.data:
            new_perms = [{"role_id": role["id"], "page_key": p["page_key"], "is_allowed": p["is_allowed"]} for p in src_perms.data]
            supabase_admin.table("role_page_permissions").insert(new_perms).execute()

    return role


@router.delete("/{role_id}", status_code=204)
async def delete_role(role_id: str, user_id: str = Depends(get_user_id)):
    business_id = _get_role_business_id(role_id)
    verify_business_access(user_id, business_id)

    role_row = supabase_admin.table("user_roles").select("role").eq("user_id", user_id).eq("business_id", business_id).limit(1).execute()
    if not role_row.data or role_row.data[0]["role"] not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only admins can delete roles")

    check = supabase_admin.table("custom_roles").select("is_system").eq("id", role_id).limit(1).execute()
    if check.data and check.data[0]["is_system"]:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")

    supabase_admin.table("custom_roles").delete().eq("id", role_id).execute()


@router.get("/{role_id}/permissions", response_model=RolePermissionsResponse)
async def get_permissions(role_id: str, user_id: str = Depends(get_user_id)):
    business_id = _get_role_business_id(role_id)
    verify_business_access(user_id, business_id)

    r = supabase_admin.table("role_page_permissions").select("page_key, is_allowed").eq("role_id", role_id).execute()
    perms = [PagePermission(page_key=p["page_key"], is_allowed=p["is_allowed"]) for p in (r.data or [])]
    return RolePermissionsResponse(role_id=role_id, permissions=perms)


@router.put("/{role_id}/permissions", response_model=RolePermissionsResponse)
async def update_permissions(
    role_id: str,
    body: UpdatePermissionsRequest,
    user_id: str = Depends(get_user_id),
):
    business_id = _get_role_business_id(role_id)
    verify_business_access(user_id, business_id)

    role_row = supabase_admin.table("user_roles").select("role").eq("user_id", user_id).eq("business_id", business_id).limit(1).execute()
    if not role_row.data or role_row.data[0]["role"] not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only admins can update permissions")

    rows = [{"role_id": role_id, "page_key": p.page_key, "is_allowed": p.is_allowed} for p in body.permissions]
    supabase_admin.table("role_page_permissions").upsert(rows, on_conflict="role_id,page_key").execute()

    r = supabase_admin.table("role_page_permissions").select("page_key, is_allowed").eq("role_id", role_id).execute()
    perms = [PagePermission(page_key=p["page_key"], is_allowed=p["is_allowed"]) for p in (r.data or [])]
    return RolePermissionsResponse(role_id=role_id, permissions=perms)
```

- [ ] **Step 3: Register router in main.py**

In `sam-backend/backend/app/main.py`:

Add to imports:
```python
from app.routers import roles as roles_router
```

Add after last `app.include_router(...)`:
```python
app.include_router(roles_router.router)
```

- [ ] **Step 4: Test with curl**

```bash
# Health check
curl -s http://localhost:8003/health
```

Expected: `{"status":"ok","service":"ai-voice-agent-api"}`

```bash
# Check the router is registered (unauthenticated → 403, not 404)
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8003/roles?business_id=da9fc4fb-2b16-48ab-8856-696870d0a18a"
```

Expected: `403` (auth required, not 404 meaning unregistered).

- [ ] **Step 5: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add backend/app/schemas/roles.py backend/app/routers/roles.py backend/app/main.py
git commit -m "feat: add /roles CRUD + /roles/{id}/permissions API"
```

---

## Task 3: Frontend API functions + useRolePermissions hook

**Files:**
- Modify: `ai-employees-app/src/lib/voiceAgentApi.ts` — add roles API functions
- Create: `ai-employees-app/src/hooks/useRolePermissions.ts`

The hook fetches the user's custom role for their business, then fetches that role's page permissions. Falls back to the static `RESTRICTED_PAGES` from `roles.ts` if no DB data found.

- [ ] **Step 1: Add API types and functions to voiceAgentApi.ts**

Add after the existing forwarding contact types (around line 430):

```typescript
// ── Custom Roles ────────────────────────────────────────────────────────────

export interface CustomRole {
  id: string;
  business_id: string;
  name: string;
  description?: string;
  base_role: "super_admin" | "admin" | "user";
  is_system: boolean;
  created_at: string;
}

export interface PagePermission {
  page_key: string;
  is_allowed: boolean;
}

export interface RolePermissionsResponse {
  role_id: string;
  permissions: PagePermission[];
}

export async function listCustomRoles(token: string, businessId: string): Promise<CustomRole[]> {
  const q = new URLSearchParams({ business_id: businessId });
  const res = await fetchWithAuth(`/roles?${q}`, token);
  if (!res.ok) return [];
  return res.json();
}

export async function createCustomRole(
  token: string,
  businessId: string,
  data: { name: string; description?: string; base_role: "super_admin" | "admin" | "user" }
): Promise<CustomRole> {
  const q = new URLSearchParams({ business_id: businessId });
  const res = await fetchWithAuth(`/roles?${q}`, token, {
    method: "POST",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create role: ${res.status}`);
  return res.json();
}

export async function deleteCustomRole(token: string, roleId: string): Promise<void> {
  const res = await fetchWithAuth(`/roles/${roleId}`, token, { method: "DELETE" });
  if (!res.ok) throw new Error(`Failed to delete role: ${res.status}`);
}

export async function getRolePermissions(token: string, roleId: string): Promise<RolePermissionsResponse> {
  const res = await fetchWithAuth(`/roles/${roleId}/permissions`, token);
  if (!res.ok) throw new Error(`Failed to get permissions: ${res.status}`);
  return res.json();
}

export async function updateRolePermissions(
  token: string,
  roleId: string,
  permissions: PagePermission[]
): Promise<RolePermissionsResponse> {
  const res = await fetchWithAuth(`/roles/${roleId}/permissions`, token, {
    method: "PUT",
    body: JSON.stringify({ permissions }),
  });
  if (!res.ok) throw new Error(`Failed to update permissions: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 2: Create useRolePermissions hook**

File: `ai-employees-app/src/hooks/useRolePermissions.ts`

```typescript
import { useState, useEffect } from "react";
import { RESTRICTED_PAGES, type AppRole } from "@/lib/roles";
import { listCustomRoles, getRolePermissions } from "@/lib/voiceAgentApi";

export interface ResolvedPermissions {
  /** Map of page_key → is_allowed derived from DB. Empty until loaded. */
  permittedPaths: Record<string, boolean> | null;
  isLoading: boolean;
}

/**
 * Fetches the user's page permissions from the DB for their role in the given business.
 * Falls back to the static RESTRICTED_PAGES map if no DB data is found.
 *
 * Returns `permittedPaths`:
 *   - null  → still loading (use static fallback in consumers)
 *   - {}    → loaded but empty (treat as static fallback)
 *   - {"/dashboard/settings/global": true, ...} → use this map
 */
export function useRolePermissions(
  token: string | null,
  businessId: string | null,
  appRole: AppRole | null
): ResolvedPermissions {
  const [permittedPaths, setPermittedPaths] = useState<Record<string, boolean> | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (!token || !businessId || !appRole) {
      setPermittedPaths(null);
      return;
    }

    setIsLoading(true);

    listCustomRoles(token, businessId)
      .then((roles) => {
        // Find the system role matching this user's app_role
        const match = roles.find((r) => r.base_role === appRole && r.is_system);
        if (!match) {
          // No DB data — fall back to static map
          setPermittedPaths({});
          return;
        }
        return getRolePermissions(token, match.id);
      })
      .then((resp) => {
        if (!resp) return;
        const map: Record<string, boolean> = {};
        for (const p of resp.permissions) {
          map[p.page_key] = p.is_allowed;
        }
        setPermittedPaths(map);
      })
      .catch(() => {
        // On error, fall back to static map
        setPermittedPaths({});
      })
      .finally(() => setIsLoading(false));
  }, [token, businessId, appRole]);

  return { permittedPaths, isLoading };
}

/**
 * Check whether a user can access a path using the DB-driven map.
 * Falls back to the static RESTRICTED_PAGES if permittedPaths is null/empty.
 */
export function canAccessPathDynamic(
  permittedPaths: Record<string, boolean> | null,
  appRole: AppRole | null,
  path: string
): boolean {
  // Strip query string for matching
  const cleanPath = path.split("?")[0];

  if (permittedPaths && Object.keys(permittedPaths).length > 0) {
    // DB-driven: if the page has an entry, use it; otherwise allow
    if (cleanPath in permittedPaths) return permittedPaths[cleanPath];
    return true;
  }

  // Static fallback
  if (!appRole) return false;
  const allowed = RESTRICTED_PAGES[cleanPath];
  if (!allowed) return true;
  return allowed.includes(appRole);
}
```

- [ ] **Step 3: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/lib/voiceAgentApi.ts src/hooks/useRolePermissions.ts
git commit -m "feat: add roles API functions and useRolePermissions hook"
```

---

## Task 4: Wire Dynamic Permissions into AuthContext + ProtectedRoute + Sidebar

**Files:**
- Modify: `ai-employees-app/src/contexts/AuthContext.tsx`
- Modify: `ai-employees-app/src/components/auth/ProtectedRoute.tsx`
- Modify: `ai-employees-app/src/components/layout/Sidebar.tsx`

The hook is called in `AuthContext` (which already has `session`, `roles`, and `businessId`). The resolved `permittedPaths` and `canAccess(path)` function are added to the context so `ProtectedRoute` and `Sidebar` can use it without prop drilling.

- [ ] **Step 1: Update AuthContext**

In `ai-employees-app/src/contexts/AuthContext.tsx`:

Add to imports:
```typescript
import { useRolePermissions, canAccessPathDynamic } from "@/hooks/useRolePermissions";
import type { AppRole } from "@/lib/roles";
```

Add to `AuthContextType` interface:
```typescript
canAccess: (path: string) => boolean;
permissionsLoading: boolean;
```

Inside `AuthProvider`, after the existing state declarations, add:

```typescript
// Derive business_id and app_role from roles (first role row)
const businessId = roles[0]?.business_id ?? null;
const appRole = (roles[0]?.role ?? null) as AppRole | null;

const { permittedPaths, isLoading: permissionsLoading } = useRolePermissions(
  session?.access_token ?? null,
  businessId,
  appRole
);

const canAccess = (path: string): boolean =>
  canAccessPathDynamic(permittedPaths, appRole, path);
```

Add `canAccess` and `permissionsLoading` to the context value object:
```typescript
value={{
  // ...existing fields...
  canAccess,
  permissionsLoading,
}}
```

Update `useAuth` export (no change needed — it already returns the full context).

- [ ] **Step 2: Update ProtectedRoute**

In `ai-employees-app/src/components/auth/ProtectedRoute.tsx`:

Replace the existing role-check block (currently uses `RESTRICTED_PAGES[location.pathname]`) with:

```typescript
import { useAuth } from "@/contexts/AuthContext";

// Inside the component, after MFA checks:
const { canAccess } = useAuth();

if (!canAccess(location.pathname)) {
  return <Navigate to="/dashboard" replace />;
}
```

Remove the now-unused import of `RESTRICTED_PAGES` if it was imported here.

- [ ] **Step 3: Update Sidebar**

In `ai-employees-app/src/components/layout/Sidebar.tsx`:

Replace the filtering logic that uses `getRolesForPath` / `RESTRICTED_PAGES` with `canAccess`:

```typescript
import { useAuth } from "@/contexts/AuthContext";

// Inside the component:
const { canAccess } = useAuth();

// When filtering nav items:
const visibleSettings = settingsNavItems.filter((item) => canAccess(item.path));
```

Remove the now-unused import of `getRolesForPath` from `@/lib/roles` if no longer used elsewhere in the file.

- [ ] **Step 4: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/contexts/AuthContext.tsx src/components/auth/ProtectedRoute.tsx src/components/layout/Sidebar.tsx
git commit -m "feat: wire dynamic DB permissions into AuthContext, ProtectedRoute, Sidebar"
```

---

## Task 5: Editable Roles & Permissions Page

**Files:**
- Modify: `ai-employees-app/src/pages/dashboard/RolesPermissions.tsx`

The existing page is a static read-only matrix. This task makes it fully interactive:
- Checkboxes become toggleable — clicking one calls `PUT /roles/{id}/permissions`
- "New Role" button opens a dialog (name + base_role selector) — calls `POST /roles`
- Each non-system role card has a delete button — calls `DELETE /roles/{id}`
- Roles are loaded from `/roles` API, permissions per selected role from `/roles/{id}/permissions`
- The matrix shows the *selected* role's permissions (role tabs at top, or show all at once)

- [ ] **Step 1: Write the updated page**

File: `ai-employees-app/src/pages/dashboard/RolesPermissions.tsx`

```typescript
import { useState, useEffect, useCallback } from "react";
import { Shield, Plus, Trash2, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";
import { useBusiness } from "@/hooks/useBusiness";
import {
  listCustomRoles,
  getRolePermissions,
  updateRolePermissions,
  createCustomRole,
  deleteCustomRole,
  type CustomRole,
  type PagePermission,
} from "@/lib/voiceAgentApi";

const ALL_PAGES = [
  { path: "/dashboard", label: "Dashboard", group: "Main" },
  { path: "/dashboard/calendar", label: "Calendar", group: "Main" },
  { path: "/dashboard/customer-service/dashboard", label: "Customer Service Employee", group: "Main" },
  { path: "/dashboard/marketing", label: "Marketing Employee", group: "Main" },
  { path: "/dashboard/sales", label: "Sales Employee", group: "Main" },
  { path: "/dashboard/hr", label: "Human Resource Employee", group: "Main" },
  { path: "/dashboard/executive", label: "Executive Assistant Employee", group: "Main" },
  { path: "/dashboard/support", label: "Support", group: "Help" },
  { path: "/dashboard/tutorials", label: "Tutorials", group: "Help" },
  { path: "/dashboard/settings/global", label: "Global Settings", group: "Settings" },
  { path: "/dashboard/settings/business", label: "Business Settings", group: "Settings" },
  { path: "/dashboard/settings/locations", label: "Location Settings", group: "Settings" },
  { path: "/dashboard/settings/account", label: "Account Settings", group: "Settings" },
  { path: "/dashboard/team", label: "Team Management", group: "Settings" },
  { path: "/dashboard/roles-permissions", label: "Roles & Permissions", group: "Settings" },
  { path: "/dashboard/settings/phone-numbers", label: "Phone Numbers", group: "Settings" },
  { path: "/dashboard/settings/billing", label: "Billing", group: "Settings" },
];

const GROUPS = ["Main", "Help", "Settings"];

const BASE_ROLE_LABELS: Record<string, string> = {
  super_admin: "Admin",
  admin: "Manager",
  user: "Team Member",
};

export default function RolesPermissions() {
  const { session, isSuperAdmin } = useAuth();
  const { business } = useBusiness();
  const token = session?.access_token ?? "";
  const businessId = business?.id ?? "";
  const isAdminUser = isSuperAdmin();

  const [roles, setRoles] = useState<CustomRole[]>([]);
  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);
  const [permissions, setPermissions] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // New Role dialog
  const [newRoleOpen, setNewRoleOpen] = useState(false);
  const [newRoleName, setNewRoleName] = useState("");
  const [newRoleBase, setNewRoleBase] = useState<"super_admin" | "admin" | "user">("user");
  const [newRoleDesc, setNewRoleDesc] = useState("");
  const [creating, setCreating] = useState(false);

  const fetchRoles = useCallback(async () => {
    if (!token || !businessId) return;
    const data = await listCustomRoles(token, businessId);
    setRoles(data);
    if (!selectedRoleId && data.length > 0) setSelectedRoleId(data[0].id);
  }, [token, businessId, selectedRoleId]);

  useEffect(() => {
    setLoading(true);
    fetchRoles().finally(() => setLoading(false));
  }, [token, businessId]);

  useEffect(() => {
    if (!selectedRoleId || !token) return;
    getRolePermissions(token, selectedRoleId).then((resp) => {
      const map: Record<string, boolean> = {};
      for (const p of resp.permissions) map[p.page_key] = p.is_allowed;
      setPermissions(map);
    });
  }, [selectedRoleId, token]);

  const togglePermission = async (pageKey: string, current: boolean) => {
    if (!selectedRoleId || !isAdminUser) return;
    const updated = { ...permissions, [pageKey]: !current };
    setPermissions(updated);
    setSaving(true);
    try {
      const perms: PagePermission[] = Object.entries(updated).map(([page_key, is_allowed]) => ({ page_key, is_allowed }));
      await updateRolePermissions(token, selectedRoleId, perms);
    } catch {
      toast.error("Failed to save permission");
      setPermissions({ ...permissions }); // revert
    } finally {
      setSaving(false);
    }
  };

  const handleCreateRole = async () => {
    if (!newRoleName.trim()) return;
    setCreating(true);
    try {
      await createCustomRole(token, businessId, {
        name: newRoleName.trim(),
        description: newRoleDesc.trim() || undefined,
        base_role: newRoleBase,
      });
      toast.success(`Role "${newRoleName}" created`);
      setNewRoleOpen(false);
      setNewRoleName("");
      setNewRoleDesc("");
      setNewRoleBase("user");
      await fetchRoles();
    } catch {
      toast.error("Failed to create role");
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteRole = async (role: CustomRole) => {
    if (!confirm(`Delete role "${role.name}"? This cannot be undone.`)) return;
    try {
      await deleteCustomRole(token, role.id);
      toast.success(`Role "${role.name}" deleted`);
      if (selectedRoleId === role.id) setSelectedRoleId(null);
      await fetchRoles();
    } catch {
      toast.error("Failed to delete role");
    }
  };

  const selectedRole = roles.find((r) => r.id === selectedRoleId);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="animate-spin text-muted-foreground" size={24} />
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Roles & Permissions</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Control which pages each role can access.
          </p>
        </div>
        {isAdminUser && (
          <Button onClick={() => setNewRoleOpen(true)}>
            <Plus size={14} className="mr-2" /> New Role
          </Button>
        )}
      </div>

      {/* Role tabs */}
      <div className="flex gap-2 mb-6 flex-wrap">
        {roles.map((role) => (
          <button
            key={role.id}
            onClick={() => setSelectedRoleId(role.id)}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-sm transition-colors ${
              selectedRoleId === role.id
                ? "bg-accent text-accent-foreground border-accent"
                : "bg-card border-border text-foreground hover:bg-muted/50"
            }`}
          >
            <Shield size={14} />
            {role.name}
            {role.is_system && (
              <Badge variant="secondary" className="text-xs ml-1">System</Badge>
            )}
            {!role.is_system && isAdminUser && (
              <span
                onClick={(e) => { e.stopPropagation(); handleDeleteRole(role); }}
                className="ml-1 text-muted-foreground hover:text-destructive"
              >
                <Trash2 size={12} />
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Selected role description */}
      {selectedRole && (
        <p className="text-sm text-muted-foreground mb-4">
          <span className="font-medium text-foreground">{selectedRole.name}</span>
          {selectedRole.description ? ` — ${selectedRole.description}` : ""}
          {" "}
          <span className="text-xs">
            (Based on: {BASE_ROLE_LABELS[selectedRole.base_role] ?? selectedRole.base_role})
          </span>
          {saving && <span className="ml-2 text-xs text-muted-foreground italic">Saving…</span>}
        </p>
      )}

      {/* Permissions matrix */}
      <div className="bg-card rounded-xl border border-border shadow-card overflow-hidden">
        <div className="p-4 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">Page Access</h2>
          <p className="text-xs text-muted-foreground">
            {isAdminUser ? "Click a checkbox to toggle access." : "Read-only view of page access."}
          </p>
        </div>

        <div className="divide-y divide-border/50">
          {GROUPS.map((group) => (
            <div key={group}>
              <div className="px-4 pt-4 pb-1">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{group}</span>
              </div>
              {ALL_PAGES.filter((p) => p.group === group).map((page) => {
                const allowed = permissions[page.path] ?? true;
                return (
                  <div
                    key={page.path}
                    className="flex items-center justify-between px-4 py-2.5 hover:bg-muted/20"
                  >
                    <span className="text-sm text-foreground">{page.label}</span>
                    <Checkbox
                      checked={allowed}
                      onCheckedChange={isAdminUser ? () => togglePermission(page.path, allowed) : undefined}
                      className={isAdminUser ? "cursor-pointer" : "pointer-events-none opacity-70"}
                    />
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>

      {/* New Role dialog */}
      <Dialog open={newRoleOpen} onOpenChange={setNewRoleOpen}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Create New Role</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1">
              <Label>Role Name</Label>
              <Input
                placeholder="e.g. Receptionist"
                value={newRoleName}
                onChange={(e) => setNewRoleName(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label>Based on</Label>
              <Select value={newRoleBase} onValueChange={(v) => setNewRoleBase(v as typeof newRoleBase)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="super_admin">Admin</SelectItem>
                  <SelectItem value="admin">Manager</SelectItem>
                  <SelectItem value="user">Team Member</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">Starts with the same permissions as the selected base role.</p>
            </div>
            <div className="space-y-1">
              <Label>Description <span className="text-muted-foreground">(optional)</span></Label>
              <Input
                placeholder="Brief description of this role"
                value={newRoleDesc}
                onChange={(e) => setNewRoleDesc(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setNewRoleOpen(false)}>Cancel</Button>
            <Button onClick={handleCreateRole} disabled={!newRoleName.trim() || creating}>
              {creating ? <Loader2 className="animate-spin mr-2" size={14} /> : null}
              Create Role
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx tsc --noEmit 2>&1
```

Expected: no output (no errors).

- [ ] **Step 3: Commit**

```bash
git add src/pages/dashboard/RolesPermissions.tsx
git commit -m "feat: make Roles & Permissions page editable — toggle checkboxes, new/delete role"
```

---

## Testing Checklist

- [ ] Log in as super_admin → all nav items visible including Global Settings, Billing, Phone Numbers, Roles & Permissions
- [ ] Log in as admin (Manager) → Global Settings, Locations, Billing, Phone Numbers, Roles & Permissions hidden
- [ ] Log in as user (Team Member) → only operational pages visible
- [ ] As user, type `/dashboard/settings/global` in URL → redirected to `/dashboard`
- [ ] Roles & Permissions page shows 3 role tabs (Admin, Manager, Team Member)
- [ ] Clicking a different role tab loads that role's permissions
- [ ] As super_admin, toggle a checkbox → spinner shows → page reloads with updated state
- [ ] After toggling, refresh the page → checkbox state persists (DB persisted)
- [ ] Click "New Role" → dialog opens → create "Receptionist" based on "Team Member" → appears as tab
- [ ] Delete the custom role → tab disappears
- [ ] System roles (Admin, Manager, Team Member) have no delete button
- [ ] Backend `GET /roles?business_id=<id>` without auth → 403

---

## Notes

- Custom role *assignment* to users (via `custom_role_id` on `user_roles`) is NOT in this plan. Roles created here appear in the UI but can't yet be assigned to staff members. That's a follow-up.
- The `useRolePermissions` hook fetches permissions on login and caches in context. If an admin edits permissions, other logged-in users see the change on next login (not live-refreshed — acceptable for MVP).
- RLS on `role_page_permissions` allows all business members to read their own role's permissions, but only admins can write.
