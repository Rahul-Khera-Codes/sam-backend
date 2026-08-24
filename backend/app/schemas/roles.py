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


class UserPermissionsResponse(BaseModel):
    user_id: str
    business_id: str
    permissions: list[PagePermission]


class UpdatePermissionsRequest(BaseModel):
    permissions: list[PagePermission]


class CheckInCodeStatus(BaseModel):
    user_id: str
    has_code: bool


class SetCheckInCodeRequest(BaseModel):
    business_id: str
    code: Optional[str] = None  # omit to auto-generate


class CheckInCodeResponse(BaseModel):
    user_id: str
    code: str  # returned once, never retrievable again after this response


class BulkGenerateCheckInCodesRequest(BaseModel):
    business_id: str


class MyCheckInCodeResponse(BaseModel):
    """The caller's own code. Distinct from CheckInCodeResponse: no one else's code is ever
    retrievable, but an employee can always view their own current code."""
    has_code: bool
    code: Optional[str] = None
