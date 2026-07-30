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
- Marketing Employee now uses real backend jobs for caption/concept and image generation.
- Real data and publishing integrations will be added later behind backend APIs.
- The product should support businesses that have no social platform integrations connected yet.

## Locked Decisions

### Current Build Mode
- Replace the previous mock backend with real persisted backend endpoints.
- Use OpenAI for caption/concept generation and image generation.
- Persist campaigns, jobs, assets, and scheduled posts in Supabase.
- Store generated media in a private Supabase Storage bucket and return signed URLs.
- Do not call Meta, TikTok, LinkedIn, X, Google, or other social publishing APIs in this phase.
- HeyGen video execution is not live yet; the API returns a disabled/needs-credentials job contract until credentials and the exact HeyGen video API are confirmed.

### Tenancy
- All future Marketing Employee data must be business-scoped.
- Marketing settings, campaigns, generated assets, schedules, and integration credentials should belong to a business.
- Location-specific marketing may be added later, but the first workspace should behave as a business-level employee.

### Campaign Generation
- The first visible screen is the Social Media Campaign Overview.
- Users describe an idea, choose advanced settings, select an aspect ratio, and choose an image count.
- The current screenshot shows image generation controls, not a full publishing flow.
- Export is not shown until a real report/export path exists.
- Confirmed create-post flow:
  - idea setup
  - generated content gallery
  - selected item opens compose/publish preview
  - mock publish schedules the post into the July 2026 calendar
- Gallery item selection should open the selected item in the compose/publish preview.
- Mock publish should create a scheduled post and show it on the calendar.
- Default scheduling should use the next available mock slot in July 2026.
- Generation flow now:
  - setup creates a campaign row
  - concept generation starts an OpenAI-backed job
  - gallery polls job status and lists concept assets
  - selected concept opens compose preview
  - image generation requires explicit confirmation before calling OpenAI image generation
  - generated image is uploaded to private Supabase Storage
  - compose preview uses signed image URLs
  - schedule creates an internal scheduled post only

### Backend Strategy
- Backend exposes normalized campaign/job/asset endpoints rather than returning raw provider payloads.
- External platform secrets must never be exposed to the frontend.
- Provider calls run server-side only.
- Long-running generation is represented through persisted jobs and frontend polling.

## Section Roadmap

### Section 1: Social Media Campaign Overview
Status: Real generation first pass implemented

Goal:
- Replace the generic Marketing Employee coming-soon page with the first dedicated Marketing Employee screen.
- Match the provided screenshot closely enough for review while keeping the code maintainable.
- Wire state locally/mock-first for prompt text, aspect ratio, image count, advanced settings, randomization, and export action.

Planned frontend:
- Add a Marketing Employee dashboard route under `/dashboard/marketing`.
- Keep the first screen directly inside the existing dashboard shell with no second-level Marketing sidebar, matching the provided screenshot.
- Add the Social Media Campaign Overview page with:
  - title and helper copy
  - last-run range/status details
  - centered campaign prompt card
  - advanced settings status
  - idea textarea
  - randomize action
  - aspect-ratio options
  - image-count segmented control
  - generation behavior

Backend/data approach:
- Supabase migration:
  - `20260729045730_marketing_employee_generation.sql`
- Private storage bucket:
  - `marketing-assets`
- Tables:
  - `marketing_campaigns`
  - `marketing_assets`
  - `marketing_generation_jobs`
  - `marketing_scheduled_posts`
- All tables are tenant-scoped by `business_id`.
- RLS is enabled on all new tables.
- Storage policies follow the business-folder pattern used by HR policy docs.

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
- Frontend helper now calls real backend endpoints and no longer uses local mock generation.
- Backend endpoints:
  - `GET /marketing/workspace`
  - `POST /marketing/campaigns`
  - `POST /marketing/campaigns/{campaign_id}/concepts`
  - `GET /marketing/campaigns/{campaign_id}/assets`
  - `POST /marketing/campaigns/randomize`
  - `POST /marketing/assets/{asset_id}/image`
  - `POST /marketing/assets/{asset_id}/video`
  - `GET /marketing/jobs/{job_id}`
  - `GET /marketing/assets/{asset_id}/signed-url`
  - `POST /marketing/scheduled-posts`
  - `GET /marketing/calendar`
