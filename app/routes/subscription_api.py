"""API routes for subscription management (frontend-facing)."""

from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import structlog

from app.database.connection import get_db
from app.models import (
    GetUserSubscriptionResponse,
    PaddleSubscriptionResponse,
    PaddleCustomerResponse,
    CancelSubscriptionRequest,
    UpdateSubscriptionRequest,
    PauseSubscriptionRequest,
    ResumeSubscriptionRequest,
    SubscriptionActionResponse,
    ScheduledChangeInfo,
    PreviewSubscriptionUpdateRequest,
    PreviewSubscriptionUpdateResponse,
    EffectiveFrom,
    ProrationBillingMode,
)
from app.services.paddle_service import (
    get_user_active_subscription,
    get_customer_by_email,
    get_subscription_by_paddle_id,
    update_subscription_cancellation_info,
)
from app.services.paddle_api_client import paddle_api_client, PaddleAPIError
from app.services.auth_middleware import authenticate
from app.services.database_service import get_user_id_by_auth_vendor_id

logger = structlog.get_logger()

router = APIRouter(prefix="/api/subscription", tags=["Subscription"])


def _get_user_id_from_auth_context(db: Session, auth_context: dict) -> str:
    """
    Extract user_id from authentication context.
    
    For authenticated users, retrieves user_id from session data.
    For unauthenticated users, returns the unauthenticated_user_id.
    """
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
        logger.debug(
            "_get_user_id_from_auth_context - Authenticated user",
            auth_vendor_id=auth_vendor_id,
            resolved_user_id=user_id
        )
        return user_id
    else:
        unauthenticated_user_id = auth_context.get("unauthenticated_user_id")
        logger.debug(
            "_get_user_id_from_auth_context - Unauthenticated user",
            unauthenticated_user_id=unauthenticated_user_id
        )
        return unauthenticated_user_id


def _validate_subscription_ownership(db: Session, subscription_id: str, user_id: Optional[str] = None):
    """
    Validate that a subscription exists and optionally belongs to the user.
    
    Returns the subscription data if valid.
    Raises HTTPException if not found or not owned by user.
    """
    subscription = get_subscription_by_paddle_id(db, subscription_id)
    
    if not subscription:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SUB_001",
                "error_message": "Subscription not found"
            }
        )
    
    if user_id and subscription.get("user_id") != user_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "SUB_002",
                "error_message": "You do not have permission to manage this subscription"
            }
        )
    
    return subscription


def _extract_scheduled_change(paddle_data: dict) -> Optional[ScheduledChangeInfo]:
    """Extract scheduled change info from Paddle response."""
    scheduled_change = paddle_data.get("scheduled_change")
    if not scheduled_change:
        return None
    
    return ScheduledChangeInfo(
        action=scheduled_change.get("action", "unknown"),
        effective_at=scheduled_change.get("effective_at", ""),
        resume_at=scheduled_change.get("resume_at")
    )


