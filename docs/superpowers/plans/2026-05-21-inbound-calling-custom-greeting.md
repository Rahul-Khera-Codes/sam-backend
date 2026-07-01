# Custom Greeting Message for Inbound Calling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pencil/edit button to the Inbound Calling toggle so a custom greeting message can be saved and used verbatim by the agent on every inbound call.

**Architecture:** Store the greeting in `config_value.greeting_message` on the existing `inbound_calling` row in `agent_settings` (no DB migration needed). `agent.py` reads it before building the system prompt and passes it to `build_instructions`, which swaps out the hardcoded welcome block when a custom greeting is present.

**Tech Stack:** Python (agent), FastAPI (backend — no changes needed), React + TypeScript (frontend), Supabase JSONB config_value column.

---

## File Map

| File | What changes |
|---|---|
| `agent/prompt_builder.py` | Add `custom_greeting` param to `build_instructions`; swap welcome block when set |
| `agent/agent.py` | Read `inbound_calling` config_value before calling `build_instructions` |
| `agent/tests/test_prompt_builder.py` | New tests for custom greeting behaviour |
| `ai-employees-app/src/pages/dashboard/customer-service/AgentSettings.tsx` | Greeting dialog state + Dialog UI + wire `onEdit` on inbound_calling |

---

## Task 1: Add `custom_greeting` param to `build_instructions`

**Files:**
- Modify: `agent/prompt_builder.py:369`
- Create: `agent/tests/test_prompt_builder.py` (or modify if it exists)

### Background

`build_instructions` (line 369 in `prompt_builder.py`) currently generates this welcome block unconditionally:

```python
welcome = (
    f"You are the AI phone receptionist for {company_name}{location_phrase}. "
    "Always start the call with a short, friendly welcome that includes the business name"
)
if location_phrase:
    welcome += " and the location"
welcome += (
    ". Example: \"Thank you for calling "
    f"{company_name}{location_phrase}, how can I help you today?\" "
    "Then continue the conversation following these rules:\n\n"
)
```

We need to keep this unchanged when `custom_greeting` is `None`, and replace it when a value is provided.

- [ ] **Step 1: Write failing tests**

Create (or add to) `agent/tests/test_prompt_builder.py`:

```python
from unittest.mock import patch, MagicMock
from prompt_builder import build_instructions


def _mock_supabase_minimal():
    """Returns a supabase mock that returns enough data to not crash build_instructions."""
    sb = MagicMock()
    # businesses
    biz_resp = MagicMock(); biz_resp.data = [{"name": "Test Biz", "phone": "", "email": "", "website": "", "address": "", "business_type": "", "service_area": "", "payment_methods": "", "policies": ""}]
    # everything else returns empty list
    empty = MagicMock(); empty.data = []
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value = empty
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = empty
    sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = empty
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = empty
    # business fetch specifically
    biz_table = MagicMock()
    biz_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = biz_resp
    sb.table.side_effect = lambda name: biz_table if name == "businesses" else sb.table.return_value
    return sb


def test_build_instructions_default_greeting_contains_example():
    """Without custom_greeting, prompt includes the hardcoded example."""
    with patch("prompt_builder._get_supabase", return_value=_mock_supabase_minimal()):
        result = build_instructions("biz-123", None)
    assert "Thank you for calling" in result
    assert "Always start the call" in result


def test_build_instructions_custom_greeting_replaces_welcome_block():
    """With custom_greeting, the custom text appears and the generic instruction is removed."""
    with patch("prompt_builder._get_supabase", return_value=_mock_supabase_minimal()):
        result = build_instructions("biz-123", None, custom_greeting="Hey, welcome to Test Biz!")
    assert "Hey, welcome to Test Biz!" in result
    assert "Start the call with this greeting" in result
    # Generic instruction should be gone
    assert "Always start the call with a short, friendly welcome" not in result
    assert "Thank you for calling" not in result


def test_build_instructions_empty_custom_greeting_uses_default():
    """Empty string for custom_greeting falls back to default behaviour."""
    with patch("prompt_builder._get_supabase", return_value=_mock_supabase_minimal()):
        result = build_instructions("biz-123", None, custom_greeting="")
    assert "Always start the call" in result
    assert "Thank you for calling" in result
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -m pytest agent/tests/test_prompt_builder.py -v 2>&1 | tail -20
```

Expected: `test_build_instructions_default_greeting_contains_example` passes (existing behaviour), the other two fail with `TypeError: build_instructions() got an unexpected keyword argument 'custom_greeting'`.

- [ ] **Step 3: Update `build_instructions` signature and welcome block**

In `agent/prompt_builder.py`, change the function signature at line 369:

```python
def build_instructions(
    business_id: str | None,
    location_id: str | None,
    custom_greeting: str | None = None,
) -> str:
```

Then find the `welcome = (...)` block (lines ~497–507) and replace it with:

```python
    if custom_greeting:
        welcome = (
            f"You are the AI phone receptionist for {company_name}{location_phrase}.\n"
            f'Start the call with this greeting: "{custom_greeting}"\n'
            "Then continue the conversation following these rules:\n\n"
        )
    else:
        welcome = (
            f"You are the AI phone receptionist for {company_name}{location_phrase}. "
            "Always start the call with a short, friendly welcome that includes the business name"
        )
        if location_phrase:
            welcome += " and the location"
        welcome += (
            ". Example: \"Thank you for calling "
            f"{company_name}{location_phrase}, how can I help you today?\" "
            "Then continue the conversation following these rules:\n\n"
        )
```

- [ ] **Step 4: Run tests — verify all three pass**

```bash
python -m pytest agent/tests/test_prompt_builder.py -v 2>&1 | tail -20
```

Expected:
```
PASSED test_build_instructions_default_greeting_contains_example
PASSED test_build_instructions_custom_greeting_replaces_welcome_block
PASSED test_build_instructions_empty_custom_greeting_uses_default
```

- [ ] **Step 5: Run full agent test suite to confirm no regressions**

```bash
python -m pytest agent/tests/ -v 2>&1 | tail -30
```

Expected: All previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
git add agent/prompt_builder.py agent/tests/test_prompt_builder.py
git commit -m "feat: add custom_greeting param to build_instructions — replaces welcome block when set"
```

---

## Task 2: Read `inbound_calling` config_value in `agent.py` and pass greeting

**Files:**
- Modify: `agent/agent.py:1472-1475`

### Background

In `agent.py` around line 1472–1475, the agent already has a `supabase` client initialised and calls `build_instructions(business_id, location_id)`. We read `inbound_calling` config_value right before that call and pass the greeting string.

`_get_feature_config_value` is already imported and available (it's used elsewhere for SMS config).

- [ ] **Step 1: Locate the exact call site**

In `agent/agent.py`, find the line:
```python
        instructions = build_instructions(business_id, location_id)
```
It is around line 1475. Verify it's in the `if business_id:` block that also loads locations, services, and staff.

- [ ] **Step 2: Add config_value read and pass greeting**

Replace:
```python
        instructions = build_instructions(business_id, location_id)
```

With:
```python
        _inbound_cfg = _get_feature_config_value(supabase, business_id, location_id, "inbound_calling") if supabase else {}
        _custom_greeting = (_inbound_cfg.get("greeting_message") or "").strip() or None
        instructions = build_instructions(business_id, location_id, custom_greeting=_custom_greeting)
```

The `or None` ensures an empty string saved in DB is treated the same as not set, falling back to the default greeting.

- [ ] **Step 3: Verify syntax**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
python -c "import agent.agent" && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 4: Run full agent test suite**

```bash
python -m pytest agent/tests/ -v 2>&1 | tail -30
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent/agent.py
git commit -m "feat: read inbound_calling greeting_message from config_value; pass to build_instructions"
```

---

## Task 3: Frontend — greeting dialog in AgentSettings

**Files:**
- Modify: `ai-employees-app/src/pages/dashboard/customer-service/AgentSettings.tsx`

### Background

The component already has:
- `configValues` state (`Record<string, Record<string, unknown>>`) — loaded from API on mount, holds all `config_value` objects keyed by feature_key
- A `FeatureToggleRow` component with an optional `onEdit` prop that shows a pencil icon
- `updateAgentSettings()` — saves a single setting including its `config_value`
- An existing Dialog for SMS/call templates (state vars: `editTemplateKey`, `editTemplateText`, `editDays`)

We add a **separate** greeting dialog with its own state vars so the two dialogs don't interfere.

- [ ] **Step 1: Add greeting dialog state vars**

After line 121 (`const [editDays, setEditDays] = useState(1);`), add:

```typescript
  // Greeting message editor (inbound_calling only)
  const [greetingDialogOpen, setGreetingDialogOpen] = useState(false);
  const [greetingText, setGreetingText] = useState("");
```

- [ ] **Step 2: Add `inbound_calling` to `EDITABLE_FEATURES` and wire its `onEdit`**

The `EDITABLE_FEATURES` array is defined inside the `.map()` at line 265. Add `"inbound_calling"` to it:

```typescript
                  const EDITABLE_FEATURES = [
                    "inbound_calling",
                    "send_texts_during_after_calls",
                    "missed_call_text_back",
                    "reschedule_cancel_appointments",
                    "confirmation_reminder_calls",
                    "noshow_followup",
                  ];
