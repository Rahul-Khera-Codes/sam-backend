# Pre-Release Checklist Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two gaps blocking real-world tester access — (1) call forwarding per-contact available hours so the agent refuses transfers outside configured times, and (2) the setup checklist in the Customer Service Employee page so items show real completion status and navigate to the correct settings page when clicked.

**Architecture:** Feature 1 adds two TEXT columns (`available_start`, `available_end`, 24h HH:MM) to `forwarding_contacts`, exposes them in the Add/Edit contact dialogs, and checks them in the agent's `forward_call` tool before executing a SIP REFER. Feature 2 replaces the hardcoded static checklist in `CustomerServiceEmployee.tsx` with real API-driven completion checks and click-to-navigate behaviour.

**Tech Stack:** FastAPI (Python), LiveKit Agents, Supabase PostgreSQL, React/TypeScript, Tailwind, shadcn/ui, react-router-dom

---

## File Map

| File | Change |
|------|--------|
| `ai-employees-app/supabase/migrations/20260428000000_forwarding_contact_hours.sql` | NEW — add `available_start`, `available_end` columns |
| `sam-backend/backend/app/schemas/settings.py` | MODIFY — add fields to Forwarding schemas |
| `ai-employees-app/src/lib/voiceAgentApi.ts` | MODIFY — add fields to `ForwardingContact` type |
| `ai-employees-app/src/pages/dashboard/customer-service/CallForwarding.tsx` | MODIFY — add time fields to Add/Edit dialogs |
| `sam-backend/agent/supabase_helpers.py` | MODIFY — fetch `available_start`/`available_end` in `_fetch_forwarding_contacts` |
| `sam-backend/agent/agent.py` | MODIFY — check available hours in `forward_call` before SIP REFER |
| `ai-employees-app/src/pages/dashboard/CustomerServiceEmployee.tsx` | MODIFY — real completion checks + navigation on each checklist item |

---

## Feature 1 — Per-Contact Available Hours

### Task 1: DB Migration

**Files:**
- Create: `ai-employees-app/supabase/migrations/20260428000000_forwarding_contact_hours.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Add optional available-hours window to forwarding contacts.
-- Times stored as HH:MM 24h TEXT (e.g. "09:00", "17:30").
-- Both columns must be set together; if either is NULL the contact is always available.
ALTER TABLE forwarding_contacts
  ADD COLUMN available_start TEXT DEFAULT NULL,
  ADD COLUMN available_end   TEXT DEFAULT NULL;
```

- [ ] **Step 2: Apply the migration**

Run in Supabase dashboard SQL editor or via CLI:
```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
supabase db push
```

Expected: migration runs cleanly, no errors.

- [ ] **Step 3: Commit**

```bash
git -C /home/lap-68/Documents/gt-rahul/ai-employees-app add supabase/migrations/20260428000000_forwarding_contact_hours.sql
git -C /home/lap-68/Documents/gt-rahul/ai-employees-app commit -m "feat: add available_start/available_end to forwarding_contacts"
```

---

### Task 2: Backend Schema

**Files:**
- Modify: `sam-backend/backend/app/schemas/settings.py`

- [ ] **Step 1: Add fields to all three Forwarding Contact schemas**

In `ForwardingContactResponse` add:
```python
available_start: Optional[str] = None
available_end: Optional[str] = None
```

In `CreateForwardingContactRequest` add:
```python
available_start: Optional[str] = None
available_end: Optional[str] = None
```

In `UpdateForwardingContactRequest` add:
```python
available_start: Optional[str] = None
available_end: Optional[str] = None
```

- [ ] **Step 2: Update `create_contact` in `forwarding.py` to persist the new fields**

In `sam-backend/backend/app/routers/forwarding.py`, the `create_contact` insert dict already uses `body.location_id`, `body.name`, etc. Add:
```python
"available_start": body.available_start,
"available_end": body.available_end,
```

The `update_contact` endpoint uses `body.model_dump(exclude_none=True)` which automatically includes the new fields when provided — no change needed there.

