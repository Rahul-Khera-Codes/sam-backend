# HR Employee Implementation Memory

## Purpose
- This file is the long-lived memory and execution guide for the HR Employee agent.
- It should preserve product decisions, implementation status, section-by-section plans, technical notes, verification history, and remaining work.
- Future sessions should read this file first before continuing HR Employee work.

## Repos In Scope
- Backend: `sam-backend`
- Frontend: `ai-employees-app`

## Product Direction
- HR Employee is a multi-tenant HR and recruiting workspace inside AI Employees.
- Greenhouse is an optional per-business connector, not a platform-wide dependency.
- The product must still work for businesses that do not use Greenhouse.
- Greenhouse is the v1 source of truth for published jobs when connected.
- AI Employees remains the home for AI workflows, draft creation, future interview intelligence, and onboarding knowledge.

## Locked Decisions

### Tenancy
- Greenhouse is connected per business.
- Credentials and board settings are stored per business from day one.
- No connected Greenhouse account is required for businesses that want standalone HR workflows.

### Jobs
- Section 1 covers the jobs/source-of-truth path.
- Existing global integrations/settings area is the Greenhouse connection UI location.
- When Greenhouse is connected:
  - published jobs come from Greenhouse
  - native AI Employees drafts may still exist
  - push-to-Greenhouse is deferred
- Single selected Greenhouse board per business in v1.
- Manual refresh is the v1 sync trigger.

### Publishing / Distribution
- Greenhouse manages LinkedIn / Indeed distribution in connected mode.
- AI Employees does not directly post to LinkedIn / Indeed in section 1.
- Native builder toggles are preserved as future intent, not live external posting.
- Greenhouse Job Board API does not expose LinkedIn / Indeed distribution states, so UI should show those as managed in Greenhouse rather than pretending to know exact sync state.

### Ava Writing Assistant
- Ava is the in-product AI writing assistant for job creation.
- Ava should feel like a warm, sharp recruiting content partner, not a generic chatbot.
- Ava helps users:
  - turn rough role notes into polished job descriptions
  - rewrite responsibilities and qualifications for clarity
  - align copy to the company tone
  - make postings more candidate-friendly and structured
- Ava should not publish jobs directly. Publishing remains part of the job workflow, while Ava focuses on drafting and refinement.

### Talent Finder
- Talent Finder is a future sourcing feature, not active yet.
- It should replace static right-rail helper content on the job builder once real sourcing exists.
- It depends on:
  - candidate sourcing provider integrations
  - permission-safe external talent access
  - internal candidate mirror / review layer
  - AI ranking and shortlist support

### Applications
- Candidate application flow will eventually be in-app and submitted to Greenhouse via backend.
- Resume mandatory.
- Cover letter optional by default, configurable per job later.
- Custom questions, GDPR, EEOC, and regional compliance are required in future sections.

### Candidate / Interviewing
- Greenhouse remains the ATS record.
- AI notes and scores remain in-app in v1.
- Interview workflow is AI-Employees-specific and maps to customer Greenhouse stages later.
- AI recommendations are advisory only.

### Onboarding / Documents
- Customers upload approved onboarding and HR documents into the platform.
- HR Agent answers onboarding questions only from approved/published material.
- Direct upload is v1 ingestion; Drive/SharePoint sync is later.

## Section Roadmap

### Section 1: Greenhouse Connector + Jobs Read Path
Status: Implemented

Goal:
- Make Greenhouse connectable per business.
- Read published jobs from Greenhouse when connected.
- Keep standalone native job support for businesses without Greenhouse.

Delivered:
- DB tables:
  - `greenhouse_connections`
  - `hr_job_postings`
- Backend:
  - `GET /integrations/greenhouse/status`
  - `POST /integrations/greenhouse/connect`
  - `POST /integrations/greenhouse/refresh`
  - `DELETE /integrations/greenhouse/disconnect`
  - `GET /hr/jobs`
  - `GET /hr/jobs/workspace`
  - `GET /hr/jobs/{job_id}`
  - `POST /hr/jobs`
  - `PUT /hr/jobs/{job_id}`
  - `DELETE /hr/jobs/{job_id}` for native drafts only
