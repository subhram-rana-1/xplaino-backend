"""Paddle service for webhook event processing and database operations."""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session
from sqlalchemy import text
import structlog

from app.models import (
    PaddleWebhookProcessingStatus,
    PaddleSubscriptionStatus,
    PaddleTransactionStatus,
    PaddleCustomerStatus,
)

logger = structlog.get_logger()


# =====================================================
# WEBHOOK EVENT FUNCTIONS
# =====================================================

def is_event_already_processed(db: Session, event_id: str) -> bool:
    """Check if a webhook event has already been processed (idempotency check)."""
    result = db.execute(
        text("""
            SELECT id, processing_status 
            FROM paddle_webhook_event 
            WHERE paddle_event_id = :event_id
        """),
        {"event_id": event_id}
    ).fetchone()
    
    return result is not None


def record_webhook_event(
    db: Session,
    event_id: str,
    event_type: str,
    occurred_at: str,
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Record a new webhook event."""
    record_id = str(uuid.uuid4())
    
    # Parse occurred_at timestamp
    try:
        occurred_at_dt = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        occurred_at_dt = datetime.now(timezone.utc)
    
    db.execute(
        text("""
            INSERT INTO paddle_webhook_event 
            (id, paddle_event_id, event_type, occurred_at, payload, processing_status)
            VALUES (:id, :event_id, :event_type, :occurred_at, :payload, :status)
        """),
        {
            "id": record_id,
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at_dt,
            "payload": json.dumps(payload),
            "status": PaddleWebhookProcessingStatus.RECEIVED.value
        }
    )
    db.commit()
    
    logger.info(
        "Recorded webhook event",
        record_id=record_id,
        event_id=event_id,
        event_type=event_type
    )
    
    return {"id": record_id, "paddle_event_id": event_id}


def update_webhook_event_status(
    db: Session,
    event_id: str,
    status: PaddleWebhookProcessingStatus,
    error: Optional[str] = None
) -> None:
    """Update webhook event processing status."""
    params = {
        "event_id": event_id,
        "status": status.value,
        "error": error,
    }
    
    if status == PaddleWebhookProcessingStatus.PROCESSED:
        db.execute(
            text("""
                UPDATE paddle_webhook_event 
                SET processing_status = :status, 
                    processed_at = CURRENT_TIMESTAMP,
                    processing_error = :error
                WHERE paddle_event_id = :event_id
            """),
            params
        )
    else:
        db.execute(
            text("""
                UPDATE paddle_webhook_event 
                SET processing_status = :status,
                    processing_error = :error
                WHERE paddle_event_id = :event_id
            """),
            params
        )
    db.commit()


# =====================================================
# CUSTOMER FUNCTIONS
# =====================================================

def process_customer_event(db: Session, event_type: str, data: Dict[str, Any]) -> None:
    """Process customer-related webhook events."""
    paddle_customer_id = data.get("id")
    
    if not paddle_customer_id:
        logger.warning("Customer event missing customer ID", event_type=event_type)
        return
    
    logger.info(
        "Processing customer event",
        event_type=event_type,
        paddle_customer_id=paddle_customer_id
    )
    
    if event_type in ["customer.created", "customer.imported"]:
        upsert_customer(db, data)
    elif event_type == "customer.updated":
        upsert_customer(db, data)


def upsert_customer(db: Session, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a Paddle customer record."""
    paddle_customer_id = data.get("id")
    email = data.get("email", "")
    name = data.get("name")
    locale = data.get("locale")
    marketing_consent = data.get("marketing_consent", False)
    custom_data = data.get("custom_data")
    status = data.get("status", "active").upper()
    
    # Check if customer exists
    existing = db.execute(
        text("SELECT id FROM paddle_customer WHERE paddle_customer_id = :paddle_id"),
        {"paddle_id": paddle_customer_id}
    ).fetchone()
    
    if existing:
        # Update existing customer
        db.execute(
            text("""
                UPDATE paddle_customer 
                SET email = :email,
                    name = :name,
                    locale = :locale,
                    marketing_consent = :marketing_consent,
                    custom_data = :custom_data,
                    status = :status,
                    updated_at = CURRENT_TIMESTAMP
                WHERE paddle_customer_id = :paddle_id
            """),
            {
                "paddle_id": paddle_customer_id,
                "email": email,
                "name": name,
                "locale": locale,
                "marketing_consent": marketing_consent,
                "custom_data": json.dumps(custom_data) if custom_data else None,
                "status": status
            }
        )
        record_id = existing[0]
        logger.info("Updated customer", paddle_customer_id=paddle_customer_id)
    else:
        # Create new customer
        record_id = str(uuid.uuid4())
        
        # Try to link to existing user by email
        user_result = db.execute(
            text("""
                SELECT u.id FROM user u
                JOIN google_user_auth_info g ON g.user_id = u.id
                WHERE g.email = :email
                LIMIT 1
            """),
            {"email": email}
        ).fetchone()
        user_id = user_result[0] if user_result else None
        
        db.execute(
            text("""
                INSERT INTO paddle_customer 
                (id, paddle_customer_id, user_id, email, name, locale, 
                 marketing_consent, custom_data, status)
                VALUES (:id, :paddle_id, :user_id, :email, :name, :locale,
                        :marketing_consent, :custom_data, :status)
            """),
            {
                "id": record_id,
                "paddle_id": paddle_customer_id,
                "user_id": user_id,
                "email": email,
                "name": name,
                "locale": locale,
                "marketing_consent": marketing_consent,
                "custom_data": json.dumps(custom_data) if custom_data else None,
                "status": status
            }
        )
        logger.info(
            "Created customer",
            paddle_customer_id=paddle_customer_id,
            linked_user_id=user_id
        )
    
    db.commit()
    return {"id": record_id, "paddle_customer_id": paddle_customer_id}


# =====================================================
# SUBSCRIPTION FUNCTIONS
# =====================================================

def process_subscription_event(db: Session, event_type: str, data: Dict[str, Any]) -> None:
    """Process subscription-related webhook events."""
    paddle_subscription_id = data.get("id")
    
    if not paddle_subscription_id:
        logger.warning("Subscription event missing subscription ID", event_type=event_type)
        return
    
    logger.info(
        "Processing subscription event",
        event_type=event_type,
        paddle_subscription_id=paddle_subscription_id
    )
    
    # Map Paddle status to our status enum
    status_map = {
        "active": PaddleSubscriptionStatus.ACTIVE.value,
        "canceled": PaddleSubscriptionStatus.CANCELED.value,
        "past_due": PaddleSubscriptionStatus.PAST_DUE.value,
        "paused": PaddleSubscriptionStatus.PAUSED.value,
        "trialing": PaddleSubscriptionStatus.TRIALING.value,
    }
    
    paddle_status = data.get("status", "active")
    status = status_map.get(paddle_status, PaddleSubscriptionStatus.ACTIVE.value)
    
    # Update status based on event type
    if event_type == "subscription.canceled":
        status = PaddleSubscriptionStatus.CANCELED.value
    elif event_type == "subscription.past_due":
        status = PaddleSubscriptionStatus.PAST_DUE.value
    elif event_type == "subscription.paused":
        status = PaddleSubscriptionStatus.PAUSED.value
    elif event_type == "subscription.trialing":
        status = PaddleSubscriptionStatus.TRIALING.value
    elif event_type in ["subscription.activated", "subscription.resumed"]:
        status = PaddleSubscriptionStatus.ACTIVE.value
    
    upsert_subscription(db, data, status)


def upsert_subscription(db: Session, data: Dict[str, Any], status: str) -> Dict[str, Any]:
    """Create or update a Paddle subscription record."""
    paddle_subscription_id = data.get("id")
    paddle_customer_id = data.get("customer_id")
    
    # Extract billing cycle info
    billing_cycle = data.get("billing_cycle", {})
    billing_cycle_interval = billing_cycle.get("interval", "month").upper()
    billing_cycle_frequency = billing_cycle.get("frequency", 1)
    
    # Extract billing period
    current_billing_period = data.get("current_billing_period", {})
    period_starts = current_billing_period.get("starts_at")
    period_ends = current_billing_period.get("ends_at")
    
    # Parse timestamps
    def parse_ts(ts_str):
        if not ts_str:
            return None
        try:
            return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
    
    period_starts_dt = parse_ts(period_starts)
    period_ends_dt = parse_ts(period_ends)
    next_billed_at_dt = parse_ts(data.get("next_billed_at"))
    paused_at_dt = parse_ts(data.get("paused_at"))
    canceled_at_dt = parse_ts(data.get("canceled_at"))
    started_at_dt = parse_ts(data.get("started_at"))
    first_billed_at_dt = parse_ts(data.get("first_billed_at"))
    
    # Items and other data
    items = data.get("items", [])
    scheduled_change = data.get("scheduled_change")
    custom_data = data.get("custom_data")
    currency_code = data.get("currency_code", "USD")
    
    # Check if subscription exists
    existing = db.execute(
        text("SELECT id FROM paddle_subscription WHERE paddle_subscription_id = :paddle_id"),
        {"paddle_id": paddle_subscription_id}
    ).fetchone()
    
    # Get user_id from customer record
    customer_result = db.execute(
        text("SELECT user_id FROM paddle_customer WHERE paddle_customer_id = :paddle_id"),
        {"paddle_id": paddle_customer_id}
    ).fetchone()
    user_id = customer_result[0] if customer_result else None
    
    if existing:
        # Update existing subscription
        db.execute(
            text("""
                UPDATE paddle_subscription 
                SET paddle_customer_id = :customer_id,
                    user_id = :user_id,
                    status = :status,
                    currency_code = :currency_code,
                    billing_cycle_interval = :billing_interval,
                    billing_cycle_frequency = :billing_frequency,
                    current_billing_period_starts_at = :period_starts,
                    current_billing_period_ends_at = :period_ends,
                    next_billed_at = :next_billed,
                    paused_at = :paused_at,
                    canceled_at = :canceled_at,
                    scheduled_change = :scheduled_change,
                    items = :items,
                    custom_data = :custom_data,
                    first_billed_at = :first_billed,
                    started_at = :started_at,
                    updated_at = CURRENT_TIMESTAMP
                WHERE paddle_subscription_id = :paddle_id
            """),
            {
                "paddle_id": paddle_subscription_id,
                "customer_id": paddle_customer_id,
                "user_id": user_id,
                "status": status,
                "currency_code": currency_code,
                "billing_interval": billing_cycle_interval,
                "billing_frequency": billing_cycle_frequency,
                "period_starts": period_starts_dt,
                "period_ends": period_ends_dt,
                "next_billed": next_billed_at_dt,
                "paused_at": paused_at_dt,
                "canceled_at": canceled_at_dt,
                "scheduled_change": json.dumps(scheduled_change) if scheduled_change else None,
                "items": json.dumps(items),
                "custom_data": json.dumps(custom_data) if custom_data else None,
                "first_billed": first_billed_at_dt,
                "started_at": started_at_dt
            }
        )
        record_id = existing[0]
        logger.info(
            "Updated subscription",
            paddle_subscription_id=paddle_subscription_id,
            status=status
        )
    else:
        # Create new subscription
        record_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO paddle_subscription 
                (id, paddle_subscription_id, paddle_customer_id, user_id, status,
                 currency_code, billing_cycle_interval, billing_cycle_frequency,
                 current_billing_period_starts_at, current_billing_period_ends_at,
                 next_billed_at, paused_at, canceled_at, scheduled_change, items,
                 custom_data, first_billed_at, started_at)
                VALUES (:id, :paddle_id, :customer_id, :user_id, :status,
                        :currency_code, :billing_interval, :billing_frequency,
                        :period_starts, :period_ends, :next_billed, :paused_at,
                        :canceled_at, :scheduled_change, :items, :custom_data,
                        :first_billed, :started_at)
            """),
            {
                "id": record_id,
                "paddle_id": paddle_subscription_id,
                "customer_id": paddle_customer_id,
                "user_id": user_id,
                "status": status,
                "currency_code": currency_code,
                "billing_interval": billing_cycle_interval,
                "billing_frequency": billing_cycle_frequency,
                "period_starts": period_starts_dt,
                "period_ends": period_ends_dt,
                "next_billed": next_billed_at_dt,
                "paused_at": paused_at_dt,
                "canceled_at": canceled_at_dt,
                "scheduled_change": json.dumps(scheduled_change) if scheduled_change else None,
                "items": json.dumps(items),
                "custom_data": json.dumps(custom_data) if custom_data else None,
                "first_billed": first_billed_at_dt,
                "started_at": started_at_dt
            }
        )
        logger.info(
            "Created subscription",
            paddle_subscription_id=paddle_subscription_id,
            status=status,
            user_id=user_id
        )
    
    db.commit()
    return {"id": record_id, "paddle_subscription_id": paddle_subscription_id}


# =====================================================
# TRANSACTION FUNCTIONS
# =====================================================

def process_transaction_event(db: Session, event_type: str, data: Dict[str, Any]) -> None:
    """Process transaction-related webhook events."""
    paddle_transaction_id = data.get("id")
    
    if not paddle_transaction_id:
        logger.warning("Transaction event missing transaction ID", event_type=event_type)
        return
    
    logger.info(
        "Processing transaction event",
        event_type=event_type,
        paddle_transaction_id=paddle_transaction_id
    )
    
    # Map Paddle status to our status enum
    status_map = {
        "draft": PaddleTransactionStatus.DRAFT.value,
        "ready": PaddleTransactionStatus.READY.value,
        "billed": PaddleTransactionStatus.BILLED.value,
        "paid": PaddleTransactionStatus.PAID.value,
        "completed": PaddleTransactionStatus.COMPLETED.value,
        "canceled": PaddleTransactionStatus.CANCELED.value,
        "past_due": PaddleTransactionStatus.PAST_DUE.value,
    }
    
    paddle_status = data.get("status", "draft")
    status = status_map.get(paddle_status, PaddleTransactionStatus.DRAFT.value)
    
    # Update status based on event type
    if event_type == "transaction.completed":
        status = PaddleTransactionStatus.COMPLETED.value
    elif event_type == "transaction.paid":
        status = PaddleTransactionStatus.PAID.value
    elif event_type == "transaction.billed":
        status = PaddleTransactionStatus.BILLED.value
    elif event_type == "transaction.canceled":
        status = PaddleTransactionStatus.CANCELED.value
    elif event_type == "transaction.past_due":
        status = PaddleTransactionStatus.PAST_DUE.value
    elif event_type == "transaction.ready":
        status = PaddleTransactionStatus.READY.value
    
    upsert_transaction(db, data, status)


def upsert_transaction(db: Session, data: Dict[str, Any], status: str) -> Dict[str, Any]:
    """Create or update a Paddle transaction record."""
    paddle_transaction_id = data.get("id")
    paddle_subscription_id = data.get("subscription_id")
    paddle_customer_id = data.get("customer_id")
    
    # Extract amounts from details
    details = data.get("details", {})
    totals = details.get("totals", {})
    
    # Get amounts (Paddle sends amounts as strings in minor units or as objects)
    def get_amount(amount_data):
        if isinstance(amount_data, dict):
            return amount_data.get("amount", "0")
        return str(amount_data) if amount_data else "0"
    
    subtotal = get_amount(totals.get("subtotal", "0"))
    tax = get_amount(totals.get("tax", "0"))
    total = get_amount(totals.get("total", "0"))
    grand_total = get_amount(totals.get("grand_total", total))
    discount_total = get_amount(totals.get("discount", "0"))
    
    # Parse billed_at timestamp
    billed_at_str = data.get("billed_at")
    billed_at_dt = None
    if billed_at_str:
        try:
            billed_at_dt = datetime.fromisoformat(billed_at_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    
    # Other fields
    origin = data.get("origin")
    currency_code = data.get("currency_code", "USD")
    items = data.get("items", [])
    payments = data.get("payments", [])
    invoice_id = data.get("invoice_id")
    invoice_number = data.get("invoice_number")
    custom_data = data.get("custom_data")
    
    # Check if transaction exists
    existing = db.execute(
        text("SELECT id FROM paddle_transaction WHERE paddle_transaction_id = :paddle_id"),
        {"paddle_id": paddle_transaction_id}
    ).fetchone()
    
    # Get user_id from customer record
    customer_result = db.execute(
        text("SELECT user_id FROM paddle_customer WHERE paddle_customer_id = :paddle_id"),
        {"paddle_id": paddle_customer_id}
    ).fetchone()
    user_id = customer_result[0] if customer_result else None
    
    if existing:
        # Update existing transaction
        db.execute(
            text("""
                UPDATE paddle_transaction 
                SET paddle_subscription_id = :subscription_id,
                    paddle_customer_id = :customer_id,
                    user_id = :user_id,
                    status = :status,
                    origin = :origin,
                    currency_code = :currency_code,
                    subtotal = :subtotal,
                    tax = :tax,
                    total = :total,
                    grand_total = :grand_total,
                    discount_total = :discount_total,
                    items = :items,
                    payments = :payments,
                    billed_at = :billed_at,
                    invoice_id = :invoice_id,
                    invoice_number = :invoice_number,
                    custom_data = :custom_data,
                    updated_at = CURRENT_TIMESTAMP
                WHERE paddle_transaction_id = :paddle_id
            """),
            {
                "paddle_id": paddle_transaction_id,
                "subscription_id": paddle_subscription_id,
                "customer_id": paddle_customer_id,
                "user_id": user_id,
                "status": status,
                "origin": origin,
                "currency_code": currency_code,
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
                "grand_total": grand_total,
                "discount_total": discount_total,
                "items": json.dumps(items),
                "payments": json.dumps(payments) if payments else None,
                "billed_at": billed_at_dt,
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "custom_data": json.dumps(custom_data) if custom_data else None
            }
        )
        record_id = existing[0]
        logger.info(
            "Updated transaction",
            paddle_transaction_id=paddle_transaction_id,
            status=status
        )
    else:
        # Create new transaction
        record_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO paddle_transaction 
                (id, paddle_transaction_id, paddle_subscription_id, paddle_customer_id,
                 user_id, status, origin, currency_code, subtotal, tax, total,
                 grand_total, discount_total, items, payments, billed_at,
                 invoice_id, invoice_number, custom_data)
                VALUES (:id, :paddle_id, :subscription_id, :customer_id, :user_id,
                        :status, :origin, :currency_code, :subtotal, :tax, :total,
                        :grand_total, :discount_total, :items, :payments, :billed_at,
                        :invoice_id, :invoice_number, :custom_data)
            """),
            {
                "id": record_id,
                "paddle_id": paddle_transaction_id,
                "subscription_id": paddle_subscription_id,
                "customer_id": paddle_customer_id,
                "user_id": user_id,
                "status": status,
                "origin": origin,
                "currency_code": currency_code,
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
                "grand_total": grand_total,
                "discount_total": discount_total,
                "items": json.dumps(items),
                "payments": json.dumps(payments) if payments else None,
                "billed_at": billed_at_dt,
                "invoice_id": invoice_id,
                "invoice_number": invoice_number,
                "custom_data": json.dumps(custom_data) if custom_data else None
            }
        )
        logger.info(
            "Created transaction",
            paddle_transaction_id=paddle_transaction_id,
            status=status,
            user_id=user_id
        )
    
    db.commit()
    return {"id": record_id, "paddle_transaction_id": paddle_transaction_id}


