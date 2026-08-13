# Mission Control Progress

**Date:** 2026-08-08
**Workspace:** Mission Control
**Status:** Core MVP implemented

## Context

Mission Control is the internal Super Admin workspace for AI Employees Inc. It is intended to give admins one place to monitor customer health, business performance, usage, finance, support, operations, reports, alerts, and AI insights.

This first pass is UI-only and uses a typed mock backend layer. The mock service is intentionally shaped like an API client so it can later be replaced with Supabase or REST endpoints.

## Current MVP Scope

- Add Mission Control as a top-level collapsible navigation group.
- Add a nested Mission Control workspace route under `/dashboard/mission-control`.
- Build the Executive Dashboard with KPI cards, charts, usage summaries, customer health, and AI insights.
- Build the Companies screen with a searchable, sortable, filterable, paginated table and export actions.
- Provide lightweight placeholder pages for the remaining Mission Control nav items.
- Keep all mock data and UI components ready for later backend integration.

## Completed

- Progress document created.
- Mission Control route group added under `/dashboard/mission-control`.
- Nested Mission Control layout added with secondary navigation.
- Main sidebar now includes a collapsible Mission Control group.
- Duplicate internal Mission Control sidebar removed; Mission Control navigation now appears only once in the main left sidebar with the full section list.
- Role permission entries added for Mission Control pages.
- Default static role restrictions limit Mission Control pages to Super Admin.
- Typed mock backend service added with 25 companies, KPI data, 90 days of time-series data, usage rankings, health scores, and AI insights.
- Mock backend endpoints added in `sam-backend/backend/app/routers/command_center_mock.py`:
  - `GET /mission-control/dashboard`
  - `GET /mission-control/companies`
- Mission Control UI services now fetch the SAM backend endpoints through `VITE_VOICE_AGENT_API_URL` and fall back to local seed data if the backend is unavailable.
- Reusable dashboard components added for KPI cards, status pills, filter bars, chart cards, tables, health score, and insight cards.
- Executive Dashboard implemented with KPI sparklines, filters, charts, health segments, top usage companies, and AI insights.
- Companies screen implemented with filter bar, searchable/sortable/paginated/exportable table, account status, usage, AI employee icons, and health score pills.
- Placeholder pages added for the remaining Mission Control navigation items.
- Supabase migration added for Super Admin Mission Control support:
  - `platform_audit_logs`
  - `impersonation_sessions`
  - Rahul Super Admin seed for `rahul.excel2011@gmail.com`
  - Mission Control page permissions for system Super Admin roles
- Backend Super Admin auth helper added in `sam-backend/backend/app/core/auth.py`.
- Protected Mission Control router added in `sam-backend/backend/app/routers/mission_control.py`.
- Scoped impersonation endpoints added:
  - `POST /mission-control/impersonation/start`
  - `GET /mission-control/impersonation/current`
  - `POST /mission-control/impersonation/end`
  - `GET /mission-control/audit-logs`
- Frontend Super Admin route guard added for Mission Control.
- Frontend role labels now show `super_admin` as Super Admin.
- Active-business role resolution: `appRole`, permissions, and `isSuperAdmin()` are scoped to the selected location’s business (not “any super_admin across businesses”).
- Mission Control is gated by **active-business Super Admin** (`isSuperAdmin()`) and also remains available to platform Super Admins.
- DB role_page_permissions cannot grant Mission Control paths; `canAccessPathDynamic` requires an explicit Super Admin gate.
- Roles & Permissions uses draft checkbox state with a Save Changes confirmation dialog (app AlertDialog). Non–Super Admins remain read-only.
- System Manager (`admin`) roles are granted Sales Manager pages via migration `20260813090000_sales_manager_permissions_for_admin.sql`.
- Profile Settings binds email to the authenticated user only, isolates password fields, and shows the active-business role badge.
- Locations settings lists all `user_locations` memberships with Created / Invited markers (Invited when a `location_invitations` record exists or the user is not the business owner; Created otherwise).
- Promoting a member to Super Admin clears `custom_role_id` and roles refresh on tab focus so Mission Control appears without a full re-login.
- Mission Control Companies screen now includes a `Login As Company` confirmation flow.
- Dashboard shell now shows a prominent `Impersonating [Company]` banner with an end action.
- Mission Control visibility bug fixed: dynamic permissions no longer treat missing DB page keys as allowed. Restricted paths now fall back to `RESTRICTED_PAGES`.
- Parent route `/dashboard/mission-control` restricted to `super_admin` only.
- Migration `20260813043000_mission_control_deny_non_super_admin.sql` inserts explicit `false` Mission Control permissions for system `admin`/`user` roles and keeps `true` for `super_admin`.
- Invite Edge Functions reject Super Admin invites and only assign `admin` or `user` on acceptance.
- Team Management role changes (including promotion to Super Admin) require an existing Super Admin; RLS already enforces the same rule on `user_roles`.

## Super Admin Role Model

- Business/location creators receive `super_admin` through `create_business_with_owner` (business Super Admin for that company only).
- Invited company members receive only `admin` or `user`.
- `rahul.excel2011@gmail.com` is seeded as a platform Super Admin via the Mission Control migration when the Auth user exists (membership on the `type = 'platform'` business).
- Any existing Super Admin for a business may promote another member of that business to Super Admin from Team Management → Change Role.
- Mission Control is visible to Super Admins of the **active business** (`isSuperAdmin()`), and also to platform Super Admins.

## Pending After MVP

- Full Company Profile route and detail tabs.
- Real export endpoints for Excel and PDF beyond the current CSV mock export.
- Mobile design review for dense tables and charts.
- Apply the Supabase migrations in the target environment and confirm Rahul's Supabase auth user exists before or during migration.
- Expand impersonation auditing from session start/end into selected sensitive actions.
- Add admin-facing audit log screen inside Mission Control Operations.
- Add impersonation expiry handling in the UI when the two-hour session expires.

## Future Functional Scope

- Company Profile tabs with subscription, usage, users, activity timeline, and quick actions.
- Health Score detail model connected to live customer telemetry.
- Communications broadcast composer and message analytics.
- SaaS analytics, API usage, AI voice analytics, AI usage, financial, customer success, support, audit logs, system health, feature flags, impersonation, subscription management, API keys, reports, alerts, automation, and AI insights workflows.
- Real backend endpoints, auth-aware permissions, audit writes, exports, scheduled reports, and impersonation safeguards.

## Backend Integration Notes

- Replace mock service calls with Supabase or REST adapters without changing screen component contracts.
- Keep export buttons UI-only until backend export endpoints are available.
- Company row click is prepared for a later Company Profile route.
- Super Admin access is database-backed through `user_roles.role = 'super_admin'`.
- Impersonation is scoped, not a customer-equivalent Supabase auth token. The actor remains Rahul/Super Admin and the target business is stored in `impersonation_sessions`.
- Backend endpoints that expose Mission Control data should use `require_platform_super_admin`.
- The frontend business context reads the active impersonation session and falls back to the user's normal business role when no impersonation is active.

## Verification

- IDE diagnostics on edited files: clean.
- IDE diagnostics on SAM backend endpoint wiring: clean.
- `sam-backend/backend/app/routers/command_center_mock.py` and `sam-backend/backend/app/main.py` Python syntax check: clean.
- `npm run lint`: not run because no JavaScript package runner is available in the shell environment.
