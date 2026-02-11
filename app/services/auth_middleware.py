"""Authentication middleware for API endpoints."""

import sys
from typing import Optional, Dict, Any, Tuple
from fastapi import Request, HTTPException, Depends, Response
from sqlalchemy.orm import Session
import structlog
from datetime import datetime, timezone, timedelta

from app.config import settings
from app.database.connection import get_db
from app.services.jwt_service import decode_access_token
from app.utils.utils import get_client_ip
from app.services.database_service import (
    get_user_session_by_id,
    get_unauthenticated_user_usage,
    create_unauthenticated_user_usage,
    increment_api_usage,
    get_authenticated_user_api_usage,
    create_authenticated_user_api_usage,
    increment_authenticated_api_usage,
    get_user_id_by_auth_vendor_id
)
from app.services.paddle_service import get_user_active_subscription
from app.services.in_memory_cache import get_in_memory_cache
from app.services.subscription_cache import (
    SubscriptionCacheEntry,
    SUBSCRIPTION_CACHE_KEY_PREFIX,
    SUBSCRIPTION_CACHE_TTL_HOURS,
    PLUS_USER_RESTRICTED_APIS,
    PLUS_USER_RATE_LIMITED_APIS,
)

logger = structlog.get_logger()

# API endpoint to counter field name mapping (METHOD:URL format)
API_ENDPOINT_TO_COUNTER_FIELD = {
    # v1 APIs
    "POST:/api/v1/image-to-text": "image_to_text_api_count_so_far",
    "POST:/api/v1/pdf-to-text": "pdf_to_text_api_count_so_far",
    "POST:/api/v1/important-words-from-text": "important_words_from_text_v1_api_count_so_far",
    "POST:/api/v1/words-explanation": "words_explanation_v1_api_count_so_far",
    "POST:/api/v1/get-more-explanations": "get_more_explanations_api_count_so_far",
    "GET:/api/v1/get-random-paragraph": "get_random_paragraph_api_count_so_far",
    
    # v2 APIs
    "POST:/api/v2/words-explanation": "words_explanation_api_count_so_far",
    "POST:/api/v2/simplify": "simplify_api_count_so_far",
    "POST:/api/v2/important-words-from-text": "important_words_from_text_v2_api_count_so_far",
    "POST:/api/v2/ask": "ask_api_count_so_far",
    "POST:/api/v2/pronunciation": "pronunciation_api_count_so_far",
    "POST:/api/v2/voice-to-text": "voice_to_text_api_count_so_far",
    "POST:/api/v2/translate": "translate_api_count_so_far",
    "POST:/api/v2/summarise": "summarise_api_count_so_far",
    "POST:/api/v2/web-search": "web_search_api_count_so_far",
    "POST:/api/v2/web-search-stream": "web_search_stream_api_count_so_far",
    "POST:/api/v2/synonyms": "synonyms_api_count_so_far",
    "POST:/api/v2/antonyms": "antonyms_api_count_so_far",
    "POST:/api/v2/simplify-image": "simplify_image_api_count_so_far",
    "POST:/api/v2/ask-image": "ask_image_api_count_so_far",
    
    # Saved words APIs (method-specific)
    "GET:/api/saved-words": "saved_words_get_api_count_so_far",
    "GET:/api/saved-words/": "saved_words_get_api_count_so_far",
    "POST:/api/saved-words": "saved_words_post_api_count_so_far",
    "POST:/api/saved-words/": "saved_words_post_api_count_so_far",
    "DELETE:/api/saved-words": "saved_words_delete_api_count_so_far",
    "DELETE:/api/saved-words/": "saved_words_delete_api_count_so_far",
    
    # Saved paragraph APIs (method-specific)
    "GET:/api/saved-paragraph": "saved_paragraph_get_api_count_so_far",
    "GET:/api/saved-paragraph/": "saved_paragraph_get_api_count_so_far",
    "POST:/api/saved-paragraph": "saved_paragraph_post_api_count_so_far",
    "POST:/api/saved-paragraph/": "saved_paragraph_post_api_count_so_far",
    "DELETE:/api/saved-paragraph": "saved_paragraph_delete_api_count_so_far",
    "DELETE:/api/saved-paragraph/": "saved_paragraph_delete_api_count_so_far",
    "POST:/api/saved-paragraph/folder": "saved_paragraph_folder_post_api_count_so_far",
    "DELETE:/api/saved-paragraph/folder": "saved_paragraph_folder_delete_api_count_so_far",
    
    # Saved link APIs (method-specific)
    "GET:/api/saved-link": "saved_link_get_api_count_so_far",
    "GET:/api/saved-link/": "saved_link_get_api_count_so_far",
    "GET:/api/saved-link/{link_id}": "saved_link_get_api_count_so_far",
    "POST:/api/saved-link": "saved_link_post_api_count_so_far",
    "POST:/api/saved-link/": "saved_link_post_api_count_so_far",
    "DELETE:/api/saved-link": "saved_link_delete_api_count_so_far",
    "DELETE:/api/saved-link/": "saved_link_delete_api_count_so_far",
    "DELETE:/api/saved-link/{link_id}": "saved_link_delete_api_count_so_far",
    "POST:/api/saved-link/folder": "saved_link_folder_post_api_count_so_far",
    "DELETE:/api/saved-link/folder": "saved_link_folder_delete_api_count_so_far",
    
    # Folders APIs (method-specific)
    "GET:/api/folders": "folders_get_api_count_so_far",
    "POST:/api/folders": "folders_post_api_count_so_far",
    "POST:/api/folders/": "folders_post_api_count_so_far",
    "DELETE:/api/folders": "folders_delete_api_count_so_far",
    
    # Saved image APIs (method-specific)
    "GET:/api/saved-image": "saved_image_get_api_count_so_far",
    "GET:/api/saved-image/": "saved_image_get_api_count_so_far",
    "POST:/api/saved-image": "saved_image_post_api_count_so_far",
    "POST:/api/saved-image/": "saved_image_post_api_count_so_far",
    "PATCH:/api/saved-image/{saved_image_id}/move-to-folder": "saved_image_move_api_count_so_far",
    "PATCH:/api/saved-words/{word_id}/move-to-folder": "saved_words_move_api_count_so_far",
    "PATCH:/api/saved-paragraph/{paragraph_id}/move-to-folder": "saved_paragraph_move_api_count_so_far",
    "PATCH:/api/saved-link/{link_id}/move-to-folder": "saved_link_move_api_count_so_far",
    "DELETE:/api/saved-image": "saved_image_delete_api_count_so_far",
    "DELETE:/api/saved-image/": "saved_image_delete_api_count_so_far",
    "DELETE:/api/saved-image/{saved_image_id}": "saved_image_delete_api_count_so_far",
    
    # Issue APIs (method-specific)
    "GET:/api/issue/": "issue_get_api_count_so_far",
    "GET:/api/issue/all": "issue_get_all_api_count_so_far",
    "PATCH:/api/issue/{issue_id}": "issue_patch_api_count_so_far",
    "POST:/api/issue/": "issue_post_api_count_so_far",
    
    # PDF APIs (method-specific)
    "POST:/api/pdf/to-html": "pdf_to_html_api_count_so_far",
    "GET:/api/pdf": "pdf_get_api_count_so_far",
    "GET:/api/pdf/": "pdf_get_api_count_so_far",
    "GET:/api/pdf/{pdf_id}/html": "pdf_get_html_api_count_so_far",
}

