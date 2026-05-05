# TC Bug Fixes (TC-ROLES-002 + TC-TEAM-006) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two pre-launch QA bugs: permission toggles saving to the wrong role (stale closure), and Remove User firing immediately with no confirmation dialog.

**Architecture:** Both are frontend-only fixes in `ai-employees-app`. TC-ROLES-002 eliminates a React state closure bug by passing the role ID explicitly at the call site instead of reading it from state inside the handler. TC-TEAM-006 adds an AlertDialog confirmation gate before the remove action fires. No backend changes needed.

**Tech Stack:** React, TypeScript, shadcn/ui (AlertDialog, Dialog), Sonner toasts

---

## File Map

| File | Change |
|---|---|
| `src/pages/dashboard/TeamManagement.tsx` | TC-TEAM-006: add `memberToRemove` state + AlertDialog confirm |
| `src/pages/dashboard/RolesPermissions.tsx` | TC-ROLES-002: pass `roleId` explicitly to `togglePermission` |

---

## Context (read before starting)

**Repo:** `/home/lap-68/Documents/gt-rahul/ai-employees-app`
**Branch:** `feature/strip-integration`

### TC-TEAM-006 bug
`TeamManagement.tsx:375` — the DropdownMenuItem for Remove User calls `handleRemoveUser(member)` directly in `onClick`. No confirmation step. If the user mis-clicks it, the user is removed immediately.

### TC-ROLES-002 bug
`RolesPermissions.tsx` — `togglePermission` is defined as:
```tsx
const togglePermission = async (pageKey: string, current: boolean) => {
  if (!selectedRoleId || !isAdminUser) return;
  // ...
  await updateRolePermissions(token, selectedRoleId, perms);
};
```
It reads `selectedRoleId` from the component's state closure. When the user switches to a different role tab, React schedules a re-render but the old closure is still attached to the checkbox's `onCheckedChange`. If a checkbox is toggled while the render is in flight, `selectedRoleId` in the closure is the old value — so the PUT goes to the wrong role.

Fix: pass `roleId` explicitly as a parameter, captured at the call site from `selectedRole.id`. Since checkboxes only render inside `{selectedRole && (...)}`, `selectedRole.id` is always current in the render that produced those checkboxes.

---

### Task 1: TC-TEAM-006 — Remove User confirmation dialog

**Files:**
- Modify: `src/pages/dashboard/TeamManagement.tsx`

**What to do:** Add `memberToRemove` state. Change the DropdownMenuItem onClick to set that state instead of calling `handleRemoveUser` directly. Add an AlertDialog at the bottom of the JSX that shows when `memberToRemove` is set, with Cancel and Confirm buttons.

- [ ] **Step 1: Add AlertDialog import**

Find the existing Dialog import block (around line 30):
```tsx
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
```

Add AlertDialog imports right after it:
```tsx
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
```

- [ ] **Step 2: Add `memberToRemove` state**

Find where `selectedMember` state is declared (around line 89):
```tsx
const [selectedMember, setSelectedMember] = useState<TeamMember | null>(null);
```

Add below it:
```tsx
const [memberToRemove, setMemberToRemove] = useState<TeamMember | null>(null);
```

- [ ] **Step 3: Change DropdownMenuItem onClick**

Find the Remove User DropdownMenuItem (around line 373):
```tsx
<DropdownMenuItem
  className="text-destructive focus:text-destructive"
  onClick={() => handleRemoveUser(member)}
>
  <Trash2 className="h-4 w-4" />
  <span className="ml-2">Remove User</span>
</DropdownMenuItem>
```

Replace the `onClick` only — do not change anything else:
```tsx
<DropdownMenuItem
  className="text-destructive focus:text-destructive"
  onClick={() => setMemberToRemove(member)}
>
  <Trash2 className="h-4 w-4" />
  <span className="ml-2">Remove User</span>
</DropdownMenuItem>
```

- [ ] **Step 4: Add AlertDialog at bottom of JSX**

Find the last closing tag in the component's return statement. It will be near `<TeamMemberHoursDialog ... />` (around line 621). Add the AlertDialog after it, before the final closing `</div>`:

