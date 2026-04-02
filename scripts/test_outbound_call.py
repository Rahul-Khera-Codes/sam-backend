#!/usr/bin/env python3
"""
Test script for outbound call API.

Usage:
    python scripts/test_outbound_call.py +14155551234
    python scripts/test_outbound_call.py +14155551234 --purpose "Appointment reminder for tomorrow at 2pm"
    python scripts/test_outbound_call.py +14155551234 --business-id <uuid>

Requires:
    - Backend running at localhost:8003 (docker compose up -d)
    - Migration applied (livekit_outbound_trunk_id column exists)
    - At least one phone number with an outbound trunk in business_phone_numbers
"""

import argparse
import json
import os
import sys
import httpx
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

API_BASE = os.getenv("API_BASE", "http://localhost:8003")

# Test business (Mirage Banquets)
DEFAULT_BUSINESS_ID = "da9fc4fb-2b16-48ab-8856-696870d0a18a"
DEFAULT_LOCATION_ID  = "fd7d1823-3d86-44cf-8039-cbaca6bfdd01"

# Backend service role key — used to get a JWT without going through browser auth
# We call Supabase directly to sign in as a test user and get a token.
SUPABASE_URL = None
SUPABASE_SERVICE_KEY = None

# Load from backend/.env
_env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "SUPABASE_URL":
            SUPABASE_URL = val
        elif key == "SUPABASE_SERVICE_ROLE_KEY":
            SUPABASE_SERVICE_KEY = val

# Also check agent/.env.local
_agent_env = Path(__file__).resolve().parent.parent / "agent" / ".env.local"
if _agent_env.exists() and (not SUPABASE_URL or not SUPABASE_SERVICE_KEY):
    for line in _agent_env.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "SUPABASE_URL" and not SUPABASE_URL:
            SUPABASE_URL = val
        elif key == "SUPABASE_SERVICE_ROLE_KEY" and not SUPABASE_SERVICE_KEY:
            SUPABASE_SERVICE_KEY = val


# ── Auth helper ───────────────────────────────────────────────────────────────

def get_jwt(email: str, password: str) -> str:
    """Sign in to Supabase and return the access token."""
    if not SUPABASE_URL:
        print("ERROR: Could not read SUPABASE_URL from backend/.env")
        sys.exit(1)

    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    resp = httpx.post(
        url,
        json={"email": email, "password": password},
        headers={"apikey": SUPABASE_SERVICE_KEY or ""},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"ERROR: Supabase sign-in failed ({resp.status_code}): {resp.text}")
        sys.exit(1)

    return resp.json()["access_token"]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test outbound call via the backend API")
    parser.add_argument("to_phone", help="E.164 phone number to dial, e.g. +14155551234")
    parser.add_argument("--purpose", default="Test outbound call", help="Call purpose / note")
    parser.add_argument("--business-id", default=DEFAULT_BUSINESS_ID)
    parser.add_argument("--location-id", default=DEFAULT_LOCATION_ID)
    parser.add_argument("--email", default="rahul.excel2011@gmail.com", help="Supabase user email for auth")
    parser.add_argument("--password", help="Supabase user password (prompted if not given)")
    parser.add_argument("--token", help="Use a pre-existing JWT instead of signing in")
    args = parser.parse_args()

    # ── Auth
    if args.token:
        token = args.token
        print(f"Using provided JWT token.")
    else:
        if not args.password:
            import getpass
            args.password = getpass.getpass(f"Password for {args.email}: ")
        print(f"Signing in as {args.email}...")
        token = get_jwt(args.email, args.password)
        print("Signed in OK.")

    # ── Normalize phone number
    to_phone = args.to_phone.strip()
    if not to_phone.startswith("+"):
        to_phone = "+1" + to_phone.lstrip("0")
    print(f"\nDialing: {to_phone}")
    print(f"Purpose: {args.purpose}")
    print(f"Business: {args.business_id}")
    print(f"API: {API_BASE}/calls/outbound\n")

    # ── Fire the request
    payload = {
        "business_id": args.business_id,
        "location_id": args.location_id,
        "to_phone_number": to_phone,
        "call_purpose": args.purpose,
    }

    try:
        resp = httpx.post(
            f"{API_BASE}/calls/outbound",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except httpx.ConnectError:
        print(f"ERROR: Could not connect to {API_BASE}. Is the backend running?")
        print("  Run: docker compose up -d")
        sys.exit(1)

    print(f"HTTP {resp.status_code}")
    try:
        data = resp.json()
        print(json.dumps(data, indent=2))
    except Exception:
        print(resp.text)

    if resp.status_code == 201:
        print("\n✓ Outbound call initiated successfully!")
        print(f"  Call ID:  {data.get('call_id')}")
        print(f"  Room ID:  {data.get('livekit_room_id')}")
        print(f"  Status:   {data.get('status')}")
        print("\nCheck agent logs: docker logs -f sam-backend-sam-agent-1")
    else:
        print(f"\n✗ Call failed. See error above.")
        if resp.status_code == 422 and "outbound trunk" in resp.text:
            print("\nHINT: No phone number with an outbound trunk found.")
            print("  Run the migration first:")
            print("    ALTER TABLE business_phone_numbers")
            print("    ADD COLUMN IF NOT EXISTS livekit_outbound_trunk_id TEXT DEFAULT '';")
            print("    UPDATE business_phone_numbers")
            print("    SET livekit_outbound_trunk_id = 'ST_WZ95dtKEntty'")
            print("    WHERE phone_number = '+14157077538';")
        sys.exit(1)


if __name__ == "__main__":
    main()
