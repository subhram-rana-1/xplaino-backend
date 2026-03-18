"""API routes for shared user tracking."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import structlog

from app.models import SharedToEmailsResponse
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_email_by_user_id,
    get_shared_to_emails_by_sharer,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/shared-users", tags=["Shared Users"])


@router.get(
    "/emails",
    response_model=SharedToEmailsResponse,
    summary="Get shared-to emails",
    description=(
        "Returns all email addresses that the caller has previously shared a folder or PDF with. "
        "Authenticated users are identified by their email; unauthenticated users by their "
        "X-Unauthenticated-User-Id header."
    ),
)
async def get_shared_to_emails(
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    if auth_context.get("authenticated"):
        auth_vendor_id = auth_context["session_data"]["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
        user_email = get_email_by_user_id(db, user_id)
        emails = get_shared_to_emails_by_sharer(db, shared_by_user_email=user_email)
    else:
        unauth_id = auth_context.get("unauthenticated_user_id")
        emails = get_shared_to_emails_by_sharer(
            db, shared_by_unauthenticated_user_id=unauth_id
        )

    logger.info(
        "Retrieved shared-to emails",
        authenticated=auth_context.get("authenticated"),
        count=len(emails),
    )

    return SharedToEmailsResponse(emails=emails)