- [ ] **Step 3: Verify syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('backend/app/schemas/settings.py').read()); print('OK')"
python -c "import ast; ast.parse(open('backend/app/routers/forwarding.py').read()); print('OK')"
```

Expected: `OK` for both.

- [ ] **Step 4: Commit**

```bash
git -C /home/lap-68/Documents/gt-rahul/sam-backend add backend/app/schemas/settings.py backend/app/routers/forwarding.py
git -C /home/lap-68/Documents/gt-rahul/sam-backend commit -m "feat: expose available_start/available_end on forwarding contacts API"
```

---

### Task 3: Frontend Type + API

**Files:**
- Modify: `ai-employees-app/src/lib/voiceAgentApi.ts`

- [ ] **Step 1: Add fields to `ForwardingContact` interface**

Find the `ForwardingContact` interface (currently around line 416) and add two optional fields:

```typescript
export interface ForwardingContact {
  id: string;
  business_id: string;
  location_id?: string;
  name: string;
  phone: string;
  department_tag?: string;
  priority?: number;
  forwarding_rule?: string;
  available_start?: string;   // "HH:MM" 24h — null means always available
  available_end?: string;     // "HH:MM" 24h — null means always available
  is_active: boolean;
  created_at: string;
}
```

The `createForwardingContact` and `updateForwardingContact` functions already pass the full body object, so no body changes are needed — the new fields will flow through automatically.

- [ ] **Step 2: Commit**

```bash
git -C /home/lap-68/Documents/gt-rahul/ai-employees-app add src/lib/voiceAgentApi.ts
git -C /home/lap-68/Documents/gt-rahul/ai-employees-app commit -m "feat: add available_start/available_end to ForwardingContact type"
```

---

### Task 4: Frontend UI — Add/Edit Contact Dialogs

**Files:**
- Modify: `ai-employees-app/src/pages/dashboard/customer-service/CallForwarding.tsx`

- [ ] **Step 1: Add state for the new time fields in the Add dialog**

In the component, find the existing state declarations for `newName`, `newPhone`, `newTitle`, `newRule` and add alongside:
```tsx
const [newAvailStart, setNewAvailStart] = useState("");
const [newAvailEnd, setNewAvailEnd] = useState("");
```

And for the Edit dialog, find `editName`, `editPhone`, `editTitle`, `editRule` and add:
```tsx
const [editAvailStart, setEditAvailStart] = useState("");
const [editAvailEnd, setEditAvailEnd] = useState("");
```

- [ ] **Step 2: Populate edit state when opening an existing contact**

In `openEdit(c: ForwardingContact)`, add:
```tsx
setEditAvailStart(c.available_start ?? "");
setEditAvailEnd(c.available_end ?? "");
```

- [ ] **Step 3: Wire the new fields into the Add Contact dialog JSX**

Find the Add Contact `<Dialog>` content. After the existing "Rule" textarea `<div>`, add:

```tsx
<div className="space-y-1.5">
  <Label>Available Hours (optional)</Label>
  <p className="text-xs text-muted-foreground">
    Agent will refuse to transfer outside these times. Leave blank to always allow. Times in 24h UTC format.
  </p>
  <div className="flex items-center gap-2">
    <Input
      type="time"
      value={newAvailStart}
      onChange={(e) => setNewAvailStart(e.target.value)}
      className="w-36"
      placeholder="09:00"
    />
    <span className="text-muted-foreground text-sm">to</span>
    <Input
      type="time"
      value={newAvailEnd}
      onChange={(e) => setNewAvailEnd(e.target.value)}
      className="w-36"
      placeholder="17:00"
    />
  </div>
