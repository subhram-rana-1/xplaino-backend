"""Database service for user and session management."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import text
import secrets
import string
import time
import uuid
import structlog
import json

from app.config import settings
from app.services.in_memory_cache.cache_factory import get_in_memory_cache

logger = structlog.get_logger()


def get_or_create_user_by_google_sub(
    db: Session,
    sub: str,
    google_data: dict
) -> Tuple[str, str, bool]:
    """
    Get or create user and google_user_auth_info records.
    
    Args:
        db: Database session
        sub: Google user ID (sub field)
        google_data: Decoded Google token data
        
    Returns:
        Tuple of (user_id, google_auth_info_id, is_new_user)
    """
    # Entry log
    logger.info(
        "Getting or creating user by Google sub",
        function="get_or_create_user_by_google_sub",
        sub=sub,
        has_email=bool(google_data.get("email")),
        email_verified=google_data.get("email_verified", False)
    )
    
    # Check if sub exists in google_user_auth_info
    logger.debug(
        "Querying database for existing user by sub",
        function="get_or_create_user_by_google_sub",
        sub=sub
    )
    result = db.execute(
        text("SELECT id, user_id FROM google_user_auth_info WHERE sub = :sub"),
        {"sub": sub}
    ).fetchone()
    
    if result:
        # User exists, update google_user_auth_info
        google_auth_info_id = result[0]
        user_id = result[1]
        is_new_user = False
        
        logger.debug(
            "Existing user found, updating google_user_auth_info",
            function="get_or_create_user_by_google_sub",
            sub=sub,
            user_id=user_id,
            google_auth_info_id=google_auth_info_id
        )
        
        # Update google_user_auth_info
        db.execute(
            text("""
                UPDATE google_user_auth_info 
                SET iss = :iss, email = :email, email_verified = :email_verified,
                    given_name = :given_name, family_name = :family_name,
                    picture = :picture, locale = :locale, azp = :azp,
                    aud = :aud, iat = :iat, exp = :exp, jti = :jti,
                    alg = :alg, kid = :kid, typ = :typ, hd = :hd,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
            """),
            {
                "id": google_auth_info_id,
                "iss": google_data.get("iss"),
                "email": google_data.get("email"),
                "email_verified": google_data.get("email_verified", False),
                "given_name": google_data.get("given_name"),
                "family_name": google_data.get("family_name"),
                "picture": google_data.get("picture"),
                "locale": google_data.get("locale"),
                "azp": google_data.get("azp"),
                "aud": google_data.get("aud"),
                "iat": str(google_data.get("iat", "")),
                "exp": str(google_data.get("exp", "")),
                "jti": google_data.get("jti"),
                "alg": google_data.get("alg"),
                "kid": google_data.get("kid"),
                "typ": google_data.get("typ"),
                "hd": google_data.get("hd")
            }
        )
        
        logger.info(
            "Updated existing user",
            function="get_or_create_user_by_google_sub",
            user_id=user_id,
            google_auth_info_id=google_auth_info_id,
            sub=sub
        )
    else:
        # New user, create records
        is_new_user = True
        
        logger.debug(
            "No existing user found, creating new user",
            function="get_or_create_user_by_google_sub",
            sub=sub
        )
        
        # Generate user_id
        user_id = str(uuid.uuid4())
        
        logger.debug(
            "Creating user record",
            function="get_or_create_user_by_google_sub",
            user_id=user_id,
            sub=sub
        )
        
        # Create user record
        db.execute(
            text("INSERT INTO user (id) VALUES (:user_id)"),
            {"user_id": user_id}
        )
        db.flush()
        
        # Generate google_auth_info_id
        google_auth_info_id = str(uuid.uuid4())
        
        logger.debug(
            "Creating google_user_auth_info record",
            function="get_or_create_user_by_google_sub",
            user_id=user_id,
            google_auth_info_id=google_auth_info_id,
            sub=sub
        )
        
        # Create google_user_auth_info record
        db.execute(
            text("""
                INSERT INTO google_user_auth_info 
                (id, user_id, iss, sub, email, email_verified, given_name, family_name,
                 picture, locale, azp, aud, iat, exp, jti, alg, kid, typ, hd)
                VALUES 
                (:id, :user_id, :iss, :sub, :email, :email_verified, :given_name,
                 :family_name, :picture, :locale, :azp, :aud, :iat, :exp, :jti,
                 :alg, :kid, :typ, :hd)
            """),
            {
                "id": google_auth_info_id,
                "user_id": user_id,
                "iss": google_data.get("iss"),
                "sub": sub,
                "email": google_data.get("email"),
                "email_verified": google_data.get("email_verified", False),
                "given_name": google_data.get("given_name"),
                "family_name": google_data.get("family_name"),
                "picture": google_data.get("picture"),
                "locale": google_data.get("locale"),
                "azp": google_data.get("azp"),
                "aud": google_data.get("aud"),
                "iat": str(google_data.get("iat", "")),
                "exp": str(google_data.get("exp", "")),
                "jti": google_data.get("jti"),
                "alg": google_data.get("alg"),
                "kid": google_data.get("kid"),
                "typ": google_data.get("typ"),
                "hd": google_data.get("hd")
            }
        )
        db.flush()
        
        logger.info(
            "Created new user",
            function="get_or_create_user_by_google_sub",
            user_id=user_id,
            google_auth_info_id=google_auth_info_id,
            sub=sub,
            email=google_data.get("email")
        )
    
    db.commit()
    
    logger.info(
        "User lookup/creation completed",
        function="get_or_create_user_by_google_sub",
        user_id=user_id,
        google_auth_info_id=google_auth_info_id,
        is_new_user=is_new_user,
        sub=sub
    )
    
    return user_id, google_auth_info_id, is_new_user


def get_or_create_user_session(
    db: Session,
    auth_vendor_type: str,
    auth_vendor_id: str,
    is_new_user: bool
) -> Tuple[str, str, datetime]:
    """
    Get or create user session and update refresh token.
    
    Args:
        db: Database session
        auth_vendor_type: Authentication vendor type (e.g., 'GOOGLE')
        auth_vendor_id: Primary key of google_user_auth_info
        is_new_user: Whether this is a new user
        
    Returns:
        Tuple of (session_id, refresh_token, refresh_token_expires_at)
    """
    # Entry log
    logger.info(
        "Getting or creating user session",
        function="get_or_create_user_session",
        auth_vendor_type=auth_vendor_type,
        auth_vendor_id=auth_vendor_id,
        is_new_user=is_new_user
    )
    
    # Generate new refresh token
    refresh_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expiry_days)
    access_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.access_token_expiry_hours)
    
    refresh_token_preview = refresh_token[:8] + "..." if refresh_token else None
    logger.debug(
        "Refresh token generated",
        function="get_or_create_user_session",
        refresh_token_preview=refresh_token_preview,
        expires_at=str(expires_at)
    )
    
    if is_new_user:
        # Generate session_id
        session_id = str(uuid.uuid4())
        
        logger.debug(
            "Creating new session for new user",
            function="get_or_create_user_session",
            session_id=session_id,
            auth_vendor_type=auth_vendor_type,
            auth_vendor_id=auth_vendor_id
        )
        
        # Create new session
        db.execute(
            text("""
                INSERT INTO user_session 
                (id, auth_vendor_type, auth_vendor_id, access_token_state,
                 refresh_token, refresh_token_expires_at, access_token_expires_at)
                VALUES 
                (:id, :auth_vendor_type, :auth_vendor_id, 'VALID',
                 :refresh_token, :refresh_token_expires_at, :access_token_expires_at)
            """),
            {
                "id": session_id,
                "auth_vendor_type": auth_vendor_type,
                "auth_vendor_id": auth_vendor_id,
                "refresh_token": refresh_token,
                "refresh_token_expires_at": expires_at,
                "access_token_expires_at": access_token_expires_at
            }
        )
        db.flush()
        
        logger.info(
            "Created new session",
            function="get_or_create_user_session",
            session_id=session_id,
            auth_vendor_type=auth_vendor_type,
            auth_vendor_id=auth_vendor_id
        )
    else:
        # Update existing session
        logger.debug(
            "Looking up existing session for user",
            function="get_or_create_user_session",
            auth_vendor_type=auth_vendor_type,
            auth_vendor_id=auth_vendor_id
        )
        session_result = db.execute(
            text("""
                SELECT id FROM user_session 
                WHERE auth_vendor_type = :auth_vendor_type 
                AND auth_vendor_id = :auth_vendor_id
                ORDER BY updated_at DESC LIMIT 1
            """),
            {
                "auth_vendor_type": auth_vendor_type,
                "auth_vendor_id": auth_vendor_id
            }
        ).fetchone()
        
        if session_result:
            session_id = session_result[0]
            logger.debug(
                "Existing session found, updating",
                function="get_or_create_user_session",
                session_id=session_id,
                auth_vendor_type=auth_vendor_type,
                auth_vendor_id=auth_vendor_id
            )
            # Update session
            db.execute(
                text("""
                    UPDATE user_session 
                    SET access_token_state = 'VALID',
                        refresh_token = :refresh_token,
                        refresh_token_expires_at = :refresh_token_expires_at,
                        access_token_expires_at = :access_token_expires_at,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :session_id
                """),
                {
                    "session_id": session_id,
                    "refresh_token": refresh_token,
                    "refresh_token_expires_at": expires_at,
                    "access_token_expires_at": access_token_expires_at
                }
            )
            logger.info(
                "Updated existing session",
                function="get_or_create_user_session",
                session_id=session_id,
                auth_vendor_type=auth_vendor_type,
                auth_vendor_id=auth_vendor_id
            )
        else:
            # No session found, create one
            session_id = str(uuid.uuid4())
            
            logger.debug(
                "No existing session found, creating new session",
                function="get_or_create_user_session",
                session_id=session_id,
                auth_vendor_type=auth_vendor_type,
                auth_vendor_id=auth_vendor_id
            )
            
            db.execute(
                text("""
                    INSERT INTO user_session 
                    (id, auth_vendor_type, auth_vendor_id, access_token_state,
                     refresh_token, refresh_token_expires_at, access_token_expires_at)
                    VALUES 
                    (:id, :auth_vendor_type, :auth_vendor_id, 'VALID',
                     :refresh_token, :refresh_token_expires_at, :access_token_expires_at)
                """),
                {
                    "id": session_id,
                    "auth_vendor_type": auth_vendor_type,
                    "auth_vendor_id": auth_vendor_id,
                    "refresh_token": refresh_token,
                    "refresh_token_expires_at": expires_at,
                    "access_token_expires_at": access_token_expires_at
                }
            )
            db.flush()
            logger.info(
                "Created new session for existing user",
                function="get_or_create_user_session",
                session_id=session_id,
                auth_vendor_type=auth_vendor_type,
                auth_vendor_id=auth_vendor_id
            )
    
    db.commit()
    
    logger.info(
        "User session operation completed",
        function="get_or_create_user_session",
        session_id=session_id,
        auth_vendor_type=auth_vendor_type,
        refresh_token_preview=refresh_token_preview,
        expires_at=str(expires_at)
    )
    
    return session_id, refresh_token, expires_at


def invalidate_user_session(
    db: Session,
    auth_vendor_type: str,
    sub: str
) -> bool:
    """
    Invalidate user session by marking access_token_state as INVALID.
    
    Args:
        db: Database session
        auth_vendor_type: Authentication vendor type (e.g., 'GOOGLE')
        sub: Google user ID (sub field)
        
    Returns:
        True if session was found and invalidated, False otherwise
    """
    # Entry log
    logger.info(
        "Invalidating user session",
        function="invalidate_user_session",
        auth_vendor_type=auth_vendor_type,
        sub=sub
    )
    
    # First, get the google_auth_info_id from sub
    logger.debug(
        "Looking up google_auth_info_id by sub",
        function="invalidate_user_session",
        sub=sub
    )
    google_auth_result = db.execute(
        text("SELECT id FROM google_user_auth_info WHERE sub = :sub"),
        {"sub": sub}
    ).fetchone()
    
    if not google_auth_result:
        logger.warning(
            "No google_auth_info found for sub",
            function="invalidate_user_session",
            sub=sub,
            auth_vendor_type=auth_vendor_type
        )
        return False
    
    google_auth_info_id = google_auth_result[0]
    
    logger.debug(
        "Google auth info found, invalidating session",
        function="invalidate_user_session",
        sub=sub,
        google_auth_info_id=google_auth_info_id,
        auth_vendor_type=auth_vendor_type
    )
    
    # Update the session to mark it as INVALID
    result = db.execute(
        text("""
            UPDATE user_session 
            SET access_token_state = 'INVALID',
                updated_at = CURRENT_TIMESTAMP
            WHERE auth_vendor_type = :auth_vendor_type 
            AND auth_vendor_id = :auth_vendor_id
            AND access_token_state = 'VALID'
        """),
        {
            "auth_vendor_type": auth_vendor_type,
            "auth_vendor_id": google_auth_info_id
        }
    )
    
    db.commit()
    
    if result.rowcount > 0:
        logger.info(
            "Session invalidated successfully",
            function="invalidate_user_session",
            auth_vendor_type=auth_vendor_type,
            sub=sub,
            google_auth_info_id=google_auth_info_id,
            rows_updated=result.rowcount
        )
        return True
    else:
        logger.warning(
            "No valid session found to invalidate",
            function="invalidate_user_session",
            auth_vendor_type=auth_vendor_type,
            sub=sub,
            google_auth_info_id=google_auth_info_id,
            rows_updated=result.rowcount
        )
        return False


def get_user_info_by_sub(
    db: Session,
    sub: str
) -> Optional[dict]:
    """
    Get user information by Google sub.
    
    Args:
        db: Database session
        sub: Google user ID (sub field)
        
    Returns:
        Dictionary with user information (user_id, name, first_name, last_name, email, picture)
        or None if user not found
    """
    # Entry log
    logger.info(
        "Getting user info by sub",
        function="get_user_info_by_sub",
        sub=sub
    )
    
    logger.debug(
        "Querying database for user info",
        function="get_user_info_by_sub",
        sub=sub
    )
    result = db.execute(
        text("""
            SELECT 
                u.id as user_id,
                g.given_name,
                g.family_name,
                g.email,
                g.picture
            FROM google_user_auth_info g
            INNER JOIN user u ON g.user_id = u.id
            WHERE g.sub = :sub
        """),
        {"sub": sub}
    ).fetchone()
    
    if not result:
        logger.warning(
            "User not found for sub",
            function="get_user_info_by_sub",
            sub=sub
        )
        return None
    
    user_id, given_name, family_name, email, picture = result
    
    # Construct full name
    name_parts = []
    if given_name:
        name_parts.append(given_name)
    if family_name:
        name_parts.append(family_name)
    name = " ".join(name_parts).strip() if name_parts else ""
    
    logger.info(
        "User info retrieved successfully",
        function="get_user_info_by_sub",
        user_id=user_id,
        sub=sub,
        email=email,
        has_name=bool(name),
        has_picture=bool(picture)
    )
    
    return {
        "user_id": user_id,
        "name": name,
        "first_name": given_name,
        "last_name": family_name,
        "email": email,
        "picture": picture
    }


def get_unauthenticated_user_usage(
    db: Session,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get unauthenticated user API usage record.
    
    Args:
        db: Database session
        user_id: Unauthenticated user ID (UUID)
        
    Returns:
        Dictionary with api_usage JSON data or None if not found
    """
    result = db.execute(
        text("SELECT api_usage FROM unauthenticated_user_api_usage WHERE user_id = :user_id"),
        {"user_id": user_id}
    ).fetchone()
    
    if not result:
        return None
    
    api_usage_json = result[0]
    if isinstance(api_usage_json, str):
        api_usage = json.loads(api_usage_json)
    else:
        api_usage = api_usage_json
    
    return api_usage


