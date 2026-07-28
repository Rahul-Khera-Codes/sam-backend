# Marketing Employee Implementation Memory

## Purpose
- This file is the long-lived memory and execution guide for the Marketing Employee agent.
- It should preserve product decisions, implementation status, screen-by-screen plans, technical notes, verification history, and remaining work.
- Future sessions should read this file first before continuing Marketing Employee work.

## Repos In Scope
- Backend: `sam-backend`
- Frontend: `ai-employees-app`

## Product Direction
- Marketing Employee is a multi-tenant marketing workspace inside AI Employees.
- The first implementation is UI-first with mock backend data so the product flow can be reviewed before committing to external platform integrations.
- Real data and publishing integrations will be added later behind backend APIs.
- The product should support businesses that have no social platform integrations connected yet.

## Locked Decisions

### Current Build Mode
- Start with mock backend/data wiring only.
- Build the UI screens from the approved screenshots first.
- Do not call Meta, TikTok, LinkedIn, X, Google, or other marketing APIs in this phase.
- Keep the screen contracts close to the future real backend shape so mock data can be replaced without a UI rewrite.
- Mock endpoints should exist in the backend as API-shaped placeholders while the frontend keeps a local fallback for easy preview.

### Tenancy
- All future Marketing Employee data must be business-scoped.
- Marketing settings, campaigns, generated assets, schedules, and integration credentials should belong to a business.
- Location-specific marketing may be added later, but the first workspace should behave as a business-level employee.

### Campaign Generation
- The first visible screen is the Social Media Campaign Overview.
- Users describe an idea, choose advanced settings, select an aspect ratio, and choose an image count.
- The current screenshot shows image generation controls, not a full publishing flow.
- Export is visible in the UI but can remain a mock/no-op until real campaign assets exist.
- Confirmed create-post flow:
  - idea setup
  - generated content gallery
  - selected item opens compose/publish preview
  - mock publish schedules the post into the July 2026 calendar
- Gallery item selection should open the selected item in the compose/publish preview.
- Mock publish should create a scheduled post and show it on the calendar.
- Default scheduling should use the next available mock slot in July 2026.

### Backend Strategy
- Mock data should be isolated behind frontend helpers or a lightweight API-shaped module.
- Later backend implementation should expose normalized campaign endpoints rather than returning raw provider payloads.
- External platform secrets must never be exposed to the frontend.

## Section Roadmap

### Section 1: Social Media Campaign Overview
Status: Mock UI first pass implemented

Goal:
- Replace the generic Marketing Employee coming-soon page with the first dedicated Marketing Employee screen.
- Match the provided screenshot closely enough for review while keeping the code maintainable.
- Wire state locally/mock-first for prompt text, aspect ratio, image count, advanced settings, randomization, and export action.

Planned frontend:
- Add a Marketing Employee dashboard route under `/dashboard/marketing`.
- Keep the first screen directly inside the existing dashboard shell with no second-level Marketing sidebar, matching the provided screenshot.
- Add the Social Media Campaign Overview page with:
  - title and helper copy
  - last-run range and export button
  - centered campaign prompt card
  - advanced settings status
  - idea textarea
  - randomize action
  - aspect-ratio options
  - image-count segmented control
  - mock generation/export behavior

Planned backend/mock approach:
- Use local mock data for now.
- Preserve an API-shaped boundary for later backend replacement.
- Real persistence, generation jobs, media storage, and platform publishing are deferred.
- Add FastAPI mock endpoints now, backed by in-memory data only.

Delivered:
- Frontend route `/dashboard/marketing` now opens the Marketing Employee screen instead of the generic coming-soon page.
- Added `MarketingCampaignOverview` with local state for:
  - idea prompt
  - advanced settings toggle
  - aspect ratio
  - image count
  - randomize action
  - mock export action
- Added `marketingEmployeeMock.ts` as the temporary mock backend/data boundary.
- Added the sequential create-post flow:
  - setup screen
  - generated gallery screen
  - compose/publish preview screen
  - calendar screen
- Gallery screen groups mock content into Instagram posts, Instagram reels, LinkedIn posts, and TikTok videos.
- Compose screen includes caption editing, media upload placeholder, link field, platform selection, platform options, and phone preview.
- Calendar screen shows July 2026, platform legend, upcoming posts, and scheduled post placement.
- Frontend mock helper now calls backend mock endpoints when auth/business context is available and falls back to local mock data otherwise.
- Backend mock endpoints:
  - `GET /marketing/workspace`
  - `POST /marketing/campaigns/generate`
  - `POST /marketing/campaigns/randomize`
  - `POST /marketing/posts/publish`
  - `GET /marketing/calendar`

Verification:
- Frontend TypeScript check passed.
- Targeted ESLint passed for `App.tsx`, `MarketingCampaignOverview.tsx`, and `marketingEmployeeMock.ts`.
- Cursor diagnostics reported no linter errors for edited files.
- Backend compile / frontend lint verification for the new multi-screen flow is pending in this session.

Pending screenshots:
- Additional Marketing Employee screens still need to be provided and converted into section entries.

### Future Sections
Status: Planned

Candidate areas:
- Campaign asset generation results
- Campaign calendar / scheduling
- Brand voice and creative settings
- Platform integration status
- Campaign analytics
- Approval workflow
- Content library

## Cross-Cutting Technical Plan

### Multi-Tenancy
- Every future record should include `business_id`.
- Access should follow existing business membership checks used elsewhere in the product.
- Admin-only actions should include integration setup, publishing, and credential changes.

### Security
- Keep provider tokens server-side only.
- Treat generated copy, uploaded assets, and external comments as untrusted content.
- Add explicit approval steps before any real external publishing.

### Frontend Patterns
- Follow existing dashboard and employee section routing conventions.
- Avoid adding broad shared abstractions until multiple Marketing screens prove the shape.
- Replace mocks screen by screen rather than building speculative backend behavior.

### Backend Patterns
- Future APIs should follow the existing FastAPI router/service/schema structure.
- Long-running generation or publishing jobs should return job state rather than blocking UI requests.
- Provider-specific payloads should be normalized before reaching the frontend.

## Current Completed Work Summary
- Marketing Employee implementation memory created.
- First screen target identified: Social Media Campaign Overview from the provided screenshot.
- Social Media Campaign Overview mock UI implemented and routed at `/dashboard/marketing`.
- Mock frontend data boundary added for later backend replacement.
- Generated gallery, compose preview, and calendar scheduling screens added.
- FastAPI mock Marketing Employee endpoints added and registered.

## Current Risks
- Only the first screenshot has been provided so far; the broader information architecture may change as more screens arrive.
- Real platform API access, review requirements, publishing constraints, and costs are intentionally deferred.
- Mock-first UI must be kept easy to replace with real API calls later.
- Browser visual QA has not yet been completed against an authenticated local session in this work pass.
- Backend mock data is in-memory and resets on process restart.

## Best Future Execution Order
1. Build the first Social Media Campaign Overview mock screen.
2. Add each provided screenshot as a concrete Marketing Employee section.
3. Define the shared mock/API contract once multiple screens reveal the data model.
4. Replace frontend mocks with backend endpoints.
5. Add provider integrations one platform at a time behind explicit approval and credential setup flows.

## Session Maintenance Rules
- Update this file whenever Marketing Employee work changes architecture, scope, or completion state.
- Record decisions made, tasks completed, tasks still pending, and validation gaps.
- Keep entries concise and practical so future sessions can resume quickly.
