"""URL normalization and hashing utilities for web highlight lookups."""

import hashlib
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

_TRACKING_PARAMS = frozenset({
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "ref",
    "source",
})


def normalize_url(raw_url: str) -> str:
    """
    Normalize a URL for consistent storage and lookup.

    - Lowercases the hostname
    - Removes known tracking query params
    - Strips trailing slashes from the path
    - Preserves all other query params and the path as-is
    """
    parsed = urlparse(raw_url)

    normalized_netloc = parsed.netloc.lower()

    filtered_params = {
        key: values
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
        if key not in _TRACKING_PARAMS
    }
    normalized_query = urlencode(filtered_params, doseq=True)

    normalized_path = parsed.path.rstrip("/") if parsed.path != "/" else parsed.path

    normalized = urlunparse((
        parsed.scheme,
        normalized_netloc,
        normalized_path,
        parsed.params,
        normalized_query,
        "",  # drop fragment
    ))
    return normalized


def hash_url(normalized_url: str) -> str:
    """Return the SHA-256 hex digest (64 chars) of a normalized URL."""
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()
