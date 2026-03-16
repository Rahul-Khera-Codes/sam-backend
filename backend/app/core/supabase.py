from supabase import create_client, Client
from app.core.config import settings

# ── Anon client ───────────────────────────────
# Used when acting on behalf of an authenticated user
# Respects RLS policies
supabase: Client = create_client(
    settings.supabase_url,
    settings.supabase_anon_key,
)

# ── Service role client ───────────────────────
# Used by voice agent worker to write call data
# Bypasses RLS — only use server-side, NEVER expose to frontend
supabase_admin: Client = create_client(
    settings.supabase_url,
    settings.supabase_service_role_key,
)
