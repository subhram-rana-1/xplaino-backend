"""Authentication middleware for API endpoints."""

from typing import Optional, Dict, Any
from fastapi import Request, HTTPException, Depends, Response
from sqlalchemy.orm import Session
import structlog
from datetime import datetime, timezone

from structlog.processors import ExceptionPrettyPrinter

from app.config import settings
from app.database.connection import get_db
from app.services.jwt_service import decode_access_token
from app.services.database_service import (
    get_user_session_by_id,
    get_unauthenticated_user_usage,
    create_unauthenticated_user_usage,
    increment_api_usage,
    check_api_usage_limit,
    get_authenticated_user_api_usage,
    create_authenticated_user_api_usage,
    increment_authenticated_api_usage,
    get_user_id_by_auth_vendor_id
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
    
    # Saved image APIs (method-specific)
    "GET:/api/saved-image": "saved_image_get_api_count_so_far",
    "GET:/api/saved-image/": "saved_image_get_api_count_so_far",
    "POST:/api/saved-image": "saved_image_post_api_count_so_far",
    "POST:/api/saved-image/": "saved_image_post_api_count_so_far",
    "PATCH:/api/saved-image/{saved_image_id}/move-to-folder": "saved_image_move_api_count_so_far",
    "DELETE:/api/saved-image": "saved_image_delete_api_count_so_far",
    "DELETE:/api/saved-image/": "saved_image_delete_api_count_so_far",
    "DELETE:/api/saved-image/{saved_image_id}": "saved_image_delete_api_count_so_far",
    
    # Issue APIs (method-specific)
    "GET:/api/issue/": "issue_get_api_count_so_far",
    "GET:/api/issue/all": "issue_get_all_api_count_so_far",
    "PATCH:/api/issue/{issue_id}": "issue_patch_api_count_so_far",
    "POST:/api/issue/": "issue_post_api_count_so_far",
}

