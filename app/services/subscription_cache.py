"""Subscription caching utilities for subscription-based API access control."""

from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass
import structlog

from app.services.in_memory_cache import get_in_memory_cache

logger = structlog.get_logger()


@dataclass
class SubscriptionCacheEntry:
    """Cache entry for subscription data with TTL."""
    expired_at: datetime
    subscription: Optional[Dict[str, Any]]


# Cache configuration
SUBSCRIPTION_CACHE_KEY_PREFIX = "SUBSCRIPTION_INFO:"
SUBSCRIPTION_CACHE_TTL_HOURS = 1

# APIs that Plus users cannot access (create operations for saved items and folders)
PLUS_USER_RESTRICTED_APIS = {
    "POST:/api/saved-words",
    "POST:/api/saved-words/",
    "POST:/api/saved-paragraph",
    "POST:/api/saved-paragraph/",
    "POST:/api/saved-link",
    "POST:/api/saved-link/",
    "POST:/api/saved-image",
    "POST:/api/saved-image/",
    "POST:/api/folders",
    "POST:/api/folders/",
}


def invalidate_subscription_cache(user_id: str) -> None:
    """
    Invalidate the subscription cache for a specific user.
    
    Called when subscription data changes (webhook events from Paddle).
    
    Args:
        user_id: The user's ID whose cache should be invalidated
    """
    if not user_id:
        return
    
    cache = get_in_memory_cache()
    cache_key = f"{SUBSCRIPTION_CACHE_KEY_PREFIX}{user_id}"
    cache.invalidate_key(cache_key)
    
    logger.info(
        "Invalidated subscription cache",
        user_id=user_id,
        cache_key=cache_key
    )
