from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"
DEFAULT_DATASET = Path(__file__).resolve().parent / "datasets" / "hr_policy_eval_cases.jsonl"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "experiments"
DEFAULT_USER_EMAIL = "rahul.excel2011@gmail.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Developer-only Ragas evaluation for the HR onboarding chatbot.",
    )
    parser.add_argument(
        "--dataset",
        default=str(DEFAULT_DATASET),
        help="Path to a JSONL dataset of HR onboarding eval cases.",
    )
    parser.add_argument(
        "--business-id",
        default=os.getenv("RAGAS_EVAL_BUSINESS_ID"),
        help="Business id to evaluate. Defaults to RAGAS_EVAL_BUSINESS_ID.",
    )
    parser.add_argument(
        "--user-email",
        default=os.getenv("RAGAS_EVAL_USER_EMAIL", DEFAULT_USER_EMAIL),
        help=(
            "Fallback user email used to resolve a business id from profiles/user_roles "
            "when --business-id is not provided."
        ),
    )
    parser.add_argument(
        "--env-file",
        default=os.getenv("RAGAS_EVAL_ENV_FILE", str(BACKEND_DIR / ".env")),
        help="Environment file to load. Point this at a dev, staging, or production env file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where JSON and CSV evaluation reports are written.",
    )
    parser.add_argument(
        "--run-name",
        default=os.getenv("RAGAS_EVAL_RUN_NAME"),
        help="Optional experiment run name. Defaults to a timestamped name.",
    )
    parser.add_argument(
        "--skip-ragas",
        action="store_true",
        help="Only collect chatbot outputs and retrieved contexts; skip Ragas metric scoring.",
    )
    return parser.parse_args()


def configure_environment(env_file: str) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError(
            "python-dotenv is required to run evaluations. Install eval dependencies with: "
            "pip install -r requirements-eval.txt"
        ) from exc

    load_dotenv(env_file)
    os.environ.setdefault("HR_ONBOARDING_CACHE_ENABLED", "false")
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if case.get("enabled", True):
                case.setdefault("id", f"case-{line_number}")
                cases.append(case)
    if not cases:
        raise ValueError(f"No enabled eval cases found in {path}")
    return cases


def _supabase_data(result: Any) -> list[dict[str, Any]]:
    data = getattr(result, "data", None)
    return data if isinstance(data, list) else []


def _select_business_with_hr_docs(supabase_admin: Any, business_ids: list[str]) -> str | None:
    for business_id in business_ids:
        try:
            result = (
                supabase_admin.table("business_documents")
                .select("id")
                .eq("business_id", business_id)
                .eq("document_scope", "hr_onboarding")
                .eq("status", "published")
                .eq("embedding_status", "ready")
                .limit(1)
                .execute()
            )
        except Exception:
            continue
        if _supabase_data(result):
            return business_id
    return business_ids[0] if business_ids else None


def resolve_business_id(
    *,
    supabase_admin: Any,
    business_id: str | None,
    user_email: str | None,
) -> str:
    if business_id:
        return business_id
    if not user_email:
        raise ValueError("Provide --business-id, RAGAS_EVAL_BUSINESS_ID, or --user-email.")

    profile_result = (
        supabase_admin.table("profiles")
        .select("id,email")
        .ilike("email", user_email)
        .limit(1)
        .execute()
    )
    profiles = _supabase_data(profile_result)
    if not profiles:
        raise ValueError(f"No profile found for email {user_email!r}. Pass --business-id directly.")

    user_id = profiles[0]["id"]
    roles_result = (
        supabase_admin.table("user_roles")
        .select("business_id,role")
        .eq("user_id", user_id)
        .execute()
    )
    role_rows = _supabase_data(roles_result)
    business_ids = [str(row["business_id"]) for row in role_rows if row.get("business_id")]
    selected_business_id = _select_business_with_hr_docs(supabase_admin, business_ids)
    if not selected_business_id:
        raise ValueError(f"No business memberships found for email {user_email!r}.")
    return selected_business_id


