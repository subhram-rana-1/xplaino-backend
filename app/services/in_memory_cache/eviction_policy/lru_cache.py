"""LRU (Least Recently Used) cache implementation."""

from typing import Any, Optional
from app.services.in_memory_cache.base import BaseCache


class Node:
    """Node for doubly linked list in LRU cache."""
    
    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value
        self.prev: Optional['Node'] = None
        self.next: Optional['Node'] = None


class LRUCache(BaseCache):
    """
    Thread-safe LRU (Least Recently Used) cache implementation.
    
    Uses a hash map for O(1) key lookup and a doubly linked list
    to maintain access order for O(1) eviction.
    """
    
    def __init__(self, max_key_count: int):
        """
        Initialize LRU cache.
        
        Args:
            max_key_count: Maximum number of keys the cache can hold
        """
        super().__init__(max_key_count)
        self._cache: dict[str, Node] = {}
        # Dummy head and tail nodes for easier list manipulation
        self._head = Node("", None)
        self._tail = Node("", None)
        self._head.next = self._tail
        self._tail.prev = self._head
    
    def get_key(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache by key.
        
        Moves the accessed node to the head (most recently used).
        
        Args:
            key: The key to look up
            
        Returns:
            The value associated with the key, or None if not found
        """
        with self._lock:
            if key not in self._cache:
                return None
            
            node = self._cache[key]
            # Move to head (most recently used)
            self._move_to_head(node)
            return node.value
    
    def set_key(self, key: str, val: Any) -> None:
        """
        Set a key-value pair in the cache.
        
        If key exists, updates value and moves to head.
        If key doesn't exist, creates new node and adds to head.
        Evicts least recently used item if cache is at capacity.
        
        Args:
            key: The key to store
            val: The value to store
        """
        with self._lock:
            if key in self._cache:
                # Update existing node
                node = self._cache[key]
                node.value = val
                self._move_to_head(node)
            else:
                # Create new node
                node = Node(key, val)
                
                # Check if we need to evict
                if len(self._cache) >= self._max_key_count:
                    self._evict_lru()
                
                # Add to cache and move to head
                self._cache[key] = node
                self._move_to_head(node)
    
    def invalidate_key(self, key: str) -> None:
        """
        Remove a key from the cache.
        
        Args:
            key: The key to remove
        """
        with self._lock:
            if key not in self._cache:
                return
            
            node = self._cache[key]
            self._remove_node(node)
            del self._cache[key]
    
    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()
            # Reset head and tail pointers
            self._head.next = self._tail
            self._tail.prev = self._head
    
    def size(self) -> int:
        """
        Get the current number of keys in the cache.
        
        Returns:
            The number of keys currently in the cache
        """
        with self._lock:
            return len(self._cache)
    
    def _move_to_head(self, node: Node) -> None:
        """
        Move a node to the head of the linked list (most recently used).
        
        Args:
            node: The node to move
        """
        # Remove from current position
        self._remove_node(node)
        
        # Insert after head
        node.next = self._head.next
        node.prev = self._head
        self._head.next.prev = node
        self._head.next = node
    
    def _remove_node(self, node: Node) -> None:
        """
        Remove a node from the linked list.
        
        Args:
            node: The node to remove
        """
        prev_node = node.prev
        next_node = node.next
        
        if prev_node:
            prev_node.next = next_node
        if next_node:
            next_node.prev = prev_node
    
    def _evict_lru(self) -> None:
        """Evict the least recently used item (tail of the list)."""
        if self._tail.prev == self._head:
            # Cache is empty
            return
        
        lru_node = self._tail.prev
        if lru_node:
            self._remove_node(lru_node)
            del self._cache[lru_node.key]

