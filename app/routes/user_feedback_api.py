"""API routes for user feedback."""

from fastapi import APIRouter, HTTPException, Depends, Request, Query
from sqlalchemy.orm import Session
from typing import Optional
import structlog

from app.models import (
    CreateUserFeedbackRequest,
    UserFeedbackResponse,
    UserFeedbackMetadata,
    UserFeedbackQnA,
    UserFeedbackVerdict,
    GetAllUserFeedbacksResponse,
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id,
    create_user_feedback,
    get_all_user_feedbacks,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/user-feedback", tags=["User Feedback"])


def _build_feedback_response(row: dict) -> UserFeedbackResponse:
    """Convert a raw user_feedback DB row to a UserFeedbackResponse."""
    metadata_raw = row.get("metadata", {})
    if isinstance(metadata_raw, dict):
        qna_list = [
            UserFeedbackQnA(question=q["question"], answer=q["answer"])
            for q in metadata_raw.get("qna", [])
        ]
    else:
        qna_list = []

    created_at = row["created_at"]
    updated_at = row["updated_at"]

    return UserFeedbackResponse(
        id=row["id"],
        user_id=row["user_id"],
        user_email=row.get("user_email"),
        verdict=row["verdict"],
        metadata=UserFeedbackMetadata(qna=qna_list),
        created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        updated_at=updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
    )


def _resolve_authenticated_user_id(auth_context: dict, db: Session) -> str:
    """
    Extract and validate the authenticated user_id from auth_context.
    Raises HTTPException (401) on any failure.
    """
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

    return user_id


@router.post(
    "/",
    response_model=UserFeedbackResponse,
    summary="Submit user feedback",
    description="Submit feedback for the authenticated user. Requires a valid session.",
)
async def create_user_feedback_endpoint(
    request: Request,
    body: CreateUserFeedbackRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Create a new user_feedback record for the currently authenticated user."""
    user_id = _resolve_authenticated_user_id(auth_context, db)

    feedback_row = create_user_feedback(
        db,
        user_id=user_id,
        verdict=body.verdict.value,
        metadata=body.metadata.model_dump(),
    )

    return _build_feedback_response(feedback_row)


@router.get(
    "/all",
    response_model=GetAllUserFeedbacksResponse,
    summary="Get all user feedbacks (Admin only)",
    description=(
        "Return a paginated list of all user feedbacks in descending order of created_at. "
        "Only ADMIN and SUPER_ADMIN users can access this endpoint. "
        "Optionally filter by verdict enum and/or user email."
    ),
)
async def get_all_user_feedbacks_endpoint(
    request: Request,
    verdict: Optional[UserFeedbackVerdict] = Query(
        default=None,
        description="Filter by verdict (UNHAPPY, NEUTRAL, HAPPY)",
    ),
    email: Optional[str] = Query(
        default=None,
        description="Filter by the email of the user who submitted feedback",
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Get all user feedbacks with optional filters. Admin / Super Admin only."""
    user_id = _resolve_authenticated_user_id(auth_context, db)

    user_role = get_user_role_by_user_id(db, user_id)
    if user_role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PERMISSION_DENIED",
                "error_message": "Only ADMIN and SUPER_ADMIN users can access this endpoint",
            },
        )

    feedbacks_data, total_count = get_all_user_feedbacks(
        db,
        verdict=verdict.value if verdict is not None else None,
        email=email,
        offset=offset,
        limit=limit,
    )

    feedbacks = [_build_feedback_response(row) for row in feedbacks_data]

    return GetAllUserFeedbacksResponse(
        feedbacks=feedbacks,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=(offset + limit) < total_count,
    )