- Frontend:
  - Greenhouse integration card in business integrations
  - HR dashboard jobs now use real jobs workspace data
  - HR job postings page now supports:
    - native drafts
    - native publish for standalone businesses
    - Greenhouse read mode for connected businesses
    - manual Greenhouse refresh
    - native draft deletion
    - app-native delete confirmation dialog

Important behavior:
- Standalone business:
  - source of truth = native
  - draft + publish both work in AI Employees
- Greenhouse-connected business:
  - source of truth = Greenhouse for published jobs
  - native builder is draft-only
  - publish-to-Greenhouse is deferred

Known limitations:
- No sandbox credentials were available during initial implementation.
- Greenhouse live normalization still needs validation against real payloads.
- `src/lib/voiceAgentApi.ts` has unrelated pre-existing lint debt.

Primary files:
- Backend:
  - `backend/app/routers/hr.py`
  - `backend/app/routers/greenhouse_integrations.py`
  - `backend/app/services/greenhouse_service.py`
  - `backend/app/schemas/hr.py`
- Frontend:
  - `src/components/business/IntegrationsTab.tsx`
  - `src/pages/dashboard/hr/HrDashboard.tsx`
  - `src/pages/dashboard/hr/HrJobPostings.tsx`
  - `src/lib/voiceAgentApi.ts`
- Migration:
  - `ai-employees-app/supabase/migrations/20260721123000_greenhouse_hr_section1.sql`

Verification history:
- Backend syntax compilation passed.
- Targeted ESLint passed for changed UI files.
- Native draft save bug was found and fixed:
  - root cause: Python Supabase query builder does not support `.single()`
  - fix: read first row from `.execute().data`
  - verified by replaying a real `POST /hr/jobs` request successfully
- Ava production diagnosis captured:
  - symptom: production `POST /hr/jobs/ai-assist` returns nginx `504 Gateway Time-out` while local succeeds
  - likely cause: Ava request path is too slow for production timeout budget because each request fetches KB rows, signs and downloads business PDFs, parses PDF text inline, and then calls OpenAI
  - infra amplifier: backend is currently started with plain single-process `uvicorn`, so a long Ava request can also block follow-up browser preflight traffic behind nginx
  - likely short-term mitigation: temporarily raise upstream timeout
  - real fix: move document extraction/caching out of the request path and keep `ai-assist` prompt assembly lightweight
  - follow-up after vector fix:
    - local `/health`, Ava preflight, and POST reachability pass
    - complete local Ava generation passes with `gpt-4o-mini`, updates six draft fields, and retrieves one document source plus four knowledge-base entries
    - local frontend is confirmed to serve `VITE_VOICE_AGENT_API_URL=http://localhost:8003`
    - production `/health` and Ava preflight both time out with zero bytes
    - production is therefore not serving the updated backend and requires a VPS backend deploy/rebuild/restart
    - reverified on July 21: production `/health` and `OPTIONS /hr/jobs/ai-assist` both return nginx `504 Gateway Time-out` after about 61 seconds; the browser's CORS message is secondary because nginx's timeout response has no CORS headers
    - production Supabase verification passed: all vector migrations are applied, `pgvector`, `hr_document_chunks`, and `match_hr_document_chunks` exist, and the target business has one ready document with two chunks
    - Git verification passed: vector commit `21c5050` is pushed and merged into remote `main` through PR #6
    - remaining fault domain is the VPS runtime: stale/unrebuilt backend container, stopped/restarting container, or unhealthy upstream process

Pending polish for section 1:
- Validate against real Greenhouse credentials
- Optionally improve native edit/delete microcopy
- Optionally refactor `voiceAgentApi.ts` lint debt in separate cleanup
- Evolve the Ava card from a UI persona into a real drafting workflow with prompt templates, refinement actions, and save/apply-to-fields behavior
- Talent Finder right rail intentionally stays unavailable until sourcing integrations and candidate mirror infrastructure exist

