from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_user_id, verify_business_access
from app.core.supabase import supabase_admin
from app.schemas.hr import (
    GreenhouseConnectionRequest,
    GreenhouseConnectionStatusResponse,
    GreenhouseRefreshResponse,
)
from app.services.greenhouse_service import GreenhouseError, fetch_board, fetch_jobs

router = APIRouter(prefix="/integrations/greenhouse", tags=["integrations"])


def _require_connector_admin(user_id: str, business_id: str) -> None:
    role = verify_business_access(user_id, business_id)
    if role not in ("super_admin", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only business administrators can manage Greenhouse credentials.",
        )


def _get_connection_row(
    business_id: str,
    *,
    include_api_key: bool = False,
) -> dict | None:
    columns = (
        "id,business_id,board_token,board_url,board_name,is_connected,last_sync_at,"
        "last_sync_status,last_sync_error,last_job_count,created_at,updated_at"
    )
    if include_api_key:
        columns += ",job_board_api_key"
    result = (
        supabase_admin.table("greenhouse_connections")
        .select(columns)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _masked_status(
    row: dict | None,
    *,
    include_configuration: bool = True,
) -> GreenhouseConnectionStatusResponse:
    if not row:
        return GreenhouseConnectionStatusResponse(connected=False)
    return GreenhouseConnectionStatusResponse(
        connected=bool(row.get("is_connected")),
        board_token=row.get("board_token") if include_configuration else None,
        board_url=row.get("board_url"),
        board_name=row.get("board_name"),
        has_job_board_api_key=bool(row.get("job_board_api_key")),
        last_sync_at=row.get("last_sync_at"),
        last_sync_status=row.get("last_sync_status"),
        last_sync_error=row.get("last_sync_error"),
        last_job_count=row.get("last_job_count") or 0,
    )


@router.get("/status")
async def get_greenhouse_status(
    business_id: str,
    user_id: str = Depends(get_user_id),
) -> GreenhouseConnectionStatusResponse:
    role = verify_business_access(user_id, business_id)
    can_manage = role in ("super_admin", "admin")
    return _masked_status(
        _get_connection_row(business_id, include_api_key=can_manage),
        include_configuration=can_manage,
    )


@router.post("/connect")
async def connect_greenhouse(
    body: GreenhouseConnectionRequest,
    user_id: str = Depends(get_user_id),
) -> GreenhouseConnectionStatusResponse:
    _require_connector_admin(user_id, body.business_id)

    try:
        board = await fetch_board(body.board_token)
        jobs = await fetch_jobs(body.board_token, content=False)
    except GreenhouseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(timezone.utc).isoformat()
    existing = _get_connection_row(body.business_id)
    row = {
        "business_id": body.business_id,
        "board_token": body.board_token.strip(),
        "board_url": body.board_url.strip(),
        "board_name": board.get("name") or "",
        "is_connected": True,
        "last_sync_at": now,
        "last_sync_status": "success",
        "last_sync_error": None,
        "last_job_count": (jobs.get("meta") or {}).get("total", 0),
    }
    supplied_api_key = (body.job_board_api_key or "").strip()
    if supplied_api_key:
        row["job_board_api_key"] = supplied_api_key

    if existing:
        (
            supabase_admin.table("greenhouse_connections")
            .update(row)
            .eq("id", existing["id"])
            .eq("business_id", body.business_id)
            .execute()
        )
    else:
        row["job_board_api_key"] = supplied_api_key or None
        supabase_admin.table("greenhouse_connections").insert(row).execute()

    return _masked_status(
        _get_connection_row(body.business_id, include_api_key=True)
    )


@router.post("/refresh")
async def refresh_greenhouse_jobs(
    business_id: str,
    user_id: str = Depends(get_user_id),
) -> GreenhouseRefreshResponse:
    verify_business_access(user_id, business_id)
    existing = _get_connection_row(business_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Greenhouse is not connected for this business.")

    try:
        board = await fetch_board(existing["board_token"])
        jobs = await fetch_jobs(existing["board_token"], content=False)
        status = "success"
        error = None
    except GreenhouseError as exc:
        status = "error"
        error = str(exc)
        supabase_admin.table("greenhouse_connections").update({
            "last_sync_at": datetime.now(timezone.utc).isoformat(),
            "last_sync_status": status,
            "last_sync_error": error,
        }).eq("id", existing["id"]).eq("business_id", business_id).execute()
        raise HTTPException(status_code=400, detail=error) from exc

    now = datetime.now(timezone.utc).isoformat()
    total_jobs = (jobs.get("meta") or {}).get("total", 0)
    supabase_admin.table("greenhouse_connections").update({
        "board_name": board.get("name") or existing.get("board_name") or "",
        "last_sync_at": now,
        "last_sync_status": status,
        "last_sync_error": error,
        "last_job_count": total_jobs,
    }).eq("id", existing["id"]).eq("business_id", business_id).execute()

    return GreenhouseRefreshResponse(
        board_name=board.get("name") or "",
        total_jobs=total_jobs,
        last_sync_at=now,
        last_sync_status=status,
    )


@router.delete("/disconnect")
async def disconnect_greenhouse(
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    _require_connector_admin(user_id, business_id)
    existing = _get_connection_row(business_id)
    if not existing:
        return {"disconnected": True}

    supabase_admin.table("hr_job_postings").delete().eq("business_id", business_id).eq("source", "greenhouse").execute()
    (
        supabase_admin.table("greenhouse_connections")
        .delete()
        .eq("id", existing["id"])
        .eq("business_id", business_id)
        .execute()
    )
    return {"disconnected": True}