@router.get(
    "/{user_id}",
    response_model=GetUserSubscriptionResponse,
    status_code=200,
    summary="Get user subscription status",
    description="Check if a user has an active Paddle subscription. Used by frontend dashboard."
)
async def get_user_subscription_status(
    user_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """
    Get user's active subscription status.
    
    This endpoint is used by your frontend application to check if a user
    has an active subscription and should have premium access.
    """
    # DEBUG: Log incoming request details
    logger.info(
        "get_user_subscription_status - Request received",
        path_user_id=user_id,
        path_user_id_type=type(user_id).__name__,
        is_authenticated=auth_context.get("authenticated"),
        auth_context_keys=list(auth_context.keys())
    )
    
    # DEBUG: Log auth_context details
    if auth_context.get("authenticated"):
        session_data = auth_context.get("session_data", {})
        logger.info(
            "get_user_subscription_status - Authenticated user details",
            auth_vendor_id=session_data.get("auth_vendor_id"),
            session_data_keys=list(session_data.keys()) if session_data else None
        )
    else:
        logger.info(
            "get_user_subscription_status - Unauthenticated user details",
            unauthenticated_user_id=auth_context.get("unauthenticated_user_id")
        )
    
    # Validate that authenticated user can only access their own subscription
    auth_user_id = _get_user_id_from_auth_context(db, auth_context)
    
    # DEBUG: Log the comparison
    logger.info(
        "get_user_subscription_status - User ID comparison",
        path_user_id=user_id,
        auth_user_id=auth_user_id,
        path_user_id_type=type(user_id).__name__,
        auth_user_id_type=type(auth_user_id).__name__ if auth_user_id else None,
        ids_match=(user_id == auth_user_id)
    )
    
    if user_id != auth_user_id:
        logger.warning(
            "get_user_subscription_status - Access denied: user_id mismatch",
            path_user_id=user_id,
            auth_user_id=auth_user_id
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "SUB_002",
                "error_message": "Cannot access another user's subscription"
            }
        )
    
    subscription_data = get_user_active_subscription(db, user_id)
    
    if not subscription_data:
        return GetUserSubscriptionResponse(
            has_active_subscription=False,
            subscription=None,
            customer=None
        )
    
    # Check if subscription billing period has expired
    is_expired = False
    billing_period_ends_at = subscription_data.get("current_billing_period_ends_at")
    if billing_period_ends_at:
        # Parse the ISO format datetime string
        if isinstance(billing_period_ends_at, str):
            ends_at = datetime.fromisoformat(billing_period_ends_at.replace('Z', '+00:00'))
        else:
            ends_at = billing_period_ends_at
        
        # Ensure timezone awareness
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        
        current_time = datetime.now(timezone.utc)
        is_expired = ends_at < current_time
    
    # Build subscription response
    subscription = PaddleSubscriptionResponse(
        id=subscription_data["id"],
        paddle_subscription_id=subscription_data["paddle_subscription_id"],
        paddle_customer_id=subscription_data["paddle_customer_id"],
        user_id=subscription_data["user_id"],
        status=subscription_data["status"],
        currency_code=subscription_data["currency_code"],
        billing_cycle_interval=subscription_data["billing_cycle_interval"],
        billing_cycle_frequency=subscription_data["billing_cycle_frequency"],
        current_billing_period_starts_at=subscription_data.get("current_billing_period_starts_at"),
        current_billing_period_ends_at=subscription_data.get("current_billing_period_ends_at"),
        next_billed_at=subscription_data.get("next_billed_at"),
        items=subscription_data.get("items", []),
        created_at=subscription_data.get("created_at", ""),
        updated_at=subscription_data.get("updated_at", "")
    )
    
    # Get customer info
    customer_data = get_customer_by_email(db, subscription_data.get("customer_email", ""))
    customer = None
    if customer_data:
        customer = PaddleCustomerResponse(
            id=customer_data["id"],
            paddle_customer_id=customer_data["paddle_customer_id"],
            user_id=customer_data.get("user_id"),
            email=customer_data["email"],
            name=customer_data.get("name"),
            locale=customer_data.get("locale"),
            status=customer_data["status"],
            created_at=customer_data.get("created_at", ""),
            updated_at=customer_data.get("updated_at", "")
        )
    
    return GetUserSubscriptionResponse(
        has_active_subscription=not is_expired,
        subscription=subscription,
        customer=customer
    )


# =====================================================
# SUBSCRIPTION MANAGEMENT ENDPOINTS
# =====================================================

@router.post(
    "/{subscription_id}/cancel",
    response_model=SubscriptionActionResponse,
    status_code=200,
    summary="Cancel subscription",
    description="Cancel a subscription. Cancellation takes effect at the end of the current billing period. Requires cancellation reasons."
)
async def cancel_subscription(
    subscription_id: str,
    body: CancelSubscriptionRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """
    Cancel a subscription.
    
    Cancellation always takes effect at the end of the current billing period.
    The actual cancellation is processed by Paddle, and a webhook will update your database.
    """
    # Always use NEXT_BILLING_PERIOD - user cannot choose immediate cancellation
    effective_from = EffectiveFrom.NEXT_BILLING_PERIOD
    
    # Extract authenticated user's ID
    user_id = _get_user_id_from_auth_context(db, auth_context)
    
    logger.info(
        "Cancel subscription request",
        subscription_id=subscription_id,
        effective_from=effective_from.value,
        cancellation_reasons=body.cancellation_info.reasons,
        user_id=user_id
    )
    
    # Validate subscription exists and belongs to the authenticated user
    _validate_subscription_ownership(db, subscription_id, user_id)
    
    try:
        # Call Paddle API to cancel
        paddle_response = await paddle_api_client.cancel_subscription(
            subscription_id=subscription_id,
            effective_from=effective_from.value
        )
        
        # Save cancellation info to database
        update_subscription_cancellation_info(
            db=db,
            paddle_subscription_id=subscription_id,
            cancellation_info=body.cancellation_info.model_dump()
        )
        
        return SubscriptionActionResponse(
            success=True,
            paddle_subscription_id=subscription_id,
            status=paddle_response.get("status", "unknown"),
            scheduled_change=_extract_scheduled_change(paddle_response),
            message="Subscription will be cancelled at end of billing period"
        )
        
    except PaddleAPIError as e:
        logger.error(
            "Paddle API error cancelling subscription",
            subscription_id=subscription_id,
            error_code=e.error_code,
            error_message=e.message
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "error_code": f"PADDLE_{e.error_code.upper()}",
                "error_message": e.message
            }
        )