### Ava Writing Assistant Design + Implementation Plan
Status: Functional first pass implemented

Product role:
- Ava is the drafting copilot inside job creation.
- She should help write and refine job content, not replace ATS workflow control.

How Ava should work:
- User enters partial job information such as role, department, location, seniority, and rough notes.
- Ava turns that into structured content for:
  - job summary
  - responsibilities
  - qualifications
  - requirements & skills
  - perks / benefits
- Ava should support both:
  - full draft generation
  - targeted refinement of a single section

Recommended personality:
- Warm, clear, organized, and recruiter-friendly
- Helpful without sounding overly playful
- Good at turning vague notes into polished, readable hiring copy
- Focused on clarity, inclusiveness, and candidate readability

Recommended system behavior:
- Prefer concise, scannable writing
- Avoid overclaiming benefits or requirements
- Avoid biased or exclusionary phrasing
- Keep copy aligned to the selected job title, location, and seniority
- Preserve employer brand tone where brand guidance exists

Implemented now:
1. Reusable UI layer
   - `AvaAssistantCard`
   - `HRAssistantAvatar`
2. Backend drafting endpoint
   - `POST /hr/jobs/ai-assist`
3. Full-draft generation
   - fills multiple job content fields at once
4. Field-level actions
   - improve
   - suggest
   - format_list
5. Future extensions still planned:
   - deeper brand-aware prompting
   - stronger compliance linting
   - apply/preview diff UX

Technical approach:
- Frontend:
  - add explicit Ava actions such as:
    - Generate draft
    - Improve section
    - Rewrite tone
    - Shorten text
  - let user apply generated output into selected fields
- Backend:
  - add HR drafting endpoint(s)
  - accept structured payload with:
    - business_id
    - role metadata
    - existing draft fields
    - target field or full-draft mode
  - return normalized generated content, not raw chat-only text

Current backend implementation:
- Route: `POST /hr/jobs/ai-assist`
- Service: `backend/app/services/hr_drafting_service.py`
- Model used by Ava: `gpt-4o-mini`
- SDK path: `AsyncOpenAI(...).chat.completions.create(...)`
- Response format: JSON object with generated fields, updated field list, grounding counts, and a short assistant message
- Grounding sources now used by Ava:
  - business branding metadata
  - tenant-scoped vector retrieval over precomputed uploaded business document chunks
  - business knowledge base entries

Vector document architecture:
- Embedding model: `text-embedding-3-small`
- Dimensions: 1,536
- Storage: Supabase Postgres with `pgvector`
- Table: `hr_document_chunks`
- Search: HNSW cosine index through `match_hr_document_chunks`
- Tenant isolation:
  - every chunk carries `business_id`
  - vector RPC filters by `business_id`
  - a composite foreign key guarantees each chunk's `business_id` matches its parent document
  - RLS only permits members to read chunks for their businesses
  - anonymous table access is denied
  - vector matching RPC execution is restricted to the backend service role
- Ingestion:
  - PDF text is extracted and chunked once after upload
  - embeddings run as a FastAPI background task after the upload response
  - document status is tracked as `pending`, `processing`, `ready`, or `failed`
  - existing documents can be queued through `POST /documents/process-embeddings`
  - individual retries use `POST /documents/{document_id}/process-embedding`
- Ava request path:
  - builds a semantic search query from job context
  - creates one query embedding
  - retrieves at most six relevant cached chunks
  - does not download or parse PDFs
  - gracefully continues without vector context if retrieval is temporarily unavailable
- Database migrations:
  - `20260721101431_ava_document_embeddings.sql`
  - `20260721103002_optimize_hr_document_chunks_rls.sql`
  - `20260721103929_harden_hr_document_chunk_tenancy.sql`
