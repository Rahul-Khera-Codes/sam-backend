-- FULL TABLE CLEANUP
-- Run this in: Supabase Dashboard → SQL Editor
-- ⚠ Deletes ALL rows from all tables. Schema is untouched.
-- Run BEFORE cleanup_database.py (which deletes auth users).

TRUNCATE TABLE
  transcripts,
  recordings,
  call_summaries,
  calls,
  appointments,
  settings_audit_log,
  agent_settings,
  agent_state,
  business_hours,
  custom_schedules,
  forwarding_rules,
  forwarding_contacts,
  gmail_tokens,
  google_calendar_tokens,
  knowledge_base,
  location_services,
  location_invitations,
  user_availability,
  user_availability_overrides,
  user_services,
  user_locations,
  user_roles,
  profiles,
  business_documents,
  business_phone_numbers,
  role_page_permissions,
  custom_roles,
  services,
  locations,
  businesses
CASCADE;
