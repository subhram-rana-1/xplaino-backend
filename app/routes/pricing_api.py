"""API routes for pricing management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session
from typing import Optional
import structlog
from datetime import datetime, timezone

from app.models import (
    CreatePricingRequest,
    UpdatePricingRequest,
    PricingResponse,
    GetAllPricingsResponse,
    GetLivePricingsResponse,
    CreatedByUser
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id,
    create_pricing,
    update_pricing,
    delete_pricing,
    get_all_pricings,
    get_live_pricings,
    check_pricing_intersection,
    check_pricing_has_subscriptions,
    get_pricing_by_id
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/pricing", tags=["Pricing"])


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
    response_model=PricingResponse,
    status_code=201,
    summary="Create a pricing",
    description="Create a new pricing plan. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def create_pricing_endpoint(
    request: Request,
    response: Response,
    body: CreatePricingRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a new pricing plan."""
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
    
    # Check intersection with existing ENABLED pricings
    has_intersection = check_pricing_intersection(
        db,
        body.recurring_period.value,
        body.recurring_period_count,
        activation_dt,
        expiry_dt
    )
    
    if has_intersection:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "PRICING_INTERSECTION",
                "error_message": f"Pricing period intersects with existing ENABLED pricing for {body.recurring_period.value} recurring period with count {body.recurring_period_count}"
            }
        )
    
    # Create pricing
    pricing_data = create_pricing(
        db,
        user_id,
        body.name,
        body.recurring_period.value,
        body.recurring_period_count,
        activation_dt,
        expiry_dt,
        body.status.value
    )
    
    logger.info(
        "Created pricing successfully",
        pricing_id=pricing_data["id"],
        user_id=user_id,
        name=body.name
    )
    
    # Convert to response model
    return PricingResponse(
        id=pricing_data["id"],
        name=pricing_data["name"],
        recurring_period=pricing_data["recurring_period"],
        recurring_period_count=pricing_data["recurring_period_count"],
        activation=pricing_data["activation"],
        expiry=pricing_data["expiry"],
        status=pricing_data["status"],
        created_by=CreatedByUser(
            id=pricing_data["created_by"]["id"],
            name=pricing_data["created_by"]["name"],
            role=pricing_data["created_by"]["role"]
        ),
        created_at=pricing_data["created_at"],
        updated_at=pricing_data["updated_at"]
    )


@router.patch(
    "/{pricing_id}",
    response_model=PricingResponse,
    summary="Update a pricing",
    description="Update a pricing plan. Only ADMIN and SUPER_ADMIN users can access this endpoint. Only provided fields will be updated."
)
async def update_pricing_endpoint(
    request: Request,
    response: Response,
    pricing_id: str,
    body: UpdatePricingRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update a pricing plan."""
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
    
    # Check if pricing exists
    existing_pricing = get_pricing_by_id(db, pricing_id)
    if not existing_pricing:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "PRICING_NOT_FOUND",
                "error_message": "Pricing not found"
            }
        )
    
    # Parse and validate timestamps if provided
    activation_dt = None
    expiry_dt = None
    current_time = datetime.now(timezone.utc)
    
    if body.activation is not None:
        try:
            activation_dt = datetime.fromisoformat(body.activation.replace('Z', '+00:00'))
            if activation_dt.tzinfo is None:
                activation_dt = activation_dt.replace(tzinfo=timezone.utc)
            
            # Validate: activation should not be before current timestamp
            if activation_dt < current_time:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error_code": "VAL_003",
                        "error_message": "Activation timestamp cannot be before current timestamp"
                    }
                )
        except HTTPException:
            raise
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
            
            # Validate: expiry should not be before current timestamp
            if expiry_dt < current_time:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error_code": "VAL_004",
                        "error_message": "Expiry timestamp cannot be before current timestamp"
                    }
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "VAL_002",
                    "error_message": f"Invalid expiry timestamp format: {str(e)}"
                }
            )
    
    # Update pricing
    pricing_data = update_pricing(
        db,
        pricing_id,
        name=body.name,
        activation=activation_dt,
        expiry=expiry_dt,
        status=body.status.value if body.status is not None else None
    )
    
    logger.info(
        "Updated pricing successfully",
        pricing_id=pricing_id,
        user_id=user_id
    )
    
    # Convert to response model
    return PricingResponse(
        id=pricing_data["id"],
        name=pricing_data["name"],
        recurring_period=pricing_data["recurring_period"],
        recurring_period_count=pricing_data["recurring_period_count"],
        activation=pricing_data["activation"],
        expiry=pricing_data["expiry"],
        status=pricing_data["status"],
        created_by=CreatedByUser(
            id=pricing_data["created_by"]["id"],
            name=pricing_data["created_by"]["name"],
            role=pricing_data["created_by"]["role"]
        ),
        created_at=pricing_data["created_at"],
        updated_at=pricing_data["updated_at"]
    )


@router.delete(
    "/{pricing_id}",
    status_code=200,
    summary="Delete a pricing",
    description="Delete a pricing plan. Only ADMIN and SUPER_ADMIN users can access this endpoint. Pricing must have no child subscription records."
)
async def delete_pricing_endpoint(
    request: Request,
    response: Response,
    pricing_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a pricing plan."""
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
    
    # Check if pricing exists
    existing_pricing = get_pricing_by_id(db, pricing_id)
    if not existing_pricing:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "PRICING_NOT_FOUND",
                "error_message": "Pricing not found"
            }
        )
    
    # Check if pricing has subscriptions
    has_subscriptions = check_pricing_has_subscriptions(db, pricing_id)
    if has_subscriptions:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "PRICING_HAS_SUBSCRIPTIONS",
                "error_message": "Cannot delete pricing with existing subscription records"
            }
        )
    
    # Delete pricing
    delete_pricing(db, pricing_id)
    
    logger.info(
        "Deleted pricing successfully",
        pricing_id=pricing_id,
        user_id=user_id
    )
    
    return {"message": "Pricing deleted successfully"}