# API endpoint to max limit config mapping for unauthenticated users (METHOD:URL format)
API_ENDPOINT_TO_MAX_LIMIT_CONFIG = {
    # v1 APIs
    "POST:/api/v1/image-to-text": "unauth_user_image_to_text_api_max_limit",
    "POST:/api/v1/pdf-to-text": "unauth_user_pdf_to_text_api_max_limit",
    "POST:/api/v1/important-words-from-text": "unauth_user_important_words_from_text_v1_api_max_limit",
    "POST:/api/v1/words-explanation": "unauth_user_words_explanation_v1_api_max_limit",
    "POST:/api/v1/get-more-explanations": "unauth_user_get_more_explanations_api_max_limit",
    "GET:/api/v1/get-random-paragraph": "unauth_user_get_random_paragraph_api_max_limit",
    
    # v2 APIs
    "POST:/api/v2/words-explanation": "unauth_user_words_explanation_api_max_limit",
    "POST:/api/v2/simplify": "unauth_user_simplify_api_max_limit",
    "POST:/api/v2/important-words-from-text": "unauth_user_important_words_from_text_v2_api_max_limit",
    "POST:/api/v2/ask": "unauth_user_ask_api_max_limit",
    "POST:/api/v2/pronunciation": "unauth_user_pronunciation_api_max_limit",
    "POST:/api/v2/voice-to-text": "unauth_user_voice_to_text_api_max_limit",
    "POST:/api/v2/translate": "unauth_user_translate_api_max_limit",
    "POST:/api/v2/summarise": "unauth_user_summarise_api_max_limit",
    "POST:/api/v2/web-search": "unauth_user_web_search_api_max_limit",
    "POST:/api/v2/web-search-stream": "unauth_user_web_search_stream_api_max_limit",
    "POST:/api/v2/synonyms": "unauth_user_synonyms_api_max_limit",
    "POST:/api/v2/antonyms": "unauth_user_antonyms_api_max_limit",
    "POST:/api/v2/simplify-image": "unauth_user_simplify_image_api_max_limit",
    "POST:/api/v2/ask-image": "unauth_user_ask_image_api_max_limit",
    
    # Saved words APIs (method-specific)
    "GET:/api/saved-words": "unauth_user_saved_words_get_api_max_limit",
    "GET:/api/saved-words/": "unauth_user_saved_words_get_api_max_limit",
    "POST:/api/saved-words": "unauth_user_saved_words_post_api_max_limit",
    "POST:/api/saved-words/": "unauth_user_saved_words_post_api_max_limit",
    "DELETE:/api/saved-words": "unauth_user_saved_words_delete_api_max_limit",
    "DELETE:/api/saved-words/": "unauth_user_saved_words_delete_api_max_limit",
    
    # Saved paragraph APIs (method-specific)
    "GET:/api/saved-paragraph": "unauth_user_saved_paragraph_get_api_max_limit",
    "GET:/api/saved-paragraph/": "unauth_user_saved_paragraph_get_api_max_limit",
    "POST:/api/saved-paragraph": "unauth_user_saved_paragraph_post_api_max_limit",
    "POST:/api/saved-paragraph/": "unauth_user_saved_paragraph_post_api_max_limit",
    "DELETE:/api/saved-paragraph": "unauth_user_saved_paragraph_delete_api_max_limit",
    "DELETE:/api/saved-paragraph/": "unauth_user_saved_paragraph_delete_api_max_limit",
    "POST:/api/saved-paragraph/folder": "unauth_user_saved_paragraph_folder_post_api_max_limit",
    "DELETE:/api/saved-paragraph/folder": "unauth_user_saved_paragraph_folder_delete_api_max_limit",
    
    # Saved link APIs (method-specific)
    "GET:/api/saved-link": "unauth_user_saved_link_get_api_max_limit",
    "GET:/api/saved-link/": "unauth_user_saved_link_get_api_max_limit",
    "GET:/api/saved-link/{link_id}": "unauth_user_saved_link_get_api_max_limit",
    "POST:/api/saved-link": "unauth_user_saved_link_post_api_max_limit",
    "POST:/api/saved-link/": "unauth_user_saved_link_post_api_max_limit",
    "DELETE:/api/saved-link": "unauth_user_saved_link_delete_api_max_limit",
    "DELETE:/api/saved-link/": "unauth_user_saved_link_delete_api_max_limit",
    "DELETE:/api/saved-link/{link_id}": "unauth_user_saved_link_delete_api_max_limit",
    "POST:/api/saved-link/folder": "unauth_user_saved_link_folder_post_api_max_limit",
    "DELETE:/api/saved-link/folder": "unauth_user_saved_link_folder_delete_api_max_limit",
    
    # Folders APIs (method-specific)
    "GET:/api/folders": "unauth_user_folders_get_api_max_limit",
    "POST:/api/folders": "unauth_user_folders_post_api_max_limit",
    "POST:/api/folders/": "unauth_user_folders_post_api_max_limit",
    "DELETE:/api/folders": "unauth_user_folders_delete_api_max_limit",
    
    # Saved image APIs (method-specific)
    "GET:/api/saved-image": "unauth_user_saved_image_get_api_max_limit",
    "GET:/api/saved-image/": "unauth_user_saved_image_get_api_max_limit",
    "POST:/api/saved-image": "unauth_user_saved_image_post_api_max_limit",
    "POST:/api/saved-image/": "unauth_user_saved_image_post_api_max_limit",
    "PATCH:/api/saved-image/{saved_image_id}/move-to-folder": "unauth_user_saved_image_move_api_max_limit",
    "PATCH:/api/saved-words/{word_id}/move-to-folder": "unauth_user_saved_words_move_api_max_limit",
    "PATCH:/api/saved-paragraph/{paragraph_id}/move-to-folder": "unauth_user_saved_paragraph_move_api_max_limit",
    "PATCH:/api/saved-link/{link_id}/move-to-folder": "unauth_user_saved_link_move_api_max_limit",
    "DELETE:/api/saved-image": "unauth_user_saved_image_delete_api_max_limit",
    "DELETE:/api/saved-image/": "unauth_user_saved_image_delete_api_max_limit",
    "DELETE:/api/saved-image/{saved_image_id}": "unauth_user_saved_image_delete_api_max_limit",
    
    # Issue APIs (method-specific)
    "GET:/api/issue/": "unauth_user_issue_get_api_max_limit",
    "GET:/api/issue/all": "unauth_user_issue_get_all_api_max_limit",
    "PATCH:/api/issue/{issue_id}": "unauth_user_issue_patch_api_max_limit",
    "POST:/api/issue/": "unauth_user_issue_post_api_max_limit",
    
    # PDF APIs (method-specific)
    "POST:/api/pdf/to-html": "unauth_user_pdf_to_html_api_max_limit",
    "GET:/api/pdf": "unauth_user_pdf_get_api_max_limit",
    "GET:/api/pdf/": "unauth_user_pdf_get_api_max_limit",
    "GET:/api/pdf/{pdf_id}/html": "unauth_user_pdf_get_html_api_max_limit",
}

