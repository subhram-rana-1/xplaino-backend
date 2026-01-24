"""Base cache interface for in-memory cache implementations."""

from abc import ABC, abstractmethod
from typing import Any, Optional
import threading


class BaseCache(ABC):
    """Abstract base class for cache implementations."""
    
    def __init__(self, max_key_count: int):
        """
        Initialize the cache.
        
        Args:
            max_key_count: Maximum number of keys the cache can hold
        """
        if max_key_count <= 0:
            raise ValueError(f"max_key_count must be positive, got {max_key_count}")
        
        self._max_key_count = max_key_count
        self._lock = threading.RLock()
    
    @abstractmethod
    def get_key(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache by key.
        
        Args:
            key: The key to look up
            
        Returns:
            The value associated with the key, or None if not found
        """
        pass
    
    @abstractmethod
    def set_key(self, key: str, val: Any) -> None:
        """
        Set a key-value pair in the cache.
        
        Args:
            key: The key to store
            val: The value to store
        """
        pass
    
    @abstractmethod
    def invalidate_key(self, key: str) -> None:
        """
        Remove a key from the cache.
        
        Args:
            key: The key to remove
        """
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """Clear all entries from the cache."""
        pass
    
    @abstractmethod
    def size(self) -> int:
        """
        Get the current number of keys in the cache.
        
        Returns:
            The number of keys currently in the cache
        """
        pass
    
    @property
    def max_key_count(self) -> int:
        """Get the maximum number of keys the cache can hold."""
        return self._max_key_count