</div>
```

- [ ] **Step 4: Pass new fields in `handleAdd`**

In `handleAdd`, update the `createForwardingContact` call to include:
```tsx
const contact = await createForwardingContact(token, businessId!, {
  name: newName.trim(),
  phone: newPhone.trim(),
  department_tag: newTitle.trim() || undefined,
  forwarding_rule: newRule.trim() || undefined,
  available_start: newAvailStart || undefined,
  available_end: newAvailEnd || undefined,
}, selectedLocationId);
```

Also reset state after success:
```tsx
setNewAvailStart(""); setNewAvailEnd("");
```

- [ ] **Step 5: Wire into Edit Contact dialog JSX**

In the Edit Contact `<Dialog>` content, after the "Rule" field, add the same time block using `editAvailStart`/`editAvailEnd`:

```tsx
<div className="space-y-1.5">
  <Label>Available Hours (optional)</Label>
  <p className="text-xs text-muted-foreground">
    Agent will refuse to transfer outside these times. Leave blank to always allow. Times in 24h UTC format.
  </p>
  <div className="flex items-center gap-2">
    <Input
      type="time"
      value={editAvailStart}
      onChange={(e) => setEditAvailStart(e.target.value)}
      className="w-36"
    />
    <span className="text-muted-foreground text-sm">to</span>
    <Input
      type="time"
      value={editAvailEnd}
      onChange={(e) => setEditAvailEnd(e.target.value)}
      className="w-36"
    />
  </div>
</div>
```

- [ ] **Step 6: Pass new fields in `handleEditSave`**

```tsx
const updated = await updateForwardingContact(token, editingId, {
  name: editName.trim(),
  phone: editPhone.trim(),
  department_tag: editTitle.trim(),
  forwarding_rule: editRule.trim(),
  available_start: editAvailStart || undefined,
  available_end: editAvailEnd || undefined,
});
```

- [ ] **Step 7: Show current hours on each contact card**

In the contact card JSX, find where `forwarding_rule` is displayed and add below it:
```tsx
{c.available_start && c.available_end && (
  <p className="text-xs text-muted-foreground mt-0.5">
    Available {c.available_start} – {c.available_end} UTC
  </p>
)}
```

- [ ] **Step 8: Commit**

```bash
git -C /home/lap-68/Documents/gt-rahul/ai-employees-app add src/pages/dashboard/customer-service/CallForwarding.tsx
git -C /home/lap-68/Documents/gt-rahul/ai-employees-app commit -m "feat: add available hours fields to forwarding contact add/edit dialogs"
```

---

### Task 5: Agent — Time Check in `forward_call`

**Files:**
- Modify: `sam-backend/agent/supabase_helpers.py`
- Modify: `sam-backend/agent/agent.py`

- [ ] **Step 1: Fetch `available_start`/`available_end` in `_fetch_forwarding_contacts`**

In `supabase_helpers.py`, find `_fetch_forwarding_contacts`. Update the `.select()` call to include the new columns:

```python
query = (
    supabase.table("forwarding_contacts")
    .select("id, name, phone, department_tag, forwarding_rule, available_start, available_end")
    .eq("business_id", business_id)
    .eq("is_active", True)
)
```

- [ ] **Step 2: Add a helper function to check if current time is within a window**

Add this function in `supabase_helpers.py` just above `_fetch_forwarding_contacts`:

```python
def _is_within_available_hours(available_start: str | None, available_end: str | None) -> bool:
    """
    Return True if the current UTC time falls within [available_start, available_end].
    If either value is missing or malformed, returns True (always available).
    Handles overnight windows where end < start (e.g. 22:00 – 06:00).
    """
    if not available_start or not available_end:
        return True
    try:
        now_utc = datetime.now(timezone.utc)
        now_minutes = now_utc.hour * 60 + now_utc.minute

        start_h, start_m = map(int, available_start.split(":"))
        end_h, end_m     = map(int, available_end.split(":"))
        start_minutes = start_h * 60 + start_m
        end_minutes   = end_h * 60 + end_m

        if start_minutes <= end_minutes:
            # Normal window e.g. 09:00 – 17:00
            return start_minutes <= now_minutes <= end_minutes
        else:
            # Overnight window e.g. 22:00 – 06:00
            return now_minutes >= start_minutes or now_minutes <= end_minutes
    except (ValueError, AttributeError):
        return True  # malformed — don't block
```

Make sure `datetime` and `timezone` are already imported at the top (they are).

- [ ] **Step 3: Add the time check in `forward_call` in `agent.py`**

In `agent.py`, inside `forward_call`, find the line that fetches the contact:

```python
r = (
    self._supabase.table("forwarding_contacts")
    .select("id, name, phone")
    ...
)
```

Update `.select()` to include the new columns:
```python
.select("id, name, phone, available_start, available_end")
```

Then, immediately after `contact = r.data[0]`, add the availability check before the phone validation:

```python
from agent.supabase_helpers import _is_within_available_hours