# API endpoint to authenticated unsubscribed max limit config mapping (METHOD:URL format)
API_ENDPOINT_TO_AUTHENTICATED_MAX_LIMIT_CONFIG = {
    # v1 APIs
    "POST:/api/v1/image-to-text": "authenticated_unsubscribed_image_to_text_api_max_limit",
    "POST:/api/v1/pdf-to-text": "authenticated_unsubscribed_pdf_to_text_api_max_limit",
    "POST:/api/v1/important-words-from-text": "authenticated_unsubscribed_important_words_from_text_v1_api_max_limit",
    "POST:/api/v1/words-explanation": "authenticated_unsubscribed_words_explanation_v1_api_max_limit",
    "POST:/api/v1/get-more-explanations": "authenticated_unsubscribed_get_more_explanations_api_max_limit",
    "GET:/api/v1/get-random-paragraph": "authenticated_unsubscribed_get_random_paragraph_api_max_limit",
    
    # v2 APIs
    "POST:/api/v2/words-explanation": "authenticated_unsubscribed_words_explanation_api_max_limit",
    "POST:/api/v2/simplify": "authenticated_unsubscribed_simplify_api_max_limit",
    "POST:/api/v2/important-words-from-text": "authenticated_unsubscribed_important_words_from_text_v2_api_max_limit",
    "POST:/api/v2/ask": "authenticated_unsubscribed_ask_api_max_limit",
    "POST:/api/v2/pronunciation": "authenticated_unsubscribed_pronunciation_api_max_limit",
    "POST:/api/v2/voice-to-text": "authenticated_unsubscribed_voice_to_text_api_max_limit",
    "POST:/api/v2/translate": "authenticated_unsubscribed_translate_api_max_limit",
    "POST:/api/v2/summarise": "authenticated_unsubscribed_summarise_api_max_limit",
    "POST:/api/v2/web-search": "authenticated_unsubscribed_web_search_api_max_limit",
    "POST:/api/v2/web-search-stream": "authenticated_unsubscribed_web_search_stream_api_max_limit",
    "POST:/api/v2/synonyms": "authenticated_unsubscribed_synonyms_api_max_limit",
    "POST:/api/v2/antonyms": "authenticated_unsubscribed_antonyms_api_max_limit",
    "POST:/api/v2/simplify-image": "authenticated_unsubscribed_simplify_image_api_max_limit",
    "POST:/api/v2/ask-image": "authenticated_unsubscribed_ask_image_api_max_limit",
    
    # Saved words APIs (method-specific)
    "GET:/api/saved-words": "authenticated_unsubscribed_saved_words_get_api_max_limit",
    "GET:/api/saved-words/": "authenticated_unsubscribed_saved_words_get_api_max_limit",
    "POST:/api/saved-words": "authenticated_unsubscribed_saved_words_post_api_max_limit",
    "POST:/api/saved-words/": "authenticated_unsubscribed_saved_words_post_api_max_limit",
    "DELETE:/api/saved-words": "authenticated_unsubscribed_saved_words_delete_api_max_limit",
    "DELETE:/api/saved-words/": "authenticated_unsubscribed_saved_words_delete_api_max_limit",
    
    # Saved paragraph APIs (method-specific)
    "GET:/api/saved-paragraph": "authenticated_unsubscribed_saved_paragraph_get_api_max_limit",
    "GET:/api/saved-paragraph/": "authenticated_unsubscribed_saved_paragraph_get_api_max_limit",
    "POST:/api/saved-paragraph": "authenticated_unsubscribed_saved_paragraph_post_api_max_limit",
    "POST:/api/saved-paragraph/": "authenticated_unsubscribed_saved_paragraph_post_api_max_limit",
    "DELETE:/api/saved-paragraph": "authenticated_unsubscribed_saved_paragraph_delete_api_max_limit",
    "DELETE:/api/saved-paragraph/": "authenticated_unsubscribed_saved_paragraph_delete_api_max_limit",
    "POST:/api/saved-paragraph/folder": "authenticated_unsubscribed_saved_paragraph_folder_post_api_max_limit",
    "DELETE:/api/saved-paragraph/folder": "authenticated_unsubscribed_saved_paragraph_folder_delete_api_max_limit",
    
    # Saved link APIs (method-specific)
    "GET:/api/saved-link": "authenticated_unsubscribed_saved_link_get_api_max_limit",
    "GET:/api/saved-link/": "authenticated_unsubscribed_saved_link_get_api_max_limit",
    "GET:/api/saved-link/{link_id}": "authenticated_unsubscribed_saved_link_get_api_max_limit",
    "POST:/api/saved-link": "authenticated_unsubscribed_saved_link_post_api_max_limit",
    "POST:/api/saved-link/": "authenticated_unsubscribed_saved_link_post_api_max_limit",
    "DELETE:/api/saved-link": "authenticated_unsubscribed_saved_link_delete_api_max_limit",
    "DELETE:/api/saved-link/": "authenticated_unsubscribed_saved_link_delete_api_max_limit",
    "DELETE:/api/saved-link/{link_id}": "authenticated_unsubscribed_saved_link_delete_api_max_limit",
    "POST:/api/saved-link/folder": "authenticated_unsubscribed_saved_link_folder_post_api_max_limit",
    "DELETE:/api/saved-link/folder": "authenticated_unsubscribed_saved_link_folder_delete_api_max_limit",
    
    # Folders APIs (method-specific)
    "GET:/api/folders": "authenticated_unsubscribed_folders_get_api_max_limit",
    "POST:/api/folders": "authenticated_unsubscribed_folders_post_api_max_limit",
    "POST:/api/folders/": "authenticated_unsubscribed_folders_post_api_max_limit",
    "DELETE:/api/folders": "authenticated_unsubscribed_folders_delete_api_max_limit",
    
    # Saved image APIs (method-specific)
    "GET:/api/saved-image": "authenticated_unsubscribed_saved_image_get_api_max_limit",
    "GET:/api/saved-image/": "authenticated_unsubscribed_saved_image_get_api_max_limit",
    "POST:/api/saved-image": "authenticated_unsubscribed_saved_image_post_api_max_limit",
    "POST:/api/saved-image/": "authenticated_unsubscribed_saved_image_post_api_max_limit",
    "PATCH:/api/saved-image/{saved_image_id}/move-to-folder": "authenticated_unsubscribed_saved_image_move_api_max_limit",
    "PATCH:/api/saved-words/{word_id}/move-to-folder": "authenticated_unsubscribed_saved_words_move_api_max_limit",
    "PATCH:/api/saved-paragraph/{paragraph_id}/move-to-folder": "authenticated_unsubscribed_saved_paragraph_move_api_max_limit",
    "PATCH:/api/saved-link/{link_id}/move-to-folder": "authenticated_unsubscribed_saved_link_move_api_max_limit",
    "DELETE:/api/saved-image": "authenticated_unsubscribed_saved_image_delete_api_max_limit",
    "DELETE:/api/saved-image/": "authenticated_unsubscribed_saved_image_delete_api_max_limit",
    "DELETE:/api/saved-image/{saved_image_id}": "authenticated_unsubscribed_saved_image_delete_api_max_limit",
    
    # Issue APIs (method-specific)
    "GET:/api/issue/": "authenticated_unsubscribed_issue_get_api_max_limit",
    "GET:/api/issue/all": "authenticated_unsubscribed_issue_get_all_api_max_limit",
    "PATCH:/api/issue/{issue_id}": "authenticated_unsubscribed_issue_patch_api_max_limit",
    "POST:/api/issue/": "authenticated_unsubscribed_issue_post_api_max_limit",
    
    # PDF APIs (method-specific)
    "POST:/api/pdf/to-html": "authenticated_unsubscribed_pdf_to_html_api_max_limit",
    "GET:/api/pdf": "authenticated_unsubscribed_pdf_get_api_max_limit",
    "GET:/api/pdf/": "authenticated_unsubscribed_pdf_get_api_max_limit",
    "GET:/api/pdf/{pdf_id}/html": "authenticated_unsubscribed_pdf_get_html_api_max_limit",
}

