"""Custom exceptions for in-memory cache operations."""


class InvalidEvictionPolicyError(Exception):
    """Raised when an invalid eviction policy is provided."""
    
    def __init__(self, policy: str):
        self.policy = policy
        super().__init__(f"Invalid eviction policy: {policy}. Supported policies: LRU, LFU")


class InvalidMaxKeyCountError(Exception):
    """Raised when an invalid max_key_count is provided."""
    
    def __init__(self, max_key_count: int):
        self.max_key_count = max_key_count
        super().__init__(f"Invalid max_key_count: {max_key_count}. Must be a positive integer greater than 0")