@router.patch(
    "/{subscription_id}/update",
    response_model=SubscriptionActionResponse,
    status_code=200,
    summary="Update subscription (upgrade only)",
    description="Update subscription items to upgrade the plan. Downgrades are not allowed. Prorated amount is charged immediately."
)
async def update_subscription(
    subscription_id: str,
    body: UpdateSubscriptionRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """
    Update a subscription (upgrade only).
    
    Send the complete list of items that should be on the subscription.
    Proration is calculated immediately (prorated amount charged right away).
    
    Note: Downgrades are not allowed. Only upgrades to higher-priced plans are permitted.
    
    The update is processed by Paddle, and a webhook will update your database.
    """
    # Always use PRORATED_IMMEDIATELY - charge prorated difference now
    proration_billing_mode = ProrationBillingMode.PRORATED_IMMEDIATELY
    
    # Extract authenticated user's ID
    user_id = _get_user_id_from_auth_context(db, auth_context)
    
    logger.info(
        "Update subscription request",
        subscription_id=subscription_id,
        items=[item.model_dump() for item in body.items],
        proration_billing_mode=proration_billing_mode.value,
        user_id=user_id
    )
    
    # Validate subscription exists and belongs to the authenticated user
    _validate_subscription_ownership(db, subscription_id, user_id)
    
    # Convert items to Paddle format
    paddle_items = [
        {"price_id": item.price_id, "quantity": item.quantity}
        for item in body.items
    ]
    
    try:
        # Preview the update to check if it's a downgrade
        preview = await paddle_api_client.preview_subscription_update(
            subscription_id=subscription_id,
            items=paddle_items,
            proration_billing_mode=proration_billing_mode.value
        )
        
        # Check if this is a downgrade by examining the immediate transaction
        # If immediate_transaction total is <= 0, it's a downgrade (credit/refund)
        immediate_transaction = preview.get("immediate_transaction", {})
        details = immediate_transaction.get("details", {})
        totals = details.get("totals", {})
        grand_total = totals.get("grand_total", "0")
        
        # Convert to integer for comparison (Paddle returns amounts as strings in minor units)
        grand_total_amount = int(grand_total) if grand_total else 0
        
        if grand_total_amount <= 0:
            logger.warning(
                "Downgrade attempt blocked",
                subscription_id=subscription_id,
                grand_total=grand_total,
                user_id=user_id
            )
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "DOWNGRADE_NOT_ALLOWED",
                    "error_message": "Subscription downgrades are not allowed. Please contact support if you need to change your plan."
                }
            )
        
        # Proceed with the upgrade
        paddle_response = await paddle_api_client.update_subscription(
            subscription_id=subscription_id,
            items=paddle_items,
            proration_billing_mode=proration_billing_mode.value
        )
        
        return SubscriptionActionResponse(
            success=True,
            paddle_subscription_id=subscription_id,
            status=paddle_response.get("status", "unknown"),
            scheduled_change=_extract_scheduled_change(paddle_response),
            message="Subscription upgraded successfully"
        )
        
    except PaddleAPIError as e:
        logger.error(
            "Paddle API error updating subscription",
            subscription_id=subscription_id,
            error_code=e.error_code,
            error_message=e.message
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "error_code": f"PADDLE_{e.error_code.upper()}",
                "error_message": e.message
            }
        )


@router.post(
    "/{subscription_id}/pause",
    response_model=SubscriptionActionResponse,
    status_code=200,
    summary="Pause subscription",
    description="Pause a subscription. Billing stops until the subscription is resumed."
)
async def pause_subscription(
    subscription_id: str,
    body: PauseSubscriptionRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """
    Pause a subscription.
    
    - effective_from="next_billing_period": Pause at end of current billing period (default)
    - effective_from="immediately": Pause immediately
    - resume_at: Optional datetime to automatically resume the subscription
    
    The pause is processed by Paddle, and a webhook will update your database.
    """
    # Extract authenticated user's ID
    user_id = _get_user_id_from_auth_context(db, auth_context)
    
    logger.info(
        "Pause subscription request",
        subscription_id=subscription_id,
        effective_from=body.effective_from.value,
        resume_at=body.resume_at,
        user_id=user_id
    )
    
    # Validate subscription exists and belongs to the authenticated user
    _validate_subscription_ownership(db, subscription_id, user_id)
    
    try:
        # Call Paddle API to pause
        paddle_response = await paddle_api_client.pause_subscription(
            subscription_id=subscription_id,
            effective_from=body.effective_from.value,
            resume_at=body.resume_at
        )
        
        message = f"Subscription will be paused {body.effective_from.value.replace('_', ' ')}"
        if body.resume_at:
            message += f", and will auto-resume at {body.resume_at}"
        
        return SubscriptionActionResponse(
            success=True,
            paddle_subscription_id=subscription_id,
            status=paddle_response.get("status", "unknown"),
            scheduled_change=_extract_scheduled_change(paddle_response),
            message=message
        )
        
    except PaddleAPIError as e:
        logger.error(
            "Paddle API error pausing subscription",
            subscription_id=subscription_id,
            error_code=e.error_code,
            error_message=e.message
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "error_code": f"PADDLE_{e.error_code.upper()}",
                "error_message": e.message
            }
        )