- Verification:
  - linked Supabase migrations applied successfully
  - migration history aligned locally/remotely
  - anonymous vector chunk access denied
  - Supabase security advisor reported no vector-specific warning
  - Supabase performance advisor reported no vector-specific warning after RLS optimization
  - existing Human resource PDF indexed into two chunks
  - semantic retrieval returned the indexed document after threshold tuning
  - vector-grounded Ava generation completed in 7.22 seconds and used one document source
  - service-role-only retrieval remained functional after tenant hardening
  - upload now rejects a `location_id` that does not belong to the selected business
  - document/KB excerpts are treated as untrusted data and fenced against prompt instructions

Current frontend implementation:
- Ava card actions:
  - Auto-Generate Draft
  - Refine Current Draft
- Per-field actions:
  - Improve with AI
  - Suggest Perks
  - Format List
  - Suggest Benefits
- Results are applied directly into the live builder form
- Builder now includes an `Ava Activity` footer showing:
  - last action label
  - response model
  - updated fields
  - business document / knowledge base grounding counts
- Field-level AI actions now show a compact AI badge ahead of the label

Inputs Ava should use:
- job title
- department
- location + location type
- seniority
- employment type
- required experience
- existing notes already typed by user
- future:
  - company brand voice
  - company mission / industry niche
  - historical successful posting templates

Avatar guidance:
- Reuse the same visual product language as existing assistants:
  - calm, premium, minimal
  - polished abstract or portrait-like identity
  - not cartoonish
- For now, a strong app-native avatar treatment is sufficient:
  - circular avatar
  - gradient background
  - initials fallback
  - subtle status badge
- Future upgrade options:
  - custom static portrait asset for Ava
  - animated state-based avatar similar to executive agent patterns

Reference pattern from existing agents:
- Existing agents use a self-contained visual identity layer rather than tightly coupling avatar internals to business logic.
- This same approach should be used for Ava:
  - keep persona / caption / state separate from the drafting logic
  - make the avatar swappable later without rewriting drafting workflows

Current delivered UI improvement:
- Ava card now has:
  - clearer persona copy
  - stronger assistant framing
  - app-native avatar styling
  - capability chips
  - more modern gradient / glass-style visual treatment
  - responsive layout fix so the text block does not collapse when action buttons are visible
- Job builder UI now:
  - avoids section-number language in user-facing copy
  - uses a native confirmation dialog for draft deletion
  - shows Talent Finder as unavailable with concrete dependency reasons instead of placeholder publishing rules
- Ava drafting flow is functional:
  - verified full-draft generation in backend container
  - verified field-level `format_list` action in backend container
  - now records and displays the last Ava activity in the builder

### Section 2: In-App Candidate Application Submission
Status: Planned

Goal:
- Let candidates apply inside AI Employees instead of redirecting to Greenhouse-hosted forms.
- Submit applications to Greenhouse Job Board API via backend.

Scope:
- Fetch per-job application schema from Greenhouse
- Render dynamic application form in frontend
- Handle:
  - resume upload
  - optional cover letter
  - custom questions
  - GDPR / EEOC / diversity inputs based on job + tenant configuration
- Submit applications through backend proxy using Job Board API key

Backend plan:
- Add backend application submission endpoint
- Add secure handling for Greenhouse Job Board API key
- Add file upload/storage strategy for candidate attachments
- Normalize Greenhouse application API errors into user-friendly responses

Frontend plan:
- Job details / apply page
- Dynamic form renderer for Greenhouse questions
- Resume + cover letter UX
- Validation based on returned schema
- Success / retry states

Data model considerations:
- Candidate application mirror table(s) will likely be needed for analytics, AI summaries, and retry safety
- Store source job id, submission status, timestamps, and any external ids returned by Greenhouse

Dependencies:
- Real Greenhouse credentials
- Final job application UX location
- Attachment handling decision

Open questions for execution:
- Where exactly candidate-facing apply UI should live
- Storage strategy for resumes
- Whether we store raw application payload snapshots for audit/debugging

### Section 3: Candidate Mirror + AI Review Layer
Status: Planned

Goal:
- Keep Greenhouse as ATS record while AI Employees stores mirrored candidate data for AI workflows.

