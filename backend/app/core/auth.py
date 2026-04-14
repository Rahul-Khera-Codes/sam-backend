from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from app.core.config import settings

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
