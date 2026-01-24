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
    check_pricing_has_subscriptions,
    get_pricing_by_id
)
from app.routes.feature_api import FEATURES

logger = structlog.get_logger()

router = APIRouter(prefix="/api/pricing", tags=["Pricing"])

# Get valid feature names from FEATURES constant
VALID_FEATURE_NAMES = {feature.name for feature in FEATURES}


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


def _enrich_features_with_descriptions(features: list) -> list:
    """
    Enrich feature dicts with descriptions from FEATURES constant.
    
    Args:
        features: List of feature dicts (from database or request)
        
    Returns:
        List of feature dicts with descriptions added
    """
    # Create a mapping of feature name to description for quick lookup
    feature_name_to_description = {feature.name: feature.description for feature in FEATURES}
    
    enriched_features = []
    for feature in features:
        feature_dict = feature.dict() if hasattr(feature, 'dict') else feature
        feature_name = feature_dict.get("name")
        
        # Add description if found in FEATURES constant
        if feature_name and feature_name in feature_name_to_description:
            feature_dict["description"] = feature_name_to_description[feature_name]
        
        enriched_features.append(feature_dict)
    
    return enriched_features


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
    
    # Validate feature names
    invalid_features = []
    for feature in body.features:
        if feature.name not in VALID_FEATURE_NAMES:
            invalid_features.append(feature.name)
    
    if invalid_features:
        valid_features_str = ", ".join(sorted(VALID_FEATURE_NAMES))
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_FEATURE_NAME",
                "error_message": f"Invalid feature name(s): {', '.join(invalid_features)}. Valid features are: {valid_features_str}"
            }
        )
    
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
    
    # Validate: expiry must be greater than activation
    if expiry_dt <= activation_dt:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_005",
                "error_message": "Expiry timestamp must be greater than activation timestamp"
            }
        )
    
    # Convert pricing_details to dict and validate discount dates
    pricing_details_dict = body.pricing_details.dict()
    
    # Validate monthly discount valid_till < pricing expiry
    monthly_discount_valid_till = datetime.fromisoformat(
        pricing_details_dict["monthly_discount"]["discount_valid_till"].replace('Z', '+00:00')
    )
    if monthly_discount_valid_till.tzinfo is None:
        monthly_discount_valid_till = monthly_discount_valid_till.replace(tzinfo=timezone.utc)
    
    if monthly_discount_valid_till >= expiry_dt:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_006",
                "error_message": "Monthly discount valid_till must be less than pricing expiry timestamp"
            }
        )
    
    # Validate yearly discount valid_till < pricing expiry (if yearly is enabled)
    if pricing_details_dict.get("is_yearly_enabled") and pricing_details_dict.get("yearly_discount"):
        yearly_discount_valid_till = datetime.fromisoformat(
            pricing_details_dict["yearly_discount"]["discount_valid_till"].replace('Z', '+00:00')
        )
        if yearly_discount_valid_till.tzinfo is None:
            yearly_discount_valid_till = yearly_discount_valid_till.replace(tzinfo=timezone.utc)
        
        if yearly_discount_valid_till >= expiry_dt:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "VAL_007",
                    "error_message": "Yearly discount valid_till must be less than pricing expiry timestamp"
                }
            )
    
    # Enrich features with descriptions before storing
    features_list = _enrich_features_with_descriptions(body.features)
    
    # Create pricing
    pricing_data = create_pricing(
        db,
        user_id,
        body.name,
        activation_dt,
        expiry_dt,
        body.status.value,
        features_list,
        body.currency.value,
        pricing_details_dict,
        body.description,
        body.is_highlighted
    )
    
    logger.info(
        "Created pricing successfully",
        pricing_id=pricing_data["id"],
        user_id=user_id,
        name=body.name
    )
    
    # Enrich features in response (ensure descriptions are present)
    enriched_features = _enrich_features_with_descriptions(pricing_data["features"])
    
    # Convert to response model
    return PricingResponse(
        id=pricing_data["id"],
        name=pricing_data["name"],
        activation=pricing_data["activation"],
        expiry=pricing_data["expiry"],
        status=pricing_data["status"],
        features=enriched_features,
        currency=pricing_data["currency"],
        pricing_details=pricing_data["pricing_details"],
        description=pricing_data["description"],
        is_highlighted=pricing_data["is_highlighted"],
        created_by=CreatedByUser(
            id=pricing_data["created_by"]["id"],
            name=pricing_data["created_by"]["name"],
            role=pricing_data["created_by"]["role"],
            profileIconUrl=pricing_data["created_by"].get("picture")
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
    # If provided in request, use them; otherwise use existing values
    final_activation = activation_dt
    final_expiry = expiry_dt
    
    if final_activation is None:
        # Parse existing activation
        try:
            final_activation = datetime.fromisoformat(existing_pricing["activation"].replace('Z', '+00:00'))
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
    
    if final_expiry is None:
        # Parse existing expiry
        try:
            final_expiry = datetime.fromisoformat(existing_pricing["expiry"].replace('Z', '+00:00'))
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
    
    # Validate: expiry must be greater than activation
    if final_expiry <= final_activation:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_005",
                "error_message": "Expiry timestamp must be greater than activation timestamp"
            }
        )
    
    # Validate feature names if features are being updated
    if body.features is not None:
        invalid_features = []
        for feature in body.features:
            if feature.name not in VALID_FEATURE_NAMES:
                invalid_features.append(feature.name)
        
        if invalid_features:
            valid_features_str = ", ".join(sorted(VALID_FEATURE_NAMES))
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "INVALID_FEATURE_NAME",
                    "error_message": f"Invalid feature name(s): {', '.join(invalid_features)}. Valid features are: {valid_features_str}"
                }
            )
    
    # Enrich features with descriptions if features are being updated
    features_list = None
    if body.features is not None:
        features_list = _enrich_features_with_descriptions(body.features)
    
    # Convert pricing_details to dict if provided and validate discount dates
    pricing_details_dict = None
    if body.pricing_details is not None:
        pricing_details_dict = body.pricing_details.dict()
        
        # Validate monthly discount valid_till < pricing expiry
        monthly_discount_valid_till = datetime.fromisoformat(
            pricing_details_dict["monthly_discount"]["discount_valid_till"].replace('Z', '+00:00')
        )
        if monthly_discount_valid_till.tzinfo is None:
            monthly_discount_valid_till = monthly_discount_valid_till.replace(tzinfo=timezone.utc)
        
        if monthly_discount_valid_till >= final_expiry:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "VAL_006",
                    "error_message": "Monthly discount valid_till must be less than pricing expiry timestamp"
                }
            )
        
        # Validate yearly discount valid_till < pricing expiry (if yearly is enabled)
        if pricing_details_dict.get("is_yearly_enabled") and pricing_details_dict.get("yearly_discount"):
            yearly_discount_valid_till = datetime.fromisoformat(
                pricing_details_dict["yearly_discount"]["discount_valid_till"].replace('Z', '+00:00')
            )
            if yearly_discount_valid_till.tzinfo is None:
                yearly_discount_valid_till = yearly_discount_valid_till.replace(tzinfo=timezone.utc)
            
            if yearly_discount_valid_till >= final_expiry:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error_code": "VAL_007",
                        "error_message": "Yearly discount valid_till must be less than pricing expiry timestamp"
                    }
                )
    
    # Update pricing
    pricing_data = update_pricing(
        db,
        pricing_id,
        name=body.name,
        activation=activation_dt,
        expiry=expiry_dt,
        status=body.status.value if body.status is not None else None,
        features=features_list,
        currency=body.currency.value if body.currency is not None else None,
        pricing_details=pricing_details_dict,
        description=body.description,
        is_highlighted=body.is_highlighted
    )
    
    logger.info(
        "Updated pricing successfully",
        pricing_id=pricing_id,
        user_id=user_id
    )
    
    # Enrich features in response (ensure descriptions are present)
    enriched_features = _enrich_features_with_descriptions(pricing_data["features"])
    
    # Convert to response model
    return PricingResponse(
        id=pricing_data["id"],
        name=pricing_data["name"],
        activation=pricing_data["activation"],
        expiry=pricing_data["expiry"],
        status=pricing_data["status"],
        features=enriched_features,
        currency=pricing_data["currency"],
        pricing_details=pricing_data["pricing_details"],
        description=pricing_data["description"],
        is_highlighted=pricing_data["is_highlighted"],
        created_by=CreatedByUser(
            id=pricing_data["created_by"]["id"],
            name=pricing_data["created_by"]["name"],
            role=pricing_data["created_by"]["role"],
            profileIconUrl=pricing_data["created_by"].get("picture")
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
        # Enrich features with descriptions
        enriched_features = _enrich_features_with_descriptions(pricing_data["features"])
        
        pricings.append(
            PricingResponse(
                id=pricing_data["id"],
                name=pricing_data["name"],
                activation=pricing_data["activation"],
                expiry=pricing_data["expiry"],
                status=pricing_data["status"],
                features=enriched_features,
                currency=pricing_data["currency"],
                pricing_details=pricing_data["pricing_details"],
                description=pricing_data["description"],
                is_highlighted=pricing_data["is_highlighted"],
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
        # Enrich features with descriptions
        enriched_features = _enrich_features_with_descriptions(pricing_data["features"])
        
        pricings.append(
            PricingResponse(
                id=pricing_data["id"],
                name=pricing_data["name"],
                activation=pricing_data["activation"],
                expiry=pricing_data["expiry"],
                status=pricing_data["status"],
                features=enriched_features,
                currency=pricing_data["currency"],
                pricing_details=pricing_data["pricing_details"],
                description=pricing_data["description"],
                is_highlighted=pricing_data["is_highlighted"],
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