# API endpoint to max limit config mapping (METHOD:URL format)
API_ENDPOINT_TO_MAX_LIMIT_CONFIG = {
    # v1 APIs
    "POST:/api/v1/image-to-text": "image_to_text_api_max_limit",
    "POST:/api/v1/pdf-to-text": "pdf_to_text_api_max_limit",
    "POST:/api/v1/important-words-from-text": "important_words_from_text_v1_api_max_limit",
    "POST:/api/v1/words-explanation": "words_explanation_v1_api_max_limit",
    "POST:/api/v1/get-more-explanations": "get_more_explanations_api_max_limit",
    "GET:/api/v1/get-random-paragraph": "get_random_paragraph_api_max_limit",
    
    # v2 APIs
    "POST:/api/v2/words-explanation": "words_explanation_api_max_limit",
    "POST:/api/v2/simplify": "simplify_api_max_limit",
    "POST:/api/v2/important-words-from-text": "important_words_from_text_v2_api_max_limit",
    "POST:/api/v2/ask": "ask_api_max_limit",
    "POST:/api/v2/pronunciation": "pronunciation_api_max_limit",
    "POST:/api/v2/voice-to-text": "voice_to_text_api_max_limit",
    "POST:/api/v2/translate": "translate_api_max_limit",
    "POST:/api/v2/summarise": "summarise_api_max_limit",
    "POST:/api/v2/web-search": "web_search_api_max_limit",
    "POST:/api/v2/web-search-stream": "web_search_stream_api_max_limit",
    "POST:/api/v2/synonyms": "synonyms_api_max_limit",
    "POST:/api/v2/antonyms": "antonyms_api_max_limit",
    "POST:/api/v2/simplify-image": "simplify_image_api_max_limit",
    "POST:/api/v2/ask-image": "ask_image_api_max_limit",
    
    # Saved words APIs (method-specific)
    "GET:/api/saved-words": "saved_words_get_api_max_limit",
    "GET:/api/saved-words/": "saved_words_get_api_max_limit",
    "POST:/api/saved-words": "saved_words_post_api_max_limit",
    "POST:/api/saved-words/": "saved_words_post_api_max_limit",
    "DELETE:/api/saved-words": "saved_words_delete_api_max_limit",
    "DELETE:/api/saved-words/": "saved_words_delete_api_max_limit",
    
    # Saved paragraph APIs (method-specific)
    "GET:/api/saved-paragraph": "saved_paragraph_get_api_max_limit",
    "GET:/api/saved-paragraph/": "saved_paragraph_get_api_max_limit",
    "POST:/api/saved-paragraph": "saved_paragraph_post_api_max_limit",
    "POST:/api/saved-paragraph/": "saved_paragraph_post_api_max_limit",
    "DELETE:/api/saved-paragraph": "saved_paragraph_delete_api_max_limit",
    "DELETE:/api/saved-paragraph/": "saved_paragraph_delete_api_max_limit",
    "POST:/api/saved-paragraph/folder": "saved_paragraph_folder_post_api_max_limit",
    "DELETE:/api/saved-paragraph/folder": "saved_paragraph_folder_delete_api_max_limit",
    
    # Saved link APIs (method-specific)
    "GET:/api/saved-link": "saved_link_get_api_max_limit",
    "GET:/api/saved-link/": "saved_link_get_api_max_limit",
    "GET:/api/saved-link/{link_id}": "saved_link_get_api_max_limit",
    "POST:/api/saved-link": "saved_link_post_api_max_limit",
    "POST:/api/saved-link/": "saved_link_post_api_max_limit",
    "DELETE:/api/saved-link": "saved_link_delete_api_max_limit",
    "DELETE:/api/saved-link/": "saved_link_delete_api_max_limit",
    "DELETE:/api/saved-link/{link_id}": "saved_link_delete_api_max_limit",
    "POST:/api/saved-link/folder": "saved_link_folder_post_api_max_limit",
    "DELETE:/api/saved-link/folder": "saved_link_folder_delete_api_max_limit",
    
    # Folders APIs (method-specific)
    "GET:/api/folders": "folders_get_api_max_limit",
    "POST:/api/folders": "folders_post_api_max_limit",
    "POST:/api/folders/": "folders_post_api_max_limit",
    
    # Saved image APIs (method-specific)
    "GET:/api/saved-image": "saved_image_get_api_max_limit",
    "GET:/api/saved-image/": "saved_image_get_api_max_limit",
    "POST:/api/saved-image": "saved_image_post_api_max_limit",
    "POST:/api/saved-image/": "saved_image_post_api_max_limit",
    "PATCH:/api/saved-image/{saved_image_id}/move-to-folder": "saved_image_move_api_max_limit",
    "DELETE:/api/saved-image": "saved_image_delete_api_max_limit",
    "DELETE:/api/saved-image/": "saved_image_delete_api_max_limit",
    "DELETE:/api/saved-image/{saved_image_id}": "saved_image_delete_api_max_limit",
    
    # Issue APIs (method-specific)
    "GET:/api/issue/": "issue_get_api_max_limit",
    "GET:/api/issue/all": "issue_get_all_api_max_limit",
    "PATCH:/api/issue/{issue_id}": "issue_patch_api_max_limit",
    "POST:/api/issue/": "issue_post_api_max_limit",
}