# API endpoint to Plus subscriber max limit config mapping (METHOD:URL format)
API_ENDPOINT_TO_PLUS_SUBSCRIBER_MAX_LIMIT_CONFIG = {
    "POST:/api/saved-words": "plus_subscriber_saved_words_post_api_max_limit",
    "POST:/api/saved-words/": "plus_subscriber_saved_words_post_api_max_limit",
    "POST:/api/saved-paragraph": "plus_subscriber_saved_paragraph_post_api_max_limit",
    "POST:/api/saved-paragraph/": "plus_subscriber_saved_paragraph_post_api_max_limit",
    "POST:/api/saved-link": "plus_subscriber_saved_link_post_api_max_limit",
    "POST:/api/saved-link/": "plus_subscriber_saved_link_post_api_max_limit",
    "POST:/api/saved-image": "plus_subscriber_saved_image_post_api_max_limit",
    "POST:/api/saved-image/": "plus_subscriber_saved_image_post_api_max_limit",
}


def get_api_counter_field_and_plus_subscriber_max_limit(request: Request) -> tuple[Optional[str], Optional[int]]:
    """
    Get the API counter field name and Plus subscriber max limit for the current request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Tuple of (counter_field_name, max_limit) or (None, None) if not found
    """
    method = request.method
    path = request.url.path
    lookup_key = f"{method}:{path}"
    
    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(lookup_key)
    limit_config = API_ENDPOINT_TO_PLUS_SUBSCRIBER_MAX_LIMIT_CONFIG.get(lookup_key)
    
    # If API counter doesn't exist, treat as unlimited (max int)
    if counter_field is None or limit_config is None:
        return None, sys.maxsize
    
    max_limit = getattr(settings, limit_config, None)
    if max_limit is None:
        # If limit config doesn't exist in settings, treat as unlimited
        return None, sys.maxsize

    return counter_field, max_limit


