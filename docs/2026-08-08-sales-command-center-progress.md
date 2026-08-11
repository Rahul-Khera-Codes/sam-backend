# Sales Command Center Progress

**Date:** 2026-08-08
**Workspace:** Sales Command Center
**Status:** Core MVP implemented

## Context

Sales Command Center is a dedicated Sales Manager workspace for guided recurring sales meetings: Monday Kick-Off, Daily Stand-Up, Friday Review, Monthly Sales Intelligence, reports, scorecards, action items, coaching, pipeline review, and AI sales intelligence.

This first pass is UI-only and uses a typed mock backend layer. The mock service is intentionally shaped like an API client so it can later be replaced with CRM, Supabase, or REST integrations.

## Current MVP Scope

- Add Sales Manager as a top-level collapsible navigation group separate from the existing Sales Employee module.
- Add a nested Sales Command Center workspace route under `/dashboard/sales-command-center`.
- Build the Meeting Dashboard with meeting timeline, revenue goal progress, attendance, pipeline highlights, and pending actions.
- Build the Monday Kick-Off guided meeting screen with a stepper, performance review, pipeline review, weekly targets, campaigns, coaching, and mocked report generation.
- Provide lightweight placeholder pages for the remaining Sales Command Center nav items.
- Keep mock data and UI components ready for later CRM and meeting assistant integration.

## Completed

- Progress document created.
- Sales Command Center route group added under `/dashboard/sales-command-center`.
- Nested Sales Command Center layout added with secondary navigation.
- Main sidebar now includes a collapsible Sales Manager group.
- Duplicate internal Sales Manager sidebar removed; Sales Manager navigation now appears only once in the main left sidebar with the full section list.
- Role permission entries added for Sales Manager pages.
- Default static role restrictions allow Admin and Manager access to Sales Manager pages.
- Typed mock backend service added with 6 sales reps, 40 pipeline deals, meeting cards, action items, coaching notes, weekly targets, and 90 days of time-series data.
- Mock backend endpoints added in `sam-backend/backend/app/routers/command_center_mock.py`:
  - `GET /sales-command-center/dashboard`
  - `GET /sales-command-center/monday-kickoff`
  - `POST /sales-command-center/monday-kickoff/report`
- Sales Command Center UI services now fetch the SAM backend endpoints through `VITE_VOICE_AGENT_API_URL` and fall back to local seed data if the backend is unavailable.
- Monday Kick-Off report generation now calls the mock POST endpoint and renders the returned report id and summary.
- Reusable meeting and dashboard components added for KPI cards, status pills, charts, tables, meeting stepper, and AI assistant drawer.
- Meeting Dashboard implemented with dashboard cards, attendance, MRR pace, upcoming meetings, pending action items, and team quota progress.
- Monday Kick-Off implemented with guided steps for performance, pipeline review, targets, campaigns, coaching, and mocked report generation.
- Placeholder pages added for the remaining Sales Command Center navigation items.

## Pending After MVP

- Detailed Daily Stand-Up, Friday Review, Monthly Intelligence, Sales Team, Pipeline, Coaching Notes, Action Items, Reports, and Scorecards screens.
- Real meeting recording, transcript, summary, PDF report, CRM sync, and attendee notification workflows.
- Mobile design review for guided meeting flows and table-heavy screens.

## Future Functional Scope

- Daily Stand-Up with timed sections, priorities, roadblocks, and AI daily brief.
- Friday Review with celebration panel, results vs goals, lost deal analysis, and improvement commitments.
- Monthly Sales Intelligence with funnel, customer, market, conversation, product feedback, lead generation, and strategic action plan sections.
- Meeting report archive with recordings, transcripts, AI summaries, decisions, action items, owners, due dates, and completion status.
- Sales team, pipeline, coaching notes, action items, reports, and scorecards screens.
- Real CRM imports, AI meeting recorder, transcript generation, PDF exports, attendee notifications, and accountability tracking.

## Backend Integration Notes

- Replace mock service calls with CRM/Supabase/REST adapters without changing screen component contracts.
- Keep report generation and recording controls UI-only until backend workflows exist.
- Preserve `/dashboard/sales` for the existing Sales Employee tools.

## Verification

- IDE diagnostics on edited files: clean.
- IDE diagnostics on SAM backend endpoint wiring: clean.
- `sam-backend/backend/app/routers/command_center_mock.py` and `sam-backend/backend/app/main.py` Python syntax check: clean.
- `npm run lint`: not run because no JavaScript package runner is available in the shell environment.