# =====================================================
# ADJUSTMENT FUNCTIONS
# =====================================================

def process_adjustment_event(db: Session, event_type: str, data: Dict[str, Any]) -> None:
    """Process adjustment-related webhook events (refunds, credits, chargebacks)."""
    paddle_adjustment_id = data.get("id")
    
    if not paddle_adjustment_id:
        logger.warning("Adjustment event missing adjustment ID", event_type=event_type)
        return
    
    logger.info(
        "Processing adjustment event",
        event_type=event_type,
        paddle_adjustment_id=paddle_adjustment_id
    )
    
    upsert_adjustment(db, data)


def upsert_adjustment(db: Session, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a Paddle adjustment record."""
    paddle_adjustment_id = data.get("id")
    paddle_transaction_id = data.get("transaction_id")
    paddle_customer_id = data.get("customer_id")
    paddle_subscription_id = data.get("subscription_id")
    
    action = data.get("action", "refund").upper()
    status = data.get("status", "pending").upper()
    reason = data.get("reason")
    currency_code = data.get("currency_code", "USD")
    
    # Get total from totals object
    totals = data.get("totals", {})
    total = str(totals.get("total", "0"))
    payout_totals = data.get("payout_totals")
    
    # Check if adjustment exists
    existing = db.execute(
        text("SELECT id FROM paddle_adjustment WHERE paddle_adjustment_id = :paddle_id"),
        {"paddle_id": paddle_adjustment_id}
    ).fetchone()
    
    if existing:
        # Update existing adjustment
        db.execute(
            text("""
                UPDATE paddle_adjustment 
                SET paddle_transaction_id = :transaction_id,
                    paddle_customer_id = :customer_id,
                    paddle_subscription_id = :subscription_id,
                    action = :action,
                    status = :status,
                    reason = :reason,
                    currency_code = :currency_code,
                    total = :total,
                    payout_totals = :payout_totals,
                    updated_at = CURRENT_TIMESTAMP
                WHERE paddle_adjustment_id = :paddle_id
            """),
            {
                "paddle_id": paddle_adjustment_id,
                "transaction_id": paddle_transaction_id,
                "customer_id": paddle_customer_id,
                "subscription_id": paddle_subscription_id,
                "action": action,
                "status": status,
                "reason": reason,
                "currency_code": currency_code,
                "total": total,
                "payout_totals": json.dumps(payout_totals) if payout_totals else None
            }
        )
        record_id = existing[0]
        logger.info(
            "Updated adjustment",
            paddle_adjustment_id=paddle_adjustment_id,
            status=status
        )
    else:
        # Create new adjustment
        record_id = str(uuid.uuid4())
        db.execute(
            text("""
                INSERT INTO paddle_adjustment 
                (id, paddle_adjustment_id, paddle_transaction_id, paddle_customer_id,
                 paddle_subscription_id, action, status, reason, currency_code,
                 total, payout_totals)
                VALUES (:id, :paddle_id, :transaction_id, :customer_id,
                        :subscription_id, :action, :status, :reason, :currency_code,
                        :total, :payout_totals)
            """),
            {
                "id": record_id,
                "paddle_id": paddle_adjustment_id,
                "transaction_id": paddle_transaction_id,
                "customer_id": paddle_customer_id,
                "subscription_id": paddle_subscription_id,
                "action": action,
                "status": status,
                "reason": reason,
                "currency_code": currency_code,
                "total": total,
                "payout_totals": json.dumps(payout_totals) if payout_totals else None
            }
        )
        logger.info(
            "Created adjustment",
            paddle_adjustment_id=paddle_adjustment_id,
            action=action,
            status=status
        )
    
    db.commit()
    return {"id": record_id, "paddle_adjustment_id": paddle_adjustment_id}


# =====================================================
# QUERY FUNCTIONS
# =====================================================

def get_user_active_subscription(
    db: Session,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """Get user's active subscription if any."""
    result = db.execute(
        text("""
            SELECT s.*, c.email, c.name as customer_name
            FROM paddle_subscription s
            JOIN paddle_customer c ON c.paddle_customer_id = s.paddle_customer_id
            WHERE s.user_id = :user_id
            AND s.status = 'ACTIVE'
            ORDER BY s.created_at DESC
            LIMIT 1
        """),
        {"user_id": user_id}
    ).fetchone()
    
    if not result:
        return None
    
    return {
        "id": result[0],
        "paddle_subscription_id": result[1],
        "paddle_customer_id": result[2],
        "user_id": result[3],
        "status": result[4],
        "currency_code": result[5],
        "billing_cycle_interval": result[6],
        "billing_cycle_frequency": result[7],
        "current_billing_period_starts_at": result[8].isoformat() if result[8] else None,
        "current_billing_period_ends_at": result[9].isoformat() if result[9] else None,
        "next_billed_at": result[10].isoformat() if result[10] else None,
        "items": json.loads(result[14]) if result[14] else [],
        "customer_email": result[-2],
        "customer_name": result[-1]
    }


def get_customer_by_email(db: Session, email: str) -> Optional[Dict[str, Any]]:
    """Get Paddle customer by email."""
    result = db.execute(
        text("""
            SELECT id, paddle_customer_id, user_id, email, name, locale, status,
                   created_at, updated_at
            FROM paddle_customer
            WHERE email = :email
            LIMIT 1
        """),
        {"email": email}
    ).fetchone()
    
    if not result:
        return None
    
    return {
        "id": result[0],
        "paddle_customer_id": result[1],
        "user_id": result[2],
        "email": result[3],
        "name": result[4],
        "locale": result[5],
        "status": result[6],
        "created_at": result[7].isoformat() if result[7] else None,
        "updated_at": result[8].isoformat() if result[8] else None
    }


def get_subscription_by_paddle_id(db: Session, paddle_subscription_id: str) -> Optional[Dict[str, Any]]:
    """Get subscription by Paddle subscription ID."""
    result = db.execute(
        text("""
            SELECT id, paddle_subscription_id, paddle_customer_id, user_id, status,
                   currency_code, billing_cycle_interval, billing_cycle_frequency,
                   current_billing_period_starts_at, current_billing_period_ends_at,
                   next_billed_at, paused_at, canceled_at, items, created_at, updated_at
            FROM paddle_subscription
            WHERE paddle_subscription_id = :paddle_id
            LIMIT 1
        """),
        {"paddle_id": paddle_subscription_id}
    ).fetchone()
    
    if not result:
        return None
    
    return {
        "id": result[0],
        "paddle_subscription_id": result[1],
        "paddle_customer_id": result[2],
        "user_id": result[3],
        "status": result[4],
        "currency_code": result[5],
        "billing_cycle_interval": result[6],
        "billing_cycle_frequency": result[7],
        "current_billing_period_starts_at": result[8].isoformat() if result[8] else None,
        "current_billing_period_ends_at": result[9].isoformat() if result[9] else None,
        "next_billed_at": result[10].isoformat() if result[10] else None,
        "paused_at": result[11].isoformat() if result[11] else None,
        "canceled_at": result[12].isoformat() if result[12] else None,
        "items": json.loads(result[13]) if result[13] else [],
        "created_at": result[14].isoformat() if result[14] else None,
        "updated_at": result[15].isoformat() if result[15] else None
    }


def link_customer_to_user(db: Session, paddle_customer_id: str, user_id: str) -> None:
    """Link a Paddle customer to a user account."""
    db.execute(
        text("""
            UPDATE paddle_customer 
            SET user_id = :user_id, updated_at = CURRENT_TIMESTAMP
            WHERE paddle_customer_id = :paddle_id
        """),
        {"paddle_id": paddle_customer_id, "user_id": user_id}
    )
    
    # Also update subscriptions and transactions
    db.execute(
        text("""
            UPDATE paddle_subscription 
            SET user_id = :user_id, updated_at = CURRENT_TIMESTAMP
            WHERE paddle_customer_id = :paddle_id
        """),
        {"paddle_id": paddle_customer_id, "user_id": user_id}
    )
    
    db.execute(
        text("""
            UPDATE paddle_transaction 
            SET user_id = :user_id, updated_at = CURRENT_TIMESTAMP
            WHERE paddle_customer_id = :paddle_id
        """),
        {"paddle_id": paddle_customer_id, "user_id": user_id}
    )
    
    db.commit()
    logger.info(
        "Linked Paddle customer to user",
        paddle_customer_id=paddle_customer_id,
        user_id=user_id
    )