avail_start = contact.get("available_start")
avail_end   = contact.get("available_end")
if not _is_within_available_hours(avail_start, avail_end):
    contact_name = contact.get("name", "that contact")
    hours_msg = f"{avail_start} – {avail_end} UTC"
    return (
        f"I'm sorry, {contact_name} is only available {hours_msg} and is not "
        f"available right now. Would you like me to take a message instead?"
    )
```

- [ ] **Step 4: Verify agent syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import ast; ast.parse(open('agent/agent.py').read()); print('OK')"
python -c "import ast; ast.parse(open('agent/supabase_helpers.py').read()); print('OK')"
```

Expected: `OK` for both.

- [ ] **Step 5: Commit**

```bash
git -C /home/lap-68/Documents/gt-rahul/sam-backend add agent/supabase_helpers.py agent/agent.py
git -C /home/lap-68/Documents/gt-rahul/sam-backend commit -m "feat: agent checks available hours before forwarding call"
```

---

## Feature 2 — Setup Checklist (Real Checks + Navigation)

### Task 6: Real Completion Checks + Click Navigation

**Files:**
- Modify: `ai-employees-app/src/pages/dashboard/CustomerServiceEmployee.tsx`

The checklist has 8 items. 6 can be checked against real API data (already loaded or easily fetched). 2 remain manual (no backend concept exists yet).

**Completion sources:**
| Item | Check | Data source |
|------|-------|-------------|
| Connect a Phone Number | `phoneNumbers.length > 0` | already loaded |
| Choose a Voice and Accent | manual toggle | no API |
| Set Voice Agent Hours | any day `is_open: true` in schedule | `getAgentSchedule` |
| Set Call Forwarding Rules | `contacts.length > 0` | `listForwardingContacts` |
| Connect Your Calendar | Gmail `is_connected: true` | `getGmailStatus` |
| Enable Booking Rules | services count > 0 | Supabase `services` table |
| Review Greeting Message | manual toggle | no API |
| Test the Voice Agent | `recentActivity.length > 0` | already loaded |

**Navigation targets:**
| Item | Path |
|------|------|
| Connect a Phone Number | `/dashboard/settings/phone-numbers` |
| Choose a Voice and Accent | `/dashboard/settings/global` |
| Set Voice Agent Hours | `/dashboard/settings/business?tab=hours` |
| Set Call Forwarding Rules | `/dashboard/customer-service/forwarding` |
| Connect Your Calendar | `/dashboard/settings/business?tab=integrations` |
| Enable Booking Rules | `/dashboard/settings/business?tab=services` |
| Review Greeting Message | `/dashboard/settings/global` |
| Test the Voice Agent | scroll to test panel (set `testTab` to `"inbound"`) |

- [ ] **Step 1: Add new imports at the top of `CustomerServiceEmployee.tsx`**

The file already imports `useNavigate`, `getPhoneNumbers`, `useAuth`, `useBusiness`, `useSelectedLocation`. Add these additional imports:

```tsx
import { getAgentSchedule, getGmailStatus, listForwardingContacts } from "@/lib/voiceAgentApi";
import { supabase } from "@/integrations/supabase/client";
```

- [ ] **Step 2: Remove the old static `checklist` state**

Delete the `useState<ChecklistItem[]>([...])` block (lines 97–106) entirely. We will replace it with derived state.

- [ ] **Step 3: Add fetched state for checklist data**

Inside the component, after the existing `phoneNumbers` state block, add:

```tsx
const [scheduleHasOpenDay, setScheduleHasOpenDay] = useState(false);
const [hasForwardingContact, setHasForwardingContact] = useState(false);
const [gmailConnected, setGmailConnected] = useState(false);
const [hasServices, setHasServices] = useState(false);
// Manual toggles for items with no backend concept
const [voiceChosen, setVoiceChosen] = useState(() =>
  localStorage.getItem("checklist_voice_chosen") === "true"
);
const [greetingReviewed, setGreetingReviewed] = useState(() =>
  localStorage.getItem("checklist_greeting_reviewed") === "true"
);
```

- [ ] **Step 4: Fetch checklist data on mount**

