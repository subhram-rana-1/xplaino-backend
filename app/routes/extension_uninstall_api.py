"""API routes for extension uninstallation feedback."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import structlog

from app.database.connection import get_db
from app.models import (
    ExtensionUninstallationFeedbackRequest,
    ExtensionUninstallationFeedbackResponse,
)
from app.services.database_service import save_extension_uninstallation_feedback

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
        has_feedback=body.user_feedback is not None
    )

    try:
        save_extension_uninstallation_feedback(
            db=db,
            reason=body.reason.value,
            user_feedback=body.user_feedback
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
