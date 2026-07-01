# Spec — Executive Agent Location Context (Gmail fix)

**Date:** 2026-06-24 · **Workstream:** WS5 (bug) · **Repos:** `sam-backend` + `ai-employees-app`

## Bug
Remi reports "we're not connected to your Gmail" even though Gmail is connected for the location (e.g. Eifel Tower 8, `rahul.excel2011@gmail.com`).

## Root cause (verified)
- Gmail tokens are **location-scoped** (`gmail_tokens.location_id`).
- `_gmail_get_valid_token(business_id, location_id)`: if `location_id` is `None` it queries `location_id IS NULL`; otherwise `= location_id`.
- The executive agent reads `location_id` from participant metadata, but the backend `/executive/session` endpoint **never puts `location_id` in the token/dispatch metadata** (only `business_id` + `user_id`) → agent's `self._location_id = None` → NULL-location lookup → no token found.
- Calendar is unaffected because its token lookup is by superadmin/staff, not location-scoped — which is why calendar works but Gmail doesn't.

## Decision
Use the **owner's currently-selected location** (`selectedLocationId`). The app requires a selected location to navigate, so it's always present — no fallback needed (a defensive one is fine but not required).

## Changes

### Frontend (`ai-employees-app`)
- `src/lib/voiceAgentApi.ts` — `createExecutiveSession(token, businessId, locationId?)`: add `locationId`, include `location_id` in the POST body (mirror `scrapeWebsiteToKB`).
- `src/hooks/useExecutiveSession.ts` — `import { useSelectedLocation } from "./useLocation"`, read `selectedLocationId`, pass it to `createExecutiveSession(token, businessId, selectedLocationId)`. Add to the connect callback deps.

### Backend (`backend/app/routers/executive.py`)
- `ExecutiveSessionRequest` — add `location_id: str | None = None`.
- Include `"location_id": body.location_id` in BOTH metadata blocks (participant token + dispatch).
- (Optional/defensive) validate the location belongs to the business; skip for now since FE only sends the user's selected location.

### Agent (`agent/executive_agent.py`)
- Already reads `location_id` from participant metadata and passes `self._location_id` to Gmail tools — no change needed for the participant path.
- Robustness: also parse `location_id` in the **job-metadata fallback** block (currently only sets business_id/user_id).

## Verification
- Backend `ast.parse` clean; frontend builds.
- Live (restart `sam-executive-agent` + FE rebuild), with Gmail connected for the selected location:
  - "List my recent emails" → returns real emails (no "not connected").
  - "Show today's emails" → real result.
  - Calendar + appointments still work.
  - Switch selected location to one WITHOUT Gmail → Remi correctly says not connected (expected).

## Out of scope
WS3 cards, WS4 avatar. (This unblocks the Gmail data that WS3's `email_list` card will display.)