Add a `useEffect` after the existing phone numbers `useEffect`:

```tsx
useEffect(() => {
  if (!token || !businessId) return;

  // Agent schedule — any open day?
  getAgentSchedule(token, businessId, selectedLocationId)
    .then((r) => setScheduleHasOpenDay(r.schedule.some((d: { is_open: boolean }) => d.is_open)))
    .catch(() => {});

  // Forwarding contacts — any active?
  listForwardingContacts(token, businessId, selectedLocationId)
    .then((c) => setHasForwardingContact(c.length > 0))
    .catch(() => {});

  // Gmail connected?
  getGmailStatus(token, businessId, selectedLocationId)
    .then((s) => setGmailConnected(s.is_connected === true))
    .catch(() => {});

  // Services — any active?
  if (businessId) {
    supabase
      .from("services")
      .select("id", { count: "exact", head: true })
      .eq("business_id", businessId)
      .eq("is_active", true)
      .then(({ count }) => setHasServices((count ?? 0) > 0))
      .catch(() => {});
  }
}, [token, businessId, selectedLocationId]);
```

- [ ] **Step 5: Derive the checklist array from real data**

Replace the old `checklist` state with a `useMemo` that builds the array from real data. Add this after all state declarations:

```tsx
const checklist = useMemo(() => [
  {
    id: "phone",
    label: "Connect a Phone Number",
    completed: phoneNumbers.length > 0,
    path: "/dashboard/settings/phone-numbers",
    manual: false,
  },
  {
    id: "voice",
    label: "Choose a Voice and Accent",
    completed: voiceChosen,
    path: "/dashboard/settings/global",
    manual: true,
  },
  {
    id: "hours",
    label: "Set Voice Agent Hours and Holidays",
    completed: scheduleHasOpenDay,
    path: "/dashboard/settings/business?tab=hours",
    manual: false,
  },
  {
    id: "forwarding",
    label: "Set Call Forwarding Rules",
    completed: hasForwardingContact,
    path: "/dashboard/customer-service/forwarding",
    manual: false,
  },
  {
    id: "calendar",
    label: "Connect Your Calendar",
    completed: gmailConnected,
    path: "/dashboard/settings/business?tab=integrations",
    manual: false,
  },
  {
    id: "booking",
    label: "Enable Booking Rules",
    completed: hasServices,
    path: "/dashboard/settings/business?tab=services",
    manual: false,
  },
  {
    id: "greeting",
    label: "Review Greeting Message",
    completed: greetingReviewed,
    path: "/dashboard/settings/global",
    manual: true,
  },
  {
    id: "test",
    label: "Test the Voice Agent",
    completed: recentActivity.length > 0,
    path: null,  // handled inline — scrolls to test panel
    manual: false,
  },
], [
  phoneNumbers, voiceChosen, scheduleHasOpenDay, hasForwardingContact,
  gmailConnected, hasServices, greetingReviewed, recentActivity,
]);
```

- [ ] **Step 6: Update `toggleItem` to handle manual + navigate items**

Replace the old `toggleItem` function with:

```tsx
const toggleItem = (id: string) => {
  const item = checklist.find((c) => c.id === id);
  if (!item) return;

  if (item.manual) {
    // Persist manual toggles across sessions
    const newVal = !item.completed;
    if (id === "voice") {
      setVoiceChosen(newVal);
      localStorage.setItem("checklist_voice_chosen", String(newVal));
    } else if (id === "greeting") {
      setGreetingReviewed(newVal);
      localStorage.setItem("checklist_greeting_reviewed", String(newVal));
    }
    return;
  }

  if (id === "test") {
    // Scroll to the test panel
    document.getElementById("agent-test-panel")?.scrollIntoView({ behavior: "smooth" });
    return;
  }

  if (item.path) {
    navigate(item.path);
  }
};
```

- [ ] **Step 7: Update the checklist item button to show navigate hint for non-manual items**

Find the checklist `<button>` JSX that renders each item. Replace it with:

