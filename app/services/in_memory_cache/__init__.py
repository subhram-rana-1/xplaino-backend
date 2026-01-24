"""In-memory cache service with support for multiple eviction policies."""

from app.services.in_memory_cache.cache_factory import create_cache, get_in_memory_cache
from app.services.in_memory_cache.eviction_policy.eviction_policy import EvictionPolicy
from app.services.in_memory_cache.base import BaseCache
from app.services.in_memory_cache.eviction_policy.lru_cache import LRUCache
from app.services.in_memory_cache.eviction_policy.lfu_cache import LFUCache
from app.services.in_memory_cache.exceptions import (
    InvalidEvictionPolicyError,
    InvalidMaxKeyCountError
)

__all__ = [
    "create_cache",
    "get_in_memory_cache",
    "EvictionPolicy",
    "BaseCache",
    "LRUCache",
    "LFUCache",
    "InvalidEvictionPolicyError",
    "InvalidMaxKeyCountError",
]

