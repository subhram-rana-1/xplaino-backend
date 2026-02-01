"""API routes for subscription management (frontend-facing)."""

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
)
from app.services.paddle_service import (
    get_user_active_subscription,
    get_customer_by_email,
    get_subscription_by_paddle_id,
)
from app.services.paddle_api_client import paddle_api_client, PaddleAPIError

logger = structlog.get_logger()

router = APIRouter(prefix="/api/subscription", tags=["Subscription"])


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
    db: Session = Depends(get_db)
):
    """
    Get user's active subscription status.
    
    This endpoint is used by your frontend application to check if a user
    has an active subscription and should have premium access.
    """
    subscription_data = get_user_active_subscription(db, user_id)
    
    if not subscription_data:
        return GetUserSubscriptionResponse(
            has_active_subscription=False,
            subscription=None,
            customer=None
        )
    
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
        has_active_subscription=True,
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
    description="Cancel a subscription. By default, cancellation takes effect at end of billing period."
)
async def cancel_subscription(
    subscription_id: str,
    body: CancelSubscriptionRequest,
    db: Session = Depends(get_db)
):
    """
    Cancel a subscription.
    
    - effective_from="next_billing_period": Cancel at end of current billing period (default)
    - effective_from="immediately": Cancel immediately and stop billing
    
    The actual cancellation is processed by Paddle, and a webhook will update your database.
    """
    logger.info(
        "Cancel subscription request",
        subscription_id=subscription_id,
        effective_from=body.effective_from.value
    )
    
    # Validate subscription exists in our DB
    _validate_subscription_ownership(db, subscription_id)
    
    try:
        # Call Paddle API to cancel
        paddle_response = await paddle_api_client.cancel_subscription(
            subscription_id=subscription_id,
            effective_from=body.effective_from.value
        )
        
        return SubscriptionActionResponse(
            success=True,
            paddle_subscription_id=subscription_id,
            status=paddle_response.get("status", "unknown"),
            scheduled_change=_extract_scheduled_change(paddle_response),
            message=f"Subscription will be cancelled {body.effective_from.value.replace('_', ' ')}"
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
    summary="Update subscription (upgrade/downgrade)",
    description="Update subscription items to upgrade or downgrade the plan."
)
async def update_subscription(
    subscription_id: str,
    body: UpdateSubscriptionRequest,
    db: Session = Depends(get_db)
):
    """
    Update a subscription (upgrade or downgrade).
    
    Send the complete list of items that should be on the subscription.
    Proration is calculated based on the proration_billing_mode.
    
    The update is processed by Paddle, and a webhook will update your database.
    """
    logger.info(
        "Update subscription request",
        subscription_id=subscription_id,
        items=[item.model_dump() for item in body.items],
        proration_billing_mode=body.proration_billing_mode.value
    )
    
    # Validate subscription exists in our DB
    _validate_subscription_ownership(db, subscription_id)
    
    try:
        # Convert items to Paddle format
        paddle_items = [
            {"price_id": item.price_id, "quantity": item.quantity}
            for item in body.items
        ]
        
        # Call Paddle API to update
        paddle_response = await paddle_api_client.update_subscription(
            subscription_id=subscription_id,
            items=paddle_items,
            proration_billing_mode=body.proration_billing_mode.value
        )
        
        return SubscriptionActionResponse(
            success=True,
            paddle_subscription_id=subscription_id,
            status=paddle_response.get("status", "unknown"),
            scheduled_change=_extract_scheduled_change(paddle_response),
            message="Subscription updated successfully"
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
    db: Session = Depends(get_db)
):
    """
    Pause a subscription.
    
    - effective_from="next_billing_period": Pause at end of current billing period (default)
    - effective_from="immediately": Pause immediately
    - resume_at: Optional datetime to automatically resume the subscription
    
    The pause is processed by Paddle, and a webhook will update your database.
    """
    logger.info(
        "Pause subscription request",
        subscription_id=subscription_id,
        effective_from=body.effective_from.value,
        resume_at=body.resume_at
    )
    
    # Validate subscription exists in our DB
    _validate_subscription_ownership(db, subscription_id)
    
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
    db: Session = Depends(get_db)
):
    """
    Resume a paused subscription.
    
    - effective_from="immediately": Resume immediately (default)
    - effective_from="next_billing_period": Resume at next billing period
    
    The resume is processed by Paddle, and a webhook will update your database.
    """
    logger.info(
        "Resume subscription request",
        subscription_id=subscription_id,
        effective_from=body.effective_from.value
    )
    
    # Validate subscription exists in our DB
    _validate_subscription_ownership(db, subscription_id)
    
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
    logger.info(
        "Preview subscription update request",
        subscription_id=subscription_id,
        items=[item.model_dump() for item in body.items]
    )
    
    # Validate subscription exists in our DB
    _validate_subscription_ownership(db, subscription_id)
    
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
