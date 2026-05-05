---
name: Backend API slow response — creation operations
description: Backend Supabase-writes consistently take >2–3s for role and location creation; test scripts need generous waits
type: feedback
originSessionId: 939c68fe-d233-49e9-82d6-467bf2824104
---
Creation endpoints are consistently slow — both `POST /roles` (role creation via `createCustomRole`) and `POST /locations/{id}/seed` (location seed after creation) take **more than 2–3 seconds** to complete. This was confirmed across Sessions 4 and 5 QA testing.

**Why:** These operations write to Supabase (remote cloud DB) and then do a secondary seed operation (copy business_hours, agent_settings, role_page_permissions, etc.), adding round-trips.

**How to apply:**
- Any test script that creates a role or location must wait **at least 5 seconds** after clicking Create/Save before checking for a success toast or checking if the new item appears in the UI.
- This is a **performance observation, not a bug** — operations succeed, just slowly. Worth flagging for production readiness review (cold-start Supabase latency on free/starter plan).
- Do NOT use 2s timeouts for creation operations in Playwright scripts.
