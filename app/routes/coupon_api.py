"""API routes for coupon management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from sqlalchemy.orm import Session
from typing import Optional
import structlog
from datetime import datetime, timezone

from app.models import (
    CreateCouponRequest,
    UpdateCouponRequest,
    CouponResponse,
    GetAllCouponsResponse,
    GetActiveHighlightedCouponResponse,
    UserInfo
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id,
    create_coupon,
    update_coupon,
    delete_coupon,
    get_all_coupons,
    get_coupon_by_id,
    get_active_highlighted_coupon
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/coupon", tags=["Coupon"])


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


@router.post(
    "/",
    response_model=CouponResponse,
    status_code=201,
    summary="Create a coupon",
    description="Create a new coupon. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def create_coupon_endpoint(
    request: Request,
    response: Response,
    body: CreateCouponRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a new coupon."""
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
    
    # Parse timestamps
    try:
        activation_dt = datetime.fromisoformat(body.activation.replace('Z', '+00:00'))
        if activation_dt.tzinfo is None:
            activation_dt = activation_dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": f"Invalid activation timestamp format: {str(e)}"
            }
        )
    
    try:
        expiry_dt = datetime.fromisoformat(body.expiry.replace('Z', '+00:00'))
        if expiry_dt.tzinfo is None:
            expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_002",
                "error_message": f"Invalid expiry timestamp format: {str(e)}"
            }
        )
    
    # Validate: expiry should be > activation
    if expiry_dt <= activation_dt:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_003",
                "error_message": "Expiry timestamp must be greater than activation timestamp"
            }
        )
    
    # Create coupon
    coupon_data = create_coupon(
        db,
        user_id,
        body.code,
        body.name,
        body.description,
        body.discount,
        activation_dt,
        expiry_dt,
        body.status.value
    )
    
    logger.info(
        "Created coupon successfully",
        coupon_id=coupon_data["id"],
        user_id=user_id,
        code=body.code
    )
    
    # Convert to response model
    return CouponResponse(
        id=coupon_data["id"],
        code=coupon_data["code"],
        name=coupon_data["name"],
        description=coupon_data["description"],
        discount=coupon_data["discount"],
        activation=coupon_data["activation"],
        expiry=coupon_data["expiry"],
        status=coupon_data["status"],
        is_highlighted=coupon_data["is_highlighted"],
        created_by=UserInfo(
            id=coupon_data["created_by"]["id"],
            name=coupon_data["created_by"]["name"],
            email=coupon_data["created_by"]["email"],
            role=coupon_data["created_by"].get("role")
        ),
        created_at=coupon_data["created_at"],
        updated_at=coupon_data["updated_at"]
    )