@router.post(
    "/{subscription_id}/resume",
    response_model=SubscriptionActionResponse,
    status_code=200,
    summary="Resume subscription",
    description="Resume a paused subscription."
)
async def resume_subscription(
    subscription_id: str,
    body: ResumeSubscriptionRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """
    Resume a paused subscription.
    
    - effective_from="immediately": Resume immediately (default)
    - effective_from="next_billing_period": Resume at next billing period
    
    The resume is processed by Paddle, and a webhook will update your database.
    """
    # Extract authenticated user's ID
    user_id = _get_user_id_from_auth_context(db, auth_context)
    
    logger.info(
        "Resume subscription request",
        subscription_id=subscription_id,
        effective_from=body.effective_from.value,
        user_id=user_id
    )
    
    # Validate subscription exists and belongs to the authenticated user
    _validate_subscription_ownership(db, subscription_id, user_id)
    
    try:
        # Call Paddle API to resume
        paddle_response = await paddle_api_client.resume_subscription(
            subscription_id=subscription_id,
            effective_from=body.effective_from.value
        )
        
        return SubscriptionActionResponse(
            success=True,
            paddle_subscription_id=subscription_id,
            status=paddle_response.get("status", "unknown"),
            scheduled_change=_extract_scheduled_change(paddle_response),
            message=f"Subscription resumed {body.effective_from.value.replace('_', ' ')}"
        )
        
    except PaddleAPIError as e:
        logger.error(
            "Paddle API error resuming subscription",
            subscription_id=subscription_id,
            error_code=e.error_code,
            error_message=e.message
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "error_code": f"PADDLE_{e.error_code.upper()}",
                "error_message": e.message
            }
        )


@router.post(
    "/{subscription_id}/preview-update",
    response_model=PreviewSubscriptionUpdateResponse,
    status_code=200,
    summary="Preview subscription update",
    description="Preview a subscription update without applying changes. See prorated amounts."
)
async def preview_subscription_update(
    subscription_id: str,
    body: PreviewSubscriptionUpdateRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """
    Preview a subscription update without applying changes.
    
    Returns information about:
    - immediate_transaction: Any charge that would be created immediately
    - next_transaction: Preview of the next scheduled transaction
    - update_summary: Summary of prorated credits and charges
    
    Use this to show users what they'll be charged before confirming an upgrade/downgrade.
    """
    # Extract authenticated user's ID
    user_id = _get_user_id_from_auth_context(db, auth_context)
    
    logger.info(
        "Preview subscription update request",
        subscription_id=subscription_id,
        items=[item.model_dump() for item in body.items],
        user_id=user_id
    )
    
    # Validate subscription exists and belongs to the authenticated user
    _validate_subscription_ownership(db, subscription_id, user_id)
    
    try:
        # Convert items to Paddle format
        paddle_items = [
            {"price_id": item.price_id, "quantity": item.quantity}
            for item in body.items
        ]
        
        # Call Paddle API to preview
        paddle_response = await paddle_api_client.preview_subscription_update(
            subscription_id=subscription_id,
            items=paddle_items,
            proration_billing_mode=body.proration_billing_mode.value
        )
        
        return PreviewSubscriptionUpdateResponse(
            paddle_subscription_id=subscription_id,
            immediate_transaction=paddle_response.get("immediate_transaction"),
            next_transaction=paddle_response.get("next_transaction"),
            update_summary=paddle_response.get("update_summary")
        )
        
    except PaddleAPIError as e:
        logger.error(
            "Paddle API error previewing subscription update",
            subscription_id=subscription_id,
            error_code=e.error_code,
            error_message=e.message
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "error_code": f"PADDLE_{e.error_code.upper()}",
                "error_message": e.message
            }
        )