def create_unauthenticated_user_usage(
    db: Session,
    api_name: str
) -> str:
    """
    Create a new unauthenticated user API usage record.
    
    Args:
        db: Database session
        api_name: Name of the API being called (used to initialize counter)
        
    Returns:
        Newly created user_id (UUID)
    """
    user_id = str(uuid.uuid4())
    
    # Initialize API usage JSON with all counters set to 0
    api_usage = {
        "words_explanation_api_count_so_far": 0,
        "get_more_explanations_api_count_so_far": 0,
        "ask_api_count_so_far": 0,
        "simplify_api_count_so_far": 0,
        "summarise_api_count_so_far": 0,
        "image_to_text_api_count_so_far": 0,
        "pdf_to_text_api_count_so_far": 0,
        "important_words_from_text_v1_api_count_so_far": 0,
        "words_explanation_v1_api_count_so_far": 0,
        "get_random_paragraph_api_count_so_far": 0,
        "important_words_from_text_v2_api_count_so_far": 0,
        "pronunciation_api_count_so_far": 0,
        "voice_to_text_api_count_so_far": 0,
        "translate_api_count_so_far": 0,
        "web_search_api_count_so_far": 0,
        "web_search_stream_api_count_so_far": 0,
        "saved_words_api_count_so_far": 0
    }
    
    # Set the current API count to 1 (this API was just called)
    if api_name in api_usage:
        api_usage[api_name] = 1
    else:
        # If api_name is not in the dictionary, add it and set to 1
        logger.warning(
            "API name not found in api_usage dictionary, adding it",
            api_name=api_name
        )
        api_usage[api_name] = 1
    
    db.execute(
        text("""
            INSERT INTO unauthenticated_user_api_usage 
            (user_id, api_usage)
            VALUES 
            (:user_id, :api_usage)
        """),
        {
            "user_id": user_id,
            "api_usage": json.dumps(api_usage)
        }
    )
    db.commit()
    
    logger.info("Created unauthenticated user API usage record", user_id=user_id, api_name=api_name)
    return user_id