@router.get(
    "/live",
    response_model=GetLivePricingsResponse,
    summary="Get live pricings",
    description="Get all live pricing plans (activation < current_time < expiry AND status=ENABLED). No authentication required."
)
async def get_live_pricings_endpoint(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """Get all live pricing plans."""
    pricings_data = get_live_pricings(db)
    
    # Convert to response models
    pricings = []
    for pricing_data in pricings_data:
        pricings.append(
            PricingResponse(
                id=pricing_data["id"],
                name=pricing_data["name"],
                recurring_period=pricing_data["recurring_period"],
                recurring_period_count=pricing_data["recurring_period_count"],
                activation=pricing_data["activation"],
                expiry=pricing_data["expiry"],
                status=pricing_data["status"],
                created_by=CreatedByUser(
                    id=pricing_data["created_by"]["id"],
                    name=pricing_data["created_by"]["name"],
                    role=pricing_data["created_by"]["role"]
                ),
                created_at=pricing_data["created_at"],
                updated_at=pricing_data["updated_at"]
            )
        )
    
    logger.info(
        "Retrieved live pricings successfully",
        count=len(pricings)
    )
    
    return GetLivePricingsResponse(pricings=pricings)


@router.get(
    "/all",
    response_model=GetAllPricingsResponse,
    summary="Get all pricings",
    description="Get all pricing plans. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def get_all_pricings_endpoint(
    request: Request,
    response: Response,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get all pricing plans."""
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
    
    pricings_data = get_all_pricings(db)
    
    # Convert to response models
    pricings = []
    for pricing_data in pricings_data:
        pricings.append(
            PricingResponse(
                id=pricing_data["id"],
                name=pricing_data["name"],
                recurring_period=pricing_data["recurring_period"],
                recurring_period_count=pricing_data["recurring_period_count"],
                activation=pricing_data["activation"],
                expiry=pricing_data["expiry"],
                status=pricing_data["status"],
                created_by=CreatedByUser(
                    id=pricing_data["created_by"]["id"],
                    name=pricing_data["created_by"]["name"],
                    role=pricing_data["created_by"]["role"]
                ),
                created_at=pricing_data["created_at"],
                updated_at=pricing_data["updated_at"]
            )
        )
    
    logger.info(
        "Retrieved all pricings successfully",
        user_id=user_id,
        count=len(pricings)
    )
    
    return GetAllPricingsResponse(pricings=pricings)