- Backend service:
  - `backend/app/services/marketing_generation_service.py`
- Backend schemas:
  - `backend/app/schemas/marketing.py`
- OpenAI settings:
  - `marketing_text_model`
  - `marketing_image_model`

Verification:
- Frontend TypeScript check passed.
- Targeted ESLint passed for `App.tsx`, `MarketingCampaignOverview.tsx`, and `marketingEmployeeMock.ts`.
- Cursor diagnostics reported no linter errors for edited files.
- Backend compile passed for marketing router/service/schema/config/main files.
- Frontend TypeScript passed after replacing mock state with real API state.
- Final verification for this real-generation pass:
  - backend compile passed for marketing router/service/schema/config/main files
  - frontend TypeScript check passed
  - targeted ESLint passed for Marketing frontend files
  - Cursor diagnostics reported no linter errors for edited files
- Runtime migration fix:
  - `POST /marketing/campaigns` initially failed because the remote Supabase project did not have `marketing_campaigns`
  - migration `20260729045730_marketing_employee_generation.sql` was patched to add the required `(id, business_id)` uniqueness for composite tenant foreign keys
  - migration `20260729045730` is now applied remotely
- UI polish / scheduling update:
  - generated concept cards now show richer visual previews before image generation
  - top step navigation is clickable with disabled states for unavailable steps
  - compose review now lets users choose a schedule date, time, and quick time preference before creating the scheduled post
  - calendar displays the selected schedule time instead of relying only on the backend default slot
  - page shell, gallery cards, empty states, and focus/aria details were polished using frontend design and web interface guidance
- Preview/export update:
  - removed the placeholder Export Report button because it did not perform a real report export
  - review screen now has selectable Instagram, X, and LinkedIn preview tabs
  - previews use the selected generated asset and caption, with platform-specific layout treatments researched from current preview/mockup references
  - Instagram preview uses feed chrome, action row, save icon, and approximate caption fold
  - X preview uses avatar/handle layout, post body, media card, and action metrics row
  - LinkedIn preview uses feed card layout, headline/meta area, media card, reaction summary, and action row
- Draft and preview adjustment update:
  - Save Draft is available from the Marketing flow so users can preserve work before scheduling
  - incomplete drafts are stored locally per business and listed on the first setup screen beneath the idea card
  - continuing a draft restores prompt, generation settings, caption, selected platforms, schedule values, preview tab, and media adjustment settings when available
  - platform previews now expose image Fit/Fill and Top/Center/Bottom controls per platform to help generated media avoid bad cropping
  - platform preview media no longer shows the internal concept title overlay, so the visual reflects the actual post creative
- Advanced settings / image generation update:
  - advanced settings disabled now hides aspect-ratio and image-count controls; users only provide prompt, randomize, platforms, and generate
  - advanced settings enabled shows aspect ratio and image amount, and those values are sent into campaign generation
  - generated concepts do not automatically start OpenAI image jobs; users must select a concept and explicitly click Generate image
  - image count controls how many concepts are produced when advanced settings are enabled
  - generated image thumbnails are selectable in Review so users can preview each generated image
  - platform previews now include zoom controls and support mouse drag crop adjustment after zooming
  - backend uses platform-native aspect defaults when advanced settings are disabled, while preserving the selected aspect ratio when advanced settings are enabled
- Signed zoom / aspect guidance update:
  - preview zoom now uses a centered 0% slider with negative zoom-out and positive zoom-in values
  - drag crop adjustment works when the zoom is moved away from 0%
  - setup screen now shows aspect-ratio guidance so users understand which platforms fit 1:1, 9:16, 16:9, and 2:3
  - selected aspect ratio is highlighted in the guidance block when advanced settings are enabled
  - backend image prompts now explicitly instruct OpenAI to compose for the selected social canvas ratio in addition to using the matching image size
