"""API routes for subscription management (admin)."""

from fastapi import APIRouter, HTTPException, Depends, Query, Request, Response
from sqlalchemy.orm import Session
import structlog

from app.models import AdminSubscriptionResponse, GetAllSubscriptionsResponse
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id,
    get_all_subscriptions,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/admin/subscriptions", tags=["Admin Subscriptions"])


@router.get(
    "",
    response_model=GetAllSubscriptionsResponse,
    status_code=200,
    summary="Get all subscriptions (Admin only)",
    description=(
        "Returns a paginated list of all Paddle subscriptions with customer email. "
        "Only ADMIN and SUPER_ADMIN users can access this endpoint."
    ),
)
async def get_all_subscriptions_endpoint(
    request: Request,
    response: Response,
    status: str = Query(default=None, description="Filter by status (ACTIVE, CANCELED, PAST_DUE, PAUSED, TRIALING)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Number of subscriptions to return (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Get all subscriptions. Admin only."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required",
            },
        )

    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data",
            },
        )

    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID",
            },
        )

    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found",
            },
        )

    user_role = get_user_role_by_user_id(db, user_id)
    if user_role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PERMISSION_DENIED",
                "error_message": "Only ADMIN and SUPER_ADMIN users can access this endpoint",
            },
        )

    subs_data, total_count = get_all_subscriptions(db, status=status, offset=offset, limit=limit)

    subscriptions = [
        AdminSubscriptionResponse(
            id=s["id"],
            paddle_subscription_id=s["paddle_subscription_id"],
            paddle_customer_id=s["paddle_customer_id"],
            customer_email=s.get("customer_email"),
            user_id=s.get("user_id"),
            status=s["status"],
            currency_code=s["currency_code"],
            billing_cycle_interval=s["billing_cycle_interval"],
            billing_cycle_frequency=s["billing_cycle_frequency"],
            current_billing_period_starts_at=str(s["current_billing_period_starts_at"]) if s.get("current_billing_period_starts_at") else None,
            current_billing_period_ends_at=str(s["current_billing_period_ends_at"]) if s.get("current_billing_period_ends_at") else None,
            next_billed_at=str(s["next_billed_at"]) if s.get("next_billed_at") else None,
            started_at=str(s["started_at"]) if s.get("started_at") else None,
            paused_at=str(s["paused_at"]) if s.get("paused_at") else None,
            canceled_at=str(s["canceled_at"]) if s.get("canceled_at") else None,
            items=s["items"] if isinstance(s["items"], list) else [],
            created_at=str(s["created_at"]),
            updated_at=str(s["updated_at"]),
        )
        for s in subs_data
    ]

    has_next = (offset + limit) < total_count

    logger.info(
        "Retrieved all subscriptions successfully (admin)",
        requesting_user_id=user_id,
        subscription_count=len(subscriptions),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next,
    )

    return GetAllSubscriptionsResponse(
        subscriptions=subscriptions,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next,
    )
