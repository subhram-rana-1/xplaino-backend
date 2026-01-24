"""Factory for creating cache instances based on eviction policy."""

from typing import Union, Optional
import threading
from app.services.in_memory_cache.eviction_policy.eviction_policy import EvictionPolicy
from app.services.in_memory_cache.eviction_policy.lru_cache import LRUCache
from app.services.in_memory_cache.eviction_policy.lfu_cache import LFUCache
from app.services.in_memory_cache.base import BaseCache
from app.services.in_memory_cache.exceptions import (
    InvalidEvictionPolicyError,
    InvalidMaxKeyCountError
)

# Singleton cache instance
_cache_instance: Optional[BaseCache] = None
_cache_lock = threading.Lock()


def create_cache(
    eviction_policy: Union[EvictionPolicy, str],
    max_key_count: int
) -> BaseCache:
    """
    Create a cache instance based on the specified eviction policy.
    
    Args:
        eviction_policy: The eviction policy to use (LRU or LFU)
        max_key_count: Maximum number of keys the cache can hold
        
    Returns:
        A cache instance implementing the BaseCache interface
        
    Raises:
        InvalidEvictionPolicyError: If the eviction policy is not supported
        InvalidMaxKeyCountError: If max_key_count is invalid
    """
    # Validate max_key_count
    if not isinstance(max_key_count, int) or max_key_count <= 0:
        raise InvalidMaxKeyCountError(max_key_count)
    
    # Normalize eviction policy
    if isinstance(eviction_policy, str):
        eviction_policy = eviction_policy.upper()
        try:
            eviction_policy = EvictionPolicy(eviction_policy)
        except ValueError:
            raise InvalidEvictionPolicyError(eviction_policy)
    
    # Create appropriate cache instance
    if eviction_policy == EvictionPolicy.LRU:
        return LRUCache(max_key_count)
    elif eviction_policy == EvictionPolicy.LFU:
        return LFUCache(max_key_count)
    else:
        raise InvalidEvictionPolicyError(str(eviction_policy))


def get_in_memory_cache(
    eviction_policy: Optional[Union[EvictionPolicy, str]] = None,
    max_key_count: Optional[int] = None
) -> BaseCache:
    """
    Get the singleton in-memory cache instance.
    
    On first call, initializes the cache with the provided parameters.
    On subsequent calls, returns the same instance (parameters are ignored).
    
    Args:
        eviction_policy: Optional eviction policy to use (LRU or LFU).
                        Defaults to LRU if not provided on first call.
        max_key_count: Optional maximum number of keys the cache can hold.
                      Defaults to 1000 if not provided on first call.
        
    Returns:
        The singleton cache instance implementing the BaseCache interface
        
    Raises:
        InvalidEvictionPolicyError: If the eviction policy is not supported (only on first call)
        InvalidMaxKeyCountError: If max_key_count is invalid (only on first call)
    
    Example:
        # First call - initializes with defaults (LRU, 1000)
        cache = get_in_memory_cache()
        
        # First call - initializes with custom parameters
        cache = get_in_memory_cache(EvictionPolicy.LFU, 500)
        
        # Subsequent calls - returns same instance, parameters ignored
        cache2 = get_in_memory_cache(EvictionPolicy.LRU, 2000)  # Same instance as cache
    """
    global _cache_instance
    
    # Double-checked locking pattern for thread-safe singleton
    if _cache_instance is None:
        with _cache_lock:
            # Check again after acquiring lock (double-checked locking)
            if _cache_instance is None:
                # Use defaults if not provided
                if eviction_policy is None:
                    eviction_policy = EvictionPolicy.LRU
                if max_key_count is None:
                    max_key_count = 1000
                
                # Create the singleton instance
                _cache_instance = create_cache(eviction_policy, max_key_count)
    
    return _cache_instance

