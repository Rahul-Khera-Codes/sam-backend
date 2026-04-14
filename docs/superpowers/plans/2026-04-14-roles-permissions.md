# Roles & Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded 3-role system (super_admin/admin/user) with a client-facing role model (Admin/Manager/Team Member), enforce page-level visibility from the permissions spreadsheet, add route-level protection, replace "Permissions" menu with "Manage Services" in Team Management, and build a Roles & Permissions admin page for future custom roles.

**Architecture:** The 3-role enum stays in the DB (`app_role`) but the UI relabels them: super_admin→Admin, admin→Manager, user→Team Member. Sidebar, ProtectedRoute, and Team Management all use a single `ROLE_PAGE_ACCESS` map derived from the client's spreadsheet. A new Roles & Permissions page (Admin-only) shows a read-only matrix of page-level visibility for the 3 default roles, with the CRUD foundation for custom roles in a future phase.

**Tech Stack:** React/TypeScript, FastAPI, Supabase (PostgreSQL), existing `user_roles` table with `app_role` enum

---

## Design Decisions

| Decision | Choice | Why |
|---|---|---|
| Keep `app_role` enum as-is | Yes — `super_admin`, `admin`, `user` stay in DB | Changing the enum means rewriting 30+ RLS policies. Too risky for the value. Instead, map display labels in the frontend. |
| Display labels | Admin = super_admin, Manager = admin, Team Member = user | Client's naming from the spreadsheet |
| Page-level permissions | Static map in a shared constant file, not DB-driven for v1 | The spreadsheet defines a fixed matrix. DB-driven custom roles is a v2 feature. |
| Route protection | `ProtectedRoute` gains a `requiredRoles` prop | Prevents URL-guessing bypasses |
| Team Management menu | Replace "Permissions" with "Manage Services" | Client spec. PermissionsDialog stays in codebase but is no longer accessible from the menu (can be re-wired later if needed). |
| Roles & Permissions page | Read-only matrix + CRUD UI shell for v1 | Shows the current permissions visually. Custom role editing is a v2 feature (needs `custom_roles` + `role_permissions` tables). |
| Backend role enforcement | Add a reusable `require_role` dependency | Standardizes the pattern currently done ad-hoc in 3 routers |

---

## Current State Reference

### Role Enum (DB)
```sql
CREATE TYPE public.app_role AS ENUM ('super_admin', 'admin', 'user');
```

### Sidebar Roles (Current)
```
Global Settings       → super_admin
Business Settings     → super_admin, admin
Account Settings      → all
Locations             → super_admin, admin
Team                  → super_admin, admin
Billing               → super_admin
Phone Numbers         → super_admin, admin
All other pages       → all
```

### Client's Desired Matrix (from spreadsheet)
```
                          Admin(super_admin)  Manager(admin)  Team Member(user)
Dashboard                      ✅                 ✅              ✅
Calendar                       ✅                 ✅              ✅
Customer Service Employee      ✅                 ✅              ✅
Marketing Employee             ✅                 ✅              ✅
Sales Employee                 ✅                 ✅              ✅
Human Resource Employee        ✅                 ✅              ✅
Executive Assistant Employee   ✅                 ✅              ✅
Support                        ✅                 ✅              ✅
Wishlist                       ✅                 ✅              ✅
Tutorials                      ✅                 ✅              ✅
Global Settings                ✅
Business Settings              ✅                 ✅
Location Settings              ✅
Account Settings               ✅                 ✅              ✅
Team Management                ✅                 ✅
Roles & Permissions            ✅
Phone Numbers                  ✅
Billing                        ✅
```

### Differences from Current
| Page | Current | Desired | Change Needed |
|---|---|---|---|
| Locations | super_admin, admin | super_admin only | **Remove admin** |
| Phone Numbers | super_admin, admin | super_admin only | **Remove admin** |
| Roles & Permissions | doesn't exist | super_admin only | **New page** |
| All other pages | same | same | No change |

---

## File Structure

### Shared Constants (new)
- `ai-employees-app/src/lib/roles.ts` — role labels, role-page access map, helper functions