# API endpoint to authenticated max limit config mapping (METHOD:URL format)
API_ENDPOINT_TO_AUTHENTICATED_MAX_LIMIT_CONFIG = {
    # v1 APIs
    "POST:/api/v1/image-to-text": "authenticated_image_to_text_api_max_limit",
    "POST:/api/v1/pdf-to-text": "authenticated_pdf_to_text_api_max_limit",
    "POST:/api/v1/important-words-from-text": "authenticated_important_words_from_text_v1_api_max_limit",
    "POST:/api/v1/words-explanation": "authenticated_words_explanation_v1_api_max_limit",
    "POST:/api/v1/get-more-explanations": "authenticated_get_more_explanations_api_max_limit",
    "GET:/api/v1/get-random-paragraph": "authenticated_get_random_paragraph_api_max_limit",
    
    # v2 APIs
    "POST:/api/v2/words-explanation": "authenticated_words_explanation_api_max_limit",
    "POST:/api/v2/simplify": "authenticated_simplify_api_max_limit",
    "POST:/api/v2/important-words-from-text": "authenticated_important_words_from_text_v2_api_max_limit",
    "POST:/api/v2/ask": "authenticated_ask_api_max_limit",
    "POST:/api/v2/pronunciation": "authenticated_pronunciation_api_max_limit",
    "POST:/api/v2/voice-to-text": "authenticated_voice_to_text_api_max_limit",
    "POST:/api/v2/translate": "authenticated_translate_api_max_limit",
    "POST:/api/v2/summarise": "authenticated_summarise_api_max_limit",
    "POST:/api/v2/web-search": "authenticated_web_search_api_max_limit",
    "POST:/api/v2/web-search-stream": "authenticated_web_search_stream_api_max_limit",
    "POST:/api/v2/synonyms": "authenticated_synonyms_api_max_limit",
    "POST:/api/v2/antonyms": "authenticated_antonyms_api_max_limit",
    "POST:/api/v2/simplify-image": "authenticated_simplify_image_api_max_limit",
    "POST:/api/v2/ask-image": "authenticated_ask_image_api_max_limit",
    
    # Saved words APIs (method-specific)
    "GET:/api/saved-words": "authenticated_saved_words_get_api_max_limit",
    "GET:/api/saved-words/": "authenticated_saved_words_get_api_max_limit",
    "POST:/api/saved-words": "authenticated_saved_words_post_api_max_limit",
    "POST:/api/saved-words/": "authenticated_saved_words_post_api_max_limit",
    "DELETE:/api/saved-words": "authenticated_saved_words_delete_api_max_limit",
    "DELETE:/api/saved-words/": "authenticated_saved_words_delete_api_max_limit",
    
    # Saved paragraph APIs (method-specific)
    "GET:/api/saved-paragraph": "authenticated_saved_paragraph_get_api_max_limit",
    "GET:/api/saved-paragraph/": "authenticated_saved_paragraph_get_api_max_limit",
    "POST:/api/saved-paragraph": "authenticated_saved_paragraph_post_api_max_limit",
    "POST:/api/saved-paragraph/": "authenticated_saved_paragraph_post_api_max_limit",
    "DELETE:/api/saved-paragraph": "authenticated_saved_paragraph_delete_api_max_limit",
    "DELETE:/api/saved-paragraph/": "authenticated_saved_paragraph_delete_api_max_limit",
    "POST:/api/saved-paragraph/folder": "authenticated_saved_paragraph_folder_post_api_max_limit",
    "DELETE:/api/saved-paragraph/folder": "authenticated_saved_paragraph_folder_delete_api_max_limit",
    
    # Saved link APIs (method-specific)
    "GET:/api/saved-link": "authenticated_saved_link_get_api_max_limit",
    "GET:/api/saved-link/": "authenticated_saved_link_get_api_max_limit",
    "GET:/api/saved-link/{link_id}": "authenticated_saved_link_get_api_max_limit",
    "POST:/api/saved-link": "authenticated_saved_link_post_api_max_limit",
    "POST:/api/saved-link/": "authenticated_saved_link_post_api_max_limit",
    "DELETE:/api/saved-link": "authenticated_saved_link_delete_api_max_limit",
    "DELETE:/api/saved-link/": "authenticated_saved_link_delete_api_max_limit",
    "DELETE:/api/saved-link/{link_id}": "authenticated_saved_link_delete_api_max_limit",
    "POST:/api/saved-link/folder": "authenticated_saved_link_folder_post_api_max_limit",
    "DELETE:/api/saved-link/folder": "authenticated_saved_link_folder_delete_api_max_limit",
    
    # Folders APIs (method-specific)
    "GET:/api/folders": "authenticated_folders_get_api_max_limit",
    "POST:/api/folders": "authenticated_folders_post_api_max_limit",
    "POST:/api/folders/": "authenticated_folders_post_api_max_limit",
    
    # Saved image APIs (method-specific)
    "GET:/api/saved-image": "authenticated_saved_image_get_api_max_limit",
    "GET:/api/saved-image/": "authenticated_saved_image_get_api_max_limit",
    "POST:/api/saved-image": "authenticated_saved_image_post_api_max_limit",
    "POST:/api/saved-image/": "authenticated_saved_image_post_api_max_limit",
    "PATCH:/api/saved-image/{saved_image_id}/move-to-folder": "authenticated_saved_image_move_api_max_limit",
    "DELETE:/api/saved-image": "authenticated_saved_image_delete_api_max_limit",
    "DELETE:/api/saved-image/": "authenticated_saved_image_delete_api_max_limit",
    "DELETE:/api/saved-image/{saved_image_id}": "authenticated_saved_image_delete_api_max_limit",
    
    # Issue APIs (method-specific)
    "GET:/api/issue/": "authenticated_issue_get_api_max_limit",
    "GET:/api/issue/all": "authenticated_issue_get_all_api_max_limit",
    "PATCH:/api/issue/{issue_id}": "authenticated_issue_patch_api_max_limit",
    "POST:/api/issue/": "authenticated_issue_post_api_max_limit",
}


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
        # Handle DELETE endpoints with path parameters
        # e.g., DELETE:/api/saved-words/abc-123 -> DELETE:/api/saved-words
        if method == "DELETE":
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
        # e.g., PATCH:/api/issue/abc-123 -> PATCH:/api/issue/{issue_id}
        elif method == "PATCH":
            # For move-to-folder endpoint, try pattern match
            if path.endswith("/move-to-folder"):
                pattern_key = f"{method}:/api/saved-image/{{saved_image_id}}/move-to-folder"
                counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                limit_config = API_ENDPOINT_TO_MAX_LIMIT_CONFIG.get(pattern_key)
            # For issue update endpoint, try pattern match
            elif path.startswith("/api/issue/"):
                path_parts = path.rstrip('/').split('/')
                if len(path_parts) == 3:  # /api/issue/{issue_id}
                    pattern_key = f"{method}:/api/issue/{{issue_id}}"
                    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                    limit_config = API_ENDPOINT_TO_MAX_LIMIT_CONFIG.get(pattern_key)
    
    if counter_field is None:
        raise Exception(f"API counter field not found for: {lookup_key}")

    if limit_config is None:
        raise Exception(f"API limit config not found for: {lookup_key}")
    
    max_limit = getattr(settings, limit_config, None)
    if max_limit is None:
        raise Exception(f"API maximum limit not found for: {lookup_key}")

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


