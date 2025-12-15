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
    check_api_usage_limit
)

logger = structlog.get_logger()

# API endpoint to counter field name mapping
API_ENDPOINT_TO_COUNTER_FIELD = {
    # v1 APIs
    "/api/v1/image-to-text": "image_to_text_api_count_so_far",
    "/api/v1/pdf-to-text": "pdf_to_text_api_count_so_far",
    "/api/v1/important-words-from-text": "important_words_from_text_v1_api_count_so_far",
    "/api/v1/words-explanation": "words_explanation_v1_api_count_so_far",
    "/api/v1/get-more-explanations": "get_more_explanations_api_count_so_far",
    "/api/v1/get-random-paragraph": "get_random_paragraph_api_count_so_far",
    
    # v2 APIs
    "/api/v2/words-explanation": "words_explanation_api_count_so_far",
    "/api/v2/simplify": "simplify_api_count_so_far",
    "/api/v2/important-words-from-text": "important_words_from_text_v2_api_count_so_far",
    "/api/v2/ask": "ask_api_count_so_far",
    "/api/v2/pronunciation": "pronunciation_api_count_so_far",
    "/api/v2/voice-to-text": "voice_to_text_api_count_so_far",
    "/api/v2/translate": "translate_api_count_so_far",
    "/api/v2/summarise": "summarise_api_count_so_far",
    "/api/v2/web-search": "web_search_api_count_so_far",
    "/api/v2/web-search-stream": "web_search_stream_api_count_so_far",
    
    # Saved words APIs
    "/api/saved-words": "saved_words_api_count_so_far",
    
    # Saved paragraph APIs
    "/api/saved-paragraph": "saved_paragraph_api_count_so_far",
    "/api/saved-paragraph/folder": "saved_paragraph_folder_api_count_so_far",
}

# API endpoint to max limit config mapping
API_ENDPOINT_TO_MAX_LIMIT_CONFIG = {
    # v1 APIs
    "/api/v1/image-to-text": "image_to_text_api_max_limit",
    "/api/v1/pdf-to-text": "pdf_to_text_api_max_limit",
    "/api/v1/important-words-from-text": "important_words_from_text_v1_api_max_limit",
    "/api/v1/words-explanation": "words_explanation_v1_api_max_limit",
    "/api/v1/get-more-explanations": "get_more_explanations_api_max_limit",
    "/api/v1/get-random-paragraph": "get_random_paragraph_api_max_limit",
    
    # v2 APIs
    "/api/v2/words-explanation": "words_explanation_api_max_limit",
    "/api/v2/simplify": "simplify_api_max_limit",
    "/api/v2/important-words-from-text": "important_words_from_text_v2_api_max_limit",
    "/api/v2/ask": "ask_api_max_limit",
    "/api/v2/pronunciation": "pronunciation_api_max_limit",
    "/api/v2/voice-to-text": "voice_to_text_api_max_limit",
    "/api/v2/translate": "translate_api_max_limit",
    "/api/v2/summarise": "summarise_api_max_limit",
    "/api/v2/web-search": "web_search_api_max_limit",
    "/api/v2/web-search-stream": "web_search_stream_api_max_limit",
    
    # Saved words APIs
    "/api/saved-words": "saved_words_api_max_limit",
    
    # Saved paragraph APIs
    "/api/saved-paragraph": "saved_paragraph_api_max_limit",
    "/api/saved-paragraph/folder": "saved_paragraph_folder_api_max_limit",
}


def get_api_counter_field_and_limit(request: Request) -> tuple[Optional[str], Optional[int]]:
    """
    Get the API counter field name and max limit for the current request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Tuple of (counter_field_name, max_limit) or (None, None) if not found
    """
    path = request.url.path
    
    # Try exact match first
    counter_field = API_ENDPOINT_TO_COUNTER_FIELD.get(path)
    if counter_field is None:
        raise Exception(f"API counter field not found for: {path}")

    limit_config = API_ENDPOINT_TO_MAX_LIMIT_CONFIG.get(path)
    if limit_config is None:
        raise Exception(f"API limit config not found for: {path}")
    
    max_limit = getattr(settings, limit_config, None)
    if max_limit is None:
        raise Exception(f"API maximum limit not found for: {path}")

    return counter_field, max_limit


def raise_login_required(status_code: int = 401, reason: str = "Please login") -> None:
    raise HTTPException(
        status_code=status_code,
        detail={
            "errorCode": "LOGIN_REQUIRED",
            "message": reason
        }
    )


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

            return {
                "authenticated": True,
                "user_session_pk": user_session_pk,
                "session_data": session_data
            }
            
        except HTTPException:
            raise
        except Exception as e:
            raise_login_required("Invalid access token, please login")
    
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
        # CRITICAL STEP: Create new unauthenticated user record
        new_user_id = create_unauthenticated_user_usage(db, api_counter_field)
        return {
            "authenticated": False,
            "unauthenticated_user_id": new_user_id,
            "is_new_unauthenticated_user": True
        }