- Image generation throttling correction:
  - removed automatic image job creation after concept generation to avoid provider rate limits and duplicate/piled-up image jobs
  - starting a new campaign clears in-flight frontend image job state
  - Review only lists generated media for the currently selected concept
  - Generate image now starts only the remaining number of jobs needed for the selected concept to reach the campaign image count
  - Generate image refuses to create more jobs once the selected concept already has the requested number of pending, generating, or ready images
- Calendar navigation/date correction:
  - Marketing calendar now tracks a dynamic visible month instead of hardcoding July 2026
  - mini calendar and main calendar month arrows now navigate months
  - scheduled posts are matched by local date, fixing cases where an August 1 scheduled post appeared on July 1
  - scheduling a post opens the calendar on the scheduled month
  - calendar view now includes a Back to Review action when a selected concept is available
- Scheduled post deletion update:
  - added backend `DELETE /marketing/scheduled-posts/{scheduled_post_id}`
  - frontend calendar API can delete scheduled posts for the current business
  - upcoming-post cards and calendar cells now expose delete actions
  - deleted scheduled posts are removed from local calendar state after backend confirmation
- Social publishing integration update:
  - added tenant-scoped `marketing_platform_integrations` storage for Instagram and X connections, with encrypted access/refresh tokens and account metadata
  - extended scheduled posts with `publishing`, `failed`, provider post IDs, publish errors, published timestamp, and attempt count
  - added backend Marketing integration OAuth endpoints for Instagram and X under `/integrations/marketing/*`
  - implemented X media upload + tweet publishing and Instagram media container + publish flow for generated image assets
  - wired the existing backend scheduler to check due Marketing scheduled posts every minute and update publish status/results
  - added Instagram and X cards to Business Settings integrations, including OAuth callback handling and disconnect
  - Marketing Review now shows selected-platform publish readiness and blocks scheduling to disconnected or unsupported targets
  - calendar and upcoming-post cards now show scheduled/publishing/published/failed status plus provider errors
  - required env remains: `marketing_x_client_id`, `marketing_x_client_secret`, `marketing_meta_app_id`, `marketing_meta_app_secret`, `marketing_token_encryption_key`
  - redirect env is split per environment: `marketing_x_redirect_uri_local`, `marketing_x_redirect_uri_production`, `marketing_meta_redirect_uri_local`, `marketing_meta_redirect_uri_production`
  - old single redirect env names are still kept as fallback values, but new local/production names should be used for active setup
  - Instagram publishing still requires generated images to be reachable by Meta over HTTPS; signed Supabase asset URLs are used for the first implementation
- Post Now update:
  - Review now includes a `Post Now` action next to `Schedule Post`
  - `Post Now` requires a selected ready generated image and connected/supported publish platforms
  - backend creates an immediate scheduled-post row, publishes it through the same Instagram/X provider services, and returns updated publish status
  - successful provider post URLs are stored in scheduled-post metadata so the UI can prompt the user to open the published post

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
- Mock endpoints replaced with real job-based backend endpoints.
- OpenAI caption/concept and image generation service added.
- Private Supabase Storage and DB persistence migration added.
- HeyGen video endpoint returns disabled/needs-credentials state for future wiring.

## Current Risks
- Only the first screenshot has been provided so far; the broader information architecture may change as more screens arrive.
- Real platform API access, review requirements, publishing constraints, and costs are intentionally deferred.
- Mock-first UI must be kept easy to replace with real API calls later.
- Browser visual QA has not yet been completed against an authenticated local session in this work pass.
- Social publishing is still deferred.
- HeyGen video execution is still deferred pending credentials/API contract.
- Supabase migration `20260729045730` is applied remotely.

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