async def collect_case_result(
    *,
    business_id: str,
    case: dict[str, Any],
    answer_onboarding_question: Any,
    retrieve_onboarding_matches: Any,
) -> dict[str, Any]:
    question = str(case["question"]).strip()
    document_id = case.get("document_id")
    category = case.get("category")
    matches = await retrieve_onboarding_matches(
        business_id=business_id,
        question=question,
        document_id=document_id,
        category=category,
    )
    response = await answer_onboarding_question(
        business_id=business_id,
        question=question,
        document_id=document_id,
        category=category,
    )
    retrieved_contexts = [
        str(match.get("content") or "").strip()
        for match in matches
        if str(match.get("content") or "").strip()
    ]
    source_documents = sorted(
        {
            str(match.get("document_name") or "HR policy document")
            for match in matches
            if match.get("content")
        }
    )
    return {
        "case_id": case["id"],
        "business_id": business_id,
        "user_input": question,
        "response": response.answer,
        "reference": str(case.get("reference") or ""),
        "retrieved_contexts": retrieved_contexts,
        "source_documents": source_documents,
        "source_count": len(retrieved_contexts),
        "expected_category": category or "",
    }


async def collect_results(
    *,
    business_id: str,
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from app.services.hr_onboarding_chat_service import (  # noqa: PLC0415
        _retrieve_onboarding_matches,
        answer_onboarding_question,
    )

    results: list[dict[str, Any]] = []
    for case in cases:
        results.append(
            await collect_case_result(
                business_id=business_id,
                case=case,
                answer_onboarding_question=answer_onboarding_question,
                retrieve_onboarding_matches=_retrieve_onboarding_matches,
            )
        )
    return results


def run_ragas(rows: list[dict[str, Any]]) -> tuple[Any, dict[str, Any]]:
    from ragas import EvaluationDataset, evaluate  # noqa: PLC0415
    from ragas.metrics import Faithfulness, FactualCorrectness, LLMContextRecall  # noqa: PLC0415

    dataset = EvaluationDataset.from_list(
        [
            {
                "user_input": row["user_input"],
                "retrieved_contexts": row["retrieved_contexts"],
                "response": row["response"],
                "reference": row["reference"],
            }
            for row in rows
        ]
    )
    result = evaluate(
        dataset=dataset,
        metrics=[
            Faithfulness(),
            LLMContextRecall(),
            FactualCorrectness(),
        ],
    )
    aggregate_scores: dict[str, Any] = {}
    try:
        aggregate_scores = dict(result)
    except Exception:
        aggregate_scores = {"repr": repr(result)}
    return result, aggregate_scores


def write_reports(
    *,
    output_dir: Path,
    run_name: str,
    business_id: str,
    env_file: str,
    rows: list[dict[str, Any]],
    aggregate_scores: dict[str, Any],
    ragas_result: Any | None,
) -> tuple[Path, Path]:
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_path = run_dir / "summary.json"
    rows_path = run_dir / "rows.csv"

    summary = {
        "run_name": run_name,
        "business_id": business_id,
        "env_file": env_file,
        "cache_enabled": os.getenv("HR_ONBOARDING_CACHE_ENABLED"),
        "case_count": len(rows),
        "aggregate_scores": aggregate_scores,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    with rows_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "business_id",
                "user_input",
                "response",
                "reference",
                "source_count",
                "source_documents",
                "expected_category",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{field: row.get(field, "") for field in writer.fieldnames},
                    "source_documents": "; ".join(row.get("source_documents") or []),
                }
            )

    if ragas_result is not None and hasattr(ragas_result, "to_pandas"):
        try:
            ragas_result.to_pandas().to_csv(run_dir / "ragas_scores.csv", index=False)
        except Exception as exc:
            (run_dir / "ragas_scores_error.txt").write_text(str(exc), encoding="utf-8")

    return summary_path, rows_path


async def async_main() -> None:
    args = parse_args()
    configure_environment(args.env_file)

    from app.core.supabase import supabase_admin  # noqa: PLC0415

    business_id = resolve_business_id(
        supabase_admin=supabase_admin,
        business_id=args.business_id,
        user_email=args.user_email,
    )
    cases = load_cases(Path(args.dataset))
    rows = await collect_results(business_id=business_id, cases=cases)

    ragas_result = None
    aggregate_scores: dict[str, Any] = {}
    if not args.skip_ragas:
        ragas_result, aggregate_scores = run_ragas(rows)

    run_name = args.run_name or f"hr-onboarding-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    summary_path, rows_path = write_reports(
        output_dir=Path(args.output_dir),
        run_name=run_name,
        business_id=business_id,
        env_file=args.env_file,
        rows=rows,
        aggregate_scores=aggregate_scores,
        ragas_result=ragas_result,
    )

    print(f"Ragas HR onboarding eval complete: {run_name}")
    print(f"Business id: {business_id}")
    print(f"Summary: {summary_path}")
    print(f"Rows: {rows_path}")
    if aggregate_scores:
        print(json.dumps(aggregate_scores, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(async_main())
