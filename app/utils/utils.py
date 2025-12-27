from typing import List, Dict
from fastapi import Request
from urllib.parse import urlparse
import re


def get_start_index_and_length_for_words_from_text(
        text: str,
        words: List[str]
) -> List[Dict]:
    result = []
    start_pos = 0

    for word in words:
        # Find the word starting from the current search position
        index = text.find(word, start_pos)
        if index == -1:
            pass  # ignore if wrong word was generated

        result.append({
            "word": word,
            "index": index,
            "length": len(word)
        })

        # Move search start beyond this word to avoid matching earlier occurrences again
        start_pos = index + len(word)

    return result


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request headers.
    
    Checks headers in order:
    1. X-Forwarded-For (for proxied requests)
    2. X-Real-IP (alternative proxy header)
    3. request.client.host (direct connection)
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Client IP address as string
    """
    # Check X-Forwarded-For header (most common for proxied requests)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one
        return forwarded_for.split(",")[0].strip()
    
    # Check X-Real-IP header (alternative proxy header)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fall back to direct client connection
    if request.client:
        return request.client.host
    
    # Last resort fallback
    return "unknown"


def validate_domain_url(url: str) -> bool:
    """Validate domain URL format.
    
    Rules:
    - No 'www.' prefix
    - No 'http://' or 'https://' protocol
    - No paths (no '/' character)
    - Valid domain format: allows subdomains and multi-level TLDs
    - Examples: 'example.com', 'sub.example.com', 'example.co.uk', 'my-domain.us'
    
    Args:
        url: Domain URL to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not url or not isinstance(url, str):
        return False
    
    # Check for www prefix
    if url.lower().startswith('www.'):
        return False
    
    # Check for http/https protocol
    if url.lower().startswith('http://') or url.lower().startswith('https://'):
        return False
    
    # Check for paths (forward slash)
    if '/' in url:
        return False
    
    # Validate domain format using regex
    # Pattern allows: alphanumeric, hyphens, dots
    # Each label: 1-63 chars, starts/ends with alphanumeric, can have hyphens in between
    # Allows multiple labels separated by dots
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$'
    
    if not re.match(domain_pattern, url):
        return False
    
    # Additional check: must have at least one dot (TLD)
    if '.' not in url:
        return False
    
    # Check length (max 100 chars as per schema)
    if len(url) > 100:
        return False
    
    return True


def detect_link_type_from_url(url: str) -> str:
    """
    Detect link type from URL based on domain patterns.
    
    Supported types:
    - YOUTUBE: youtube.com, youtu.be, www.youtube.com, m.youtube.com
    - LINKEDIN: linkedin.com, www.linkedin.com
    - TWITTER: x.com, twitter.com, www.x.com, www.twitter.com
    - REDDIT: reddit.com, www.reddit.com
    - FACEBOOK: facebook.com, fb.com, www.facebook.com, m.facebook.com
    - INSTAGRAM: instagram.com, www.instagram.com
    - WEBPAGE: default for all other URLs
    
    Args:
        url: URL string to analyze
        
    Returns:
        Link type string (WEBPAGE, YOUTUBE, LINKEDIN, TWITTER, REDDIT, FACEBOOK, INSTAGRAM)
    """
    if not url or not isinstance(url, str):
        return 'WEBPAGE'
    
    try:
        # Parse the URL to extract domain
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove 'www.' prefix if present for consistent matching
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Check for YouTube domains
        if 'youtube.com' in domain or domain == 'youtu.be':
            return 'YOUTUBE'
        
        # Check for LinkedIn domain
        if domain == 'linkedin.com':
            return 'LINKEDIN'
        
        # Check for Twitter/X domains
        if domain == 'x.com' or domain == 'twitter.com':
            return 'TWITTER'
        
        # Check for Reddit domain
        if domain == 'reddit.com':
            return 'REDDIT'
        
        # Check for Facebook domains
        if domain == 'facebook.com' or domain == 'fb.com':
            return 'FACEBOOK'
        
        # Check for Instagram domain
        if domain == 'instagram.com':
            return 'INSTAGRAM'
        
        # Default to WEBPAGE for all other URLs
        return 'WEBPAGE'
        
    except Exception:
        # If URL parsing fails, default to WEBPAGE
        return 'WEBPAGE'
