"""LFU (Least Frequently Used) cache implementation."""

from typing import Any, Optional
from app.services.in_memory_cache.base import BaseCache


class Node:
    """Node for doubly linked list in LFU cache with frequency tracking."""
    
    def __init__(self, key: str, value: Any):
        self.key = key
        self.value = value
        self.frequency = 1
        self.prev: Optional['Node'] = None
        self.next: Optional['Node'] = None


class DoublyLinkedList:
    """Doubly linked list for frequency buckets in LFU cache."""
    
    def __init__(self):
        # Dummy head and tail nodes
        self._head = Node("", None)
        self._tail = Node("", None)
        self._head.next = self._tail
        self._tail.prev = self._head
        self._size = 0
    
    def add_to_head(self, node: Node) -> None:
        """
        Add a node to the head of the list.
        
        Args:
            node: The node to add
        """
        node.next = self._head.next
        node.prev = self._head
        self._head.next.prev = node
        self._head.next = node
        self._size += 1
    
    def remove_node(self, node: Node) -> None:
        """
        Remove a node from the list.
        
        Args:
            node: The node to remove
        """
        if node.prev:
            node.prev.next = node.next
        if node.next:
            node.next.prev = node.prev
        self._size -= 1
    
    def remove_tail(self) -> Optional[Node]:
        """
        Remove and return the tail node (least recently used in this frequency bucket).
        
        Returns:
            The removed node, or None if list is empty
        """
        if self._size == 0:
            return None
        
        tail_node = self._tail.prev
        if tail_node and tail_node != self._head:
            self.remove_node(tail_node)
            return tail_node
        return None
    
    def is_empty(self) -> bool:
        """Check if the list is empty."""
        return self._size == 0


class LFUCache(BaseCache):
    """
    Thread-safe LFU (Least Frequently Used) cache implementation.
    
    Uses a hash map for O(1) key lookup and frequency buckets with
    doubly linked lists to maintain frequency order for O(1) eviction.
    """
    
    def __init__(self, max_key_count: int):
        """
        Initialize LFU cache.
        
        Args:
            max_key_count: Maximum number of keys the cache can hold
        """
        super().__init__(max_key_count)
        self._cache: dict[str, Node] = {}
        # Frequency buckets: frequency -> DoublyLinkedList
        self._frequency_buckets: dict[int, DoublyLinkedList] = {}
        self._min_frequency = 1
    
    def get_key(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache by key.
        
        Increments the frequency of the accessed key.
        
        Args:
            key: The key to look up
            
        Returns:
            The value associated with the key, or None if not found
        """
        with self._lock:
            if key not in self._cache:
                return None
            
            node = self._cache[key]
            self._increment_frequency(node)
            return node.value
    
    def set_key(self, key: str, val: Any) -> None:
        """
        Set a key-value pair in the cache.
        
        If key exists, updates value and increments frequency.
        If key doesn't exist, creates new node with frequency=1.
        Evicts least frequently used item if cache is at capacity.
        
        Args:
            key: The key to store
            val: The value to store
        """
        with self._lock:
            if key in self._cache:
                # Update existing node
                node = self._cache[key]
                node.value = val
                self._increment_frequency(node)
            else:
                # Check if we need to evict
                if len(self._cache) >= self._max_key_count:
                    self._evict_lfu()
                
                # Create new node with frequency=1
                node = Node(key, val)
                self._cache[key] = node
                self._add_to_frequency_bucket(node, 1)
                self._min_frequency = 1
    
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
            frequency = node.frequency
            self._remove_from_frequency_bucket(node)
            del self._cache[key]
            
            # Update min_frequency if we removed the last node from min_frequency bucket
            if frequency == self._min_frequency:
                if self._frequency_buckets:
                    self._min_frequency = min(self._frequency_buckets.keys())
                else:
                    self._min_frequency = 1
    
    def clear(self) -> None:
        """Clear all entries from the cache."""
        with self._lock:
            self._cache.clear()
            self._frequency_buckets.clear()
            self._min_frequency = 1
    
    def size(self) -> int:
        """
        Get the current number of keys in the cache.
        
        Returns:
            The number of keys currently in the cache
        """
        with self._lock:
            return len(self._cache)
    
    def _increment_frequency(self, node: Node) -> None:
        """
        Increment the frequency of a node and move it to the appropriate bucket.
        
        Args:
            node: The node whose frequency should be incremented
        """
        old_frequency = node.frequency
        new_frequency = old_frequency + 1
        
        # Remove from old frequency bucket
        self._remove_from_frequency_bucket(node)
        
        # Update frequency and add to new bucket
        node.frequency = new_frequency
        self._add_to_frequency_bucket(node, new_frequency)
        
        # Update min_frequency if needed
        if old_frequency == self._min_frequency:
            # Check if the old frequency bucket is now empty
            if old_frequency not in self._frequency_buckets or \
               self._frequency_buckets[old_frequency].is_empty():
                # Find the new minimum frequency from all remaining buckets
                if self._frequency_buckets:
                    self._min_frequency = min(self._frequency_buckets.keys())
                else:
                    self._min_frequency = 1
    
    def _add_to_frequency_bucket(self, node: Node, frequency: int) -> None:
        """
        Add a node to the appropriate frequency bucket.
        
        Args:
            node: The node to add
            frequency: The frequency bucket to add to
        """
        if frequency not in self._frequency_buckets:
            self._frequency_buckets[frequency] = DoublyLinkedList()
        
        self._frequency_buckets[frequency].add_to_head(node)
    
    def _remove_from_frequency_bucket(self, node: Node) -> None:
        """
        Remove a node from its current frequency bucket.
        
        Args:
            node: The node to remove
        """
        frequency = node.frequency
        if frequency in self._frequency_buckets:
            self._frequency_buckets[frequency].remove_node(node)
            # Clean up empty buckets
            if self._frequency_buckets[frequency].is_empty():
                del self._frequency_buckets[frequency]
    
    def _evict_lfu(self) -> None:
        """Evict the least frequently used item (from min_frequency bucket)."""
        if self._min_frequency not in self._frequency_buckets:
            return
        
        bucket = self._frequency_buckets[self._min_frequency]
        lfu_node = bucket.remove_tail()
        
        if lfu_node:
            del self._cache[lfu_node.key]
            
            # Update min_frequency if bucket is now empty
            if bucket.is_empty():
                del self._frequency_buckets[self._min_frequency]
                # Find new min_frequency
                if self._frequency_buckets:
                    self._min_frequency = min(self._frequency_buckets.keys())
                else:
                    self._min_frequency = 1