### Frontend Files (modify)
- `ai-employees-app/src/components/layout/Sidebar.tsx` — use shared access map instead of inline `roles` arrays
- `ai-employees-app/src/components/auth/ProtectedRoute.tsx` — add optional `requiredRoles` prop for route-level enforcement
- `ai-employees-app/src/App.tsx` — add `requiredRoles` to role-restricted routes
- `ai-employees-app/src/pages/dashboard/TeamManagement.tsx` — replace "Permissions" menu item with "Manage Services", update role labels in Change Role modal
- `ai-employees-app/src/contexts/AuthContext.tsx` — no structural changes; `isSuperAdmin`/`isAdmin` stay as-is

### Frontend Files (new)
- `ai-employees-app/src/pages/dashboard/RolesPermissions.tsx` — new page showing permissions matrix + role list
- `ai-employees-app/src/components/team/ManageServicesDialog.tsx` — dialog to assign services to a team member (replaces Permissions in the context menu)

### Backend Files (modify)
- `backend/app/core/auth.py` — add reusable `require_role(roles)` dependency
- `backend/app/routers/settings.py` — use `require_role` instead of ad-hoc checks where applicable

---

## Phase 1: Shared Role Constants

### Task 1: Create `roles.ts` shared constants

**Files:**
- Create: `ai-employees-app/src/lib/roles.ts`

- [ ] **Step 1: Write the constants file**

```typescript
/**
 * Centralized role definitions and page-level access map.
 * Source of truth: client's Roles & Permissions spreadsheet.
 *
 * DB values: 'super_admin' | 'admin' | 'user'
 * Display:   'Admin'       | 'Manager' | 'Team Member'
 */

export type AppRole = "super_admin" | "admin" | "user";

export const ROLE_LABELS: Record<AppRole, string> = {
  super_admin: "Admin",
  admin: "Manager",
  user: "Team Member",
};

export const ROLE_OPTIONS: { value: AppRole; label: string }[] = [
  { value: "super_admin", label: "Admin" },
  { value: "admin", label: "Manager" },
  { value: "user", label: "Team Member" },
];

/**
 * Page-level visibility per role.
 * Key = route path suffix (matched against location.pathname).
 * Value = list of roles that can see/access this page.
 *
 * Pages not listed here are accessible to ALL authenticated roles.
 */
export const RESTRICTED_PAGES: Record<string, AppRole[]> = {
  // Settings — Admin only
  "/dashboard/settings/global":       ["super_admin"],
  "/dashboard/settings/locations":    ["super_admin"],
  "/dashboard/settings/phone-numbers":["super_admin"],
  "/dashboard/settings/billing":      ["super_admin"],
  "/dashboard/roles-permissions":     ["super_admin"],

  // Settings — Admin + Manager
  "/dashboard/settings/business":     ["super_admin", "admin"],
  "/dashboard/team":                  ["super_admin", "admin"],
};

/**
 * Sidebar nav item role arrays — derived from RESTRICTED_PAGES.
 * If a path isn't in RESTRICTED_PAGES, it's visible to all roles.
 */
export function getRolesForPath(path: string): AppRole[] | undefined {
  return RESTRICTED_PAGES[path];
}

/**
 * Check whether a user with the given role can access a path.
 */
export function canAccessPath(role: AppRole, path: string): boolean {
  const allowed = RESTRICTED_PAGES[path];
  if (!allowed) return true; // unrestricted page
  return allowed.includes(role);
}
```

- [ ] **Step 2: Commit**

```bash
git add src/lib/roles.ts
git commit -m "feat: add centralized role constants and page-access map"
```

---

## Phase 2: Sidebar + Route Protection

### Task 2: Update Sidebar to use shared role map

**Files:**
- Modify: `ai-employees-app/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Replace inline `roles` arrays with the shared map**

Import the helper:
```typescript
import { getRolesForPath } from "@/lib/roles";
```

Update each nav item definition. Replace the hardcoded `roles` property with a computed one:

```typescript
const settingsNavItems = [
  { icon: Settings, label: "Global Settings",    path: "/dashboard/settings/global" },
  { icon: Building2, label: "Business Settings", path: "/dashboard/settings/business" },
  { icon: User, label: "Account Settings",       path: "/dashboard/settings/account" },
  { icon: MapPin, label: "Locations",             path: "/dashboard/settings/locations" },
  { icon: Users, label: "Team",                   path: "/dashboard/team" },
  { icon: CreditCard, label: "Billing",           path: "/dashboard/settings/billing" },
  { icon: Phone, label: "Phone Numbers",          path: "/dashboard/settings/phone-numbers" },
];
```

When rendering, filter by the user's role:
```typescript
const { roles } = useAuth();
const userRole = roles[0]?.role as AppRole | undefined;