def increment_api_usage(
    db: Session,
    user_id: str,
    api_name: str
) -> None:
    """
    Increment the API usage counter for a specific API.
    
    Args:
        db: Database session
        user_id: Unauthenticated user ID (UUID)
        api_name: Name of the API counter field to increment
    """
    # Get current usage
    result = db.execute(
        text("SELECT api_usage FROM unauthenticated_user_api_usage WHERE user_id = :user_id"),
        {"user_id": user_id}
    ).fetchone()
    
    if not result:
        logger.warning("Unauthenticated user usage record not found", user_id=user_id)
        return
    
    api_usage_json = result[0]
    if isinstance(api_usage_json, str):
        api_usage = json.loads(api_usage_json)
    else:
        api_usage = api_usage_json
    
    # Increment the counter
    if api_name in api_usage:
        api_usage[api_name] = api_usage.get(api_name, 0) + 1
    else:
        api_usage[api_name] = 1
    
    # Update the record
    db.execute(
        text("""
            UPDATE unauthenticated_user_api_usage 
            SET api_usage = :api_usage,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = :user_id
        """),
        {
            "user_id": user_id,
            "api_usage": json.dumps(api_usage)
        }
    )
    db.commit()
    
    logger.info("Incremented API usage", user_id=user_id, api_name=api_name, count=api_usage[api_name])


def check_api_usage_limit(
    db: Session,
    user_id: str,
    api_name: str,
    max_limit: int
) -> bool:
    """
    Check if API usage has exceeded the maximum limit.
    
    Args:
        db: Database session
        user_id: Unauthenticated user ID (UUID)
        api_name: Name of the API counter field to check
        max_limit: Maximum allowed usage count
        
    Returns:
        True if limit is exceeded, False otherwise
    """
    api_usage = get_unauthenticated_user_usage(db, user_id)
    
    if not api_usage:
        return True  # No record found, consider as limit exceeded
    
    current_count = api_usage.get(api_name, 0)
    return current_count >= max_limit