@router.get(
    "/",
    response_model=GetAllCouponsResponse,
    summary="Get all coupons",
    description="Get all coupons with optional filters and pagination. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def get_all_coupons_endpoint(
    request: Request,
    response: Response,
    code: Optional[str] = Query(default=None, description="Filter by exact coupon code"),
    name: Optional[str] = Query(default=None, description="Filter by name (LIKE %name%)"),
    status: Optional[str] = Query(default=None, description="Filter by status (ENABLED or DISABLED)"),
    is_active: Optional[bool] = Query(default=None, description="If true, only fetch coupons where expiry > current timestamp"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get all coupons with optional filters and pagination."""
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
    
    # Get coupons
    coupons_data, total_count = get_all_coupons(
        db,
        code=code,
        name=name,
        status=status,
        is_active=is_active,
        offset=offset,
        limit=limit
    )
    
    # Convert to response models
    coupons = []
    for coupon_data in coupons_data:
        coupons.append(
            CouponResponse(
                id=coupon_data["id"],
                code=coupon_data["code"],
                name=coupon_data["name"],
                description=coupon_data["description"],
                discount=coupon_data["discount"],
                activation=coupon_data["activation"],
                expiry=coupon_data["expiry"],
                status=coupon_data["status"],
                is_highlighted=coupon_data["is_highlighted"],
                created_by=UserInfo(
                    id=coupon_data["created_by"]["id"],
                    name=coupon_data["created_by"]["name"],
                    email=coupon_data["created_by"]["email"],
                    role=coupon_data["created_by"].get("role")
                ),
                created_at=coupon_data["created_at"],
                updated_at=coupon_data["updated_at"]
            )
        )
    
    # Calculate has_next
    has_next = (offset + limit) < total_count
    
    logger.info(
        "Retrieved all coupons successfully",
        user_id=user_id,
        coupon_count=len(coupons),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )
    
    return GetAllCouponsResponse(
        coupons=coupons,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )


@router.get(
    "/{coupon_id}",
    response_model=CouponResponse,
    summary="Get coupon by ID",
    description="Get a coupon by its ID. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def get_coupon_by_id_endpoint(
    request: Request,
    response: Response,
    coupon_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get a coupon by ID."""
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
    
    # Get coupon
    coupon_data = get_coupon_by_id(db, coupon_id)
    if not coupon_data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "COUPON_NOT_FOUND",
                "error_message": "Coupon not found"
            }
        )
    
    logger.info(
        "Retrieved coupon successfully",
        coupon_id=coupon_id,
        user_id=user_id
    )
    
    return CouponResponse(
        id=coupon_data["id"],
        code=coupon_data["code"],
        name=coupon_data["name"],
        description=coupon_data["description"],
        discount=coupon_data["discount"],
        activation=coupon_data["activation"],
        expiry=coupon_data["expiry"],
        status=coupon_data["status"],
        is_highlighted=coupon_data["is_highlighted"],
        created_by=UserInfo(
            id=coupon_data["created_by"]["id"],
            name=coupon_data["created_by"]["name"],
            email=coupon_data["created_by"]["email"],
            role=coupon_data["created_by"].get("role")
        ),
        created_at=coupon_data["created_at"],
        updated_at=coupon_data["updated_at"]
    )