```tsx
<AlertDialog
  open={memberToRemove !== null}
  onOpenChange={(open) => { if (!open) setMemberToRemove(null); }}
>
  <AlertDialogContent>
    <AlertDialogHeader>
      <AlertDialogTitle>Remove team member?</AlertDialogTitle>
      <AlertDialogDescription>
        This will remove{" "}
        <span className="font-medium">{memberToRemove?.name ?? "this user"}</span>{" "}
        from your business. They will lose all access immediately. This cannot be undone.
      </AlertDialogDescription>
    </AlertDialogHeader>
    <AlertDialogFooter>
      <AlertDialogCancel>Cancel</AlertDialogCancel>
      <AlertDialogAction
        className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
        onClick={async () => {
          if (memberToRemove) {
            await handleRemoveUser(memberToRemove);
            setMemberToRemove(null);
          }
        }}
      >
        Remove
      </AlertDialogAction>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

- [ ] **Step 5: Type-check**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx tsc --noEmit 2>&1 | grep TeamManagement
```

Expected: no errors for TeamManagement.tsx.

- [ ] **Step 6: Manual verification**

Start dev server if not running: `npm run dev`

Navigate to Team Management page. Click the `⋮` menu on any team member. Click "Remove User". **Verify:** an AlertDialog appears with the user's name, Cancel and Remove buttons. Click Cancel — dialog closes, user not removed. Click Remove — user is removed, toast appears.

- [ ] **Step 7: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/pages/dashboard/TeamManagement.tsx
git commit -m "$(cat <<'EOF'
fix: add confirmation dialog before removing team member (TC-TEAM-006)

Remove User now shows an AlertDialog with the member's name before
firing — prevents accidental removals from a mis-click.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: TC-ROLES-002 — Fix stale closure in togglePermission

**Files:**
- Modify: `src/pages/dashboard/RolesPermissions.tsx`

**What to do:** Change `togglePermission` to accept an explicit `roleId: string` as its first parameter. Update the call site to pass `selectedRole.id` directly. Remove the dependency on `selectedRoleId` state inside the function body.

- [ ] **Step 1: Update `togglePermission` signature and body**

Find `togglePermission` (around line 101):
```tsx
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
    setPermissions((prev) => ({ ...prev, [pageKey]: current })); // revert just this key
  } finally {
    setSaving(false);
  }
};
```

Replace entirely with:
```tsx
const togglePermission = async (roleId: string, pageKey: string, current: boolean) => {
  if (!roleId || !isAdminUser) return;
  const updated = { ...permissions, [pageKey]: !current };
  setPermissions(updated);
  setSaving(true);
  try {
    const perms: PagePermission[] = Object.entries(updated).map(([page_key, is_allowed]) => ({ page_key, is_allowed }));
    await updateRolePermissions(token, roleId, perms);
  } catch {
    toast.error("Failed to save permission");
    setPermissions((prev) => ({ ...prev, [pageKey]: current }));
  } finally {
    setSaving(false);
  }
};
```

- [ ] **Step 2: Update the call site**

Find the `onCheckedChange` on the Checkbox (around line 246):
```tsx
onCheckedChange={isAdminUser ? () => togglePermission(page.path, allowed) : undefined}
```

Replace with:
```tsx
onCheckedChange={isAdminUser ? () => togglePermission(selectedRole.id, page.path, allowed) : undefined}
```

Note: `selectedRole` is computed as `roles.find((r) => r.id === selectedRoleId)` and the checkbox block is inside `{selectedRole && (...)}`, so `selectedRole` is guaranteed non-null here. No optional chaining needed.

- [ ] **Step 3: Type-check**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx tsc --noEmit 2>&1 | grep RolesPermissions
```

Expected: no errors for RolesPermissions.tsx.

- [ ] **Step 4: Manual verification**

Navigate to Roles & Permissions page. Create or select a non-default role tab (e.g. a custom role). Click a different role tab. Immediately toggle a permission checkbox on the newly selected role. **Verify:** the PUT request in the network tab (or backend logs) targets the ID of the role tab you clicked — not the original auto-loaded role. Reload the page — the toggled permission persists on the correct role.

- [ ] **Step 5: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/pages/dashboard/RolesPermissions.tsx
git commit -m "$(cat <<'EOF'
fix: pass roleId explicitly to togglePermission to eliminate stale closure (TC-ROLES-002)

togglePermission was reading selectedRoleId from state closure, which
could be stale when tabs switched. Now receives roleId at the call site
from selectedRole.id which is always current in the render.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- ✅ TC-TEAM-006: AlertDialog blocks Remove User from firing immediately — Task 1
- ✅ TC-ROLES-002: togglePermission uses explicit roleId, no state closure — Task 2
- ✅ Both tasks independent — can be done in either order, no shared state

**Placeholder scan:** None found — all code is complete and exact.

**Type consistency:** `PagePermission` type is already used in the file at line 107, `togglePermission` signature change is consistent with its single call site at line 246. `TeamMember` type imported from `useTeamManagement` — `memberToRemove` uses the same type.
