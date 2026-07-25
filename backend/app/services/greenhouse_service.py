from __future__ import annotations

from typing import Any

import httpx


BASE_URL = "https://boards-api.greenhouse.io/v1"
HARVEST_BASE_URL = "https://harvest.greenhouse.io/v1"


class GreenhouseError(Exception):
    """Raised when the Greenhouse Job Board API request fails."""


async def _get_json(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(url)
    if response.status_code >= 400:
        detail = response.text.strip() or f"Greenhouse request failed with status {response.status_code}"
        raise GreenhouseError(detail)
    try:
        return response.json()
    except ValueError as exc:
        raise GreenhouseError("Greenhouse returned invalid JSON") from exc


async def _harvest_request(
    harvest_api_key: str,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Any:
    key = (harvest_api_key or "").strip()
    if not key:
        raise GreenhouseError("Greenhouse Harvest API key is not configured.")
    async with httpx.AsyncClient(
        timeout=30.0,
        auth=(key, ""),
        headers={"Accept": "application/json"},
    ) as client:
        response = await client.request(
            method,
            f"{HARVEST_BASE_URL}{path}",
            params=params,
            json=json_body,
        )
    if response.status_code >= 400:
        detail = response.text.strip() or f"Greenhouse Harvest request failed with status {response.status_code}"
        raise GreenhouseError(detail)
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise GreenhouseError("Greenhouse Harvest returned invalid JSON") from exc


async def fetch_board(board_token: str) -> dict[str, Any]:
    return await _get_json(f"{BASE_URL}/boards/{board_token}")


async def fetch_jobs(board_token: str, *, content: bool = True) -> dict[str, Any]:
    content_flag = "true" if content else "false"
    return await _get_json(f"{BASE_URL}/boards/{board_token}/jobs?content={content_flag}")


async def fetch_harvest_applications_for_job(
    harvest_api_key: str,
    greenhouse_internal_job_id: str,
) -> list[dict[str, Any]]:
    data = await _harvest_request(
        harvest_api_key,
        "GET",
        "/applications",
        params={"job_id": greenhouse_internal_job_id, "per_page": 100},
    )
    return data if isinstance(data, list) else []


async def fetch_harvest_candidate(
    harvest_api_key: str,
    candidate_id: str,
) -> dict[str, Any]:
    data = await _harvest_request(harvest_api_key, "GET", f"/candidates/{candidate_id}")
    return data if isinstance(data, dict) else {}


async def reject_harvest_application(
    harvest_api_key: str,
    application_id: str,
) -> None:
    await _harvest_request(harvest_api_key, "POST", f"/applications/{application_id}/reject")


async def advance_harvest_application(
    harvest_api_key: str,
    application_id: str,
) -> None:
    await _harvest_request(harvest_api_key, "POST", f"/applications/{application_id}/advance")


def normalize_greenhouse_candidate(
    application: dict[str, Any],
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = candidate or application.get("candidate") or {}
    candidate_id = str(candidate.get("id") or application.get("candidate_id") or "")
    application_id = str(application.get("id") or "")
    first_name = candidate.get("first_name") or ""
    last_name = candidate.get("last_name") or ""
    name = f"{first_name} {last_name}".strip() or candidate.get("name") or "Candidate"

    email_rows = candidate.get("email_addresses") or []
    phone_rows = candidate.get("phone_numbers") or []
    address_rows = candidate.get("addresses") or []
    stage = application.get("current_stage") or {}

    return {
        "id": application_id or candidate_id,
        "application_id": application_id,
        "candidate_id": candidate_id,
        "name": name,
        "title": candidate.get("title") or "",
        "company": candidate.get("company") or "",
        "location": (address_rows[0].get("value") if address_rows else "") or "",
        "email": (email_rows[0].get("value") if email_rows else None),
        "phone": (phone_rows[0].get("value") if phone_rows else None),
        "status": application.get("status") or ("Rejected" if application.get("rejected_at") else "Active"),
        "stage": stage.get("name") if isinstance(stage, dict) else "",
        "applied_at": application.get("applied_at"),
        "source": (application.get("source") or {}).get("public_name") if isinstance(application.get("source"), dict) else "",
        "prospect": bool(application.get("prospect")),
        "greenhouse_url": application.get("greenhouse_url") or candidate.get("greenhouse_url"),
    }


def normalize_greenhouse_job(
    job: dict[str, Any],
    *,
    board_token: str,
) -> dict[str, Any]:
    departments = job.get("departments") or []
    offices = job.get("offices") or []
    location_name = (job.get("location") or {}).get("name") or ""
    department_name = departments[0]["name"] if departments else ""

    return {
        "id": f"greenhouse:{job['id']}",
        "job_id": str(job["id"]),
        "source": "greenhouse",
        "status": "Active",
        "sync_state": "greenhouse_synced",
        "title": job.get("title") or "",
        "department": department_name,
        "location": location_name,
        "location_type": "",
        "employment_type": "",
        "job_type": "",
        "shift": "",
        "schedule": "",
        "summary": "",
        "perks": "",
        "responsibilities": "",
        "qualifications": "",
        "requirements_skills": "",
        "comments": "",
        "pay_min": "",
        "pay_max": "",
        "pay_period": "",
        "benefits": "",
        "required_experience": "",
        "seniority": "",
        "posted_on": job.get("updated_at") or "",
        "absolute_url": job.get("absolute_url") or "",
        "language": job.get("language") or "en",
        "content_html": job.get("content") or "",
        "metadata": job.get("metadata"),
        "platforms": ["GH"],
        "applicants": 0,
        "applicant_bar_class_name": "bg-blue-500",
        "publish_in_linkedin": False,
        "publish_in_indeed": False,
        "greenhouse_managed_distribution": True,
        "linkedin_status": "Managed in GH",
        "indeed_status": "Managed in GH",
        "ai_status": "Synced",
        "greenhouse_job_id": str(job.get("id") or ""),
        "greenhouse_internal_job_id": (
            str(job["internal_job_id"])
            if job.get("internal_job_id") is not None
            else None
        ),
        "greenhouse_board_token_snapshot": None,
        "offices": offices,
        "departments": departments,
        "source_payload": {},
    }
