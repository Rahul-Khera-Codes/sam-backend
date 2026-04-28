from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_user_id, verify_business_access
from app.core.supabase import supabase_admin
from app.schemas.roles import (
    CustomRoleResponse, CreateCustomRoleRequest,
    RolePermissionsResponse, PagePermission, UpdatePermissionsRequest,
)

router = APIRouter(prefix="/roles", tags=["roles"])


def _get_role_business_id(role_id: str) -> str:
    r = supabase_admin.table("custom_roles").select("business_id").eq("id", role_id).limit(1).execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Role not found")
    return r.data[0]["business_id"]


def _require_admin(user_id: str, business_id: str):
    role_row = supabase_admin.table("user_roles").select("role").eq("user_id", user_id).eq("business_id", business_id).limit(1).execute()
    if not role_row.data or role_row.data[0]["role"] not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only admins can perform this action")


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
            supabase_admin.table("role_page_permissions").insert(new_perms).execute()

    return role


@router.delete("/{role_id}", status_code=204)
async def delete_role(role_id: str, user_id: str = Depends(get_user_id)):
    business_id = _get_role_business_id(role_id)
    verify_business_access(user_id, business_id)
    _require_admin(user_id, business_id)

    check = supabase_admin.table("custom_roles").select("is_system").eq("id", role_id).limit(1).execute()
    if check.data and check.data[0]["is_system"]:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")

    supabase_admin.table("custom_roles").delete().eq("id", role_id).execute()


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
