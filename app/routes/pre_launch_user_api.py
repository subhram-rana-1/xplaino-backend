"""API routes for pre-launch user registration."""

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
import structlog

from app.models import (
    CreatePreLaunchUserRequest,
    PreLaunchUserResponse,
    CreatePreLaunchUserApiResponse,
)
from app.database.connection import get_db
from app.services.database_service import (
    create_pre_launch_user,
    get_pre_launch_user_by_email,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/pre-launch-user", tags=["Pre Launch User"])


@router.post(
    "",
    response_model=CreatePreLaunchUserApiResponse,
    status_code=200,
    summary="Register pre-launch user",
    description="Store a pre-launch user signup with email and optional meta information. Returns 200 even when email already exists."
)
async def register_pre_launch_user(
    body: CreatePreLaunchUserRequest,
    db: Session = Depends(get_db)
):
    """Register a pre-launch user. Public endpoint."""
    # Minimal validation: trim email and ensure non-empty
    email = body.email.strip()
    if not email:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Email is required"
            }
        )
    
    # Check if email already exists
    existing = get_pre_launch_user_by_email(db, email)
    if existing:
        logger.info(
            "Pre-launch user email already exists",
            email=email,
            pre_launch_user_id=existing["id"],
        )
        return CreatePreLaunchUserApiResponse(
            code="EMAIL_ALREADY_EXISTS",
            user=PreLaunchUserResponse(
                id=existing["id"],
                email=existing["email"],
                metaInfo=existing["meta_info"],
                createdAt=existing["created_at"],
                updatedAt=existing["updated_at"],
            ),
        )
    
    # Create new record
    record = create_pre_launch_user(db, email, body.metaInfo)
    
    return CreatePreLaunchUserApiResponse(
        code=None,
        user=PreLaunchUserResponse(
            id=record["id"],
            email=record["email"],
            metaInfo=record["meta_info"],
            createdAt=record["created_at"],
            updatedAt=record["updated_at"],
        ),
    )