def get_user_session_by_id(
    db: Session,
    session_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get user session by session ID.
    
    Args:
        db: Database session
        session_id: User session ID (primary key)
        
    Returns:
        Dictionary with session data or None if not found
    """
    # Get cache instance
    cache = get_in_memory_cache()
    cache_key = f"USER_SESSION_INFO:{session_id}"
    
    # Check cache first
    cached_session = cache.get_key(cache_key)
    if cached_session is not None:
        return cached_session
    
    result = db.execute(
        text("""
            SELECT id, auth_vendor_type, auth_vendor_id, access_token_state,
                   refresh_token, refresh_token_expires_at, access_token_expires_at
            FROM user_session 
            WHERE id = :session_id
        """),
        {"session_id": session_id}
    ).fetchone()
    
    if not result:
        return None
    
    session_data = {
        "id": result[0],
        "auth_vendor_type": result[1],
        "auth_vendor_id": result[2],
        "access_token_state": result[3],
        "refresh_token": result[4],
        "refresh_token_expires_at": result[5],
        "access_token_expires_at": result[6]
    }
    
    # Store in cache before returning
    cache.set_key(cache_key, session_data)

    return session_data


def update_user_session_refresh_token(
    db: Session,
        session_id: str,
    access_token_expires_at: Optional[datetime] = None
) -> Tuple[str, datetime]:
    """
    Update refresh token and expiry for a user session.
    Also updates access_token_expires_at and sets access_token_state to VALID if access_token_expires_at is provided.
    
    Args:
        db: Database session
        session_id: User session ID (primary key)
        access_token_expires_at: Optional access token expiry datetime. If provided, also updates access_token_expires_at and sets access_token_state to 'VALID'
        
    Returns:
        Tuple of (new_refresh_token, new_refresh_token_expires_at)
    """
    # Entry log
    logger.info(
        "Updating user session refresh token",
        function="update_user_session_refresh_token",
        session_id=session_id
    )
    
    # Generate new refresh token
    refresh_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    
    refresh_token_preview = refresh_token[:8] + "..." if refresh_token else None
    logger.debug(
        "New refresh token generated",
        function="update_user_session_refresh_token",
        session_id=session_id,
        refresh_token_preview=refresh_token_preview,
        expires_at=str(expires_at)
    )
    
    # Update the session
    logger.debug(
        "Updating session in database",
        function="update_user_session_refresh_token",
        session_id=session_id,
        has_access_token_expires_at=access_token_expires_at is not None
    )
    
    # Build SQL query based on whether access_token_expires_at is provided
    if access_token_expires_at:
        db.execute(
            text("""
                UPDATE user_session 
                SET refresh_token = :refresh_token,
                    refresh_token_expires_at = :refresh_token_expires_at,
                    access_token_expires_at = :access_token_expires_at,
                    access_token_state = 'VALID',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :session_id
            """),
            {
                "session_id": session_id,
                "refresh_token": refresh_token,
                "refresh_token_expires_at": expires_at,
                "access_token_expires_at": access_token_expires_at
            }
        )
    else:
        db.execute(
            text("""
                UPDATE user_session 
                SET refresh_token = :refresh_token,
                    refresh_token_expires_at = :refresh_token_expires_at,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :session_id
            """),
            {
                "session_id": session_id,
                "refresh_token": refresh_token,
                "refresh_token_expires_at": expires_at
            }
        )
    
    db.commit()
    
    logger.info(
        "Refresh token updated successfully",
        function="update_user_session_refresh_token",
        session_id=session_id,
        refresh_token_preview=refresh_token_preview,
        expires_at=str(expires_at)
    )
    
    return refresh_token, expires_at


def get_user_id_by_auth_vendor_id(
    db: Session,
    auth_vendor_id: str
) -> Optional[str]:
    """
    Get user_id from google_user_auth_info by auth_vendor_id.
    
    Args:
        db: Database session
        auth_vendor_id: The google_user_auth_info.id (from user_session.auth_vendor_id)
        
    Returns:
        user_id (CHAR(36) UUID) or None if not found
    """
    logger.info(
        "Getting user_id by auth_vendor_id",
        function="get_user_id_by_auth_vendor_id",
        auth_vendor_id=auth_vendor_id
    )
    
    result = db.execute(
        text("SELECT user_id FROM google_user_auth_info WHERE id = :auth_vendor_id"),
        {"auth_vendor_id": auth_vendor_id}
    ).fetchone()
    
    if not result:
        logger.warning(
            "No google_user_auth_info found for auth_vendor_id",
            function="get_user_id_by_auth_vendor_id",
            auth_vendor_id=auth_vendor_id
        )
        return None
    
    user_id = result[0]
    
    logger.info(
        "User_id retrieved successfully",
        function="get_user_id_by_auth_vendor_id",
        auth_vendor_id=auth_vendor_id,
        user_id=user_id
    )
    
    return user_id


def get_saved_words_by_user_id(
    db: Session,
    user_id: str,
    offset: int = 0,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get saved words for a user with pagination, ordered by created_at DESC.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 20)
        
    Returns:
        Tuple of (list of saved words dictionaries, total count)
    """
    logger.info(
        "Getting saved words by user_id",
        function="get_saved_words_by_user_id",
        user_id=user_id,
        offset=offset,
        limit=limit
    )
    
    # Get total count
    count_result = db.execute(
        text("SELECT COUNT(*) FROM saved_word WHERE user_id = :user_id"),
        {"user_id": user_id}
    ).fetchone()
    
    total_count = count_result[0] if count_result else 0
    
    # Get paginated words
    words_result = db.execute(
        text("""
            SELECT id, word, contextual_meaning, source_url, user_id, created_at
            FROM saved_word
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {
            "user_id": user_id,
            "limit": limit,
            "offset": offset
        }
    ).fetchall()
    
    words = []
    for row in words_result:
        word_id, word, contextual_meaning, source_url, user_id_val, created_at = row
        # Convert created_at to ISO format string
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        words.append({
            "id": word_id,
            "word": word,
            "contextual_meaning": contextual_meaning,
            "source_url": source_url,
            "user_id": user_id_val,
            "created_at": created_at_str
        })
    
    logger.info(
        "Retrieved saved words successfully",
        function="get_saved_words_by_user_id",
        user_id=user_id,
        words_count=len(words),
        total_count=total_count
    )
    
    return words, total_count


def create_saved_word(
    db: Session,
    user_id: str,
    word: str,
    source_url: str
) -> Dict[str, Any]:
    """
    Create a new saved word for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        word: Word to save (max 32 characters)
        source_url: Source URL (max 1024 characters)
        
    Returns:
        Dictionary with created saved word data
    """
    logger.info(
        "Creating saved word",
        function="create_saved_word",
        user_id=user_id,
        word=word,
        source_url_length=len(source_url)
    )
    
    # Generate UUID for the new saved word
    word_id = str(uuid.uuid4())
    
    # Insert the new saved word
    db.execute(
        text("""
            INSERT INTO saved_word (id, word, source_url, user_id)
            VALUES (:id, :word, :source_url, :user_id)
        """),
        {
            "id": word_id,
            "word": word,
            "source_url": source_url,
            "user_id": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, word, source_url, user_id, created_at
            FROM saved_word
            WHERE id = :id
        """),
        {"id": word_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created saved word",
            function="create_saved_word",
            word_id=word_id
        )
        raise Exception("Failed to retrieve created saved word")
    
    word_id_val, word_val, source_url_val, user_id_val, created_at = result
    
    # Convert created_at to ISO format string
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    saved_word = {
        "id": word_id_val,
        "word": word_val,
        "source_url": source_url_val,
        "user_id": user_id_val,
        "created_at": created_at_str
    }
    
    logger.info(
        "Created saved word successfully",
        function="create_saved_word",
        word_id=word_id_val,
        user_id=user_id
    )
    
    return saved_word


def get_saved_word_by_id_and_user_id(
    db: Session,
    word_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a saved word by ID and verify it belongs to the user.
    
    Args:
        db: Database session
        word_id: Saved word ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with saved word data or None if not found or doesn't belong to user
    """
    logger.info(
        "Getting saved word by id and user_id",
        function="get_saved_word_by_id_and_user_id",
        word_id=word_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            SELECT id, word, source_url, user_id, created_at
            FROM saved_word
            WHERE id = :word_id AND user_id = :user_id
        """),
        {
            "word_id": word_id,
            "user_id": user_id
        }
    ).fetchone()
    
    if not result:
        logger.warning(
            "Saved word not found or doesn't belong to user",
            function="get_saved_word_by_id_and_user_id",
            word_id=word_id,
            user_id=user_id
        )
        return None
    
    word_id_val, word, source_url, user_id_val, created_at = result
    
    # Convert created_at to ISO format string
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    saved_word = {
        "id": word_id_val,
        "word": word,
        "source_url": source_url,
        "user_id": user_id_val,
        "created_at": created_at_str
    }
    
    logger.info(
        "Retrieved saved word successfully",
        function="get_saved_word_by_id_and_user_id",
        word_id=word_id_val,
        user_id=user_id
    )
    
    return saved_word


def delete_saved_word_by_id_and_user_id(
    db: Session,
    word_id: str,
    user_id: str
) -> bool:
    """
    Delete a saved word by ID if it belongs to the user.
    
    Args:
        db: Database session
        word_id: Saved word ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        True if word was deleted, False if not found or doesn't belong to user
    """
    logger.info(
        "Deleting saved word by id and user_id",
        function="delete_saved_word_by_id_and_user_id",
        word_id=word_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            DELETE FROM saved_word
            WHERE id = :word_id AND user_id = :user_id
        """),
        {
            "word_id": word_id,
            "user_id": user_id
        }
    )
    
    db.commit()
    
    if result.rowcount > 0:
        logger.info(
            "Deleted saved word successfully",
            function="delete_saved_word_by_id_and_user_id",
            word_id=word_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return True
    else:
        logger.warning(
            "Saved word not found or doesn't belong to user",
            function="delete_saved_word_by_id_and_user_id",
            word_id=word_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return False


def get_folders_by_user_id_and_parent_id(
    db: Session,
    user_id: str,
    parent_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get folders for a user with a specific parent_id.
    If parent_id is None, get folders where parent_id IS NULL.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        parent_id: Parent folder ID (CHAR(36) UUID) or None for root folders
        
    Returns:
        List of folder dictionaries
    """
    logger.info(
        "Getting folders by user_id and parent_id",
        function="get_folders_by_user_id_and_parent_id",
        user_id=user_id,
        parent_id=parent_id
    )
    
    if parent_id is None:
        result = db.execute(
            text("""
                SELECT id, name, type, parent_id, user_id, created_at, updated_at
                FROM folder
                WHERE user_id = :user_id AND parent_id IS NULL
                ORDER BY created_at DESC
            """),
            {"user_id": user_id}
        ).fetchall()
    else:
        result = db.execute(
            text("""
                SELECT id, name, type, parent_id, user_id, created_at, updated_at
                FROM folder
                WHERE user_id = :user_id AND parent_id = :parent_id
                ORDER BY created_at DESC
            """),
            {
                "user_id": user_id,
                "parent_id": parent_id
            }
        ).fetchall()
    
    folders = []
    for row in result:
        folder_id, name, folder_type, parent_id_val, user_id_val, created_at, updated_at = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        folders.append({
            "id": folder_id,
            "name": name,
            "type": folder_type,
            "parent_id": parent_id_val,
            "user_id": user_id_val,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        })
    
    logger.info(
        "Retrieved folders successfully",
        function="get_folders_by_user_id_and_parent_id",
        user_id=user_id,
        parent_id=parent_id,
        folders_count=len(folders)
    )
    
    return folders


def get_saved_paragraphs_by_user_id_and_folder_id(
    db: Session,
    user_id: str,
    folder_id: Optional[str] = None,
    offset: int = 0,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get saved paragraphs for a user with pagination, ordered by created_at DESC.
    If folder_id is None, get paragraphs where folder_id IS NULL.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        folder_id: Folder ID (CHAR(36) UUID) or None for root paragraphs
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 20)
        
    Returns:
        Tuple of (list of paragraph dictionaries, total count)
    """
    logger.info(
        "Getting saved paragraphs by user_id and folder_id",
        function="get_saved_paragraphs_by_user_id_and_folder_id",
        user_id=user_id,
        folder_id=folder_id,
        offset=offset,
        limit=limit
    )
    
    # Get total count
    if folder_id is None:
        count_result = db.execute(
            text("SELECT COUNT(*) FROM saved_paragraph WHERE user_id = :user_id AND folder_id IS NULL"),
            {"user_id": user_id}
        ).fetchone()
    else:
        count_result = db.execute(
            text("SELECT COUNT(*) FROM saved_paragraph WHERE user_id = :user_id AND folder_id = :folder_id"),
            {
                "user_id": user_id,
                "folder_id": folder_id
            }
        ).fetchone()
    
    total_count = count_result[0] if count_result else 0
    
    # Get paginated paragraphs
    if folder_id is None:
        paragraphs_result = db.execute(
            text("""
                SELECT id, source_url, name, content, folder_id, user_id, created_at, updated_at
                FROM saved_paragraph
                WHERE user_id = :user_id AND folder_id IS NULL
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "user_id": user_id,
                "limit": limit,
                "offset": offset
            }
        ).fetchall()
    else:
        paragraphs_result = db.execute(
            text("""
                SELECT id, source_url, name, content, folder_id, user_id, created_at, updated_at
                FROM saved_paragraph
                WHERE user_id = :user_id AND folder_id = :folder_id
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "user_id": user_id,
                "folder_id": folder_id,
                "limit": limit,
                "offset": offset
            }
        ).fetchall()
    
    paragraphs = []
    for row in paragraphs_result:
        para_id, source_url, name, content, folder_id_val, user_id_val, created_at, updated_at = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        paragraphs.append({
            "id": para_id,
            "source_url": source_url,
            "name": name,
            "content": content,
            "folder_id": folder_id_val,
            "user_id": user_id_val,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        })
    
    logger.info(
        "Retrieved saved paragraphs successfully",
        function="get_saved_paragraphs_by_user_id_and_folder_id",
        user_id=user_id,
        folder_id=folder_id,
        paragraphs_count=len(paragraphs),
        total_count=total_count,
        offset=offset,
        limit=limit
    )
    
    return paragraphs, total_count


def create_saved_paragraph(
    db: Session,
    user_id: str,
    content: str,
    source_url: str,
    name: Optional[str] = None,
    folder_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new saved paragraph for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        content: Paragraph content (TEXT)
        source_url: Source URL (max 1024 characters)
        name: Optional name for the paragraph (max 50 characters)
        folder_id: Optional folder ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with created saved paragraph data
    """
    logger.info(
        "Creating saved paragraph",
        function="create_saved_paragraph",
        user_id=user_id,
        content_length=len(content),
        source_url_length=len(source_url),
        has_name=name is not None,
        has_folder_id=folder_id is not None
    )
    
    # Generate UUID for the new saved paragraph
    paragraph_id = str(uuid.uuid4())
    
    # Insert the new saved paragraph
    db.execute(
        text("""
            INSERT INTO saved_paragraph (id, source_url, name, content, folder_id, user_id)
            VALUES (:id, :source_url, :name, :content, :folder_id, :user_id)
        """),
        {
            "id": paragraph_id,
            "source_url": source_url,
            "name": name,
            "content": content,
            "folder_id": folder_id,
            "user_id": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, source_url, name, content, folder_id, user_id, created_at, updated_at
            FROM saved_paragraph
            WHERE id = :id
        """),
        {"id": paragraph_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created saved paragraph",
            function="create_saved_paragraph",
            paragraph_id=paragraph_id
        )
        raise Exception("Failed to retrieve created saved paragraph")
    
    para_id, source_url_val, name_val, content_val, folder_id_val, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    saved_paragraph = {
        "id": para_id,
        "source_url": source_url_val,
        "name": name_val,
        "content": content_val,
        "folder_id": folder_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created saved paragraph successfully",
        function="create_saved_paragraph",
        paragraph_id=para_id,
        user_id=user_id
    )
    
    return saved_paragraph


def delete_saved_paragraph_by_id_and_user_id(
    db: Session,
    paragraph_id: str,
    user_id: str
) -> bool:
    """
    Delete a saved paragraph by ID if it belongs to the user.
    
    Args:
        db: Database session
        paragraph_id: Saved paragraph ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        True if paragraph was deleted, False if not found or doesn't belong to user
    """
    logger.info(
        "Deleting saved paragraph by id and user_id",
        function="delete_saved_paragraph_by_id_and_user_id",
        paragraph_id=paragraph_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            DELETE FROM saved_paragraph
            WHERE id = :paragraph_id AND user_id = :user_id
        """),
        {
            "paragraph_id": paragraph_id,
            "user_id": user_id
        }
    )
    
    db.commit()
    
    if result.rowcount > 0:
        logger.info(
            "Deleted saved paragraph successfully",
            function="delete_saved_paragraph_by_id_and_user_id",
            paragraph_id=paragraph_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return True
    else:
        logger.warning(
            "Saved paragraph not found or doesn't belong to user",
            function="delete_saved_paragraph_by_id_and_user_id",
            paragraph_id=paragraph_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return False


def get_folder_by_id_and_user_id(
    db: Session,
    folder_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a folder by ID and verify it belongs to the user.
    
    Args:
        db: Database session
        folder_id: Folder ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with folder data or None if not found or doesn't belong to user
    """
    logger.info(
        "Getting folder by id and user_id",
        function="get_folder_by_id_and_user_id",
        folder_id=folder_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            SELECT id, name, type, parent_id, user_id, created_at, updated_at
            FROM folder
            WHERE id = :folder_id AND user_id = :user_id
        """),
        {
            "folder_id": folder_id,
            "user_id": user_id
        }
    ).fetchone()
    
    if not result:
        logger.warning(
            "Folder not found or doesn't belong to user",
            function="get_folder_by_id_and_user_id",
            folder_id=folder_id,
            user_id=user_id
        )
        return None
    
    folder_id_val, name, folder_type, parent_id, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    folder = {
        "id": folder_id_val,
        "name": name,
        "type": folder_type,
        "parent_id": parent_id,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Retrieved folder successfully",
        function="get_folder_by_id_and_user_id",
        folder_id=folder_id_val,
        user_id=user_id
    )
    
    return folder


def delete_folder_by_id_and_user_id(
    db: Session,
    folder_id: str,
    user_id: str
) -> bool:
    """
    Delete a folder by ID if it belongs to the user.
    
    Args:
        db: Database session
        folder_id: Folder ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        True if folder was deleted, False if not found or doesn't belong to user
    """
    logger.info(
        "Deleting folder by id and user_id",
        function="delete_folder_by_id_and_user_id",
        folder_id=folder_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            DELETE FROM folder
            WHERE id = :folder_id AND user_id = :user_id
        """),
        {
            "folder_id": folder_id,
            "user_id": user_id
        }
    )
    
    db.commit()
    
    if result.rowcount > 0:
        logger.info(
            "Deleted folder successfully",
            function="delete_folder_by_id_and_user_id",
            folder_id=folder_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return True
    else:
        logger.warning(
            "Folder not found or doesn't belong to user",
            function="delete_folder_by_id_and_user_id",
            folder_id=folder_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return False


def create_paragraph_folder(
    db: Session,
    user_id: str,
    name: str,
    parent_folder_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new PARAGRAPH type folder for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        name: Folder name (max 50 characters)
        parent_folder_id: Optional parent folder ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with created folder data
    """
    logger.info(
        "Creating paragraph folder",
        function="create_paragraph_folder",
        user_id=user_id,
        name=name,
        has_parent_folder_id=parent_folder_id is not None
    )
    
    # Generate UUID for the new folder
    folder_id = str(uuid.uuid4())
    
    # Insert the new folder with type = 'PARAGRAPH'
    db.execute(
        text("""
            INSERT INTO folder (id, name, type, parent_id, user_id)
            VALUES (:id, :name, 'PARAGRAPH', :parent_id, :user_id)
        """),
        {
            "id": folder_id,
            "name": name,
            "parent_id": parent_folder_id,
            "user_id": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, name, type, parent_id, user_id, created_at, updated_at
            FROM folder
            WHERE id = :id
        """),
        {"id": folder_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created folder",
            function="create_paragraph_folder",
            folder_id=folder_id
        )
        raise Exception("Failed to retrieve created folder")
    
    folder_id_val, name_val, folder_type, parent_id_val, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    folder = {
        "id": folder_id_val,
        "name": name_val,
        "type": folder_type,
        "parent_id": parent_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created paragraph folder successfully",
        function="create_paragraph_folder",
        folder_id=folder_id_val,
        user_id=user_id
    )
    
    return folder


def get_folders_by_user_id_and_parent_id_and_type(
    db: Session,
    user_id: str,
    parent_id: Optional[str] = None,
    folder_type: str = "PAGE"
) -> List[Dict[str, Any]]:
    """
    Get folders for a user with a specific parent_id and type.
    If parent_id is None, get folders where parent_id IS NULL.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        parent_id: Parent folder ID (CHAR(36) UUID) or None for root folders
        folder_type: Folder type ('PAGE' or 'PARAGRAPH')
        
    Returns:
        List of folder dictionaries
    """
    logger.info(
        "Getting folders by user_id, parent_id and type",
        function="get_folders_by_user_id_and_parent_id_and_type",
        user_id=user_id,
        parent_id=parent_id,
        folder_type=folder_type
    )
    
    if parent_id is None:
        result = db.execute(
            text("""
                SELECT id, name, type, parent_id, user_id, created_at, updated_at
                FROM folder
                WHERE user_id = :user_id AND parent_id IS NULL AND type = :folder_type
                ORDER BY created_at DESC
            """),
            {
                "user_id": user_id,
                "folder_type": folder_type
            }
        ).fetchall()
    else:
        result = db.execute(
            text("""
                SELECT id, name, type, parent_id, user_id, created_at, updated_at
                FROM folder
                WHERE user_id = :user_id AND parent_id = :parent_id AND type = :folder_type
                ORDER BY created_at DESC
            """),
            {
                "user_id": user_id,
                "parent_id": parent_id,
                "folder_type": folder_type
            }
        ).fetchall()
    
    folders = []
    for row in result:
        folder_id, name, folder_type_val, parent_id_val, user_id_val, created_at, updated_at = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        folders.append({
            "id": folder_id,
            "name": name,
            "type": folder_type_val,
            "parent_id": parent_id_val,
            "user_id": user_id_val,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        })
    
    logger.info(
        "Retrieved folders successfully",
        function="get_folders_by_user_id_and_parent_id_and_type",
        user_id=user_id,
        parent_id=parent_id,
        folder_type=folder_type,
        folders_count=len(folders)
    )
    
    return folders


def get_saved_pages_by_user_id_and_folder_id(
    db: Session,
    user_id: str,
    folder_id: Optional[str] = None,
    offset: int = 0,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get saved pages for a user with pagination, ordered by created_at DESC.
    If folder_id is None, get pages where folder_id IS NULL.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        folder_id: Folder ID (CHAR(36) UUID) or None for root pages
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 20)
        
    Returns:
        Tuple of (list of page dictionaries, total count)
    """
    logger.info(
        "Getting saved pages by user_id and folder_id",
        function="get_saved_pages_by_user_id_and_folder_id",
        user_id=user_id,
        folder_id=folder_id,
        offset=offset,
        limit=limit
    )
    
    # Get total count
    if folder_id is None:
        count_result = db.execute(
            text("SELECT COUNT(*) FROM saved_page WHERE user_id = :user_id AND folder_id IS NULL"),
            {"user_id": user_id}
        ).fetchone()
    else:
        count_result = db.execute(
            text("SELECT COUNT(*) FROM saved_page WHERE user_id = :user_id AND folder_id = :folder_id"),
            {
                "user_id": user_id,
                "folder_id": folder_id
            }
        ).fetchone()
    
    total_count = count_result[0] if count_result else 0
    
    # Get paginated pages
    if folder_id is None:
        pages_result = db.execute(
            text("""
                SELECT id, url, name, folder_id, user_id, created_at, updated_at
                FROM saved_page
                WHERE user_id = :user_id AND folder_id IS NULL
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "user_id": user_id,
                "limit": limit,
                "offset": offset
            }
        ).fetchall()
    else:
        pages_result = db.execute(
            text("""
                SELECT id, url, name, folder_id, user_id, created_at, updated_at
                FROM saved_page
                WHERE user_id = :user_id AND folder_id = :folder_id
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "user_id": user_id,
                "folder_id": folder_id,
                "limit": limit,
                "offset": offset
            }
        ).fetchall()
    
    pages = []
    for row in pages_result:
        page_id, url, name, folder_id_val, user_id_val, created_at, updated_at = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        pages.append({
            "id": page_id,
            "url": url,
            "name": name,
            "folder_id": folder_id_val,
            "user_id": user_id_val,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        })
    
    logger.info(
        "Retrieved saved pages successfully",
        function="get_saved_pages_by_user_id_and_folder_id",
        user_id=user_id,
        folder_id=folder_id,
        pages_count=len(pages),
        total_count=total_count,
        offset=offset,
        limit=limit
    )
    
    return pages, total_count


def create_saved_page(
    db: Session,
    user_id: str,
    url: str,
    name: Optional[str] = None,
    folder_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new saved page for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        url: Page URL (max 1024 characters)
        name: Optional name for the page (max 50 characters)
        folder_id: Optional folder ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with created saved page data
    """
    logger.info(
        "Creating saved page",
        function="create_saved_page",
        user_id=user_id,
        url_length=len(url),
        has_name=name is not None,
        has_folder_id=folder_id is not None
    )
    
    # Generate UUID for the new saved page
    page_id = str(uuid.uuid4())
    
    # Insert the new saved page
    db.execute(
        text("""
            INSERT INTO saved_page (id, url, name, folder_id, user_id)
            VALUES (:id, :url, :name, :folder_id, :user_id)
        """),
        {
            "id": page_id,
            "url": url,
            "name": name,
            "folder_id": folder_id,
            "user_id": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, url, name, folder_id, user_id, created_at, updated_at
            FROM saved_page
            WHERE id = :id
        """),
        {"id": page_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created saved page",
            function="create_saved_page",
            page_id=page_id
        )
        raise Exception("Failed to retrieve created saved page")
    
    page_id_val, url_val, name_val, folder_id_val, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    saved_page = {
        "id": page_id_val,
        "url": url_val,
        "name": name_val,
        "folder_id": folder_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created saved page successfully",
        function="create_saved_page",
        page_id=page_id_val,
        user_id=user_id
    )
    
    return saved_page


def delete_saved_page_by_id_and_user_id(
    db: Session,
    page_id: str,
    user_id: str
) -> bool:
    """
    Delete a saved page by ID if it belongs to the user.
    
    Args:
        db: Database session
        page_id: Saved page ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        True if page was deleted, False if not found or doesn't belong to user
    """
    logger.info(
        "Deleting saved page by id and user_id",
        function="delete_saved_page_by_id_and_user_id",
        page_id=page_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            DELETE FROM saved_page
            WHERE id = :page_id AND user_id = :user_id
        """),
        {
            "page_id": page_id,
            "user_id": user_id
        }
    )
    
    db.commit()
    
    if result.rowcount > 0:
        logger.info(
            "Deleted saved page successfully",
            function="delete_saved_page_by_id_and_user_id",
            page_id=page_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return True
    else:
        logger.warning(
            "Saved page not found or doesn't belong to user",
            function="delete_saved_page_by_id_and_user_id",
            page_id=page_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return False


def create_page_folder(
    db: Session,
    user_id: str,
    name: str,
    parent_folder_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new PAGE type folder for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        name: Folder name (max 50 characters)
        parent_folder_id: Optional parent folder ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with created folder data
    """
    logger.info(
        "Creating page folder",
        function="create_page_folder",
        user_id=user_id,
        name=name,
        has_parent_folder_id=parent_folder_id is not None
    )
    
    # Generate UUID for the new folder
    folder_id = str(uuid.uuid4())
    
    # Insert the new folder with type = 'PAGE'
    db.execute(
        text("""
            INSERT INTO folder (id, name, type, parent_id, user_id)
            VALUES (:id, :name, 'PAGE', :parent_id, :user_id)
        """),
        {
            "id": folder_id,
            "name": name,
            "parent_id": parent_folder_id,
            "user_id": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, name, type, parent_id, user_id, created_at, updated_at
            FROM folder
            WHERE id = :id
        """),
        {"id": folder_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created folder",
            function="create_page_folder",
            folder_id=folder_id
        )
        raise Exception("Failed to retrieve created folder")
    
    folder_id_val, name_val, folder_type, parent_id_val, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    folder = {
        "id": folder_id_val,
        "name": name_val,
        "type": folder_type,
        "parent_id": parent_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created page folder successfully",
        function="create_page_folder",
        folder_id=folder_id_val,
        user_id=user_id
    )
    
    return folder


def generate_ticket_id(db: Session) -> str:
    """
    Generate a unique 14-character ticket ID using timestamp (base36) + random characters.
    
    Format: timestamp in base36 (8-9 chars) + random alphanumeric (5-6 chars)
    Characters used: A-Z, 0-9
    
    Args:
        db: Database session
        
    Returns:
        14-character ticket ID string (A-Z, 0-9)
    """
    logger.info(
        "Generating ticket ID",
        function="generate_ticket_id"
    )
    
    # Base36 character set (0-9, A-Z)
    base36_chars = string.digits + string.ascii_uppercase
    
    max_attempts = 10
    for attempt in range(max_attempts):
        # Get current timestamp in milliseconds
        timestamp_ms = int(time.time() * 1000)
        
        # Convert timestamp to base36 (8-9 characters)
        timestamp_base36 = ""
        temp = timestamp_ms
        while temp > 0:
            timestamp_base36 = base36_chars[temp % 36] + timestamp_base36
            temp //= 36
        
        # Ensure timestamp part is at least 8 chars, pad with zeros if needed
        # But we want total of 14, so if timestamp is longer, truncate
        if len(timestamp_base36) > 9:
            timestamp_base36 = timestamp_base36[-9:]
        elif len(timestamp_base36) < 8:
            timestamp_base36 = timestamp_base36.zfill(8)
        
        # Generate random suffix (5-6 characters to make total 14)
        remaining_chars = 14 - len(timestamp_base36)
        random_suffix = ''.join(secrets.choice(base36_chars) for _ in range(remaining_chars))
        
        ticket_id = timestamp_base36 + random_suffix
        
        # Check uniqueness
        result = db.execute(
            text("SELECT COUNT(*) FROM issue WHERE ticket_id = :ticket_id"),
            {"ticket_id": ticket_id}
        ).fetchone()
        
        if result and result[0] == 0:
            logger.info(
                "Generated unique ticket ID",
                function="generate_ticket_id",
                ticket_id=ticket_id,
                attempt=attempt + 1
            )
            return ticket_id
    
    # If we couldn't generate a unique ID after max attempts, raise error
    logger.error(
        "Failed to generate unique ticket ID after max attempts",
        function="generate_ticket_id",
        max_attempts=max_attempts
    )
    raise Exception("Failed to generate unique ticket ID")


def create_issue(
    db: Session,
    user_id: str,
    issue_type: str,
    heading: Optional[str],
    description: str,
    webpage_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new issue record.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID) who is creating the issue
        issue_type: Issue type (GLITCH, SUBSCRIPTION, AUTHENTICATION, FEATURE_REQUEST, OTHERS)
        heading: Optional issue heading (max 100 characters)
        description: Issue description (TEXT)
        webpage_url: Optional webpage URL (max 1024 characters)
        
    Returns:
        Dictionary with created issue data
    """
    logger.info(
        "Creating issue",
        function="create_issue",
        user_id=user_id,
        issue_type=issue_type,
        heading_length=len(heading) if heading else 0,
        description_length=len(description),
        has_webpage_url=webpage_url is not None,
        has_heading=heading is not None
    )
    
    # Generate UUID for the new issue
    issue_id = str(uuid.uuid4())
    
    # Generate unique ticket_id
    ticket_id = generate_ticket_id(db)
    
    # Insert the new issue
    db.execute(
        text("""
            INSERT INTO issue (id, ticket_id, type, heading, description, webpage_url, status, created_by)
            VALUES (:id, :ticket_id, :type, :heading, :description, :webpage_url, 'OPEN', :created_by)
        """),
        {
            "id": issue_id,
            "ticket_id": ticket_id,
            "type": issue_type,
            "heading": heading,
            "description": description,
            "webpage_url": webpage_url,
            "created_by": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, ticket_id, type, heading, description, webpage_url, status, 
                   created_by, closed_by, closed_at, created_at, updated_at
            FROM issue
            WHERE id = :id
        """),
        {"id": issue_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created issue",
            function="create_issue",
            issue_id=issue_id
        )
        raise Exception("Failed to retrieve created issue")
    
    (issue_id_val, ticket_id_val, type_val, heading_val, description_val, 
     webpage_url_val, status_val, created_by_val, closed_by_val, closed_at_val, 
     created_at, updated_at) = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    closed_at_str = None
    if closed_at_val:
        if isinstance(closed_at_val, datetime):
            closed_at_str = closed_at_val.isoformat() + "Z" if closed_at_val.tzinfo else closed_at_val.isoformat()
        else:
            closed_at_str = str(closed_at_val)
    
    issue = {
        "id": issue_id_val,
        "ticket_id": ticket_id_val,
        "type": type_val,
        "heading": heading_val,
        "description": description_val,
        "webpage_url": webpage_url_val,
        "status": status_val,
        "created_by": created_by_val,
        "closed_by": closed_by_val,
        "closed_at": closed_at_str,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created issue successfully",
        function="create_issue",
        issue_id=issue_id_val,
        ticket_id=ticket_id_val,
        user_id=user_id
    )
    
    return issue


def get_issues_by_user_id(
    db: Session,
    user_id: str,
    statuses: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Get issues for a user with optional status filter.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        statuses: Optional list of status values to filter by
        
    Returns:
        List of dictionaries with issue data, ordered by created_at DESC
    """
    logger.info(
        "Getting issues by user_id",
        function="get_issues_by_user_id",
        user_id=user_id,
        has_status_filter=statuses is not None and len(statuses) > 0,
        status_count=len(statuses) if statuses else 0
    )
    
    # Build query based on whether statuses filter is provided
    if statuses and len(statuses) > 0:
        # Filter by statuses
        placeholders = ",".join([f":status_{i}" for i in range(len(statuses))])
        query = text(f"""
            SELECT id, ticket_id, type, heading, description, webpage_url, status, 
                   created_by, closed_by, closed_at, created_at, updated_at
            FROM issue
            WHERE created_by = :user_id AND status IN ({placeholders})
            ORDER BY created_at DESC
        """)
        
        params = {"user_id": user_id}
        for i, status in enumerate(statuses):
            params[f"status_{i}"] = status
        
        result = db.execute(query, params)
    else:
        # Get all issues for user
        result = db.execute(
            text("""
                SELECT id, ticket_id, type, heading, description, webpage_url, status, 
                       created_by, closed_by, closed_at, created_at, updated_at
                FROM issue
                WHERE created_by = :user_id
                ORDER BY created_at DESC
            """),
            {"user_id": user_id}
        )
    
    rows = result.fetchall()
    
    issues = []
    for row in rows:
        (issue_id, ticket_id, type_val, heading_val, description_val, 
         webpage_url_val, status_val, created_by_val, closed_by_val, closed_at_val, 
         created_at, updated_at) = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        closed_at_str = None
        if closed_at_val:
            if isinstance(closed_at_val, datetime):
                closed_at_str = closed_at_val.isoformat() + "Z" if closed_at_val.tzinfo else closed_at_val.isoformat()
            else:
                closed_at_str = str(closed_at_val)
        
        issue = {
            "id": issue_id,
            "ticket_id": ticket_id,
            "type": type_val,
            "heading": heading_val,
            "description": description_val,
            "webpage_url": webpage_url_val,
            "status": status_val,
            "created_by": created_by_val,
            "closed_by": closed_by_val,
            "closed_at": closed_at_str,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        }
        issues.append(issue)
    
    logger.info(
        "Retrieved issues successfully",
        function="get_issues_by_user_id",
        user_id=user_id,
        issue_count=len(issues)
    )
    
    return issues


def get_user_role_by_user_id(
    db: Session,
    user_id: str
) -> Optional[str]:
    """
    Get user role by user_id.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        User role (ADMIN, SUPER_ADMIN) or None if not found or no role
    """
    logger.info(
        "Getting user role by user_id",
        function="get_user_role_by_user_id",
        user_id=user_id
    )
    
    result = db.execute(
        text("SELECT role FROM user WHERE id = :user_id"),
        {"user_id": user_id}
    ).fetchone()
    
    if not result:
        logger.warning(
            "User not found",
            function="get_user_role_by_user_id",
            user_id=user_id
        )
        return None
    
    role = result[0]
    
    logger.info(
        "User role retrieved successfully",
        function="get_user_role_by_user_id",
        user_id=user_id,
        role=role
    )
    
    return role


def get_user_name_by_user_id(
    db: Session,
    user_id: str
) -> Optional[str]:
    """
    Get user name by user_id.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        User's full name (given_name + family_name) or empty string if not found
    """
    logger.info(
        "Getting user name by user_id",
        function="get_user_name_by_user_id",
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            SELECT given_name, family_name
            FROM google_user_auth_info
            WHERE user_id = :user_id
            LIMIT 1
        """),
        {"user_id": user_id}
    ).fetchone()
    
    if not result:
        logger.warning(
            "User name not found",
            function="get_user_name_by_user_id",
            user_id=user_id
        )
        return ""
    
    given_name, family_name = result
    
    # Construct full name
    name_parts = []
    if given_name:
        name_parts.append(given_name)
    if family_name:
        name_parts.append(family_name)
    name = " ".join(name_parts).strip() if name_parts else ""
    
    logger.info(
        "User name retrieved successfully",
        function="get_user_name_by_user_id",
        user_id=user_id,
        has_name=bool(name)
    )
    
    return name


def get_user_name_and_role_by_user_id(
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    Get user name and role by user_id.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with 'name' (str) and 'role' (Optional[str])
    """
    logger.info(
        "Getting user name and role by user_id",
        function="get_user_name_and_role_by_user_id",
        user_id=user_id
    )
    
    # Get name from google_user_auth_info
    name_result = db.execute(
        text("""
            SELECT given_name, family_name
            FROM google_user_auth_info
            WHERE user_id = :user_id
            LIMIT 1
        """),
        {"user_id": user_id}
    ).fetchone()
    
    # Get role from user table
    role_result = db.execute(
        text("SELECT role FROM user WHERE id = :user_id"),
        {"user_id": user_id}
    ).fetchone()
    
    # Construct name
    name = ""
    if name_result:
        given_name, family_name = name_result
        name_parts = []
        if given_name:
            name_parts.append(given_name)
        if family_name:
            name_parts.append(family_name)
        name = " ".join(name_parts).strip() if name_parts else ""
    
    # Get role
    role = role_result[0] if role_result else None
    
    logger.info(
        "User name and role retrieved successfully",
        function="get_user_name_and_role_by_user_id",
        user_id=user_id,
        has_name=bool(name),
        role=role
    )
    
    return {
        "name": name,
        "role": role
    }


def get_comment_by_id(
    db: Session,
    comment_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get comment by ID.
    
    Args:
        db: Database session
        comment_id: Comment ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with comment data or None if not found
    """
    logger.info(
        "Getting comment by id",
        function="get_comment_by_id",
        comment_id=comment_id
    )
    
    result = db.execute(
        text("""
            SELECT id, content, entity_type, entity_id, parent_comment_id, 
                   visibility, created_by, created_at, updated_at
            FROM comment
            WHERE id = :comment_id
        """),
        {"comment_id": comment_id}
    ).fetchone()
    
    if not result:
        logger.warning(
            "Comment not found",
            function="get_comment_by_id",
            comment_id=comment_id
        )
        return None
    
    (comment_id_val, content, entity_type, entity_id, parent_comment_id,
     visibility, created_by, created_at, updated_at) = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    comment = {
        "id": comment_id_val,
        "content": content,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "parent_comment_id": parent_comment_id,
        "visibility": visibility,
        "created_by": created_by,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Comment retrieved successfully",
        function="get_comment_by_id",
        comment_id=comment_id
    )
    
    return comment


def get_comments_by_entity(
    db: Session,
    entity_type: str,
    entity_id: str,
    count: int,
    user_role: Optional[str]
) -> List[Dict[str, Any]]:
    """
    Get comments by entity with hierarchical structure.
    Fetches X root comments and all their nested children.
    
    Args:
        db: Database session
        entity_type: Entity type (ISSUE)
        entity_id: Entity ID (CHAR(36) UUID)
        count: Number of root comments to fetch
        user_role: User role (ADMIN, SUPER_ADMIN, or None) for visibility filtering
        
    Returns:
        List of dictionaries with comment data, including parent relationships
    """
    logger.info(
        "Getting comments by entity",
        function="get_comments_by_entity",
        entity_type=entity_type,
        entity_id=entity_id,
        count=count,
        user_role=user_role
    )
    
    # Determine visibility filter
    # ADMIN and SUPER_ADMIN can see all comments, others only PUBLIC
    is_admin = user_role in ("ADMIN", "SUPER_ADMIN")
    
    # Build visibility filter
    if is_admin:
        visibility_filter = ""
        visibility_params = {}
    else:
        visibility_filter = "AND visibility = 'PUBLIC'"
        visibility_params = {}
    
    # First, get root comments (parent_comment_id IS NULL) ordered by created_at DESC
    root_query = text(f"""
        SELECT id, content, entity_type, entity_id, parent_comment_id, 
               visibility, created_by, created_at, updated_at
        FROM comment
        WHERE entity_type = :entity_type 
          AND entity_id = :entity_id 
          AND parent_comment_id IS NULL
          {visibility_filter}
        ORDER BY created_at DESC
        LIMIT :count
    """)
    
    params = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "count": count
    }
    params.update(visibility_params)
    
    root_comments = db.execute(root_query, params).fetchall()
    
    if not root_comments:
        logger.info(
            "No root comments found",
            function="get_comments_by_entity",
            entity_type=entity_type,
            entity_id=entity_id
        )
        return []
    
    # Get all root comment IDs
    root_comment_ids = [row[0] for row in root_comments]
    
    # Fetch all nested children recursively using a recursive CTE
    # We'll fetch all comments for this entity and build the tree in Python
    all_comments_query = text(f"""
        SELECT id, content, entity_type, entity_id, parent_comment_id, 
               visibility, created_by, created_at, updated_at
        FROM comment
        WHERE entity_type = :entity_type 
          AND entity_id = :entity_id
          {visibility_filter}
    """)
    
    all_comments_result = db.execute(all_comments_query, {
        "entity_type": entity_type,
        "entity_id": entity_id,
        **visibility_params
    }).fetchall()
    
    # Convert all comments to dictionaries
    all_comments_dict = {}
    for row in all_comments_result:
        (comment_id, content, entity_type_val, entity_id_val, parent_comment_id,
         visibility, created_by, created_at, updated_at) = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        all_comments_dict[comment_id] = {
            "id": comment_id,
            "content": content,
            "entity_type": entity_type_val,
            "entity_id": entity_id_val,
            "parent_comment_id": parent_comment_id,
            "visibility": visibility,
            "created_by": created_by,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        }
    
    # Filter to only include root comments and their descendants
    # Build a set of all comment IDs that are descendants of root comments
    descendant_ids = set(root_comment_ids)
    queue = list(root_comment_ids)
    
    while queue:
        parent_id = queue.pop(0)
        # Find all comments with this parent
        for comment_id, comment_data in all_comments_dict.items():
            if comment_data["parent_comment_id"] == parent_id:
                if comment_id not in descendant_ids:
                    descendant_ids.add(comment_id)
                    queue.append(comment_id)
    
    # Return only root comments and their descendants
    result = [all_comments_dict[cid] for cid in descendant_ids if cid in all_comments_dict]
    
    # Fetch user names and roles for all unique created_by values
    unique_user_ids = set(comment["created_by"] for comment in result)
    user_info_map = {}
    for user_id in unique_user_ids:
        user_info = get_user_name_and_role_by_user_id(db, user_id)
        user_info_map[user_id] = user_info
    
    # Add user info to comments
    for comment in result:
        user_id = comment["created_by"]
        user_info = user_info_map.get(user_id, {"name": "", "role": None})
        comment["created_by_user"] = {
            "id": user_id,
            "name": user_info.get("name", ""),
            "role": user_info.get("role")
        }
    
    logger.info(
        "Comments retrieved successfully",
        function="get_comments_by_entity",
        entity_type=entity_type,
        entity_id=entity_id,
        root_count=len(root_comment_ids),
        total_count=len(result)
    )
    
    return result


def create_comment(
    db: Session,
    user_id: str,
    entity_type: str,
    entity_id: str,
    content: str,
    visibility: str,
    parent_comment_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new comment.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID) who is creating the comment
        entity_type: Entity type (ISSUE)
        entity_id: Entity ID (CHAR(36) UUID)
        content: Comment content (will be stripped and validated)
        visibility: Comment visibility (PUBLIC or INTERNAL)
        parent_comment_id: Optional parent comment ID for nested replies
        
    Returns:
        Dictionary with created comment data
        
    Raises:
        ValueError: If content is empty after stripping
        Exception: If parent_comment_id is provided but doesn't exist
    """
    logger.info(
        "Creating comment",
        function="create_comment",
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        visibility=visibility,
        has_parent=parent_comment_id is not None
    )
    
    # Strip and validate content
    content_stripped = content.strip()
    if len(content_stripped) == 0:
        logger.error(
            "Comment content is empty after stripping",
            function="create_comment",
            user_id=user_id
        )
        raise ValueError("Comment content cannot be empty")
    
    # Validate parent_comment_id exists if provided
    if parent_comment_id:
        parent_comment = get_comment_by_id(db, parent_comment_id)
        if not parent_comment:
            logger.error(
                "Parent comment not found",
                function="create_comment",
                parent_comment_id=parent_comment_id
            )
            raise Exception("Parent comment not found")
    
    # Generate UUID for the new comment
    comment_id = str(uuid.uuid4())
    
    # Insert the new comment
    db.execute(
        text("""
            INSERT INTO comment (id, content, entity_type, entity_id, parent_comment_id, visibility, created_by)
            VALUES (:id, :content, :entity_type, :entity_id, :parent_comment_id, :visibility, :created_by)
        """),
        {
            "id": comment_id,
            "content": content_stripped,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "parent_comment_id": parent_comment_id,
            "visibility": visibility,
            "created_by": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, content, entity_type, entity_id, parent_comment_id, 
                   visibility, created_by, created_at, updated_at
            FROM comment
            WHERE id = :id
        """),
        {"id": comment_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created comment",
            function="create_comment",
            comment_id=comment_id
        )
        raise Exception("Failed to retrieve created comment")
    
    (comment_id_val, content_val, entity_type_val, entity_id_val, parent_comment_id_val,
     visibility_val, created_by_val, created_at, updated_at) = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Get user name and role
    user_info = get_user_name_and_role_by_user_id(db, created_by_val)
    
    comment = {
        "id": comment_id_val,
        "content": content_val,
        "entity_type": entity_type_val,
        "entity_id": entity_id_val,
        "parent_comment_id": parent_comment_id_val,
        "visibility": visibility_val,
        "created_by": created_by_val,
        "created_by_user": {
            "id": created_by_val,
            "name": user_info.get("name", ""),
            "role": user_info.get("role")
        },
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Comment created successfully",
        function="create_comment",
        comment_id=comment_id,
        user_id=user_id
    )
    
    return comment


def create_file_upload(
    db: Session,
    file_name: str,
    file_type: str,
    entity_type: str,
    entity_id: str,
    s3_url: str,
    metadata: Optional[dict] = None
) -> Dict[str, Any]:
    """
    Create a new file_upload record.
    
    Args:
        db: Database session
        file_name: File name (max 50 characters)
        file_type: File type (IMAGE or PDF)
        entity_type: Entity type (ISSUE)
        entity_id: Entity ID (CHAR(36) UUID)
        s3_url: S3 URL for the file (max 2044 characters)
        metadata: Optional metadata JSON
        
    Returns:
        Dictionary with created file_upload data
    """
    logger.info(
        "Creating file upload",
        function="create_file_upload",
        file_name=file_name,
        file_type=file_type,
        entity_type=entity_type,
        entity_id=entity_id
    )
    
    # Generate UUID for the new file_upload
    file_upload_id = str(uuid.uuid4())
    
    # Prepare metadata JSON
    metadata_json = json.dumps(metadata) if metadata else None
    
    # Insert the new file_upload
    db.execute(
        text("""
            INSERT INTO file_upload (id, file_name, file_type, entity_type, entity_id, s3_url, metadata)
            VALUES (:id, :file_name, :file_type, :entity_type, :entity_id, :s3_url, :metadata)
        """),
        {
            "id": file_upload_id,
            "file_name": file_name,
            "file_type": file_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "s3_url": s3_url,
            "metadata": metadata_json
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, file_name, file_type, entity_type, entity_id, s3_url, metadata, created_at, updated_at
            FROM file_upload
            WHERE id = :id
        """),
        {"id": file_upload_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created file_upload",
            function="create_file_upload",
            file_upload_id=file_upload_id
        )
        raise Exception("Failed to retrieve created file_upload")
    
    (file_upload_id_val, file_name_val, file_type_val, entity_type_val, entity_id_val,
     s3_url_val, metadata_val, created_at, updated_at) = result
    
    # Parse metadata JSON if present
    metadata_dict = None
    if metadata_val:
        try:
            metadata_dict = json.loads(metadata_val) if isinstance(metadata_val, str) else metadata_val
        except (json.JSONDecodeError, TypeError):
            metadata_dict = None
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    file_upload = {
        "id": file_upload_id_val,
        "file_name": file_name_val,
        "file_type": file_type_val,
        "entity_type": entity_type_val,
        "entity_id": entity_id_val,
        "s3_url": s3_url_val,
        "metadata": metadata_dict,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "File upload created successfully",
        function="create_file_upload",
        file_upload_id=file_upload_id,
        entity_id=entity_id
    )
    
    return file_upload


def get_file_uploads_by_entity(
    db: Session,
    entity_type: str,
    entity_id: str
) -> List[Dict[str, Any]]:
    """
    Get all file_uploads for a specific entity.
    
    Args:
        db: Database session
        entity_type: Entity type (ISSUE)
        entity_id: Entity ID (CHAR(36) UUID)
        
    Returns:
        List of dictionaries with file_upload data
    """
    logger.info(
        "Getting file uploads by entity",
        function="get_file_uploads_by_entity",
        entity_type=entity_type,
        entity_id=entity_id
    )
    
    result = db.execute(
        text("""
            SELECT id, file_name, file_type, entity_type, entity_id, s3_url, metadata, created_at, updated_at
            FROM file_upload
            WHERE entity_type = :entity_type AND entity_id = :entity_id
            ORDER BY created_at ASC
        """),
        {
            "entity_type": entity_type,
            "entity_id": entity_id
        }
    ).fetchall()
    
    file_uploads = []
    for row in result:
        (file_upload_id, file_name, file_type, entity_type_val, entity_id_val,
         s3_url, metadata, created_at, updated_at) = row
        
        # Parse metadata JSON if present
        metadata_dict = None
        if metadata:
            try:
                metadata_dict = json.loads(metadata) if isinstance(metadata, str) else metadata
            except (json.JSONDecodeError, TypeError):
                metadata_dict = None
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        file_upload = {
            "id": file_upload_id,
            "file_name": file_name,
            "file_type": file_type,
            "entity_type": entity_type_val,
            "entity_id": entity_id_val,
            "s3_url": s3_url,
            "metadata": metadata_dict,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        }
        file_uploads.append(file_upload)
    
    logger.info(
        "File uploads retrieved successfully",
        function="get_file_uploads_by_entity",
        entity_type=entity_type,
        entity_id=entity_id,
        count=len(file_uploads)
    )
    
    return file_uploads