def get_api_counter_field_and_limit(request: Request) -> tuple[Optional[str], Optional[int]]:
    """
    Get the API counter field name and max limit for the current request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Tuple of (counter_field_name, max_limit) or (None, None) if not found
    """
    method = request.method
    path = request.url.path
    lookup_key = f"{method}:{path}"
    
    # Try exact match first
    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(lookup_key)
    limit_config = API_ENDPOINT_TO_MAX_LIMIT_CONFIG.get(lookup_key)
    
    # If no exact match, try pattern matching for paths with parameters
    if counter_field is None or limit_config is None:
        # Handle GET endpoints with path parameters
        # e.g., GET:/api/pdf/abc-123/html -> GET:/api/pdf/{pdf_id}/html
        if method == "GET":
            if path.startswith("/api/pdf/") and path.endswith("/html"):
                pattern_key = f"{method}:/api/pdf/{{pdf_id}}/html"
                counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                limit_config = API_ENDPOINT_TO_MAX_LIMIT_CONFIG.get(pattern_key)
        # Handle DELETE endpoints with path parameters
        # e.g., DELETE:/api/saved-words/abc-123 -> DELETE:/api/saved-words
        elif method == "DELETE":
            # Try removing the last path segment (the ID parameter)
            path_parts = path.rstrip('/').split('/')
            if len(path_parts) > 0:
                # Try base path without the ID
                base_path = '/'.join(path_parts[:-1])
                if base_path:
                    base_lookup_key = f"{method}:{base_path}"
                    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(base_lookup_key)
                    limit_config = API_ENDPOINT_TO_MAX_LIMIT_CONFIG.get(base_lookup_key)
        # Handle PATCH endpoints with path parameters
        # e.g., PATCH:/api/saved-image/abc-123/move-to-folder -> PATCH:/api/saved-image/{saved_image_id}/move-to-folder
        # e.g., PATCH:/api/saved-words/abc-123/move-to-folder -> PATCH:/api/saved-words/{word_id}/move-to-folder
        # e.g., PATCH:/api/saved-paragraph/abc-123/move-to-folder -> PATCH:/api/saved-paragraph/{paragraph_id}/move-to-folder
        # e.g., PATCH:/api/saved-link/abc-123/move-to-folder -> PATCH:/api/saved-link/{link_id}/move-to-folder
        # e.g., PATCH:/api/issue/abc-123 -> PATCH:/api/issue/{issue_id}
        elif method == "PATCH":
            # For move-to-folder endpoint, try pattern match
            if path.endswith("/move-to-folder"):
                # Try different move-to-folder patterns
                if path.startswith("/api/saved-image/"):
                    pattern_key = f"{method}:/api/saved-image/{{saved_image_id}}/move-to-folder"
                elif path.startswith("/api/saved-words/"):
                    pattern_key = f"{method}:/api/saved-words/{{word_id}}/move-to-folder"
                elif path.startswith("/api/saved-paragraph/"):
                    pattern_key = f"{method}:/api/saved-paragraph/{{paragraph_id}}/move-to-folder"
                elif path.startswith("/api/saved-link/"):
                    pattern_key = f"{method}:/api/saved-link/{{link_id}}/move-to-folder"
                else:
                    pattern_key = None
                
                if pattern_key:
                    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                    limit_config = API_ENDPOINT_TO_MAX_LIMIT_CONFIG.get(pattern_key)
            # For issue update endpoint, try pattern match
            elif path.startswith("/api/issue/"):
                path_parts = path.rstrip('/').split('/')
                if len(path_parts) == 3:  # /api/issue/{issue_id}
                    pattern_key = f"{method}:/api/issue/{{issue_id}}"
                    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                    limit_config = API_ENDPOINT_TO_MAX_LIMIT_CONFIG.get(pattern_key)
    
    # If API counter doesn't exist, treat as unlimited (max int)
    if counter_field is None or limit_config is None:
        return None, sys.maxsize
    
    max_limit = getattr(settings, limit_config, None)
    if max_limit is None:
        # If limit config doesn't exist in settings, treat as unlimited
        return None, sys.maxsize

    return counter_field, max_limit


