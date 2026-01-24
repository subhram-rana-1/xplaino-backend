"""Eviction policy definitions for in-memory cache."""

from enum import Enum


class EvictionPolicy(str, Enum):
    """Enumeration of supported eviction policies."""
    
    LRU = "LRU"  # Least Recently Used
    LFU = "LFU"  # Least Frequently Used

