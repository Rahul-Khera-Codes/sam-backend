from __future__ import annotations

from typing import Any

import httpx


BASE_URL = "https://boards-api.greenhouse.io/v1"


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


async def fetch_board(board_token: str) -> dict[str, Any]:
    return await _get_json(f"{BASE_URL}/boards/{board_token}")


async def fetch_jobs(board_token: str, *, content: bool = True) -> dict[str, Any]:
    content_flag = "true" if content else "false"
    return await _get_json(f"{BASE_URL}/boards/{board_token}/jobs?content={content_flag}")


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
        "greenhouse_board_token_snapshot": board_token,
        "offices": offices,
        "departments": departments,
        "source_payload": job,
    }