```tsx
{checklist.map((item, index) => (
  <button
    key={item.id}
    onClick={() => toggleItem(item.id)}
    className="w-full flex items-center gap-3 p-3 rounded-lg hover:bg-secondary/50 transition-colors text-left group"
  >
    {item.completed ? (
      <CheckCircle2 className="text-green-500 shrink-0" size={20} />
    ) : (
      <Circle className="text-muted-foreground shrink-0" size={20} />
    )}
    <span className={`flex-1 ${item.completed ? "text-muted-foreground line-through" : "text-foreground"}`}>
      {String.fromCharCode(65 + index)}. {item.label}
    </span>
    {!item.manual && !item.completed && (
      <span className="text-xs text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
        Set up →
      </span>
    )}
  </button>
))}
```

- [ ] **Step 8: Remove unused `setChecklist` references and `ChecklistItem` interface**

The old `interface ChecklistItem` and `setChecklist` are no longer needed. Remove them:
- Delete `interface ChecklistItem { id: string; label: string; completed: boolean; }` (around line 48)
- `toggleItem` no longer calls `setChecklist` — already replaced in Step 6
- `completedCount` already uses `checklist.filter(...)` — still works because `checklist` is now a derived array

- [ ] **Step 9: Add `id` to the test panel div for scroll targeting**

Find the test panel `<div>` (the one with `className="mt-6 bg-card rounded-xl ..."`) and add an id:
```tsx
<div id="agent-test-panel" className="mt-6 bg-card rounded-xl border border-border p-6 shadow-card">
```

- [ ] **Step 10: Add missing imports**

At the top of the file, add `useMemo` to the React import if not already present:
```tsx
import { useState, useCallback, useEffect, useMemo } from "react";
```

- [ ] **Step 11: Verify TypeScript compiles cleanly**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx tsc --noEmit 2>&1 | grep "CustomerServiceEmployee\|voiceAgentApi" | head -20
```

Expected: no errors for these files.

- [ ] **Step 12: Commit**

```bash
git -C /home/lap-68/Documents/gt-rahul/ai-employees-app add src/pages/dashboard/CustomerServiceEmployee.tsx
git -C /home/lap-68/Documents/gt-rahul/ai-employees-app commit -m "feat: setup checklist shows real completion status and navigates on click"
```

---

## Manual Testing Checklist

### Feature 1 — Per-Contact Available Hours
- [ ] Open Call Forwarding → Add Contact → "Available Hours" time fields appear
- [ ] Add a contact with `available_start: 09:00`, `available_end: 17:00`
- [ ] Call the agent outside those UTC hours → agent refuses transfer and offers to take a message
- [ ] Call within those hours → agent transfers normally
- [ ] Edit an existing contact → hours pre-fill correctly from saved values
- [ ] Contact with no hours set → agent always forwards (no change in behavior)
- [ ] Overnight window: set `22:00` to `06:00` → verify correct behavior at 23:00 and 03:00

### Feature 2 — Setup Checklist
- [ ] Load Customer Service Employee page — items with real data auto-check (phone number if provisioned, hours if set, etc.)
- [ ] Click a non-manual non-completed item → navigates to correct settings page
- [ ] Click "Voice / Accent" or "Review Greeting" → toggles locally and persists after page refresh
- [ ] Click "Test the Voice Agent" → page scrolls to the Agent Testing panel
- [ ] Complete all setup steps → "Deploy!" button becomes enabled
- [ ] Newly provisioned phone number → checklist reflects it on next load without manual toggle
- [ ] "Forwarding Rules" item → unchecked until at least 1 contact is added in Call Forwarding, then auto-checks

---

## Self-Review

**Spec coverage:**
- Call forwarding time-based rules → Tasks 1-5 ✅
- Setup checklist real completion → Task 6 ✅
- Setup checklist navigation on click → Task 6 (Steps 6-7) ✅
- Test checklist testing → Manual Testing section ✅

**Placeholder scan:** None found — all steps contain concrete code.

**Type consistency:**
- `available_start` / `available_end` used consistently as `string | None` (Python) and `string | undefined` (TypeScript) throughout Tasks 2-5.
- `_is_within_available_hours` defined in Task 5 Step 2 and called in Step 3 — same module, no import issues.
- `checklist` array shape (with `path`, `manual` fields) defined in Task 6 Step 5 and consumed in Steps 6-7 — consistent.