Scope:
- Mirror candidates/applications submitted through AI Employees
- Candidate summaries
- AI scoring
- shortlist recommendations
- recruiter-friendly internal candidate views

Backend plan:
- Add candidate mirror schema
- Add ingestion/update pipeline tied to in-app submissions
- Keep Greenhouse ids on records for traceability

Frontend plan:
- Replace current candidate mocks with real mirrored data
- Candidate list, candidate details, AI score badges, summaries

Rules:
- AI outputs are advisory only
- No automatic rejection or progression based solely on AI

Future extension:
- customer-controlled sync back to Greenhouse as note/tag

### Section 4: Interview Workflow + Stage Mapping
Status: Planned

Goal:
- Build AI Employees interview pipeline while allowing mapping to customer-specific Greenhouse stages.

Default conceptual flow:
- Applied
- AI Screened
- Shortlisted
- Interview Scheduled
- Interview Done
- Human Review
- Offer
- Hired / Rejected

Scope:
- Stage model in AI Employees
- Mapping layer to Greenhouse stages per tenant
- Human-triggered stage changes only

Backend plan:
- Stage definitions table
- Tenant stage mapping table
- Candidate workflow state storage

Frontend plan:
- Replace interviews mocks with mapped pipeline UI
- Stage chips, movement actions, and history

Constraints:
- Stage names vary by tenant
- exact one-to-one mirroring cannot be assumed

### Section 5: AI Interviewer Context + Question Bank + Rubrics
Status: Functional first pass implemented

Goal:
- Give the AI interviewer structured job-specific context and safe questioning rules.

Inputs required:
- job description
- required skills
- candidate application data
- role-specific scoring rubric
- question bank configuration
- compliance guardrails

Scope:
- fixed core question bank
- optional adaptive ordering
- follow-up probing toggle
- per-posting scoring rubric

Hard compliance rules:
- never allow questions about protected characteristics
- never allow salary history questions where restricted
- blocklist must not be removable at customer level

Future extension:
- import Greenhouse scorecards via Harvest API later

Section 5 implementation:
- Source of truth:
  - the latest published AI Employees interview-bank version is authoritative for future interviews
  - recruiters edit a mutable draft; `Publish & Activate` creates an immutable JSON snapshot and moves `active_version_id`
  - AI suggestions are draft inputs only and never become active without an administrator saving and publishing them
  - job descriptions ground suggestions, but they do not replace the saved question bank or rubric
  - future Greenhouse scorecard imports will enter as reviewable drafts rather than overwriting active content
- Current job scope:
  - attached only to saved native `hr_job_postings` UUIDs
  - Greenhouse jobs remain unavailable until the later canonical job-mirroring layer persists them locally
  - no Greenhouse token, Job Board API key, Harvest access, candidate mirror, or live interviewer runtime is required
- Database migration:
  - `20260722140000_hr_section5_interview_context.sql`
  - `hr_interview_banks` stores the mutable per-job settings/messages and active version pointer
  - `hr_interview_questions` stores ordered, enabled/required, category, competency, timing, follow-up, source, and compliance metadata
  - `hr_interview_rubric_criteria` stores weighted criteria and score 1/3/5 evidence anchors
  - `hr_interview_bank_versions` stores immutable published snapshots and publisher/version audit data
  - `hr_interview_compliance_rules` contains the 10 immutable platform rules
  - `hr_tenant_interview_restrictions` reserves additive tenant restrictions; tenants cannot remove platform rules
  - `hr_interview_compliance_checks` stores hashed-input safety outcomes and policy versions
  - all tenant children carry `business_id` and use composite foreign keys
  - all exposed tables have RLS and service-role-only policies