def raise_login_required(status_code: int = 401, reason: str = "Please login") -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "errorCode": "LOGIN_REQUIRED",
            "message": reason
        }
    )


def raise_subscription_required(reason: str = "API usage limit exceeded. Please subscribe to continue.") -> None:
    raise HTTPException(
        status_code=429,
        detail={
            "errorCode": "SUBSCRIPTION_REQUIRED",
            "message": reason
        }
    )


def get_api_counter_field_and_authenticated_max_limit(request: Request) -> tuple[Optional[str], Optional[int]]:
    """
    Get the API counter field name and authenticated max limit for the current request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Tuple of (counter_field_name, max_limit) or (None, None) if not found
    """
    method = request.method
    path = request.url.path
    lookup_key = f"{method}:{path}"
    
    # Try exact match first
    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(lookup_key)
    limit_config = API_ENDPOINT_TO_AUTHENTICATED_MAX_LIMIT_CONFIG.get(lookup_key)
    
    # If no exact match, try pattern matching for paths with parameters
    if counter_field is None or limit_config is None:
        # Handle GET endpoints with path parameters
        # e.g., GET:/api/pdf/abc-123/html -> GET:/api/pdf/{pdf_id}/html
        if method == "GET":
            if path.startswith("/api/pdf/") and path.endswith("/html"):
                pattern_key = f"{method}:/api/pdf/{{pdf_id}}/html"
                counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                limit_config = API_ENDPOINT_TO_AUTHENTICATED_MAX_LIMIT_CONFIG.get(pattern_key)
        # Handle DELETE endpoints with path parameters
        # e.g., DELETE:/api/saved-words/abc-123 -> DELETE:/api/saved-words
        elif method == "DELETE":
            # Try removing the last path segment (the ID parameter)
            path_parts = path.rstrip('/').split('/')
            if len(path_parts) > 0:
                # Try base path without the ID
                base_path = '/'.join(path_parts[:-1])
                if base_path:
                    base_lookup_key = f"{method}:{base_path}"
                    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(base_lookup_key)
                    limit_config = API_ENDPOINT_TO_AUTHENTICATED_MAX_LIMIT_CONFIG.get(base_lookup_key)
        # Handle PATCH endpoints with path parameters
        # e.g., PATCH:/api/saved-image/abc-123/move-to-folder -> PATCH:/api/saved-image/{saved_image_id}/move-to-folder
        # e.g., PATCH:/api/saved-words/abc-123/move-to-folder -> PATCH:/api/saved-words/{word_id}/move-to-folder
        # e.g., PATCH:/api/saved-paragraph/abc-123/move-to-folder -> PATCH:/api/saved-paragraph/{paragraph_id}/move-to-folder
        # e.g., PATCH:/api/saved-link/abc-123/move-to-folder -> PATCH:/api/saved-link/{link_id}/move-to-folder
        # e.g., PATCH:/api/issue/abc-123 -> PATCH:/api/issue/{issue_id}
        elif method == "PATCH":
            # For move-to-folder endpoint, try pattern match
            if path.endswith("/move-to-folder"):
                # Try different move-to-folder patterns
                if path.startswith("/api/saved-image/"):
                    pattern_key = f"{method}:/api/saved-image/{{saved_image_id}}/move-to-folder"
                elif path.startswith("/api/saved-words/"):
                    pattern_key = f"{method}:/api/saved-words/{{word_id}}/move-to-folder"
                elif path.startswith("/api/saved-paragraph/"):
                    pattern_key = f"{method}:/api/saved-paragraph/{{paragraph_id}}/move-to-folder"
                elif path.startswith("/api/saved-link/"):
                    pattern_key = f"{method}:/api/saved-link/{{link_id}}/move-to-folder"
                else:
                    pattern_key = None
                
                if pattern_key:
                    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                    limit_config = API_ENDPOINT_TO_AUTHENTICATED_MAX_LIMIT_CONFIG.get(pattern_key)
            # For issue update endpoint, try pattern match
            elif path.startswith("/api/issue/"):
                path_parts = path.rstrip('/').split('/')
                if len(path_parts) == 3:  # /api/issue/{issue_id}
                    pattern_key = f"{method}:/api/issue/{{issue_id}}"
                    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                    limit_config = API_ENDPOINT_TO_AUTHENTICATED_MAX_LIMIT_CONFIG.get(pattern_key)
    
    # If API counter doesn't exist, treat as unlimited (max int)
    if counter_field is None or limit_config is None:
        return None, sys.maxsize
    
    max_limit = getattr(settings, limit_config, None)
    if max_limit is None:
        # If limit config doesn't exist in settings, treat as unlimited
        return None, sys.maxsize

    return counter_field, max_limit


