"""API routes for extension uninstallation feedback."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import Optional
import structlog

from app.database.connection import get_db
from app.models import (
    ExtensionUninstallationFeedbackRequest,
    ExtensionUninstallationFeedbackResponse,
    ExtensionUninstallationReason,
    ExtensionUninstallFeedbackItem,
    GetAllExtensionUninstallFeedbacksResponse,
)
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    save_extension_uninstallation_feedback,
    get_all_extension_uninstallation_feedbacks,
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/extension-uninstall", tags=["Extension Uninstall"])


@router.post(
    "/feedback",
    response_model=ExtensionUninstallationFeedbackResponse,
    status_code=201,
    summary="Submit extension uninstallation feedback",
    description="Submit feedback about why the extension was uninstalled."
)
async def submit_uninstallation_feedback(
    body: ExtensionUninstallationFeedbackRequest,
    db: Session = Depends(get_db)
):
    """
    Submit feedback for extension uninstallation.
    
    Public endpoint — no authentication required. Stores the reason
    and optional feedback text in the database.
    """
    logger.info(
        "Extension uninstallation feedback received",
        reason=body.reason.value,
        has_metadata=body.metadata is not None
    )

    try:
        save_extension_uninstallation_feedback(
            db=db,
            reason=body.reason.value,
            metadata=body.metadata
        )

        return ExtensionUninstallationFeedbackResponse(
            success=True,
            message="Feedback submitted successfully"
        )

    except Exception as e:
        logger.error(
            "Failed to save extension uninstallation feedback",
            error=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "FEEDBACK_SAVE_FAILED",
                "error_message": "Failed to save feedback"
            }
        )


@router.get(
    "/feedbacks",
    response_model=GetAllExtensionUninstallFeedbacksResponse,
    summary="Get all extension uninstallation feedbacks (Admin only)",
    description=(
        "Return a paginated list of all extension uninstallation feedbacks in descending order of "
        "created_at. Only ADMIN and SUPER_ADMIN users can access this endpoint. "
        "Optionally filter by uninstallation reason enum."
    ),
)
async def get_all_extension_uninstall_feedbacks_endpoint(
    request: Request,
    reason: Optional[ExtensionUninstallationReason] = Query(
        default=None,
        description=(
            "Filter by uninstallation reason "
            "(TOO_EXPENSIVE, NOT_USING, FOUND_ALTERNATIVE, MISSING_FEATURES, "
            "EXTENSION_NOT_WORKING, OTHER)"
        ),
    ),
    created_at_from: Optional[str] = Query(
        default=None,
        description="Filter feedbacks created on or after this ISO-8601 datetime (e.g. 2025-01-01T00:00:00Z)",
    ),
    created_at_to: Optional[str] = Query(
        default=None,
        description="Filter feedbacks created on or before this ISO-8601 datetime (e.g. 2025-12-31T23:59:59Z)",
    ),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Get all extension uninstallation feedbacks with optional reason filter. Admin / Super Admin only."""
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

    feedbacks_data, total_count = get_all_extension_uninstallation_feedbacks(
        db,
        reason=reason.value if reason is not None else None,
        created_at_from=created_at_from,
        created_at_to=created_at_to,
        offset=offset,
        limit=limit,
    )

    feedbacks = [
        ExtensionUninstallFeedbackItem(
            id=row["id"],
            reason=row["reason"],
            metadata=row.get("metadata"),
            created_at=(
                row["created_at"].isoformat()
                if hasattr(row["created_at"], "isoformat")
                else str(row["created_at"])
            ),
        )
        for row in feedbacks_data
    ]

    logger.info(
        "Retrieved all extension uninstallation feedbacks (admin)",
        user_id=user_id,
        feedback_count=len(feedbacks),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_reason_filter=reason is not None,
        has_created_at_from=created_at_from is not None,
        has_created_at_to=created_at_to is not None,
    )

    return GetAllExtensionUninstallFeedbacksResponse(
        feedbacks=feedbacks,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=(offset + limit) < total_count,
    )