- Backend:
  - router: `backend/app/routers/hr_interviews.py`
  - schemas: `backend/app/schemas/hr_interviews.py`
  - persistence/versioning: `backend/app/services/hr_interview_bank_service.py`
  - generation/preview: `backend/app/services/hr_interview_generation_service.py`
  - compliance: `backend/app/services/hr_interview_compliance_service.py`
  - endpoints:
    - `GET /hr/jobs/{job_id}/interview-bank`
    - `PUT /hr/jobs/{job_id}/interview-bank`
    - `POST /hr/jobs/{job_id}/interview-bank/ai-suggest`
    - `POST /hr/jobs/{job_id}/interview-bank/preview`
    - `POST /hr/jobs/{job_id}/interview-bank/publish`
  - reads require business membership; editing/publishing require business `admin` or `super_admin`
  - generation and semantic safety classification use `gpt-4o-mini` with structured JSON
  - manual questions, AI suggestions, preview interviewer turns, rubric criteria, and publication all pass compliance validation
  - deterministic protected-topic checks run first; structured semantic classification follows and fails closed if unavailable
- Permanent prohibited categories:
  - age
  - race / ethnicity
  - religion
  - disability / medical history
  - pregnancy, childcare, or family plans
  - marital / relationship status
  - sexual orientation / gender identity
  - citizenship / national origin, while neutral legal work-authorization questions remain allowed
  - union membership / organizing
  - salary / compensation history
- Frontend:
  - dedicated deep-link route: `/dashboard/hr/job-postings/:jobId/interview-bank`
  - page: `src/pages/dashboard/hr/HrInterviewQuestionBank.tsx`
  - job-specific question actions now retain the native job ID
  - responsive run-sheet layout based on the approved reference, with a sticky settings rail on desktop and stacked mobile layout
  - the settings rail now matches the approved hierarchy: Interview Settings / AI Preview / Scoring Rubric tabs, Interview Format, AI Interviewer Persona and behavior controls, then AI Opening Message / closing script
  - visual redesign aligned to the approved reference: soft white surfaces, `#EAEAEA` hairline borders, pastel category badges, blue primary actions, card-based question run sheet, AI Suggest banner, role pill + AI Mode Active status, and Active Qs / Est. Minutes / Follow-ups stats
  - unsafe autosave failures open an accessible app-native `Question Not Saved` dialog that names the prohibited category, explains why the question was blocked, and tells the editor to revise or remove it
  - a blocked draft revision is not retried automatically until the editor changes it, preventing repeated warning dialogs
  - category/search state and Settings / AI Preview / Rubric tab state are URL-backed
  - question add/edit/delete, enable/disable, keyboard-friendly reordering, AI suggestions, autosave/manual save, safe synthetic preview, rubric editing, and publish are functional
  - Greenhouse scorecard import is visibly unavailable with its Harvest dependency explained
- Draft and publication validation:
  - minimum 3 enabled compliant questions
  - rubric requires at least 1 criterion
  - rubric weights must total exactly 100
  - active published versions remain unchanged while a draft is edited or a draft question is deleted
- Verification completed:
  - migration applied to linked Supabase
  - migration history aligned locally/remotely
  - tenant composite foreign keys verified live
  - RLS verified live on Section 5 tables
  - 10 immutable compliance rules verified live
  - backend modules compile successfully
  - frontend ESLint and TypeScript checks pass
  - the compliance service now returns category-specific human-readable reasons for deterministic blocks
  - frontend production build passes inside the Node 20 container
  - deterministic compliance unit coverage added under `backend/tests/test_hr_interview_compliance.py`
  - all 5 deterministic compliance tests pass in the backend container
  - isolated temporary-job E2E passed: draft revision 1 saved, immutable version 1 published, 2 AI questions generated, and a 6-turn synthetic preview returned by `gpt-4o-mini`
  - unsafe age-question E2E was rejected before any interview-bank row was created
- Deferred:
  - live AI interviewer runtime consumption of the active version
  - candidate-specific context from Sections 2 and 3
  - Greenhouse scorecard import via Harvest
  - approved/published HR document grounding after Section 7 adds editorial status

### Section 6: Candidate Review, Decision Support, and Human Approval Loop
Status: Planned

Goal:
- Turn AI outputs into usable decision support without automating hiring decisions.

