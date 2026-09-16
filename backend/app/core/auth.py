import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from app.core.config import settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    Validates the Supabase JWT token sent from the frontend.
    The frontend already handles login via Supabase Auth —
    we just verify the same token here, no second auth system needed.

    Returns the decoded JWT payload which contains:
      - sub: user UUID
      - email: user email
      - role: authenticated
    """
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},  # Supabase doesn't use aud claim
        )
        return payload

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_user_id(current_user: dict = Depends(get_current_user)) -> str:
    """Shortcut to extract just the user UUID from the token."""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user ID",
        )
    return user_id


def verify_business_access(user_id: str, business_id: str) -> str:
    """
    Verify the authenticated user has a role for the given business_id.
    Returns the user's role for that business.

    Raises 403 if the user has no membership in this business — prevents
    a user from passing an arbitrary business_id in the URL/body to
    access another business's data.

    Also raises 403 if the business has been soft-deleted.
    """
    import httpx
    from app.core.supabase import supabase_admin

    def _execute_with_retry(query):
        """Retry once on httpx.RemoteProtocolError (stale HTTP/2 connection)."""
        try:
            return query.execute()
        except httpx.RemoteProtocolError:
            logger.warning("Supabase connection dropped; retrying once")
            return query.execute()

    role_row = _execute_with_retry(
        supabase_admin.table("user_roles")
        .select("role")
        .eq("user_id", user_id)
        .eq("business_id", business_id)
        .limit(1)
    )
    if not role_row.data:
        raise HTTPException(
            status_code=403,
            detail="You don't have access to this business",
        )

    biz = _execute_with_retry(
        supabase_admin.table("businesses")
        .select("is_deleted")
        .eq("id", business_id)
        .limit(1)
    )
    if biz.data and biz.data[0].get("is_deleted"):
        raise HTTPException(
            status_code=403,
            detail="This business account has been deactivated. Contact support to restore access.",
        )

    return role_row.data[0]["role"]


def require_business_access(business_id_param: str = "business_id"):
    """
    FastAPI dependency factory that verifies the authenticated user has
    access to the business_id passed in the request.

    Usage (most common):
        @router.get("/foo")
        async def foo(business_id: str, _: str = Depends(require_business_access())):
            ...

    The dependency reads the `business_id` from the request query/path
    and validates the user against user_roles. Returns the user's role.
    """
    from fastapi import Request

    def _check(
        request: Request,
        user_id: str = Depends(get_user_id),
    ) -> str:
        # Try query params first (most common), then path params
        business_id = request.query_params.get(business_id_param) \
            or request.path_params.get(business_id_param)
        if not business_id:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required parameter: {business_id_param}",
            )
        return verify_business_access(user_id, business_id)

    return _check


def require_role(*allowed_roles: str):
    """
    Returns a callable that verifies the user has one of the allowed roles
    and returns their business_id. Can be used two ways:

    1. As a FastAPI dependency:
        business_id: str = Depends(require_role("super_admin", "admin"))

    2. As a plain function call (when user_id is already available):
        business_id = require_role("super_admin", "admin")(user_id)
    """
    from app.core.supabase import supabase_admin

    def _check(user_id: str) -> str:
        role_row = (
            supabase_admin.table("user_roles")
            .select("business_id, role")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not role_row.data:
            raise HTTPException(status_code=403, detail="User has no role assigned")
        if role_row.data[0]["role"] not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"This action requires one of: {', '.join(allowed_roles)}",
            )
        return role_row.data[0]["business_id"]

    return _check


def verify_platform_super_admin(user_id: str, aal: str | None = None) -> None:
    """Verify that the authenticated user has platform Super Admin privileges
    AND completed MFA for this session.

    Must check super_admin against the platform's own internal business
    (businesses.type = 'platform'), not just "super_admin of any business" —
    every tenant's business owner also holds role='super_admin' for their own
    business, which would otherwise satisfy this check and expose Mission
    Control's cross-tenant company list and impersonation endpoints to any
    paying customer. Mirrors the is_platform_super_admin() SQL function used
    for the equivalent RLS-side check.

    Administrative interfaces require MFA, not just a password — Supabase
    marks a session 'aal2' once the user has verified a second factor for
    that session (vs. 'aal1', password only). A distinct "MFA_REQUIRED" detail
    (rather than the generic 403) lets the frontend show a mandatory 2FA setup
    screen instead of a plain access-denied error.
    """
    from app.core.supabase import supabase_admin

    role_row = (
        supabase_admin.table("user_roles")
        .select("business_id, businesses!inner(type)")
        .eq("user_id", user_id)
        .eq("role", "super_admin")
        .eq("businesses.type", "platform")
        .limit(1)
        .execute()
    )
    if not role_row.data:
        raise HTTPException(
            status_code=403,
            detail="Mission Control requires Super Admin access",
        )

    if aal != "aal2":
        raise HTTPException(
            status_code=403,
            detail="MFA_REQUIRED",
        )


def require_platform_super_admin(current_user: dict = Depends(get_current_user)) -> str:
    """FastAPI dependency that returns the actor user id after Super Admin + MFA validation."""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user ID")
    verify_platform_super_admin(user_id, aal=current_user.get("aal"))
    return user_id