// Filter nav items
const visibleSettings = settingsNavItems.filter((item) => {
  const allowed = getRolesForPath(item.path);
  if (!allowed) return true;
  return userRole && allowed.includes(userRole);
});
```

Remove the old inline `roles: [...]` property from each nav item definition.

- [ ] **Step 2: Commit**

```bash
git add src/components/layout/Sidebar.tsx
git commit -m "feat: sidebar uses shared role-page access map"
```

---

### Task 3: Add role-based route protection to ProtectedRoute

**Files:**
- Modify: `ai-employees-app/src/components/auth/ProtectedRoute.tsx`

- [ ] **Step 1: Add `requiredRoles` prop**

```typescript
import { type AppRole, RESTRICTED_PAGES, canAccessPath } from "@/lib/roles";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRoles?: AppRole[];  // if set, overrides path-based lookup
}
```

After existing auth/MFA checks, add role check:

```typescript
// Role check — block access if user's role isn't in the allowed list
const userRole = roles[0]?.role as AppRole | undefined;
const currentPath = location.pathname;

// Use explicit requiredRoles prop, or derive from path map
const allowed = requiredRoles ?? RESTRICTED_PAGES[currentPath];
if (allowed && userRole && !allowed.includes(userRole)) {
  return <Navigate to="/dashboard" replace />;
}
```

This means typing `/dashboard/settings/global` in the address bar as a `user` role redirects to the dashboard instead of showing the page.

- [ ] **Step 2: Commit**

```bash
git add src/components/auth/ProtectedRoute.tsx
git commit -m "feat: ProtectedRoute enforces role-based page access"
```

---

## Phase 3: Team Management Updates

### Task 4: Replace "Permissions" menu with "Manage Services"

**Files:**
- Modify: `ai-employees-app/src/pages/dashboard/TeamManagement.tsx`
- Create: `ai-employees-app/src/components/team/ManageServicesDialog.tsx`

- [ ] **Step 1: Create ManageServicesDialog**

This dialog lets an admin assign which services a staff member can perform, using the existing `user_services` junction table.

```typescript
import { useEffect, useState } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { supabase } from "@/integrations/supabase/client";
import { useServices } from "@/hooks/useServices";
import { toast } from "sonner";

interface Props {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  userId: string;
  userName: string;
}