def get_api_counter_field_and_authenticated_limit(request: Request) -> tuple[Optional[str], Optional[int]]:
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
        # Handle DELETE endpoints with path parameters
        # e.g., DELETE:/api/saved-words/abc-123 -> DELETE:/api/saved-words
        if method == "DELETE":
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
        # e.g., PATCH:/api/issue/abc-123 -> PATCH:/api/issue/{issue_id}
        elif method == "PATCH":
            # For move-to-folder endpoint, try pattern match
            if path.endswith("/move-to-folder"):
                pattern_key = f"{method}:/api/saved-image/{{saved_image_id}}/move-to-folder"
                counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                limit_config = API_ENDPOINT_TO_AUTHENTICATED_MAX_LIMIT_CONFIG.get(pattern_key)
            # For issue update endpoint, try pattern match
            elif path.startswith("/api/issue/"):
                path_parts = path.rstrip('/').split('/')
                if len(path_parts) == 3:  # /api/issue/{issue_id}
                    pattern_key = f"{method}:/api/issue/{{issue_id}}"
                    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(pattern_key)
                    limit_config = API_ENDPOINT_TO_AUTHENTICATED_MAX_LIMIT_CONFIG.get(pattern_key)
    
    if counter_field is None:
        raise Exception(f"API counter field not found for: {lookup_key}")

    if limit_config is None:
        raise Exception(f"API authenticated limit config not found for: {lookup_key}")
    
    max_limit = getattr(settings, limit_config, None)
    if max_limit is None:
        raise Exception(f"API authenticated maximum limit not found for: {lookup_key}")

    return counter_field, max_limit


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

            # CRITICAL STEP: Get API counter field and authenticated max limit
            api_counter_field, max_limit = get_api_counter_field_and_authenticated_limit(request)
            
            if not api_counter_field or max_limit is None:
                raise_subscription_required()

            # CRITICAL STEP: Get or create authenticated user API usage record
            api_usage = get_authenticated_user_api_usage(db, user_id)
            if not api_usage:
                # Create new record with all counters initialized to 0
                create_authenticated_user_api_usage(db, user_id, api_counter_field)
                # Re-fetch to get the newly created record
                api_usage = get_authenticated_user_api_usage(db, user_id)
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
            raise_login_required(f"Invalid access token, please login: {e}")
    
    # Case 2: Unauthenticated user ID header is available
    elif unauthenticated_user_id:
        api_usage = get_unauthenticated_user_usage(db, unauthenticated_user_id)
        if not api_usage:
            raise_login_required()

        # Get API counter field and max limit for this endpoint
        api_counter_field, max_limit = get_api_counter_field_and_limit(request)

        # Now check if we can determine the API counter field and max limit
        if not api_counter_field or max_limit is None:
            raise_login_required(status_code=429)
        
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
        
        # If max_limit is 0, this API doesn't allow unauthenticated access
        if max_limit == 0:
            raise_login_required()
        
        new_user_id = create_unauthenticated_user_usage(db, api_counter_field)
        return {
            "authenticated": False,
            "unauthenticated_user_id": new_user_id,
            "is_new_unauthenticated_user": True
        }

