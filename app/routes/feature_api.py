"""API routes for feature management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session
from typing import List
import structlog

from app.models import FeaturesResponse, Feature
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/feature", tags=["Feature"])

# Features constant - empty list to be filled later
FEATURES: List[Feature] = []


def _check_admin_role(user_id: str, db: Session) -> None:
    """
    Check if user has ADMIN or SUPER_ADMIN role.
    
    Args:
        user_id: User ID
        db: Database session
        
    Raises:
        HTTPException: 403 if user is not ADMIN or SUPER_ADMIN
    """
    user_role = get_user_role_by_user_id(db, user_id)
    if user_role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PERMISSION_DENIED",
                "error_message": "Only ADMIN and SUPER_ADMIN users can access this endpoint"
            }
        )


@router.get(
    "",
    response_model=FeaturesResponse,
    status_code=200,
    summary="Get all features",
    description="Get list of all available features. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def get_all_features(
    request: Request,
    response: Response,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get all features. Admin only."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Check admin role
    _check_admin_role(user_id, db)
    
    logger.info(
        "Retrieved features list",
        user_id=user_id,
        feature_count=len(FEATURES)
    )
    
    return FeaturesResponse(features=FEATURES)