@router.put(
    "/{coupon_id}",
    response_model=CouponResponse,
    summary="Update a coupon",
    description="Update a coupon (full update). Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def update_coupon_endpoint(
    request: Request,
    response: Response,
    coupon_id: str,
    body: UpdateCouponRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update a coupon."""
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
    
    # Check if coupon exists
    existing_coupon = get_coupon_by_id(db, coupon_id)
    if not existing_coupon:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "COUPON_NOT_FOUND",
                "error_message": "Coupon not found"
            }
        )
    
    # Parse and validate timestamps if provided
    activation_dt = None
    expiry_dt = None
    
    if body.activation is not None:
        try:
            activation_dt = datetime.fromisoformat(body.activation.replace('Z', '+00:00'))
            if activation_dt.tzinfo is None:
                activation_dt = activation_dt.replace(tzinfo=timezone.utc)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "VAL_001",
                    "error_message": f"Invalid activation timestamp format: {str(e)}"
                }
            )
    
    if body.expiry is not None:
        try:
            expiry_dt = datetime.fromisoformat(body.expiry.replace('Z', '+00:00'))
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "VAL_002",
                    "error_message": f"Invalid expiry timestamp format: {str(e)}"
                }
            )
    
    # Determine final activation/expiry values for validation
    if activation_dt is not None:
        final_activation = activation_dt
    else:
        try:
            final_activation = datetime.fromisoformat(existing_coupon["activation"].replace('Z', '+00:00'))
            if final_activation.tzinfo is None:
                final_activation = final_activation.replace(tzinfo=timezone.utc)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "INTERNAL_ERROR",
                    "error_message": f"Failed to parse existing activation timestamp: {str(e)}"
                }
            )
    
    if expiry_dt is not None:
        final_expiry = expiry_dt
    else:
        try:
            final_expiry = datetime.fromisoformat(existing_coupon["expiry"].replace('Z', '+00:00'))
            if final_expiry.tzinfo is None:
                final_expiry = final_expiry.replace(tzinfo=timezone.utc)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "INTERNAL_ERROR",
                    "error_message": f"Failed to parse existing expiry timestamp: {str(e)}"
                }
            )
    
    # Validate: expiry should be > activation
    if final_expiry <= final_activation:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_003",
                "error_message": "Expiry timestamp must be greater than activation timestamp"
            }
        )
    
    # Update coupon
    coupon_data = update_coupon(
        db,
        coupon_id,
        code=body.code,
        name=body.name,
        description=body.description,
        discount=body.discount,
        activation=activation_dt,
        expiry=expiry_dt,
        status=body.status.value if body.status is not None else None,
        is_highlighted=body.is_highlighted
    )
    
    # Check for intersection error
    if coupon_data and coupon_data.get("error") == "HIGHLIGHTED_INTERSECTION":
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "COUPON_HIGHLIGHTED_INTERSECTION",
                "error_message": "Cannot set status=ENABLED and is_highlighted=True: another ENABLED highlighted coupon has an intersecting activation period"
            }
        )
    
    if not coupon_data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "COUPON_NOT_FOUND",
                "error_message": "Coupon not found"
            }
        )
    
    logger.info(
        "Updated coupon successfully",
        coupon_id=coupon_id,
        user_id=user_id
    )
    
    # Convert to response model
    return CouponResponse(
        id=coupon_data["id"],
        code=coupon_data["code"],
        name=coupon_data["name"],
        description=coupon_data["description"],
        discount=coupon_data["discount"],
        activation=coupon_data["activation"],
        expiry=coupon_data["expiry"],
        status=coupon_data["status"],
        is_highlighted=coupon_data["is_highlighted"],
        created_by=UserInfo(
            id=coupon_data["created_by"]["id"],
            name=coupon_data["created_by"]["name"],
            email=coupon_data["created_by"]["email"],
            role=coupon_data["created_by"].get("role")
        ),
        created_at=coupon_data["created_at"],
        updated_at=coupon_data["updated_at"]
    )


@router.delete(
    "/{coupon_id}",
    status_code=200,
    summary="Delete a coupon",
    description="Delete a coupon. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def delete_coupon_endpoint(
    request: Request,
    response: Response,
    coupon_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a coupon."""
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
    
    # Check if coupon exists
    existing_coupon = get_coupon_by_id(db, coupon_id)
    if not existing_coupon:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "COUPON_NOT_FOUND",
                "error_message": "Coupon not found"
            }
        )
    
    # Delete coupon
    deleted = delete_coupon(db, coupon_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "COUPON_NOT_FOUND",
                "error_message": "Coupon not found"
            }
        )
    
    logger.info(
        "Deleted coupon successfully",
        coupon_id=coupon_id,
        user_id=user_id
    )
    
    return {"message": "Coupon deleted successfully"}


@router.get(
    "/active-highlighted",
    response_model=GetActiveHighlightedCouponResponse,
    summary="Get current highlighted coupon",
    description="Get the currently active highlighted coupon. No authentication required."
)
async def get_active_highlighted_coupon_endpoint(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """Get the currently active highlighted coupon."""
    coupon_data = get_active_highlighted_coupon(db)
    
    if not coupon_data:
        logger.info(
            "No active highlighted coupon found",
            function="get_active_highlighted_coupon_endpoint"
        )
        return GetActiveHighlightedCouponResponse(
            code="NO_ACTIVE_HIGHLIGHTED_COUPON"
        )
    
    logger.info(
        "Retrieved active highlighted coupon successfully",
        coupon_id=coupon_data["id"],
        discount=coupon_data["discount"]
    )
    
    return GetActiveHighlightedCouponResponse(
        code=None,
        id=coupon_data["id"],
        coupon_code=coupon_data["code"],
        name=coupon_data["name"],
        description=coupon_data["description"],
        discount=coupon_data["discount"],
        activation=coupon_data["activation"],
        expiry=coupon_data["expiry"],
        status=coupon_data["status"],
        is_highlighted=coupon_data["is_highlighted"]
    )
