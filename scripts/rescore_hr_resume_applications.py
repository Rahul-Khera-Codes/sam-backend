"""
AIE-74: Rescore existing HR candidate resume scores.

The AI resume-scoring prompt (app/services/hr_resume_scoring_service.py) never told
the model what numeric scale total_score should be on, so scores generated before
this fix are uncalibrated (e.g. a full match could still land in single digits).
This re-runs the (now-fixed) scoring prompt for every existing
hr_application_resume_scores row and overwrites it in place.

Usage:
    cd /home/lap-68/Documents/gt-rahul/sam-backend
    source venv/sam-agent/bin/activate
    python scripts/rescore_hr_resume_applications.py            # dry run — lists rows only
    python scripts/rescore_hr_resume_applications.py --apply    # actually rescore + overwrite
"""

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "backend")

if os.path.isdir("/app") and os.path.isfile("/app/app/core/supabase.py"):
    # Running inside the sam-backend container: /app is the backend dir
    # (bind-mounted), and env vars already come from docker-compose's env_file.
    sys.path.insert(0, "/app")
else:
    # Running from a host checkout, sibling to backend/.
    sys.path.insert(0, BACKEND_DIR)
    load_dotenv(os.path.join(BACKEND_DIR, ".env"))


async def main(apply: bool) -> None:
    from app.core.supabase import supabase_admin
    from app.services.hr_resume_scoring_service import generate_and_store_resume_score

    existing = (
        supabase_admin.table("hr_application_resume_scores")
        .select("id,business_id,application_id,total_score")
        .execute()
    )
    rows = existing.data or []

    print("=" * 60)
    print("  RESCORE HR RESUME APPLICATIONS")
    print("=" * 60)
    print(f"  Found {len(rows)} existing resume score row(s).\n")
    if not rows:
        print("Nothing to do.")
        return

    if not apply:
        for row in rows:
            print(f"  [dry run] application {row['application_id']}: current score {row['total_score']}")
        print("\nDry run only — no changes made. Re-run with --apply to rescore for real.")
        return

    answer = input(f"Type 'RESCORE {len(rows)}' to rescore and overwrite all {len(rows)} row(s): ").strip()
    if answer != f"RESCORE {len(rows)}":
        print("Aborted.")
        sys.exit(0)

    updated = 0
    errors = 0
    for row in rows:
        old_score = row["total_score"]
        try:
            result = await generate_and_store_resume_score(
                business_id=row["business_id"],
                application_id=row["application_id"],
            )
            new_score = result.get("total_score") if result else None
            print(f"  ✓ application {row['application_id']}: {old_score} -> {new_score}")
            updated += 1
        except Exception as exc:
            print(f"  ✗ application {row['application_id']}: {exc}")
            errors += 1

    print(f"\nDone — {updated} rescored, {errors} error(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually rescore and overwrite (default is dry run)")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