Scope:
- AI summaries
- strong hire / borderline / no hire recommendations
- interview transcript summaries
- recruiter review panels
- explicit human action requirement for all important state changes

Backend plan:
- review records
- recommendation snapshots
- transcript/summary references

Frontend plan:
- candidate review detail view
- recommendation cards
- human approval controls

Legal / product constraint:
- recommendations are advisory only

### Section 7: Onboarding Knowledge Base + HR Agent Grounding
Status: Functional first pass implemented

Goal:
- Use approved customer documents as the trusted source for onboarding and HR support answers.

Scope:
- document upload and categorization
- document status awareness
- answer only from approved / published docs
- employee onboarding helper flows

Data expectations:
- owner
- category
- status: Draft / Under Review / Published

Future extension:
- Google Drive / SharePoint sync

Implemented now:
- Supabase:
  - migration `20260723084216_hr_policy_docs_onboarding.sql`
  - private storage bucket id `hr-policy-docs`
  - `business_documents` now carries onboarding metadata:
    - `document_scope`
    - `category`
    - `tags`
    - `status`
    - `uploaded_by`
    - `storage_bucket`
  - `hr_document_read_progress` stores per-user read progress
  - `match_hr_policy_document_chunks` retrieves only tenant-scoped, published, AI-ready HR onboarding documents
- Backend:
  - HR policy upload/list/update/category merge/bulk delete/signed URL/progress/retry endpoints under `/documents/hr-policy`
  - uploaded PDFs are stored in `hr-policy-docs`
  - new uploads are queued for embedding immediately
  - onboarding chat endpoint: `POST /hr/onboarding/chat`
  - chat answers use only retrieved published HR policy chunks and refuse unsupported answers
- Frontend:
  - `HrOnboarding.tsx` no longer uses `getHrMockWorkspace`
  - document library loads real HR policy documents
  - upload dialog, search, category/status filters, pagination, row selection, bulk delete, category merge, signed document viewing, download/open, embedding retry, save progress, quick prompts, and chat are functional
  - support view embeds the signed PDF and sends questions to the onboarding chat endpoint
  - upload completion now shows an app-native success dialog confirming the document was stored in the HR policy Docs bucket and queued for vector indexing
  - onboarding chat now searches across all uploaded published HR policy documents rather than limiting context to the currently opened document
  - support view layout was tightened to match the approved reference more closely:
    - app-level document controls are aligned in the document card header
    - signed PDF preview uses an inline embedded view with browser PDF chrome suppressed where supported
    - HR AI Agent panel spacing, prompt chips, input, and icon-only button accessibility were polished
  - PDF controls were corrected:
    - zoom buttons now update the embedded PDF URL zoom fragment and force the iframe to refresh
    - the default `100%` document state now requests PDF fit-to-width mode so the page fits the viewer window instead of clipping
    - zoom levels now scale relative to the fit-to-width baseline, so `75%` is visibly smaller than `100%`
    - download now fetches the signed URL as a blob and triggers a real file download using the stored filename

Verification completed:
- migration `20260723084216_hr_policy_docs_onboarding.sql` applied to the linked Supabase project
- migration history confirms local and remote both have `20260723084216`
- Backend changed modules compile successfully
- Frontend TypeScript check passes
- Targeted ESLint passes for `HrOnboarding.tsx`
- Reverified TypeScript and targeted `HrOnboarding.tsx` ESLint after the upload success dialog / all-document chat update
- Reverified TypeScript, targeted `HrOnboarding.tsx` ESLint, and editor diagnostics after the support-view UI polish
- Reverified TypeScript, targeted `HrOnboarding.tsx` ESLint, and editor diagnostics after fixing PDF zoom/download controls
- Reverified TypeScript, targeted `HrOnboarding.tsx` ESLint, and editor diagnostics after changing the `100%` PDF state to fit-to-width
- Reverified TypeScript, targeted `HrOnboarding.tsx` ESLint, and editor diagnostics after normalizing PDF zoom levels relative to fit-to-width

