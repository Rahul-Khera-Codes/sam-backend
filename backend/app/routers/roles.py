import random
import re
from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError
from app.core.auth import get_user_id, verify_business_access
from app.core.supabase import supabase_admin
from app.schemas.roles import (
    CustomRoleResponse, CreateCustomRoleRequest,
    RolePermissionsResponse, UserPermissionsResponse, PagePermission, UpdatePermissionsRequest,
    CheckInCodeStatus, SetCheckInCodeRequest, CheckInCodeResponse, BulkGenerateCheckInCodesRequest,
    MyCheckInCodeResponse,
)

router = APIRouter(prefix="/roles", tags=["roles"])


def _get_role(role_id: str) -> dict:
    """Returns dict with business_id and is_system for the given role_id."""
    r = supabase_admin.table("custom_roles").select("business_id, is_system").eq("id", role_id).limit(1).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Role not found")
    return r.data[0]


def _get_role_business_id(role_id: str) -> str:
    return _get_role(role_id)["business_id"]


def _require_admin(user_id: str, business_id: str):
    role_row = supabase_admin.table("user_roles").select("role").eq("user_id", user_id).eq("business_id", business_id).limit(1).execute()
    if not role_row.data or role_row.data[0]["role"] not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only admins can perform this action")


def _require_business_member(target_user_id: str, business_id: str):
    role_row = supabase_admin.table("user_roles").select("id").eq("user_id", target_user_id).eq("business_id", business_id).limit(1).execute()
    if not role_row.data:
        raise HTTPException(status_code=404, detail="User is not a member of this business")


def _existing_check_in_codes(business_id: str) -> set[str]:
    r = supabase_admin.table("user_roles").select("check_in_code").eq("business_id", business_id).execute()
    return {row["check_in_code"] for row in (r.data or []) if row.get("check_in_code")}


def _generate_unused_check_in_code(existing: set[str]) -> str:
    for _ in range(50):
        candidate = f"{random.randint(0, 9999):04d}"
        if candidate not in existing:
            return candidate
    raise HTTPException(
        status_code=500,
        detail="Could not generate a unique employee code — too many codes already in use",
    )


_UNIQUE_VIOLATION = "23505"


def _write_check_in_code(target_user_id: str, business_id: str, code: str) -> bool:
    """Returns True on success, False if the DB's unique index rejected the code
    (another request assigned it to someone else first — a genuine race)."""
    try:
        result = (
            supabase_admin.table("user_roles")
            .update({"check_in_code": code})
            .eq("user_id", target_user_id)
            .eq("business_id", business_id)
            .execute()
        )
    except APIError as e:
        if e.code == _UNIQUE_VIOLATION:
            return False
        raise
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to set employee code")
    return True


def _assign_unique_code(target_user_id: str, business_id: str, existing: set[str], max_attempts: int = 5) -> str:
    """Generates and writes a code, transparently retrying with a fresh candidate if a
    concurrent request wins the same code first (the in-memory `existing` check can't see
    writes from other concurrent requests — the DB's unique index is the real guarantee)."""
    for _ in range(max_attempts):
        code = _generate_unused_check_in_code(existing)
        if _write_check_in_code(target_user_id, business_id, code):
            return code
        existing.add(code)
    raise HTTPException(
        status_code=500,
        detail="Could not assign a unique employee code after several attempts — please try again",
    )


@router.get("", response_model=list[CustomRoleResponse])
async def list_roles(business_id: str, user_id: str = Depends(get_user_id)):
    verify_business_access(user_id, business_id)
    r = supabase_admin.table("custom_roles").select("*").eq("business_id", business_id).order("created_at").execute()
    return r.data or []


