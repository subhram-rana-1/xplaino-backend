"""API routes for user management (admin)."""

from fastapi import APIRouter, HTTPException, Depends, Query, Request, Response
from sqlalchemy.orm import Session
import structlog

from app.models import AdminUserResponse, GetAllUsersResponse
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id,
    get_all_users,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get(
    "",
    response_model=GetAllUsersResponse,
    status_code=200,
    summary="Get all users (Admin only)",
    description=(
        "Returns a paginated list of all users with their profile information. "
        "Only ADMIN and SUPER_ADMIN users can access this endpoint."
    ),
)
async def get_all_users_endpoint(
    request: Request,
    response: Response,
    role: str = Query(default=None, description="Filter by role (ADMIN, SUPER_ADMIN)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Number of users to return (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Get all users. Admin only."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required",
            },
        )

    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data",
            },
        )

    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID",
            },
        )

    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found",
            },
        )

    user_role = get_user_role_by_user_id(db, user_id)
    if user_role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PERMISSION_DENIED",
                "error_message": "Only ADMIN and SUPER_ADMIN users can access this endpoint",
            },
        )

    users_data, total_count = get_all_users(db, role=role, offset=offset, limit=limit)

    users = [
        AdminUserResponse(
            id=u["id"],
            email=u.get("email"),
            email_verified=u.get("email_verified"),
            first_name=u.get("given_name"),
            last_name=u.get("family_name"),
            picture=u.get("picture"),
            role=u.get("role"),
            locale=u.get("locale"),
            hd=u.get("hd"),
            created_at=str(u["created_at"]),
            updated_at=str(u["updated_at"]),
        )
        for u in users_data
    ]

    has_next = (offset + limit) < total_count

    logger.info(
        "Retrieved all users successfully (admin)",
        requesting_user_id=user_id,
        user_count=len(users),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next,
    )

    return GetAllUsersResponse(
        users=users,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next,
    )