def should_allow_api_in_case_of_subscriber(
    user_id: str,
    request: Request,
    db: Session
) -> Tuple[bool, bool, bool]:
    """
    Check if user is subscribed and if they should be allowed to access the API.
    
    This function checks the user's subscription status and determines API access
    based on their subscription tier (Ultra vs Plus).
    
    Args:
        user_id: The user's ID
        request: FastAPI request object
        db: Database session
        
    Returns:
        tuple[bool, bool, bool]: (is_subscribed_user, is_api_allowed, needs_rate_limiting)
        - (False, True, False): User is NOT subscribed - let existing rate-limiting handle it
        - (True, True, False): User IS subscribed and API is allowed (unlimited)
        - (True, True, True): User IS subscribed, API is allowed but needs rate limiting (Plus tier)
        - (True, False, False): User IS subscribed but API is NOT allowed (restricted/expired)
    """
    current_time = datetime.now(timezone.utc)
    
    # Step 1: Get existing cache instance (singleton)
    cache = get_in_memory_cache()
    cache_key = f"{SUBSCRIPTION_CACHE_KEY_PREFIX}{user_id}"
    
    # Step 2: Check cache
    cache_entry: Optional[SubscriptionCacheEntry] = cache.get_key(cache_key)
    
    if cache_entry is None or cache_entry.expired_at < current_time:
        # Cache miss or expired - fetch from DB
        subscription = get_user_active_subscription(db, user_id)
        
        # Store in cache with 1 hour TTL
        cache_expired_at = current_time + timedelta(hours=SUBSCRIPTION_CACHE_TTL_HOURS)
        cache_entry = SubscriptionCacheEntry(
            expired_at=cache_expired_at,
            subscription=subscription
        )
        cache.set_key(cache_key, cache_entry)
    
    subscription = cache_entry.subscription
    
    # Step 3: No active subscription - user is not subscribed, let existing flow handle
    if subscription is None:
        return (False, True, False)  # Not subscribed, allow existing rate-limiting to proceed
    
    # Step 4: Check if subscription period has ended
    period_ends_at = subscription.get("current_billing_period_ends_at")
    if period_ends_at:
        ends_at = datetime.fromisoformat(period_ends_at.replace('Z', '+00:00'))
        # Normalize to UTC if Paddle returns datetime without timezone
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=timezone.utc)
        if ends_at < current_time:
            return (True, False, False)  # Subscribed but expired
    
    # Step 5: Determine plan tier from items
    items = subscription.get("items", [])
    if not items:
        return (True, False, False)  # Subscribed but no items (invalid state)
    
    # First item's price name determines the tier
    first_item = items[0]
    price_name = first_item.get("price", {}).get("name", "")
    
    # Step 6: Ultra users - allow all APIs (unlimited, no rate limiting)
    if "Ultra" in price_name:
        return (True, True, False)
    
    # Step 7: Plus users - restrict certain APIs, rate-limit others
    if "Plus" in price_name:
        lookup_key = f"{request.method}:{request.url.path}"
        if lookup_key in PLUS_USER_RESTRICTED_APIS:
            return (True, False, False)  # Subscribed but API restricted for Plus tier
        if lookup_key in PLUS_USER_RATE_LIMITED_APIS:
            return (True, True, True)  # Subscribed, allowed but rate limited for Plus tier
        return (True, True, False)
    
    # Unknown tier - subscribed but deny access
    return (True, False, False)


