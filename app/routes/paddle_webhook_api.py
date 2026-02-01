"""API routes for Paddle webhook handling."""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Depends, Header
from sqlalchemy.orm import Session
import structlog

from app.config import settings
from app.database.connection import get_db
from app.models import (
    PaddleWebhookResponse,
    PaddleWebhookEventType,
    PaddleWebhookProcessingStatus,
)
from app.services.paddle_service import (
    record_webhook_event,
    update_webhook_event_status,
    is_event_already_processed,
    process_customer_event,
    process_subscription_event,
    process_transaction_event,
    process_adjustment_event,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/webhooks", tags=["Paddle Webhooks"])


def verify_paddle_signature(
    request_body: bytes,
    paddle_signature: str,
    webhook_secret: str
) -> bool:
    """
    Verify Paddle webhook signature.
    
    Paddle uses HMAC-SHA256 to sign webhook payloads.
    The signature format is: ts=<timestamp>;h1=<hash>
    
    Args:
        request_body: Raw request body bytes
        paddle_signature: Paddle-Signature header value
        webhook_secret: Webhook secret key from Paddle
        
    Returns:
        True if signature is valid, False otherwise
    """
    if not paddle_signature or not webhook_secret:
        return False
    
    try:
        # Parse the signature header
        # Format: ts=<timestamp>;h1=<hash>
        parts = {}
        for part in paddle_signature.split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                parts[key] = value
        
        timestamp = parts.get("ts")
        signature = parts.get("h1")
        
        if not timestamp or not signature:
            logger.warning(
                "Invalid Paddle signature format",
                paddle_signature=paddle_signature
            )
            return False
        
        # Build the signed payload: timestamp:request_body
        signed_payload = f"{timestamp}:{request_body.decode('utf-8')}"
        
        # Calculate expected signature
        expected_signature = hmac.new(
            webhook_secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures (constant-time comparison)
        is_valid = hmac.compare_digest(expected_signature, signature)
        
        if not is_valid:
            logger.warning(
                "Paddle signature verification failed",
                expected=expected_signature[:16] + "...",
                received=signature[:16] + "..."
            )
        
        return is_valid
        
    except Exception as e:
        logger.error(
            "Error verifying Paddle signature",
            error=str(e)
        )
        return False


@router.post(
    "/paddle",
    response_model=PaddleWebhookResponse,
    status_code=200,
    summary="Handle Paddle webhooks",
    description="Receives and processes webhooks from Paddle for subscription and transaction events."
)
async def handle_paddle_webhook(
    request: Request,
    db: Session = Depends(get_db),
    paddle_signature: Optional[str] = Header(None, alias="Paddle-Signature")
):
    """
    Handle incoming Paddle webhook events.
    
    This endpoint:
    1. Verifies the webhook signature
    2. Checks for duplicate events (idempotency)
    3. Processes the event based on type
    4. Returns acknowledgment to Paddle
    """
    # Get raw request body for signature verification
    body = await request.body()
    
    # Verify signature (skip in development if secret not configured)
    if settings.paddle_webhook_secret:
        if not verify_paddle_signature(body, paddle_signature or "", settings.paddle_webhook_secret):
            logger.error(
                "Paddle webhook signature verification failed",
                has_signature=bool(paddle_signature)
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "error_code": "WEBHOOK_001",
                    "error_message": "Invalid webhook signature"
                }
            )
    else:
        logger.warning(
            "Paddle webhook secret not configured - skipping signature verification",
            environment=settings.paddle_environment
        )
    
    # Parse request body
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse webhook payload", error=str(e))
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "WEBHOOK_002",
                "error_message": "Invalid JSON payload"
            }
        )
    
    # Extract event details
    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    occurred_at = payload.get("occurred_at")
    data = payload.get("data", {})
    
    if not event_id or not event_type:
        logger.error(
            "Missing required webhook fields",
            has_event_id=bool(event_id),
            has_event_type=bool(event_type)
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "WEBHOOK_003",
                "error_message": "Missing event_id or event_type"
            }
        )
    
    logger.info(
        "Received Paddle webhook",
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at
    )
    
    # Check for duplicate events (idempotency)
    if is_event_already_processed(db, event_id):
        logger.info(
            "Duplicate webhook event - already processed",
            event_id=event_id,
            event_type=event_type
        )
        return PaddleWebhookResponse(
            status="acknowledged",
            event_id=event_id,
            message="Event already processed"
        )
    
    # Record the webhook event
    webhook_event = record_webhook_event(
        db=db,
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=payload
    )
    
    # Process the event based on type
    try:
        update_webhook_event_status(
            db, event_id, PaddleWebhookProcessingStatus.PROCESSING
        )
        
        # Route to appropriate handler
        if event_type.startswith("customer."):
            process_customer_event(db, event_type, data)
        elif event_type.startswith("subscription."):
            process_subscription_event(db, event_type, data)
        elif event_type.startswith("transaction."):
            process_transaction_event(db, event_type, data)
        elif event_type.startswith("adjustment."):
            process_adjustment_event(db, event_type, data)
        else:
            logger.info(
                "Unhandled webhook event type - acknowledging without processing",
                event_type=event_type
            )
        
        # Mark as processed
        update_webhook_event_status(
            db, event_id, PaddleWebhookProcessingStatus.PROCESSED
        )
        
        logger.info(
            "Successfully processed Paddle webhook",
            event_id=event_id,
            event_type=event_type
        )
        
        return PaddleWebhookResponse(
            status="processed",
            event_id=event_id,
            message=f"Successfully processed {event_type}"
        )
        
    except Exception as e:
        logger.error(
            "Error processing Paddle webhook",
            event_id=event_id,
            event_type=event_type,
            error=str(e)
        )
        
        # Mark as failed
        update_webhook_event_status(
            db, event_id, PaddleWebhookProcessingStatus.FAILED, str(e)
        )
        
        # Still return 200 to acknowledge receipt (Paddle will retry on non-2xx)
        # We've recorded the failure and can investigate/retry later
        return PaddleWebhookResponse(
            status="error",
            event_id=event_id,
            message=f"Error processing event: {str(e)}"
        )


@router.get(
    "/paddle/health",
    response_model=dict,
    status_code=200,
    summary="Webhook health check",
    description="Health check endpoint for Paddle webhook configuration."
)
async def webhook_health():
    """Health check for webhook endpoint."""
    return {
        "status": "healthy",
        "webhook_secret_configured": bool(settings.paddle_webhook_secret),
        "environment": settings.paddle_environment
    }
