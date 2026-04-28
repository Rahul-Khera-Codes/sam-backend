from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class CustomRoleResponse(BaseModel):
    id: str
    business_id: str
    name: str
    description: Optional[str] = None
    base_role: str
    is_system: bool
    created_at: datetime


class CreateCustomRoleRequest(BaseModel):
    name: str
    description: Optional[str] = None
    base_role: str  # 'super_admin' | 'admin' | 'user'


class PagePermission(BaseModel):
    page_key: str
    is_allowed: bool


class RolePermissionsResponse(BaseModel):
    role_id: str
    permissions: list[PagePermission]


class UpdatePermissionsRequest(BaseModel):
    permissions: list[PagePermission]