```

Then change the `onEdit` prop on `FeatureToggleRow` to route inbound_calling to the greeting dialog:

```typescript
                      onEdit={isEditable ? () => {
                        if (feature.id === "inbound_calling") {
                          setGreetingText(
                            ((configValues["inbound_calling"]?.greeting_message as string) ?? "")
                          );
                          setGreetingDialogOpen(true);
                        } else {
                          setEditTemplateKey(feature.id);
                          setEditTemplateText(
                            ((configValues[feature.id]?.message_template as string) ?? "")
                          );
                          setEditDays(
                            ((configValues[feature.id]?.days as number) ?? getDefaultDays(feature.id))
                          );
                        }
                      } : undefined}
```

- [ ] **Step 3: Add the greeting Dialog component**

After the closing `</Dialog>` tag of the existing feature config editor dialog (around line 405), add:

```tsx
      {/* Greeting Message Editor */}
      <Dialog open={greetingDialogOpen} onOpenChange={(open) => { if (!open) setGreetingDialogOpen(false); }}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Custom Greeting Message</DialogTitle>
            <DialogDescription>
              Write the exact greeting your agent will say at the start of every inbound call.
              Leave blank to use the default greeting.
            </DialogDescription>
          </DialogHeader>
          <div className="py-2">
            <Textarea
              placeholder={`e.g. "Thank you for calling ${businessId ? 'your business' : 'us'}, how can I help you today?"`}
              value={greetingText}
              onChange={(e) => setGreetingText(e.target.value)}
              rows={4}
              className="resize-none"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGreetingDialogOpen(false)}>Cancel</Button>
            <Button
              onClick={async () => {
                if (!businessId) return;
                const updatedConfig = {
                  ...(configValues["inbound_calling"] || {}),
                  greeting_message: greetingText.trim() || null,
                };
                await updateAgentSettings(token, businessId, [
                  {
                    feature_key: "inbound_calling",
                    is_enabled: features["inbound_calling"] ?? true,
                    config_value: updatedConfig,
                  },
                ], selectedLocationId ?? undefined);
                setConfigValues((prev) => ({ ...prev, inbound_calling: updatedConfig }));
                setGreetingDialogOpen(false);
              }}
              disabled={isSaving}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
```

- [ ] **Step 4: Verify TypeScript compiles clean**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
npx tsc --noEmit 2>&1 | grep -E "error TS|AgentSettings"
```

Expected: no output (no errors).

- [ ] **Step 5: Commit**

```bash
cd /home/lap-68/Documents/gt-rahul/ai-employees-app
git add src/pages/dashboard/customer-service/AgentSettings.tsx
git commit -m "feat: add custom greeting dialog to inbound calling toggle in agent settings"
```

---

## Task 4: Smoke test end-to-end

- [ ] **Step 1: Start the stack**

```bash
cd /home/lap-68/Documents/gt-rahul/sam-backend
docker compose up -d
docker logs -f sam-backend-sam-agent-1 &
```

- [ ] **Step 2: Set a custom greeting via UI**

1. Open the app, navigate to **Customer Service → Agent Settings**
2. Find "Inbound Calling" toggle — confirm it now has a pencil icon
3. Click the pencil → greeting dialog opens
4. Type: `Hey, thanks for calling Downtown Barber Shop — how can I help you today?`
5. Click Save → dialog closes, no error

- [ ] **Step 3: Verify it saved to DB**

In Supabase dashboard, run:
```sql
SELECT feature_key, is_enabled, config_value
FROM agent_settings
WHERE feature_key = 'inbound_calling'
ORDER BY updated_at DESC
LIMIT 5;
```

Expected: a row with `config_value = {"greeting_message": "Hey, thanks for calling Downtown Barber Shop — how can I help you today?"}`.

- [ ] **Step 4: Make a test web call**

1. Go to **Phone Numbers**, click **Test with Web Call** on the Mirage number
2. Agent answers — first words should be the custom greeting text (or very close to it)

- [ ] **Step 5: Clear the greeting and verify fallback**

1. Open the greeting dialog again, clear the text, Save
2. Make another test call — agent should revert to the default `"Thank you for calling..."` style opening

- [ ] **Step 6: Restart agent and confirm greeting persists**

```bash
docker compose restart sam-agent
```

Make another test call — custom greeting (if set) should still be in effect after restart, since it's read from DB on each call.

---

## Self-Review Checklist

- [x] **Spec coverage**: all requirements covered — toggle+edit UI (Task 3), agent reads greeting (Task 2), prompt_builder swaps block (Task 1), empty/null falls back to default (Task 1 step 3 + Task 2 step 2)
- [x] **No placeholders**: all code blocks are complete and exact
- [x] **Type consistency**: `custom_greeting: str | None` in prompt_builder; `greetingText: string` in frontend saved as `greeting_message: text.trim() || null`; `_get_feature_config_value` returns `dict` so `.get("greeting_message")` is valid
- [x] **No migration needed**: confirmed `config_value JSONB` already exists on `agent_settings`
- [x] **Location scoping**: `_get_feature_config_value` already accepts `location_id`; frontend passes `selectedLocationId` to `updateAgentSettings` — covered by existing infrastructure
