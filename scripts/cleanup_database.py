"""
FULL DATABASE CLEANUP — Auth Users
====================================
Deletes ALL Supabase auth users.
Run AFTER running cleanup_tables.sql in the Supabase SQL Editor.

⚠ THIS IS IRREVERSIBLE.

Usage:
    cd /home/lap-68/Documents/gt-rahul/sam-backend
    source venv/sam-agent/bin/activate
    python scripts/cleanup_database.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv("backend/.env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in backend/.env")
    sys.exit(1)


def main():
    print("=" * 60)
    print("  DELETE ALL AUTH USERS")
    print("=" * 60)
    print(f"  Project: {SUPABASE_URL}")
    print("\n⚠ This will permanently delete ALL Supabase auth users.")
    print("  This CANNOT be undone.\n")

    answer = input("Type 'DELETE ALL USERS' to confirm: ").strip()
    if answer != "DELETE ALL USERS":
        print("Aborted.")
        sys.exit(0)

    from supabase import create_client
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    print("\n--- Deleting auth users ---")
    deleted = 0
    errors = 0
    page = 1

    while True:
        try:
            response = supabase.auth.admin.list_users(page=page, per_page=50)
            users = getattr(response, "users", [])
            if not users:
                break
            for user in users:
                try:
                    supabase.auth.admin.delete_user(user.id)
                    label = user.email or user.id
                    print(f"  ✓ {label}")
                    deleted += 1
                except Exception as e:
                    print(f"  ✗ {user.email or user.id}: {e}")
                    errors += 1
            page += 1
        except Exception as e:
            print(f"  ERROR listing users page {page}: {e}")
            break

    print(f"\n✅ Done — {deleted} deleted, {errors} errors.")


if __name__ == "__main__":
    main()