async def authenticate(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Authentication middleware that handles three cases:
    1. Authenticated user (Authorization header with Bearer token)
    2. Unauthenticated user with ID (X-Unauthenticated-User-Id header)
    3. New unauthenticated user (no headers)
    
    IMPORTANT - INTERNAL IMPLEMENTATION DETAIL:
    ============================================
    When this function raises an HTTPException with status 401 or 429, FastAPI's
    dependency injection system will:
    1. Catch the HTTPException
    2. Use the exception handler to convert it to a JSONResponse
    3. SKIP executing the endpoint function entirely
    4. Return the error response directly to the client
    
    This means:
    - The endpoint's business logic will NOT run
    - No database queries for the endpoint will execute
    - No API service calls will be made
    - The client receives the 401/429 error immediately
    
    This is FastAPI's standard behavior: when a dependency raises an HTTPException,
    it bypasses the endpoint and uses the exception handler to return the response.
    
    Args:
        request: FastAPI request object
        response: FastAPI response object
        db: Database session
        
    Returns:
        Dictionary with authentication context
        
    Raises:
        HTTPException: 401 or 429 for authentication/authorization failures
    """
    # Entry log with request metadata
    authorization_header = request.headers.get("Authorization")
    unauthenticated_user_id = request.headers.get("X-Unauthenticated-User-Id")
    
    # Extract access token from Authorization header (Bearer <token> format)
    access_token = None
    if authorization_header:
        if authorization_header.startswith("Bearer "):
            access_token = authorization_header[7:].strip()  # Remove "Bearer " prefix

    # Case 1: Access token header is available (authenticated user)
    if access_token:
        try:
            # Decode JWT access token
            token_payload = decode_access_token(access_token, verify_exp=False)
            user_session_pk = token_payload.get("user_session_pk")
            
            if not user_session_pk:
                raise_login_required()

            session_data = get_user_session_by_id(db, user_session_pk)
            if not session_data:
                raise_login_required()

            # CRITICAL STEP: Validate session state
            session_state = session_data.get("access_token_state")
            
            # Check if session is INVALID
            if session_state != "VALID":
                raise_login_required()

            # Check if access_token_expires_at has expired
            access_token_expires_at = session_data.get("access_token_expires_at")
            if access_token_expires_at:
                if isinstance(access_token_expires_at, datetime):
                    expires_at = access_token_expires_at
                else:
                    # Parse if it's a string
                    expires_at = datetime.fromisoformat(str(access_token_expires_at).replace('Z', '+00:00'))
                
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                
                current_time = datetime.now(timezone.utc)
                if expires_at < current_time:
                    raise HTTPException(
                        status_code=401,
                        detail={
                            "errorCode": "TOKEN_EXPIRED",
                            "reason": "Please refresh the access token with refresh token"
                        }
                    )

            # CRITICAL STEP: Get user_id from session
            auth_vendor_id = session_data.get("auth_vendor_id")
            if not auth_vendor_id:
                raise_login_required()
            
            user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
            if not user_id:
                raise_login_required()

            # CRITICAL STEP: Check subscription-based API access
            is_subscribed_user, is_api_allowed, needs_rate_limiting = should_allow_api_in_case_of_subscriber(user_id, request, db)
            
            if is_subscribed_user:
                # User has a subscription - check if API is allowed for their tier
                if not is_api_allowed:
                    raise_subscription_required()
                
                if needs_rate_limiting:
                    # Plus subscriber with rate-limited API - apply Plus subscriber limits
                    api_counter_field, max_limit = get_api_counter_field_and_plus_subscriber_max_limit(request)
                    
                    if api_counter_field is None and max_limit == sys.maxsize:
                        # Unlimited access - skip rate limiting checks
                        pass
                    elif not api_counter_field or max_limit is None:
                        raise_subscription_required()
                    else:
                        # CRITICAL STEP: Extract IP address from request
                        ip_address = get_client_ip(request)
                        
                        # CRITICAL STEP: Get or create authenticated user API usage record
                        api_usage = get_authenticated_user_api_usage(db, user_id, ip_address)
                        if not api_usage:
                            # Create new record with all counters initialized to 0
                            create_authenticated_user_api_usage(db, user_id, api_counter_field, ip_address)
                            # Re-fetch to get the newly created record
                            api_usage = get_authenticated_user_api_usage(db, user_id, ip_address)
                            if not api_usage:
                                raise_subscription_required()

                        # CRITICAL STEP: Check if limit exceeded (before incrementing)
                        current_count = api_usage.get(api_counter_field, 0)
                        if current_count >= max_limit:
                            raise_subscription_required()
                        
                        # CRITICAL STEP: Increment usage counter
                        increment_authenticated_api_usage(db, user_id, api_counter_field)
                
                # Subscribed user with allowed API - return success
                return {
                    "authenticated": True,
                    "user_session_pk": user_session_pk,
                    "session_data": session_data
                }

            # User is NOT subscribed - continue with existing rate-limiting logic below
            # CRITICAL STEP: Get API counter field and authenticated max limit
            api_counter_field, max_limit = get_api_counter_field_and_authenticated_max_limit(request)
            
            # If API counter doesn't exist, treat as unlimited (skip rate limiting)
            if api_counter_field is None and max_limit == sys.maxsize:
                # Unlimited access - skip rate limiting checks
                pass
            elif not api_counter_field or max_limit is None:
                raise_subscription_required()
            else:
                # CRITICAL STEP: Extract IP address from request
                ip_address = get_client_ip(request)
                
                # CRITICAL STEP: Get or create authenticated user API usage record
                api_usage = get_authenticated_user_api_usage(db, user_id, ip_address)
                if not api_usage:
                    # Create new record with all counters initialized to 0
                    create_authenticated_user_api_usage(db, user_id, api_counter_field, ip_address)
                    # Re-fetch to get the newly created record
                    api_usage = get_authenticated_user_api_usage(db, user_id, ip_address)
                    if not api_usage:
                        raise_subscription_required()

                # CRITICAL STEP: Check if limit exceeded (before incrementing)
                current_count = api_usage.get(api_counter_field, 0)
                if current_count >= max_limit:
                    raise_subscription_required()
                
                # CRITICAL STEP: Increment usage counter
                increment_authenticated_api_usage(db, user_id, api_counter_field)

            return {
                "authenticated": True,
                "user_session_pk": user_session_pk,
                "session_data": session_data
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise_login_required(reason=f"Invalid access token, please login: {e}")
    
    # Case 2: Unauthenticated user ID header is available
    elif unauthenticated_user_id:
        api_usage = get_unauthenticated_user_usage(db, unauthenticated_user_id)
        if not api_usage:
            raise_login_required()

        # Get API counter field and max limit for this endpoint
        api_counter_field, max_limit = get_api_counter_field_and_limit(request)

        # If API counter doesn't exist, treat as unlimited (skip rate limiting)
        if api_counter_field is None and max_limit == sys.maxsize:
            # Unlimited access - skip rate limiting checks
            pass
        elif not api_counter_field or max_limit is None:
            raise_login_required(status_code=429)
        else:
            # CRITICAL STEP: Check if limit exceeded
            current_count = api_usage.get(api_counter_field, 0)
            if current_count >= max_limit:
                raise_login_required(status_code=429)
            
            # CRITICAL STEP: Increment usage counter
            increment_api_usage(db, unauthenticated_user_id, api_counter_field)

        return {
            "authenticated": False,
            "unauthenticated_user_id": unauthenticated_user_id
        }
    
    # Case 3: Neither header present (new unauthenticated user)
    else:
        print('else:')
        # CRITICAL STEP: Create new unauthenticated user record
        api_counter_field, max_limit = get_api_counter_field_and_limit(request)
        
        # If API counter doesn't exist, treat as unlimited (skip rate limiting)
        if api_counter_field is None and max_limit == sys.maxsize:
            # Unlimited access - create user but skip counter initialization
            # Pass empty string as placeholder since api_name parameter is required
            new_user_id = create_unauthenticated_user_usage(db, "")
        elif max_limit == 0:
            # If max_limit is 0, this API doesn't allow unauthenticated access
            raise_login_required()
        else:
            new_user_id = create_unauthenticated_user_usage(db, api_counter_field)
        return {
            "authenticated": False,
            "unauthenticated_user_id": new_user_id,
            "is_new_unauthenticated_user": True
        }