export function ManageServicesDialog({ open, onOpenChange, userId, userName }: Props) {
  const { services } = useServices();
  const [assignedIds, setAssignedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !userId) return;
    setLoading(true);
    supabase
      .from("user_services")
      .select("service_id")
      .eq("user_id", userId)
      .then(({ data }) => {
        setAssignedIds((data || []).map((r) => r.service_id));
        setLoading(false);
      });
  }, [open, userId]);

  const toggle = async (serviceId: string, enabled: boolean) => {
    if (enabled) {
      await supabase.from("user_services").insert({ user_id: userId, service_id: serviceId });
      setAssignedIds((prev) => [...prev, serviceId]);
    } else {
      await supabase.from("user_services").delete().eq("user_id", userId).eq("service_id", serviceId);
      setAssignedIds((prev) => prev.filter((id) => id !== serviceId));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Manage Services — {userName}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2 py-2 max-h-80 overflow-y-auto">
          {loading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : services.length === 0 ? (
            <p className="text-sm text-muted-foreground">No services configured.</p>
          ) : (
            services.map((svc) => (
              <div key={svc.id} className="flex items-center justify-between p-2 border rounded-lg">
                <div>
                  <p className="text-sm font-medium">{svc.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {svc.duration_minutes} min{svc.price && Number(svc.price) > 0 ? ` — $${svc.price}` : ""}
                  </p>
                </div>
                <Switch
                  checked={assignedIds.includes(svc.id)}
                  onCheckedChange={(checked) => toggle(svc.id, checked)}
                />
              </div>
            ))
          )}
        </div>
        <DialogFooter>
          <Button onClick={() => { onOpenChange(false); toast.success("Services updated"); }}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Replace "Permissions" menu item in TeamManagement.tsx**

Find the DropdownMenuItem for "Permissions" (around line 347) and replace:

Before:
```typescript
<DropdownMenuItem onClick={() => { setSelectedMember(member); setPermissionsOpen(true); }}>
  <Shield size={14} className="mr-2" /> Permissions
</DropdownMenuItem>
```

After:
```typescript
<DropdownMenuItem onClick={() => { setSelectedMember(member); setManageServicesOpen(true); }}>
  <Briefcase size={14} className="mr-2" /> Manage Services
</DropdownMenuItem>
```

Add state:
```typescript
const [manageServicesOpen, setManageServicesOpen] = useState(false);
```

Add dialog at the end of JSX:
```typescript
{selectedMember && (
  <ManageServicesDialog
    open={manageServicesOpen}
    onOpenChange={setManageServicesOpen}
    userId={selectedMember.id}
    userName={`${selectedMember.first_name ?? ""} ${selectedMember.last_name ?? ""}`.trim()}
  />
)}
```

- [ ] **Step 3: Update role labels in Change Role modal**

In the Change Role dropdown (around lines 527-530), replace raw DB values with display labels:

```typescript
import { ROLE_OPTIONS } from "@/lib/roles";

// In the role selection dropdown:
{ROLE_OPTIONS.map((opt) => (
  <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
))}
```

Also update the role badge displayed on each team member card to use `ROLE_LABELS`:
```typescript
import { ROLE_LABELS, type AppRole } from "@/lib/roles";

// Where role is displayed:
<Badge>{ROLE_LABELS[member.role as AppRole] ?? member.role}</Badge>
```

- [ ] **Step 4: Commit**

```bash
git add src/components/team/ManageServicesDialog.tsx src/pages/dashboard/TeamManagement.tsx
git commit -m "feat: replace Permissions with Manage Services, relabel roles"
```

---

## Phase 4: Roles & Permissions Page

### Task 5: Create the Roles & Permissions page

**Files:**
- Create: `ai-employees-app/src/pages/dashboard/RolesPermissions.tsx`
- Modify: `ai-employees-app/src/App.tsx` — add route
- Modify: `ai-employees-app/src/components/layout/Sidebar.tsx` — add nav item

- [ ] **Step 1: Write the page**

This page shows a read-only permissions matrix matching the spreadsheet. For v1 it's informational — admins can see who can access what. The "+ New Role" button and edit functionality are disabled/placeholder for v2 (custom roles).

```typescript
import { Shield, Plus, Lock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ROLE_OPTIONS, RESTRICTED_PAGES, type AppRole } from "@/lib/roles";
import { toast } from "sonner";

const ALL_PAGES = [
  // Main
  { path: "/dashboard", label: "Dashboard", group: "Main" },
  { path: "/dashboard/calendar", label: "Calendar", group: "Main" },
  { path: "/dashboard/customer-service/dashboard", label: "Customer Service Employee", group: "Main" },
  { path: "/dashboard/marketing", label: "Marketing Employee", group: "Main" },
  { path: "/dashboard/sales", label: "Sales Employee", group: "Main" },
  { path: "/dashboard/hr", label: "Human Resource Employee", group: "Main" },
  { path: "/dashboard/executive", label: "Executive Assistant Employee", group: "Main" },
  // Help
  { path: "/dashboard/support", label: "Support", group: "Help" },
  { path: "/dashboard/support?mode=wishlist", label: "Wishlist", group: "Help" },
  { path: "/dashboard/tutorials", label: "Tutorials", group: "Help" },
  // Settings
  { path: "/dashboard/settings/global", label: "Global Settings", group: "Settings" },
  { path: "/dashboard/settings/business", label: "Business Settings", group: "Settings" },
  { path: "/dashboard/settings/locations", label: "Location Settings", group: "Settings" },
  { path: "/dashboard/settings/account", label: "Account Settings", group: "Settings" },
  { path: "/dashboard/team", label: "Team Management", group: "Settings" },
  { path: "/dashboard/roles-permissions", label: "Roles & Permissions", group: "Settings" },
  { path: "/dashboard/settings/phone-numbers", label: "Phone Numbers", group: "Settings" },
  { path: "/dashboard/settings/billing", label: "Billing", group: "Settings" },
];

function hasAccess(role: AppRole, path: string): boolean {
  const restricted = RESTRICTED_PAGES[path];
  if (!restricted) return true;
  return restricted.includes(role);
}

const groups = ["Main", "Help", "Settings"];

export default function RolesPermissions() {
  return (
    <div className="animate-fade-in">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Roles & Permissions</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            View which pages and features each role can access.
          </p>
        </div>
        <Button variant="outline" disabled onClick={() => toast.info("Custom roles coming soon.")}>
          <Plus size={14} className="mr-2" /> New Role
        </Button>
      </div>

      {/* Role cards */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {ROLE_OPTIONS.map((r) => (
          <div key={r.value} className="bg-card rounded-xl border border-border p-4 shadow-card">
            <div className="flex items-center gap-2 mb-1">
              <Shield size={16} className="text-accent" />
              <h3 className="font-semibold text-foreground">{r.label}</h3>
            </div>
            <p className="text-xs text-muted-foreground">
              {r.value === "super_admin" && "Full access to all pages and settings."}
              {r.value === "admin" && "Can manage business settings, team, and daily operations."}
              {r.value === "user" && "Can access operational pages and personal settings."}
            </p>
          </div>
        ))}
      </div>

      {/* Permissions matrix */}
      <div className="bg-card rounded-xl border border-border shadow-card overflow-hidden">
        <div className="p-4 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">Page Access Matrix</h2>
          <p className="text-xs text-muted-foreground">Which pages each role can see</p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/30">
                <th className="text-left py-2 px-4 font-medium text-muted-foreground w-1/2">Page</th>
                {ROLE_OPTIONS.map((r) => (
                  <th key={r.value} className="text-center py-2 px-4 font-medium text-muted-foreground w-1/6">
                    {r.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <>
                  <tr key={`group-${group}`}>
                    <td colSpan={4} className="px-4 pt-4 pb-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      {group}
                    </td>
                  </tr>
                  {ALL_PAGES.filter((p) => p.group === group).map((page) => (
                    <tr key={page.path} className="border-b border-border/50 hover:bg-muted/20">
                      <td className="py-2 px-4 text-foreground">{page.label}</td>
                      {ROLE_OPTIONS.map((r) => (
                        <td key={r.value} className="text-center py-2 px-4">
                          <Checkbox checked={hasAccess(r.value, page.path)} disabled className="pointer-events-none" />
                        </td>
                      ))}
                    </tr>
                  ))}
                </>
              ))}
            </tbody>
          </table>
        </div>

        <div className="p-4 bg-muted/20 border-t border-border flex items-center gap-2 text-xs text-muted-foreground">
          <Lock size={12} />
          <span>This matrix reflects the default role configuration. Custom roles with editable permissions are coming in a future update.</span>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add route in App.tsx**

```typescript
import RolesPermissions from "./pages/dashboard/RolesPermissions";

// Inside dashboard routes:
<Route path="roles-permissions" element={<RolesPermissions />} />
```

- [ ] **Step 3: Add to Sidebar**

In the settings nav items, add after "Team":
```typescript
{ icon: Shield, label: "Roles & Permissions", path: "/dashboard/roles-permissions" },
```

Import `Shield` from `lucide-react`.

- [ ] **Step 4: Commit**

```bash
git add src/pages/dashboard/RolesPermissions.tsx src/App.tsx src/components/layout/Sidebar.tsx
git commit -m "feat: add Roles & Permissions page (read-only matrix)"
```

---

## Phase 5: Backend — Reusable Role Dependency

### Task 6: Add `require_role` dependency

**Files:**
- Modify: `backend/app/core/auth.py`

- [ ] **Step 1: Add the dependency**

```python
from typing import Sequence

def require_role(*allowed_roles: str):
    """
    FastAPI dependency that verifies the authenticated user has one of
    the allowed roles (from user_roles table). Usage:

        @router.post("/foo")
        async def foo(business_id: str = Depends(require_role("super_admin", "admin"))):
            ...

    Returns business_id if the check passes.
    """
    from app.core.supabase import supabase_admin

    def _check(user_id: str = Depends(get_user_id)) -> str:
        role_row = (
            supabase_admin.table("user_roles")
            .select("business_id, role")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not role_row.data:
            raise HTTPException(status_code=403, detail="User has no role assigned")
        if role_row.data[0]["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires one of: {', '.join(allowed_roles)}",
            )
        return role_row.data[0]["business_id"]

    return _check
```

- [ ] **Step 2: Refactor existing routers to use it**

In `phone_numbers.py`, `custom_schedules.py`, and `locations.py`, replace the inline role-check pattern:

Before:
```python
role_row = supabase_admin.table("user_roles").select("business_id, role").eq("user_id", user_id).limit(1).execute()
if not role_row.data:
    raise HTTPException(status_code=403, detail="User has no role assigned")
if role_row.data[0]["role"] not in ("super_admin", "admin"):
    raise HTTPException(status_code=403, detail="Only admins can ...")
business_id = role_row.data[0]["business_id"]
```

After:
```python
from app.core.auth import require_role

@router.post("/provision", status_code=201)
async def provision_number(
    body: ProvisionRequest,
    business_id: str = Depends(require_role("super_admin", "admin")),
):
    ...
```

This is a refactor with no behavior change — just standardization.

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/auth.py backend/app/routers/phone_numbers.py backend/app/routers/custom_schedules.py backend/app/routers/locations.py
git commit -m "feat: add require_role dependency; refactor ad-hoc role checks"
```

---

## Phase 6 (Future — v2): Custom Roles

> **This phase is NOT being implemented now.** It's documented here for future planning.

### What's Needed for Custom Roles

1. **New DB tables:**

```sql
CREATE TABLE custom_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    is_system BOOLEAN NOT NULL DEFAULT false,  -- true for the 3 defaults
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(business_id, name)
);

CREATE TABLE role_page_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role_id UUID NOT NULL REFERENCES custom_roles(id) ON DELETE CASCADE,
    page_key TEXT NOT NULL,
    is_allowed BOOLEAN NOT NULL DEFAULT false,
    UNIQUE(role_id, page_key)
);
```

2. **Migrate existing roles:**
- Seed 3 rows into `custom_roles` per business: Admin, Manager, Team Member (`is_system=true`)
- Populate `role_page_permissions` from the static spreadsheet matrix
- `user_roles.role` still uses the enum for RLS compatibility, but a new `custom_role_id UUID` column links to `custom_roles` for resolution

3. **Dynamic sidebar + ProtectedRoute:**
- Replace the static `RESTRICTED_PAGES` map with a DB-driven permission resolver
- `useAuth` fetches the user's resolved page permissions on login

4. **Roles & Permissions page becomes editable:**
- CRUD for custom_roles (non-system only)
- Toggle checkboxes save to `role_page_permissions`
- "New Role" button is enabled
- System roles (Admin/Manager/Team Member) are non-deletable but their permissions can be customized

5. **RLS changes:**
- Keep `app_role` enum for backward compatibility
- Add a `custom_role_id` column to `user_roles`
- Policies can optionally check `custom_role_id` → `role_page_permissions` for finer control

This is estimated at 3-5 days of work and should be planned as its own project.

---

## Execution Order Summary

| Phase | Tasks | Description | Effort |
|---|---|---|---|
| **Phase 1** | Task 1 | Shared role constants + page-access map | 15 min |
| **Phase 2** | Tasks 2-3 | Sidebar uses map + ProtectedRoute enforces roles | 30 min |
| **Phase 3** | Task 4 | Team Management: replace Permissions → Manage Services, relabel roles | 45 min |
| **Phase 4** | Task 5 | Roles & Permissions page (read-only matrix) | 45 min |
| **Phase 5** | Task 6 | Backend require_role dependency + refactor | 30 min |
| **Phase 6** | — | Custom roles (v2, future) | 3-5 days |

**Total for Phases 1-5:** ~3 hours

---

## Testing Checklist

- [ ] Log in as super_admin → see all nav items including Global Settings, Locations, Billing, Phone Numbers, Roles & Permissions
- [ ] Log in as admin (Manager) → see Business Settings + Team Management; NOT see Global Settings, Locations, Phone Numbers, Billing, Roles & Permissions
- [ ] Log in as user (Team Member) → see Dashboard, Calendar, all Employees, Support, Wishlist, Tutorials, Account Settings; NOT see any other settings
- [ ] As user, type `/dashboard/settings/global` in URL bar → redirected to `/dashboard`
- [ ] As admin, type `/dashboard/settings/billing` in URL bar → redirected to `/dashboard`
- [ ] Team Management → 3-dot menu → "Manage Services" opens service assignment dialog (not Permissions)
- [ ] Team Management → Change Role modal shows "Admin / Manager / Team Member" (not super_admin/admin/user)
- [ ] Roles & Permissions page shows the correct matrix matching the spreadsheet
- [ ] "+ New Role" button is disabled with "coming soon" toast
- [ ] Backend: call `POST /phone-numbers/provision` as a `user` role → 403
- [ ] Backend: call `POST /custom-schedules` as a `user` role → 403