Remaining validation / limitations:
- End-to-end upload, signed preview, embedding readiness, and chat Q&A still need live verification against Supabase/OpenAI
- `voiceAgentApi.ts` still has unrelated pre-existing lint debt
- Image-only/scanned PDFs still require future OCR fallback
- FastAPI background tasks remain a retryable bridge, not a durable document-ingestion queue

## Cross-Cutting Technical Plan

### Multi-Tenancy
- All HR Employee data must stay business-scoped.
- Greenhouse configuration is business-level, not location-level.
- Access must continue to use `verify_business_access`.
- Greenhouse tenant isolation is implemented and hardened:
  - one connector row per business through `UNIQUE (business_id)`
  - every connector/job API verifies membership and scopes reads/writes by `business_id`
  - only business `admin` / `super_admin` roles can connect, replace, or disconnect credentials
  - database composite foreign key prevents an HR job from referencing another business's Greenhouse connection
  - migration `20260721130000_harden_greenhouse_multitenancy.sql` is applied remotely
  - live database verification confirmed both tables have RLS enabled, service-role-only policies, the one-connection-per-business constraint, and the composite tenant foreign key
  - service-role native-job updates repeat `id`, `business_id`, and `source = native` predicates on the final mutation
  - ordinary HR job responses no longer include board-token snapshots or raw Greenhouse source payloads
  - non-admin connector status responses omit the board token, and non-credential operations do not load the Job Board API key
- Standalone businesses remain fully supported: without an active connector, native jobs are the source of truth.

### Security
- Never expose Greenhouse API keys to frontend.
- Submission must remain backend-proxied.
- Keep ATS secrets server-side only.
- Job Board API keys are stored only in the service-role-protected connector table; status responses expose only a boolean indicating whether a key is configured.
- Editing a connector while leaving the API-key field blank preserves the existing secret rather than clearing it.

### Data Model Direction
- Current foundation:
  - `greenhouse_connections`
  - `hr_job_postings`
- Likely future additions:
  - candidate mirror tables
  - application mirror / submission logs
  - interview stage mapping tables
  - interview session / transcript tables
  - onboarding answer/source trace tables

### Backend Patterns
- Follow existing FastAPI router structure
- Keep integration routes separate from HR routes where appropriate
- Use service-role Supabase access in backend

### Frontend Patterns
- Keep business-wide connector UI under existing integrations/settings area
- Replace mocks section by section rather than rewriting every HR page at once

## Current Completed Work Summary
- Section 1 implemented
- Native draft save fixed after first runtime bug
- Native draft delete added
- Browser confirm replaced with app-native confirmation dialog
- LinkedIn / Indeed explanation copy added to builder
- Section 5 interview question bank, settings, AI preview, scoring rubric, compliance policy, and immutable publication implemented
- Section 7 onboarding document library, HR policy upload, embeddings, signed PDF viewing, and grounded onboarding chat implemented as a first pass

## Current Risks
- No Greenhouse sandbox credentials yet for true live validation
- Job Board API coverage is limited to public jobs + application-related flows; deeper ATS sync will require Harvest later
- Existing `voiceAgentApi.ts` lint debt remains unrelated but present
- Image-only/scanned PDFs have no extractable text with `pypdf`; they are marked `failed` and require a future OCR ingestion fallback
- FastAPI background tasks are a retryable bridge, not a durable queue; interrupted indexing remains `pending`/`failed` and can be requeued from Documents settings

## Best Future Execution Order
1. Finish live validation of section 1 with real/sandbox Greenhouse
2. Build section 2 application submission flow
3. Replace candidate mocks with mirrored data
4. Build interview stage mapping
5. Wire the active Section 5 version into the live interviewer after candidate/session records exist
6. Build decision-support review layer
7. Apply and live-verify Section 7 onboarding document upload, embedding, preview, and chat

## Session Maintenance Rules
- Update this file whenever HR Employee work changes architecture, scope, or completion state.
- Record both what is done and what still remains.
- Keep section status current so future sessions can resume quickly.