@router.post("", response_model=CustomRoleResponse, status_code=201)
async def create_role(
    business_id: str,
    body: CreateCustomRoleRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    _require_admin(user_id, business_id)

    if body.base_role not in ("super_admin", "admin", "user"):
        raise HTTPException(status_code=400, detail="base_role must be super_admin, admin, or user")

    r = supabase_admin.table("custom_roles").insert({
        "business_id": business_id,
        "name": body.name,
        "description": body.description,
        "base_role": body.base_role,
        "is_system": False,
    }).execute()

    if not r.data:
        raise HTTPException(status_code=500, detail="Failed to create role")

    role = r.data[0]

    # Seed permissions by copying from the system role with the same base_role
    system_role = supabase_admin.table("custom_roles").select("id").eq("business_id", business_id).eq("base_role", body.base_role).eq("is_system", True).limit(1).execute()
    if system_role.data:
        src_id = system_role.data[0]["id"]
        src_perms = supabase_admin.table("role_page_permissions").select("page_key, is_allowed").eq("role_id", src_id).execute()
        if src_perms.data:
            new_perms = [{"role_id": role["id"], "page_key": p["page_key"], "is_allowed": p["is_allowed"]} for p in src_perms.data]
            seed_result = supabase_admin.table("role_page_permissions").insert(new_perms).execute()
            if not seed_result.data:
                raise HTTPException(status_code=500, detail="Role created but permission seeding failed")

    return role


@router.delete("/{role_id}", status_code=204)
async def delete_role(role_id: str, user_id: str = Depends(get_user_id)):
    role = _get_role(role_id)
    verify_business_access(user_id, role["business_id"])
    _require_admin(user_id, role["business_id"])

    if role["is_system"]:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")

    supabase_admin.table("custom_roles").delete().eq("id", role_id).execute()


@router.get("/users/{target_user_id}/permissions", response_model=UserPermissionsResponse)
async def get_user_permissions(
    target_user_id: str,
    business_id: str,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    if target_user_id != user_id:
        _require_admin(user_id, business_id)
    _require_business_member(target_user_id, business_id)

    r = (
        supabase_admin.table("user_page_permissions")
        .select("page_key, is_allowed")
        .eq("business_id", business_id)
        .eq("user_id", target_user_id)
        .execute()
    )
    perms = [PagePermission(page_key=p["page_key"], is_allowed=p["is_allowed"]) for p in (r.data or [])]
    return UserPermissionsResponse(user_id=target_user_id, business_id=business_id, permissions=perms)


@router.put("/users/{target_user_id}/permissions", response_model=UserPermissionsResponse)
async def update_user_permissions(
    target_user_id: str,
    business_id: str,
    body: UpdatePermissionsRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, business_id)
    _require_admin(user_id, business_id)
    _require_business_member(target_user_id, business_id)

    rows = [
        {
            "business_id": business_id,
            "user_id": target_user_id,
            "page_key": p.page_key,
            "is_allowed": p.is_allowed,
        }
        for p in body.permissions
    ]
    supabase_admin.table("user_page_permissions").upsert(
        rows,
        on_conflict="business_id,user_id,page_key",
    ).execute()

    r = (
        supabase_admin.table("user_page_permissions")
        .select("page_key, is_allowed")
        .eq("business_id", business_id)
        .eq("user_id", target_user_id)
        .execute()
    )
    perms = [PagePermission(page_key=p["page_key"], is_allowed=p["is_allowed"]) for p in (r.data or [])]
    return UserPermissionsResponse(user_id=target_user_id, business_id=business_id, permissions=perms)


@router.get("/{role_id}/permissions", response_model=RolePermissionsResponse)
async def get_permissions(role_id: str, user_id: str = Depends(get_user_id)):
    business_id = _get_role_business_id(role_id)
    verify_business_access(user_id, business_id)

    r = supabase_admin.table("role_page_permissions").select("page_key, is_allowed").eq("role_id", role_id).execute()
    perms = [PagePermission(page_key=p["page_key"], is_allowed=p["is_allowed"]) for p in (r.data or [])]
    return RolePermissionsResponse(role_id=role_id, permissions=perms)


@router.put("/{role_id}/permissions", response_model=RolePermissionsResponse)
async def update_permissions(
    role_id: str,
    body: UpdatePermissionsRequest,
    user_id: str = Depends(get_user_id),
):
    business_id = _get_role_business_id(role_id)
    verify_business_access(user_id, business_id)
    _require_admin(user_id, business_id)

    rows = [{"role_id": role_id, "page_key": p.page_key, "is_allowed": p.is_allowed} for p in body.permissions]
    supabase_admin.table("role_page_permissions").upsert(rows, on_conflict="role_id,page_key").execute()

    r = supabase_admin.table("role_page_permissions").select("page_key, is_allowed").eq("role_id", role_id).execute()
    perms = [PagePermission(page_key=p["page_key"], is_allowed=p["is_allowed"]) for p in (r.data or [])]
    return RolePermissionsResponse(role_id=role_id, permissions=perms)


# ── Employee check-in codes (AIE-28) ──────────────────────────────────────
# Codes are admin-assigned only. For everyone except the code's owner, they're write-only:
# once set, the plaintext value is returned exactly once (in the response to the
# set/bulk-generate call that created it) and never again. The owner can always view their
# own current code (GET /roles/my-check-in-code) so they have a way to find it out.

@router.get("/my-check-in-code", response_model=MyCheckInCodeResponse)
async def get_my_check_in_code(business_id: str, user_id: str = Depends(get_user_id)):
    verify_business_access(user_id, business_id)

    r = (
        supabase_admin.table("user_roles")
        .select("check_in_code")
        .eq("user_id", user_id)
        .eq("business_id", business_id)
        .limit(1)
        .execute()
    )
    code = r.data[0].get("check_in_code") if r.data else None
    return MyCheckInCodeResponse(has_code=bool(code), code=code)


@router.get("/check-in-codes", response_model=list[CheckInCodeStatus])
async def get_check_in_code_status(business_id: str, user_id: str = Depends(get_user_id)):
    verify_business_access(user_id, business_id)
    _require_admin(user_id, business_id)

    r = supabase_admin.table("user_roles").select("user_id, check_in_code").eq("business_id", business_id).execute()
    return [
        CheckInCodeStatus(user_id=row["user_id"], has_code=bool(row.get("check_in_code")))
        for row in (r.data or [])
    ]


@router.put("/users/{target_user_id}/check-in-code", response_model=CheckInCodeResponse)
async def set_check_in_code(
    target_user_id: str,
    body: SetCheckInCodeRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    _require_admin(user_id, body.business_id)
    _require_business_member(target_user_id, body.business_id)

    existing = _existing_check_in_codes(body.business_id)

    if body.code is not None:
        if not re.fullmatch(r"[0-9]{4}", body.code):
            raise HTTPException(status_code=422, detail="Code must be exactly 4 digits")
        current = supabase_admin.table("user_roles").select("check_in_code").eq(
            "user_id", target_user_id
        ).eq("business_id", body.business_id).limit(1).execute()
        current_code = current.data[0].get("check_in_code") if current.data else None
        if body.code in existing and body.code != current_code:
            raise HTTPException(status_code=409, detail="This code is already assigned to another employee")
        # An admin chose this exact code, so on a rare concurrent-write race we surface a
        # clean 409 rather than silently substituting a different code they didn't ask for.
        if not _write_check_in_code(target_user_id, body.business_id, body.code):
            raise HTTPException(status_code=409, detail="This code is already assigned to another employee")
        code = body.code
    else:
        code = _assign_unique_code(target_user_id, body.business_id, existing)

    return CheckInCodeResponse(user_id=target_user_id, code=code)


@router.post("/check-in-codes/bulk-generate", response_model=list[CheckInCodeResponse])
async def bulk_generate_check_in_codes(
    body: BulkGenerateCheckInCodesRequest,
    user_id: str = Depends(get_user_id),
):
    verify_business_access(user_id, body.business_id)
    _require_admin(user_id, body.business_id)

    r = supabase_admin.table("user_roles").select("user_id, check_in_code").eq("business_id", body.business_id).execute()
    members = r.data or []
    existing = {row["check_in_code"] for row in members if row.get("check_in_code")}

    generated: list[CheckInCodeResponse] = []
    for member in members:
        if member.get("check_in_code"):
            continue
        code = _assign_unique_code(member["user_id"], body.business_id, existing)
        existing.add(code)
        generated.append(CheckInCodeResponse(user_id=member["user_id"], code=code))

    return generated
