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
from app.models import DEFAULT_USER_SETTINGS

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
        
        # Create user record with default settings
        db.execute(
            text("INSERT INTO user (id, settings) VALUES (:user_id, :settings)"),
            {"user_id": user_id, "settings": json.dumps(DEFAULT_USER_SETTINGS)}
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
        
        # Create personal folder for new user
        # Determine folder name: "{given_name}'s Personal" > "{family_name}'s Personal" > "Personal"
        given_name = google_data.get("given_name")
        family_name = google_data.get("family_name")
        
        if given_name and given_name.strip():
            folder_name = f"{given_name.strip()}'s Personal"
        elif family_name and family_name.strip():
            folder_name = f"{family_name.strip()}'s Personal"
        else:
            folder_name = "Personal"
        
        # Ensure folder name doesn't exceed 50 characters (database constraint)
        if len(folder_name) > 50:
            folder_name = folder_name[:47] + "..."
        
        logger.debug(
            "Creating personal folder for new user",
            function="get_or_create_user_by_google_sub",
            user_id=user_id,
            folder_name=folder_name,
            has_given_name=bool(given_name),
            has_family_name=bool(family_name)
        )
        
        # Generate folder_id
        folder_id = str(uuid.uuid4())
        
        # Create folder record (root folder, no parent_id)
        db.execute(
            text("""
                INSERT INTO folder (id, name, parent_id, user_id)
                VALUES (:id, :name, :parent_id, :user_id)
            """),
            {
                "id": folder_id,
                "name": folder_name,
                "parent_id": None,
                "user_id": user_id
            }
        )
        db.flush()
        
        logger.info(
            "Created personal folder for new user",
            function="get_or_create_user_by_google_sub",
            user_id=user_id,
            folder_id=folder_id,
            folder_name=folder_name
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
            
            # Invalidate cached session data to prevent stale access_token_expires_at
            cache = get_in_memory_cache()
            cache_key = f"USER_SESSION_INFO:{session_id}"
            cache.invalidate_key(cache_key)
            
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
    
    # First, get the session IDs that will be affected (for cache invalidation)
    session_ids_result = db.execute(
        text("""
            SELECT id FROM user_session
            WHERE auth_vendor_type = :auth_vendor_type 
            AND auth_vendor_id = :auth_vendor_id
            AND access_token_state = 'VALID'
        """),
        {
            "auth_vendor_type": auth_vendor_type,
            "auth_vendor_id": google_auth_info_id
        }
    ).fetchall()
    
    session_ids_to_invalidate = [row[0] for row in session_ids_result]
    
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
    
    # Invalidate cached session data for all affected sessions
    cache = get_in_memory_cache()
    for session_id in session_ids_to_invalidate:
        cache_key = f"USER_SESSION_INFO:{session_id}"
        cache.invalidate_key(cache_key)
    
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
        "synonyms_api_count_so_far": 0,
        "antonyms_api_count_so_far": 0,
        # Method-specific counters for saved words
        "saved_words_get_api_count_so_far": 0,
        "saved_words_post_api_count_so_far": 0,
        "saved_words_delete_api_count_so_far": 0,
        # Method-specific counters for saved paragraph
        "saved_paragraph_get_api_count_so_far": 0,
        "saved_paragraph_post_api_count_so_far": 0,
        "saved_paragraph_delete_api_count_so_far": 0,
        "saved_paragraph_folder_post_api_count_so_far": 0,
        "saved_paragraph_folder_delete_api_count_so_far": 0,
        # Method-specific counters for saved link
        "saved_link_get_api_count_so_far": 0,
        "saved_link_post_api_count_so_far": 0,
        "saved_link_delete_api_count_so_far": 0,
        "saved_link_folder_post_api_count_so_far": 0,
        "saved_link_folder_delete_api_count_so_far": 0,
        # Method-specific counters for folders
        "folders_get_api_count_so_far": 0
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


def get_authenticated_user_api_usage(
    db: Session,
    user_id: str,
    ip_address: str
) -> Optional[Dict[str, Any]]:
    """
    Get authenticated user API usage record.
    Queries by user_id OR ip_address and returns aggregated maximum values across all matching records.
    
    Args:
        db: Database session
        user_id: User ID (UUID) - foreign key to user table
        ip_address: IP address from request header
        
    Returns:
        Dictionary with api_usage JSON data aggregated with maximum values, or None if not found
    """
    results = db.execute(
        text("SELECT api_usage FROM unsubscribed_user_api_usage WHERE user_id = :user_id OR ip_address = :ip_address"),
        {"user_id": user_id, "ip_address": ip_address}
    ).fetchall()
    
    if not results:
        return None
    
    # Collect all api_usage JSON objects
    api_usage_list = []
    for result in results:
        api_usage_json = result[0]
        if isinstance(api_usage_json, str):
            api_usage = json.loads(api_usage_json)
        else:
            api_usage = api_usage_json
        api_usage_list.append(api_usage)
    
    # Aggregate maximum values across all records
    aggregated_usage = {}
    all_keys = set()
    
    # Collect all unique keys from all records
    for api_usage in api_usage_list:
        all_keys.update(api_usage.keys())
    
    # For each key, find the maximum value across all records
    for key in all_keys:
        max_value = 0
        for api_usage in api_usage_list:
            value = api_usage.get(key, 0)
            if isinstance(value, (int, float)):
                max_value = max(max_value, value)
        aggregated_usage[key] = max_value
    
    return aggregated_usage


def create_authenticated_user_api_usage(
    db: Session,
    user_id: str,
    api_name: str,
    ip_address: str
) -> None:
    """
    Create a new authenticated user API usage record.
    
    Args:
        db: Database session
        user_id: User ID (UUID) - foreign key to user table
        api_name: Name of the API being called (used to initialize counter)
        ip_address: IP address from request header
    """
    # Initialize API usage JSON with all counters set to 0
    # Note: We initialize to 0 because the caller will increment it after creation
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
        "synonyms_api_count_so_far": 0,
        "antonyms_api_count_so_far": 0,
        # Method-specific counters for saved words
        "saved_words_get_api_count_so_far": 0,
        "saved_words_post_api_count_so_far": 0,
        "saved_words_delete_api_count_so_far": 0,
        # Method-specific counters for saved paragraph
        "saved_paragraph_get_api_count_so_far": 0,
        "saved_paragraph_post_api_count_so_far": 0,
        "saved_paragraph_delete_api_count_so_far": 0,
        "saved_paragraph_folder_post_api_count_so_far": 0,
        "saved_paragraph_folder_delete_api_count_so_far": 0,
        # Method-specific counters for saved link
        "saved_link_get_api_count_so_far": 0,
        "saved_link_post_api_count_so_far": 0,
        "saved_link_delete_api_count_so_far": 0,
        "saved_link_folder_post_api_count_so_far": 0,
        "saved_link_folder_delete_api_count_so_far": 0,
        # Method-specific counters for folders
        "folders_get_api_count_so_far": 0
    }
    
    # Ensure the api_name field exists (initialize to 0, will be incremented by caller)
    if api_name not in api_usage:
        logger.warning(
            "API name not found in api_usage dictionary, adding it",
            api_name=api_name
        )
        api_usage[api_name] = 0
    
    db.execute(
        text("""
            INSERT INTO unsubscribed_user_api_usage 
            (user_id, ip_address, api_usage)
            VALUES 
            (:user_id, :ip_address, :api_usage)
        """),
        {
            "user_id": user_id,
            "ip_address": ip_address,
            "api_usage": json.dumps(api_usage)
        }
    )
    db.commit()
    
    logger.info("Created authenticated user API usage record", user_id=user_id, api_name=api_name, ip_address=ip_address)


def increment_authenticated_api_usage(
    db: Session,
    user_id: str,
    api_name: str
) -> None:
    """
    Increment the API usage counter for a specific API for authenticated user.
    
    Args:
        db: Database session
        user_id: User ID (UUID) - foreign key to user table
        api_name: Name of the API counter field to increment
    """
    # Get current usage
    result = db.execute(
        text("SELECT api_usage FROM unsubscribed_user_api_usage WHERE user_id = :user_id"),
        {"user_id": user_id}
    ).fetchone()
    
    if not result:
        logger.warning("Authenticated user usage record not found", user_id=user_id)
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
            UPDATE unsubscribed_user_api_usage 
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
    
    logger.info("Incremented authenticated API usage", user_id=user_id, api_name=api_name, count=api_usage[api_name])


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
    
    # Invalidate cached session data to prevent stale access_token_expires_at
    cache = get_in_memory_cache()
    cache_key = f"USER_SESSION_INFO:{session_id}"
    cache.invalidate_key(cache_key)
    
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
            SELECT id, word, contextual_meaning, source_url, folder_id, user_id, created_at
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
        word_id, word, contextual_meaning, source_url, folder_id, user_id_val, created_at = row
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
            "folder_id": folder_id,
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


def get_saved_words_by_folder_id_and_user_id(
    db: Session,
    user_id: str,
    folder_id: str,
    offset: int = 0,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get saved words for a user and folder with pagination, ordered by created_at DESC.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        folder_id: Folder ID (CHAR(36) UUID)
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 20)
        
    Returns:
        Tuple of (list of saved words dictionaries, total count)
    """
    logger.info(
        "Getting saved words by user_id and folder_id",
        function="get_saved_words_by_folder_id_and_user_id",
        user_id=user_id,
        folder_id=folder_id,
        offset=offset,
        limit=limit
    )
    
    # Get total count
    count_result = db.execute(
        text("SELECT COUNT(*) FROM saved_word WHERE user_id = :user_id AND folder_id = :folder_id"),
        {
            "user_id": user_id,
            "folder_id": folder_id
        }
    ).fetchone()
    
    total_count = count_result[0] if count_result else 0
    
    # Get paginated words
    words_result = db.execute(
        text("""
            SELECT id, word, contextual_meaning, source_url, folder_id, user_id, created_at
            FROM saved_word
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
    
    words = []
    for row in words_result:
        word_id, word, contextual_meaning, source_url, folder_id_val, user_id_val, created_at = row
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
            "folder_id": folder_id_val,
            "user_id": user_id_val,
            "created_at": created_at_str
        })
    
    logger.info(
        "Retrieved saved words successfully",
        function="get_saved_words_by_folder_id_and_user_id",
        user_id=user_id,
        folder_id=folder_id,
        words_count=len(words),
        total_count=total_count
    )
    
    return words, total_count


def create_saved_word(
    db: Session,
    user_id: str,
    word: str,
    source_url: str,
    folder_id: str,
    contextual_meaning: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new saved word for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        word: Word to save (max 32 characters)
        source_url: Source URL (max 1024 characters)
        folder_id: Folder ID (CHAR(36) UUID)
        contextual_meaning: Optional contextual meaning (max 1000 characters)
        
    Returns:
        Dictionary with created saved word data
    """
    logger.info(
        "Creating saved word",
        function="create_saved_word",
        user_id=user_id,
        word=word,
        source_url_length=len(source_url),
        folder_id=folder_id,
        has_contextual_meaning=contextual_meaning is not None
    )
    
    # Generate UUID for the new saved word
    word_id = str(uuid.uuid4())
    
    # Insert the new saved word
    db.execute(
        text("""
            INSERT INTO saved_word (id, word, source_url, folder_id, user_id, contextual_meaning)
            VALUES (:id, :word, :source_url, :folder_id, :user_id, :contextual_meaning)
        """),
        {
            "id": word_id,
            "word": word,
            "source_url": source_url,
            "folder_id": folder_id,
            "user_id": user_id,
            "contextual_meaning": contextual_meaning
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, word, contextual_meaning, source_url, folder_id, user_id, created_at
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
    
    word_id_val, word_val, contextual_meaning_val, source_url_val, folder_id_val, user_id_val, created_at = result
    
    # Convert created_at to ISO format string
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    saved_word = {
        "id": word_id_val,
        "word": word_val,
        "contextual_meaning": contextual_meaning_val,
        "source_url": source_url_val,
        "folder_id": folder_id_val,
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


def create_pre_launch_user(
    db: Session,
    email: str,
    meta_info: Optional[dict] = None
) -> Dict[str, Any]:
    """
    Create a new pre-launch user record.
    
    Args:
        db: Database session
        email: Email address of the pre-launch user
        meta_info: Optional metadata dictionary (will be converted to JSON)
        
    Returns:
        Dictionary with created pre-launch user data
    """
    logger.info(
        "Creating pre-launch user",
        function="create_pre_launch_user",
        email=email,
        has_meta_info=meta_info is not None
    )
    
    # Generate UUID for the new pre-launch user
    pre_launch_user_id = str(uuid.uuid4())
    
    # Convert meta_info dict to JSON string if provided
    meta_info_json = None
    if meta_info is not None:
        meta_info_json = json.dumps(meta_info)
    
    # Insert the new pre-launch user
    db.execute(
        text("""
            INSERT INTO pre_launch_user (id, email, meta_info)
            VALUES (:id, :email, :meta_info)
        """),
        {
            "id": pre_launch_user_id,
            "email": email,
            "meta_info": meta_info_json
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, email, meta_info, created_at, updated_at
            FROM pre_launch_user
            WHERE id = :id
        """),
        {"id": pre_launch_user_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created pre-launch user",
            function="create_pre_launch_user",
            pre_launch_user_id=pre_launch_user_id
        )
        raise Exception("Failed to retrieve created pre-launch user")
    
    record_id, record_email, record_meta_info, created_at, updated_at = result
    
    # Parse meta_info JSON if it's a string
    meta_info_dict = None
    if record_meta_info:
        if isinstance(record_meta_info, str):
            try:
                meta_info_dict = json.loads(record_meta_info)
            except json.JSONDecodeError:
                meta_info_dict = None
        else:
            meta_info_dict = record_meta_info
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    pre_launch_user = {
        "id": record_id,
        "email": record_email,
        "meta_info": meta_info_dict,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created pre-launch user successfully",
        function="create_pre_launch_user",
        pre_launch_user_id=record_id,
        email=record_email
    )
    
    return pre_launch_user


def get_pre_launch_user_by_email(
    db: Session,
    email: str,
) -> Optional[Dict[str, Any]]:
    """
    Get a pre-launch user record by email.
    
    Args:
        db: Database session
        email: Email address of the pre-launch user
        
    Returns:
        Dictionary with pre-launch user data or None if not found
    """
    logger.info(
        "Getting pre-launch user by email",
        function="get_pre_launch_user_by_email",
        email=email,
    )
    
    result = db.execute(
        text("""
            SELECT id, email, meta_info, created_at, updated_at
            FROM pre_launch_user
            WHERE email = :email
            LIMIT 1
        """),
        {"email": email}
    ).fetchone()
    
    if not result:
        logger.info(
            "Pre-launch user not found by email",
            function="get_pre_launch_user_by_email",
            email=email,
        )
        return None
    
    record_id, record_email, record_meta_info, created_at, updated_at = result
    
    # Parse meta_info JSON if it's a string
    meta_info_dict = None
    if record_meta_info:
        if isinstance(record_meta_info, str):
            try:
                meta_info_dict = json.loads(record_meta_info)
            except json.JSONDecodeError:
                meta_info_dict = None
        else:
            meta_info_dict = record_meta_info
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    pre_launch_user = {
        "id": record_id,
        "email": record_email,
        "meta_info": meta_info_dict,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Retrieved pre-launch user by email successfully",
        function="get_pre_launch_user_by_email",
        pre_launch_user_id=record_id,
        email=record_email
    )
    
    return pre_launch_user


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
            SELECT id, word, contextual_meaning, source_url, user_id, created_at
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
    
    word_id_val, word, contextual_meaning, source_url, user_id_val, created_at = result
    
    # Convert created_at to ISO format string
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    saved_word = {
        "id": word_id_val,
        "word": word,
        "contextual_meaning": contextual_meaning,
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


def update_saved_word_folder_id(
    db: Session,
    word_id: str,
    user_id: str,
    new_folder_id: str
) -> Optional[Dict[str, Any]]:
    """
    Update the folder_id for a saved word.
    
    Args:
        db: Database session
        word_id: Saved word ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID) - for validation
        new_folder_id: New folder ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with updated saved word data or None if not found or doesn't belong to user
    """
    logger.info(
        "Updating saved word folder_id",
        function="update_saved_word_folder_id",
        word_id=word_id,
        user_id=user_id,
        new_folder_id=new_folder_id
    )
    
    # Update the folder_id (saved_word table doesn't have updated_at)
    result = db.execute(
        text("""
            UPDATE saved_word
            SET folder_id = :new_folder_id
            WHERE id = :word_id AND user_id = :user_id
        """),
        {
            "word_id": word_id,
            "user_id": user_id,
            "new_folder_id": new_folder_id
        }
    )
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "Saved word not found or doesn't belong to user",
            function="update_saved_word_folder_id",
            word_id=word_id,
            user_id=user_id
        )
        return None
    
    # Fetch the updated record
    fetch_result = db.execute(
        text("""
            SELECT id, word, contextual_meaning, source_url, folder_id, user_id, created_at
            FROM saved_word
            WHERE id = :word_id
        """),
        {"word_id": word_id}
    ).fetchone()
    
    if not fetch_result:
        logger.error(
            "Failed to retrieve updated saved word",
            function="update_saved_word_folder_id",
            word_id=word_id
        )
        return None
    
    word_id_val, word, contextual_meaning, source_url, folder_id_val, user_id_val, created_at = fetch_result
    
    # Convert created_at to ISO format string
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    saved_word = {
        "id": word_id_val,
        "word": word,
        "contextual_meaning": contextual_meaning,
        "source_url": source_url,
        "folder_id": folder_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str
    }
    
    logger.info(
        "Updated saved word folder_id successfully",
        function="update_saved_word_folder_id",
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
                SELECT id, name, parent_id, user_id, created_at, updated_at
                FROM folder
                WHERE user_id = :user_id AND parent_id IS NULL
                ORDER BY created_at DESC
            """),
            {"user_id": user_id}
        ).fetchall()
    else:
        result = db.execute(
            text("""
                SELECT id, name, parent_id, user_id, created_at, updated_at
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
        folder_id, name, parent_id_val, user_id_val, created_at, updated_at = row
        
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
    folder_id: str,
    name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new saved paragraph for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        content: Paragraph content (TEXT)
        source_url: Source URL (max 1024 characters)
        folder_id: Folder ID (CHAR(36) UUID)
        name: Optional name for the paragraph (max 50 characters)
        
    Returns:
        Dictionary with created saved paragraph data
    """
    logger.info(
        "Creating saved paragraph",
        function="create_saved_paragraph",
        user_id=user_id,
        content_length=len(content),
        source_url_length=len(source_url),
        folder_id=folder_id,
        has_name=name is not None
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


def get_saved_paragraph_by_id_and_user_id(
    db: Session,
    paragraph_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a saved paragraph by ID and verify it belongs to the user.
    
    Args:
        db: Database session
        paragraph_id: Saved paragraph ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with saved paragraph data or None if not found or doesn't belong to user
    """
    logger.info(
        "Getting saved paragraph by id and user_id",
        function="get_saved_paragraph_by_id_and_user_id",
        paragraph_id=paragraph_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            SELECT id, source_url, name, content, folder_id, user_id, created_at, updated_at
            FROM saved_paragraph
            WHERE id = :paragraph_id AND user_id = :user_id
        """),
        {
            "paragraph_id": paragraph_id,
            "user_id": user_id
        }
    ).fetchone()
    
    if not result:
        logger.warning(
            "Saved paragraph not found or doesn't belong to user",
            function="get_saved_paragraph_by_id_and_user_id",
            paragraph_id=paragraph_id,
            user_id=user_id
        )
        return None
    
    para_id, source_url, name, content, folder_id, user_id_val, created_at, updated_at = result
    
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
        "source_url": source_url,
        "name": name,
        "content": content,
        "folder_id": folder_id,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Retrieved saved paragraph successfully",
        function="get_saved_paragraph_by_id_and_user_id",
        paragraph_id=para_id,
        user_id=user_id
    )
    
    return saved_paragraph


def get_saved_paragraphs_by_ids_and_user_id(
    db: Session,
    paragraph_ids: List[str],
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Get multiple saved paragraphs by IDs and verify they all belong to the user.
    
    Args:
        db: Database session
        paragraph_ids: List of saved paragraph IDs (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        List of dictionaries with saved paragraph data. Only returns paragraphs that belong to the user.
        If some IDs don't belong to the user or don't exist, they are silently excluded.
    """
    logger.info(
        "Getting saved paragraphs by ids and user_id",
        function="get_saved_paragraphs_by_ids_and_user_id",
        paragraph_ids=paragraph_ids,
        user_id=user_id,
        ids_count=len(paragraph_ids)
    )
    
    if not paragraph_ids:
        return []
    
    # Build query with IN clause
    placeholders = ",".join([f":id_{i}" for i in range(len(paragraph_ids))])
    params = {f"id_{i}": para_id for i, para_id in enumerate(paragraph_ids)}
    params["user_id"] = user_id
    
    result = db.execute(
        text(f"""
            SELECT id, source_url, name, content, folder_id, user_id, created_at, updated_at
            FROM saved_paragraph
            WHERE id IN ({placeholders}) AND user_id = :user_id
        """),
        params
    ).fetchall()
    
    paragraphs = []
    for row in result:
        para_id, source_url, name, content, folder_id, user_id_val, created_at, updated_at = row
        
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
            "folder_id": folder_id,
            "user_id": user_id_val,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        })
    
    logger.info(
        "Retrieved saved paragraphs successfully",
        function="get_saved_paragraphs_by_ids_and_user_id",
        requested_count=len(paragraph_ids),
        retrieved_count=len(paragraphs),
        user_id=user_id
    )
    
    return paragraphs


def update_saved_paragraph_folder_id(
    db: Session,
    paragraph_id: str,
    user_id: str,
    new_folder_id: str
) -> Optional[Dict[str, Any]]:
    """
    Update the folder_id for a saved paragraph.
    
    Args:
        db: Database session
        paragraph_id: Saved paragraph ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID) - for validation
        new_folder_id: New folder ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with updated saved paragraph data or None if not found or doesn't belong to user
    """
    logger.info(
        "Updating saved paragraph folder_id",
        function="update_saved_paragraph_folder_id",
        paragraph_id=paragraph_id,
        user_id=user_id,
        new_folder_id=new_folder_id
    )
    
    # Update the folder_id
    result = db.execute(
        text("""
            UPDATE saved_paragraph
            SET folder_id = :new_folder_id, updated_at = CURRENT_TIMESTAMP
            WHERE id = :paragraph_id AND user_id = :user_id
        """),
        {
            "paragraph_id": paragraph_id,
            "user_id": user_id,
            "new_folder_id": new_folder_id
        }
    )
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "Saved paragraph not found or doesn't belong to user",
            function="update_saved_paragraph_folder_id",
            paragraph_id=paragraph_id,
            user_id=user_id
        )
        return None
    
    # Fetch the updated record
    fetch_result = db.execute(
        text("""
            SELECT id, source_url, name, content, folder_id, user_id, created_at, updated_at
            FROM saved_paragraph
            WHERE id = :paragraph_id
        """),
        {"paragraph_id": paragraph_id}
    ).fetchone()
    
    if not fetch_result:
        logger.error(
            "Failed to retrieve updated saved paragraph",
            function="update_saved_paragraph_folder_id",
            paragraph_id=paragraph_id
        )
        return None
    
    para_id, source_url, name, content, folder_id_val, user_id_val, created_at, updated_at = fetch_result
    
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
        "source_url": source_url,
        "name": name,
        "content": content,
        "folder_id": folder_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Updated saved paragraph folder_id successfully",
        function="update_saved_paragraph_folder_id",
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
            SELECT id, name, parent_id, user_id, created_at, updated_at
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
    
    folder_id_val, name, parent_id, user_id_val, created_at, updated_at = result
    
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


def update_folder_name_by_id_and_user_id(
    db: Session,
    folder_id: str,
    user_id: str,
    new_name: str
) -> Optional[Dict[str, Any]]:
    """
    Update a folder's name by ID if it belongs to the user.
    
    Args:
        db: Database session
        folder_id: Folder ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        new_name: New folder name (max 50 characters)
        
    Returns:
        Dictionary with updated folder data or None if not found or doesn't belong to user
    """
    logger.info(
        "Updating folder name by id and user_id",
        function="update_folder_name_by_id_and_user_id",
        folder_id=folder_id,
        user_id=user_id,
        new_name=new_name
    )
    
    result = db.execute(
        text("""
            UPDATE folder
            SET name = :name, updated_at = CURRENT_TIMESTAMP
            WHERE id = :folder_id AND user_id = :user_id
        """),
        {
            "name": new_name,
            "folder_id": folder_id,
            "user_id": user_id
        }
    )
    
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "Folder not found or doesn't belong to user",
            function="update_folder_name_by_id_and_user_id",
            folder_id=folder_id,
            user_id=user_id
        )
        return None
    
    # Fetch the updated record
    result = db.execute(
        text("""
            SELECT id, name, parent_id, user_id, created_at, updated_at
            FROM folder
            WHERE id = :folder_id
        """),
        {"folder_id": folder_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve updated folder",
            function="update_folder_name_by_id_and_user_id",
            folder_id=folder_id
        )
        return None
    
    folder_id_val, name, parent_id, user_id_val, created_at, updated_at = result
    
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
        "parent_id": parent_id,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Updated folder name successfully",
        function="update_folder_name_by_id_and_user_id",
        folder_id=folder_id_val,
        user_id=user_id
    )
    
    return folder


def create_paragraph_folder(
    db: Session,
    user_id: str,
    name: str,
    parent_folder_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new folder for a user.
    
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
    
    # Insert the new folder
    db.execute(
        text("""
            INSERT INTO folder (id, name, parent_id, user_id)
            VALUES (:id, :name, :parent_id, :user_id)
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
            SELECT id, name, parent_id, user_id, created_at, updated_at
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
    
    folder_id_val, name_val, parent_id_val, user_id_val, created_at, updated_at = result
    
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


def get_saved_links_by_user_id_and_folder_id(
    db: Session,
    user_id: str,
    folder_id: Optional[str] = None,
    offset: int = 0,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get saved links for a user with pagination, ordered by created_at DESC.
    If folder_id is None, get links where folder_id IS NULL.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        folder_id: Folder ID (CHAR(36) UUID) or None for root links
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 20)
        
    Returns:
        Tuple of (list of link dictionaries, total count)
    """
    logger.info(
        "Getting saved links by user_id and folder_id",
        function="get_saved_links_by_user_id_and_folder_id",
        user_id=user_id,
        folder_id=folder_id,
        offset=offset,
        limit=limit
    )
    
    # Get total count
    if folder_id is None:
        count_result = db.execute(
            text("SELECT COUNT(*) FROM saved_link WHERE user_id = :user_id AND folder_id IS NULL"),
            {"user_id": user_id}
        ).fetchone()
    else:
        count_result = db.execute(
            text("SELECT COUNT(*) FROM saved_link WHERE user_id = :user_id AND folder_id = :folder_id"),
            {
                "user_id": user_id,
                "folder_id": folder_id
            }
        ).fetchone()
    
    total_count = count_result[0] if count_result else 0
    
    # Get paginated links
    if folder_id is None:
        links_result = db.execute(
            text("""
                SELECT id, url, name, type, summary, metadata, folder_id, user_id, created_at, updated_at
                FROM saved_link
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
        links_result = db.execute(
            text("""
                SELECT id, url, name, type, summary, metadata, folder_id, user_id, created_at, updated_at
                FROM saved_link
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
    
    links = []
    for row in links_result:
        link_id, url, name, link_type, summary, metadata, folder_id_val, user_id_val, created_at, updated_at = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        # Parse metadata JSON if it's a string
        metadata_dict = None
        if metadata:
            if isinstance(metadata, str):
                try:
                    metadata_dict = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata_dict = None
            else:
                metadata_dict = metadata
        
        links.append({
            "id": link_id,
            "url": url,
            "name": name,
            "type": link_type,
            "summary": summary,
            "metadata": metadata_dict,
            "folder_id": folder_id_val,
            "user_id": user_id_val,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        })
    
    logger.info(
        "Retrieved saved links successfully",
        function="get_saved_links_by_user_id_and_folder_id",
        user_id=user_id,
        folder_id=folder_id,
        links_count=len(links),
        total_count=total_count,
        offset=offset,
        limit=limit
    )
    
    return links, total_count


def create_saved_link(
    db: Session,
    user_id: str,
    url: str,
    folder_id: str,
    name: Optional[str] = None,
    link_type: Optional[str] = None,
    summary: Optional[str] = None,
    metadata: Optional[dict] = None
) -> Dict[str, Any]:
    """
    Create a new saved link for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        url: Link URL (max 1024 characters)
        folder_id: Folder ID (CHAR(36) UUID)
        name: Optional name for the link (max 50 characters)
        link_type: Optional link type (defaults to 'WEBPAGE' if None)
        summary: Optional summary text
        metadata: Optional metadata dictionary (will be converted to JSON)
        
    Returns:
        Dictionary with created saved link data
    """
    logger.info(
        "Creating saved link",
        function="create_saved_link",
        user_id=user_id,
        url_length=len(url),
        folder_id=folder_id,
        has_name=name is not None,
        link_type=link_type
    )
    
    # Generate UUID for the new saved link
    link_id = str(uuid.uuid4())
    
    # Default to WEBPAGE if type is not provided
    if link_type is None:
        link_type = 'WEBPAGE'
    
    # Convert metadata dict to JSON string if provided
    metadata_json = None
    if metadata is not None:
        metadata_json = json.dumps(metadata)
    
    # Insert the new saved link
    db.execute(
        text("""
            INSERT INTO saved_link (id, url, name, type, summary, metadata, folder_id, user_id)
            VALUES (:id, :url, :name, :type, :summary, :metadata, :folder_id, :user_id)
        """),
        {
            "id": link_id,
            "url": url,
            "name": name,
            "type": link_type,
            "summary": summary,
            "metadata": metadata_json,
            "folder_id": folder_id,
            "user_id": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, url, name, type, summary, metadata, folder_id, user_id, created_at, updated_at
            FROM saved_link
            WHERE id = :id
        """),
        {"id": link_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created saved link",
            function="create_saved_link",
            link_id=link_id
        )
        raise Exception("Failed to retrieve created saved link")
    
    link_id_val, url_val, name_val, link_type_val, summary_val, metadata_val, folder_id_val, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Parse metadata JSON if it's a string
    metadata_dict = None
    if metadata_val:
        if isinstance(metadata_val, str):
            try:
                metadata_dict = json.loads(metadata_val)
            except json.JSONDecodeError:
                metadata_dict = None
        else:
            metadata_dict = metadata_val
    
    saved_link = {
        "id": link_id_val,
        "url": url_val,
        "name": name_val,
        "type": link_type_val,
        "summary": summary_val,
        "metadata": metadata_dict,
        "folder_id": folder_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created saved link successfully",
        function="create_saved_link",
        link_id=link_id_val,
        user_id=user_id
    )
    
    return saved_link


def delete_saved_link_by_id_and_user_id(
    db: Session,
    link_id: str,
    user_id: str
) -> bool:
    """
    Delete a saved link by ID if it belongs to the user.
    
    Args:
        db: Database session
        link_id: Saved link ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        True if link was deleted, False if not found or doesn't belong to user
    """
    logger.info(
        "Deleting saved link by id and user_id",
        function="delete_saved_link_by_id_and_user_id",
        link_id=link_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            DELETE FROM saved_link
            WHERE id = :link_id AND user_id = :user_id
        """),
        {
            "link_id": link_id,
            "user_id": user_id
        }
    )
    
    db.commit()
    
    if result.rowcount > 0:
        logger.info(
            "Deleted saved link successfully",
            function="delete_saved_link_by_id_and_user_id",
            link_id=link_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return True
    else:
        logger.warning(
            "Saved link not found or doesn't belong to user",
            function="delete_saved_link_by_id_and_user_id",
            link_id=link_id,
            user_id=user_id,
            rows_deleted=result.rowcount
        )
        return False


def get_saved_link_by_url_and_user_id(
    db: Session,
    url: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a saved link by URL and verify it belongs to the user.
    
    Args:
        db: Database session
        url: Link URL
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with saved link data or None if not found or doesn't belong to user
    """
    logger.info(
        "Getting saved link by url and user_id",
        function="get_saved_link_by_url_and_user_id",
        url=url,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            SELECT id, url, name, type, summary, metadata, folder_id, user_id, created_at, updated_at
            FROM saved_link
            WHERE url = :url AND user_id = :user_id
        """),
        {
            "url": url,
            "user_id": user_id
        }
    ).fetchone()
    
    if not result:
        logger.info(
            "Saved link not found by URL",
            function="get_saved_link_by_url_and_user_id",
            url=url,
            user_id=user_id
        )
        return None
    
    link_id_val, url_val, name, link_type, summary, metadata, folder_id, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Parse metadata JSON if it's a string
    metadata_dict = None
    if metadata:
        if isinstance(metadata, str):
            try:
                metadata_dict = json.loads(metadata)
            except json.JSONDecodeError:
                metadata_dict = None
        else:
            metadata_dict = metadata
    
    saved_link = {
        "id": link_id_val,
        "url": url_val,
        "name": name,
        "type": link_type,
        "summary": summary,
        "metadata": metadata_dict,
        "folder_id": folder_id,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Retrieved saved link by URL successfully",
        function="get_saved_link_by_url_and_user_id",
        link_id=link_id_val,
        user_id=user_id
    )
    
    return saved_link


def update_saved_link_summary_and_metadata(
    db: Session,
    link_id: str,
    user_id: str,
    summary: Optional[str] = None,
    metadata: Optional[dict] = None
) -> Optional[Dict[str, Any]]:
    """
    Update summary and metadata for an existing saved link.
    Summary is only updated if it's not None and has non-zero stripped length.
    
    Args:
        db: Database session
        link_id: Saved link ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        summary: Optional summary text to update (only updated if not None and stripped length > 0)
        metadata: Optional metadata dictionary to update (will be converted to JSON)
        
    Returns:
        Dictionary with updated saved link data or None if not found or doesn't belong to user
    """
    # Check if summary should be updated (not None and has non-zero stripped length)
    should_update_summary = summary is not None and len(summary.strip()) > 0
    
    logger.info(
        "Updating saved link summary and metadata",
        function="update_saved_link_summary_and_metadata",
        link_id=link_id,
        user_id=user_id,
        has_summary=summary is not None,
        should_update_summary=should_update_summary,
        has_metadata=metadata is not None
    )
    
    # Convert metadata dict to JSON string if provided
    metadata_json = None
    if metadata is not None:
        metadata_json = json.dumps(metadata)
    
    # Build UPDATE statement conditionally based on what needs to be updated
    update_fields = []
    params = {
        "link_id": link_id,
        "user_id": user_id
    }
    
    if should_update_summary:
        update_fields.append("summary = :summary")
        params["summary"] = summary.strip()
    
    if metadata_json is not None:
        update_fields.append("metadata = :metadata")
        params["metadata"] = metadata_json
    
    # Always update updated_at timestamp
    update_fields.append("updated_at = CURRENT_TIMESTAMP")
    
    # Update the saved link (always update updated_at at minimum)
    update_query = f"""
        UPDATE saved_link
        SET {', '.join(update_fields)}
        WHERE id = :link_id AND user_id = :user_id
    """
    
    result = db.execute(
        text(update_query),
        params
    )
    
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "Saved link not found or doesn't belong to user",
            function="update_saved_link_summary_and_metadata",
            link_id=link_id,
            user_id=user_id
        )
        return None
    
    # Fetch the updated record
    updated_result = db.execute(
        text("""
            SELECT id, url, name, type, summary, metadata, folder_id, user_id, created_at, updated_at
            FROM saved_link
            WHERE id = :id
        """),
        {"id": link_id}
    ).fetchone()
    
    if not updated_result:
        logger.error(
            "Failed to retrieve updated saved link",
            function="update_saved_link_summary_and_metadata",
            link_id=link_id
        )
        return None
    
    link_id_val, url_val, name_val, link_type_val, summary_val, metadata_val, folder_id_val, user_id_val, created_at, updated_at = updated_result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Parse metadata JSON if it's a string
    metadata_dict = None
    if metadata_val:
        if isinstance(metadata_val, str):
            try:
                metadata_dict = json.loads(metadata_val)
            except json.JSONDecodeError:
                metadata_dict = None
        else:
            metadata_dict = metadata_val
    
    saved_link = {
        "id": link_id_val,
        "url": url_val,
        "name": name_val,
        "type": link_type_val,
        "summary": summary_val,
        "metadata": metadata_dict,
        "folder_id": folder_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Updated saved link summary and metadata successfully",
        function="update_saved_link_summary_and_metadata",
        link_id=link_id_val,
        user_id=user_id
    )
    
    return saved_link


def get_saved_link_by_id_and_user_id(
    db: Session,
    link_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a saved link by ID and verify it belongs to the user.
    
    Args:
        db: Database session
        link_id: Saved link ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with saved link data or None if not found or doesn't belong to user
    """
    logger.info(
        "Getting saved link by id and user_id",
        function="get_saved_link_by_id_and_user_id",
        link_id=link_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            SELECT id, url, name, type, summary, metadata, folder_id, user_id, created_at, updated_at
            FROM saved_link
            WHERE id = :link_id AND user_id = :user_id
        """),
        {
            "link_id": link_id,
            "user_id": user_id
        }
    ).fetchone()
    
    if not result:
        logger.warning(
            "Saved link not found or doesn't belong to user",
            function="get_saved_link_by_id_and_user_id",
            link_id=link_id,
            user_id=user_id
        )
        return None
    
    link_id_val, url, name, link_type, summary, metadata, folder_id, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Parse metadata JSON if it's a string
    metadata_dict = None
    if metadata:
        if isinstance(metadata, str):
            try:
                metadata_dict = json.loads(metadata)
            except json.JSONDecodeError:
                metadata_dict = None
        else:
            metadata_dict = metadata
    
    saved_link = {
        "id": link_id_val,
        "url": url,
        "name": name,
        "type": link_type,
        "summary": summary,
        "metadata": metadata_dict,
        "folder_id": folder_id,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Retrieved saved link successfully",
        function="get_saved_link_by_id_and_user_id",
        link_id=link_id_val,
        user_id=user_id
    )
    
    return saved_link


def update_saved_link_folder_id(
    db: Session,
    link_id: str,
    user_id: str,
    new_folder_id: str
) -> Optional[Dict[str, Any]]:
    """
    Update the folder_id for a saved link.
    
    Args:
        db: Database session
        link_id: Saved link ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID) - for validation
        new_folder_id: New folder ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with updated saved link data or None if not found or doesn't belong to user
    """
    logger.info(
        "Updating saved link folder_id",
        function="update_saved_link_folder_id",
        link_id=link_id,
        user_id=user_id,
        new_folder_id=new_folder_id
    )
    
    # Update the folder_id
    result = db.execute(
        text("""
            UPDATE saved_link
            SET folder_id = :new_folder_id, updated_at = CURRENT_TIMESTAMP
            WHERE id = :link_id AND user_id = :user_id
        """),
        {
            "link_id": link_id,
            "user_id": user_id,
            "new_folder_id": new_folder_id
        }
    )
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "Saved link not found or doesn't belong to user",
            function="update_saved_link_folder_id",
            link_id=link_id,
            user_id=user_id
        )
        return None
    
    # Fetch the updated record
    fetch_result = db.execute(
        text("""
            SELECT id, url, name, type, summary, metadata, folder_id, user_id, created_at, updated_at
            FROM saved_link
            WHERE id = :link_id
        """),
        {"link_id": link_id}
    ).fetchone()
    
    if not fetch_result:
        logger.error(
            "Failed to retrieve updated saved link",
            function="update_saved_link_folder_id",
            link_id=link_id
        )
        return None
    
    link_id_val, url, name, link_type, summary, metadata, folder_id_val, user_id_val, created_at, updated_at = fetch_result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Parse metadata JSON if it's a string
    metadata_dict = None
    if metadata:
        if isinstance(metadata, str):
            try:
                metadata_dict = json.loads(metadata)
            except json.JSONDecodeError:
                metadata_dict = None
        else:
            metadata_dict = metadata
    
    saved_link = {
        "id": link_id_val,
        "url": url,
        "name": name,
        "type": link_type,
        "summary": summary,
        "metadata": metadata_dict,
        "folder_id": folder_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Updated saved link folder_id successfully",
        function="update_saved_link_folder_id",
        link_id=link_id_val,
        user_id=user_id
    )
    
    return saved_link


def get_saved_images_by_folder_id_and_user_id(
    db: Session,
    user_id: str,
    folder_id: str,
    offset: int = 0,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get saved images for a user and folder with pagination, ordered by created_at DESC.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        folder_id: Folder ID (CHAR(36) UUID)
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 20)
        
    Returns:
        Tuple of (list of image dictionaries, total count)
    """
    logger.info(
        "Getting saved images by user_id and folder_id",
        function="get_saved_images_by_folder_id_and_user_id",
        user_id=user_id,
        folder_id=folder_id,
        offset=offset,
        limit=limit
    )
    
    # Get total count
    count_result = db.execute(
        text("SELECT COUNT(*) FROM saved_image WHERE user_id = :user_id AND folder_id = :folder_id"),
        {
            "user_id": user_id,
            "folder_id": folder_id
        }
    ).fetchone()
    
    total_count = count_result[0] if count_result else 0
    
    # Get paginated images
    images_result = db.execute(
        text("""
            SELECT id, source_url, image_url, name, folder_id, user_id, created_at, updated_at
            FROM saved_image
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
    
    images = []
    for row in images_result:
        image_id, source_url, image_url, name, folder_id_val, user_id_val, created_at, updated_at = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        images.append({
            "id": image_id,
            "source_url": source_url,
            "image_url": image_url,
            "name": name,
            "folder_id": folder_id_val,
            "user_id": user_id_val,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        })
    
    logger.info(
        "Retrieved saved images successfully",
        function="get_saved_images_by_folder_id_and_user_id",
        user_id=user_id,
        folder_id=folder_id,
        images_count=len(images),
        total_count=total_count,
        offset=offset,
        limit=limit
    )
    
    return images, total_count


def create_saved_image(
    db: Session,
    user_id: str,
    source_url: str,
    image_url: str,
    folder_id: str,
    name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new saved image for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        source_url: Source URL (max 1024 characters)
        image_url: Image URL (max 1024 characters)
        folder_id: Folder ID (CHAR(36) UUID)
        name: Optional name for the image (max 100 characters)
        
    Returns:
        Dictionary with created saved image data
    """
    logger.info(
        "Creating saved image",
        function="create_saved_image",
        user_id=user_id,
        source_url_length=len(source_url),
        image_url_length=len(image_url),
        folder_id=folder_id,
        has_name=name is not None
    )
    
    # Generate UUID for the new saved image
    image_id = str(uuid.uuid4())
    
    # Insert the new saved image
    db.execute(
        text("""
            INSERT INTO saved_image (id, source_url, image_url, name, folder_id, user_id)
            VALUES (:id, :source_url, :image_url, :name, :folder_id, :user_id)
        """),
        {
            "id": image_id,
            "source_url": source_url,
            "image_url": image_url,
            "name": name,
            "folder_id": folder_id,
            "user_id": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, source_url, image_url, name, folder_id, user_id, created_at, updated_at
            FROM saved_image
            WHERE id = :id
        """),
        {"id": image_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created saved image",
            function="create_saved_image",
            image_id=image_id
        )
        raise Exception("Failed to retrieve created saved image")
    
    image_id_val, source_url_val, image_url_val, name_val, folder_id_val, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    saved_image = {
        "id": image_id_val,
        "source_url": source_url_val,
        "image_url": image_url_val,
        "name": name_val,
        "folder_id": folder_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created saved image successfully",
        function="create_saved_image",
        image_id=image_id_val,
        user_id=user_id
    )
    
    return saved_image


def get_saved_image_by_id_and_user_id(
    db: Session,
    image_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a saved image by ID and verify it belongs to the user.
    
    Args:
        db: Database session
        image_id: Saved image ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with saved image data or None if not found or doesn't belong to user
    """
    logger.info(
        "Getting saved image by id and user_id",
        function="get_saved_image_by_id_and_user_id",
        image_id=image_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            SELECT id, source_url, image_url, name, folder_id, user_id, created_at, updated_at
            FROM saved_image
            WHERE id = :image_id AND user_id = :user_id
        """),
        {
            "image_id": image_id,
            "user_id": user_id
        }
    ).fetchone()
    
    if not result:
        logger.warning(
            "Saved image not found or doesn't belong to user",
            function="get_saved_image_by_id_and_user_id",
            image_id=image_id,
            user_id=user_id
        )
        return None
    
    image_id_val, source_url, image_url, name, folder_id, user_id_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    saved_image = {
        "id": image_id_val,
        "source_url": source_url,
        "image_url": image_url,
        "name": name,
        "folder_id": folder_id,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Retrieved saved image successfully",
        function="get_saved_image_by_id_and_user_id",
        image_id=image_id_val,
        user_id=user_id
    )
    
    return saved_image


def update_saved_image_folder_id(
    db: Session,
    image_id: str,
    user_id: str,
    new_folder_id: str
) -> Optional[Dict[str, Any]]:
    """
    Update the folder_id for a saved image.
    
    Args:
        db: Database session
        image_id: Saved image ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID) - for validation
        new_folder_id: New folder ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with updated saved image data or None if not found or doesn't belong to user
    """
    logger.info(
        "Updating saved image folder_id",
        function="update_saved_image_folder_id",
        image_id=image_id,
        user_id=user_id,
        new_folder_id=new_folder_id
    )
    
    # Update the folder_id
    result = db.execute(
        text("""
            UPDATE saved_image
            SET folder_id = :new_folder_id, updated_at = CURRENT_TIMESTAMP
            WHERE id = :image_id AND user_id = :user_id
        """),
        {
            "image_id": image_id,
            "user_id": user_id,
            "new_folder_id": new_folder_id
        }
    )
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "Saved image not found or doesn't belong to user",
            function="update_saved_image_folder_id",
            image_id=image_id,
            user_id=user_id
        )
        return None
    
    # Fetch the updated record
    fetch_result = db.execute(
        text("""
            SELECT id, source_url, image_url, name, folder_id, user_id, created_at, updated_at
            FROM saved_image
            WHERE id = :image_id
        """),
        {"image_id": image_id}
    ).fetchone()
    
    if not fetch_result:
        logger.error(
            "Failed to retrieve updated saved image",
            function="update_saved_image_folder_id",
            image_id=image_id
        )
        return None
    
    image_id_val, source_url, image_url, name, folder_id_val, user_id_val, created_at, updated_at = fetch_result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    saved_image = {
        "id": image_id_val,
        "source_url": source_url,
        "image_url": image_url,
        "name": name,
        "folder_id": folder_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Updated saved image folder_id successfully",
        function="update_saved_image_folder_id",
        image_id=image_id_val,
        user_id=user_id
    )
    
    return saved_image


def delete_saved_image_by_id_and_user_id(
    db: Session,
    image_id: str,
    user_id: str
) -> bool:
    """
    Delete a saved image by ID and verify it belongs to the user.
    
    Args:
        db: Database session
        image_id: Saved image ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        True if deleted, False if not found or doesn't belong to user
    """
    logger.info(
        "Deleting saved image by id and user_id",
        function="delete_saved_image_by_id_and_user_id",
        image_id=image_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            DELETE FROM saved_image
            WHERE id = :image_id AND user_id = :user_id
        """),
        {
            "image_id": image_id,
            "user_id": user_id
        }
    )
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "Saved image not found or doesn't belong to user",
            function="delete_saved_image_by_id_and_user_id",
            image_id=image_id,
            user_id=user_id
        )
        return False
    
    logger.info(
        "Deleted saved image successfully",
        function="delete_saved_image_by_id_and_user_id",
        image_id=image_id,
        user_id=user_id
    )
    
    return True


def create_link_folder(
    db: Session,
    user_id: str,
    name: str,
    parent_folder_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new folder for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        name: Folder name (max 50 characters)
        parent_folder_id: Optional parent folder ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with created folder data
    """
    logger.info(
        "Creating link folder",
        function="create_link_folder",
        user_id=user_id,
        name=name,
        has_parent_folder_id=parent_folder_id is not None
    )
    
    # Generate UUID for the new folder
    folder_id = str(uuid.uuid4())
    
    # Insert the new folder
    db.execute(
        text("""
            INSERT INTO folder (id, name, parent_id, user_id)
            VALUES (:id, :name, :parent_id, :user_id)
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
            SELECT id, name, parent_id, user_id, created_at, updated_at
            FROM folder
            WHERE id = :id
        """),
        {"id": folder_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created folder",
            function="create_link_folder",
            folder_id=folder_id
        )
        raise Exception("Failed to retrieve created folder")
    
    folder_id_val, name_val, parent_id_val, user_id_val, created_at, updated_at = result
    
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
        "parent_id": parent_id_val,
        "user_id": user_id_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created link folder successfully",
        function="create_link_folder",
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


def get_all_issues(
    db: Session,
    ticket_id: Optional[str] = None,
    issue_type: Optional[str] = None,
    status: Optional[str] = None,
    closed_by: Optional[str] = None,
    offset: int = 0,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get all issues with optional filters and pagination, ordered by created_at ASC.
    
    Args:
        db: Database session
        ticket_id: Optional ticket_id to filter by (exact match)
        issue_type: Optional issue type to filter by (GLITCH, SUBSCRIPTION, etc.)
        status: Optional status to filter by (OPEN, WORK_IN_PROGRESS, etc.)
        closed_by: Optional closed_by user ID to filter by
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 20)
        
    Returns:
        Tuple of (list of issue dictionaries, total count)
    """
    logger.info(
        "Getting all issues with filters",
        function="get_all_issues",
        has_ticket_id=ticket_id is not None,
        has_issue_type=issue_type is not None,
        has_status=status is not None,
        has_closed_by=closed_by is not None,
        offset=offset,
        limit=limit
    )
    
    # Build conditions and params for WHERE clause
    conditions = []
    params = {}
    
    if ticket_id is not None:
        conditions.append("ticket_id = :ticket_id")
        params["ticket_id"] = ticket_id
    
    if issue_type is not None:
        conditions.append("type = :issue_type")
        params["issue_type"] = issue_type
    
    if status is not None:
        conditions.append("status = :status")
        params["status"] = status
    
    if closed_by is not None:
        conditions.append("closed_by = :closed_by")
        params["closed_by"] = closed_by
    
    # Build WHERE clause
    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM issue{where_clause}"
    count_result = db.execute(text(count_query), params).fetchone()
    total_count = count_result[0] if count_result else 0
    
    # Build paginated query
    base_query = f"""
        SELECT id, ticket_id, type, heading, description, webpage_url, status, 
               created_by, closed_by, closed_at, created_at, updated_at
        FROM issue{where_clause}
        ORDER BY created_at ASC
        LIMIT :limit OFFSET :offset
    """
    
    # Add pagination params
    params["limit"] = limit
    params["offset"] = offset
    
    result = db.execute(text(base_query), params)
    rows = result.fetchall()
    
    issues = []
    for row in rows:
        (issue_id, ticket_id_val, type_val, heading_val, description_val, 
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
        issues.append(issue)
    
    logger.info(
        "Retrieved all issues successfully",
        function="get_all_issues",
        issue_count=len(issues),
        total_count=total_count,
        offset=offset,
        limit=limit
    )
    
    return issues, total_count


def get_issue_by_id(
    db: Session,
    issue_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get an issue by its ID.
    
    Args:
        db: Database session
        issue_id: Issue ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with issue data or None if not found
    """
    logger.info(
        "Getting issue by id",
        function="get_issue_by_id",
        issue_id=issue_id
    )
    
    result = db.execute(
        text("""
            SELECT id, ticket_id, type, heading, description, webpage_url, status, 
                   created_by, closed_by, closed_at, created_at, updated_at
            FROM issue
            WHERE id = :issue_id
        """),
        {"issue_id": issue_id}
    )
    
    row = result.fetchone()
    
    if not row:
        logger.info(
            "Issue not found",
            function="get_issue_by_id",
            issue_id=issue_id
        )
        return None
    
    (issue_id_val, ticket_id, type_val, heading_val, description_val, 
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
        "id": issue_id_val,
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
    
    logger.info(
        "Retrieved issue successfully",
        function="get_issue_by_id",
        issue_id=issue_id
    )
    
    return issue


def get_issue_by_ticket_id(
    db: Session,
    ticket_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get an issue by its ticket_id with user information.
    
    Args:
        db: Database session
        ticket_id: Ticket ID (VARCHAR(14))
        
    Returns:
        Dictionary with issue data including created_by_user and closed_by_user, or None if not found
    """
    logger.info(
        "Getting issue by ticket_id",
        function="get_issue_by_ticket_id",
        ticket_id=ticket_id
    )
    
    result = db.execute(
        text("""
            SELECT id, ticket_id, type, heading, description, webpage_url, status, 
                   created_by, closed_by, closed_at, created_at, updated_at
            FROM issue
            WHERE ticket_id = :ticket_id
        """),
        {"ticket_id": ticket_id}
    )
    
    row = result.fetchone()
    
    if not row:
        logger.info(
            "Issue not found",
            function="get_issue_by_ticket_id",
            ticket_id=ticket_id
        )
        return None
    
    (issue_id_val, ticket_id_val, type_val, heading_val, description_val, 
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
    
    # Get user information for created_by
    created_by_user_info = get_user_name_and_role_by_user_id(db, created_by_val)
    
    # Get user information for closed_by (if not None)
    closed_by_user_info = None
    if closed_by_val:
        closed_by_user_info = get_user_name_and_role_by_user_id(db, closed_by_val)
    
    issue = {
        "id": issue_id_val,
        "ticket_id": ticket_id_val,
        "type": type_val,
        "heading": heading_val,
        "description": description_val,
        "webpage_url": webpage_url_val,
        "status": status_val,
        "created_by": created_by_val,
        "created_by_user": {
            "id": created_by_val,
            "name": created_by_user_info.get("name", ""),
            "role": created_by_user_info.get("role"),
            "picture": created_by_user_info.get("picture")
        },
        "closed_by": closed_by_val,
        "closed_by_user": {
            "id": closed_by_val,
            "name": closed_by_user_info.get("name", ""),
            "role": closed_by_user_info.get("role"),
            "picture": closed_by_user_info.get("picture")
        } if closed_by_user_info else None,
        "closed_at": closed_at_str,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Retrieved issue successfully",
        function="get_issue_by_ticket_id",
        ticket_id=ticket_id
    )
    
    return issue


def update_issue(
    db: Session,
    issue_id: str,
    status: str,
    closed_by: Optional[str] = None,
    closed_at: Optional[datetime] = None
) -> Optional[Dict[str, Any]]:
    """
    Update an issue's status and optionally closed_by/closed_at fields.
    
    Args:
        db: Database session
        issue_id: Issue ID (CHAR(36) UUID)
        status: New status value
        closed_by: User ID who closed the issue (optional)
        closed_at: Timestamp when the issue was closed (optional)
        
    Returns:
        Dictionary with updated issue data or None if not found
    """
    logger.info(
        "Updating issue",
        function="update_issue",
        issue_id=issue_id,
        status=status,
        has_closed_by=closed_by is not None,
        has_closed_at=closed_at is not None
    )
    
    # Check if issue exists
    existing = get_issue_by_id(db, issue_id)
    if not existing:
        return None
    
    # Update the issue
    db.execute(
        text("""
            UPDATE issue
            SET status = :status, closed_by = :closed_by, closed_at = :closed_at
            WHERE id = :issue_id
        """),
        {
            "issue_id": issue_id,
            "status": status,
            "closed_by": closed_by,
            "closed_at": closed_at
        }
    )
    db.commit()
    
    # Fetch and return updated issue
    updated_issue = get_issue_by_id(db, issue_id)
    
    logger.info(
        "Issue updated successfully",
        function="update_issue",
        issue_id=issue_id,
        new_status=status
    )
    
    return updated_issue


def get_user_settings_by_user_id(
    db: Session,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get user settings by user_id.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with settings JSON or None if user not found
    """
    logger.info(
        "Getting user settings by user_id",
        function="get_user_settings_by_user_id",
        user_id=user_id
    )
    
    result = db.execute(
        text("SELECT settings FROM user WHERE id = :user_id"),
        {"user_id": user_id}
    ).fetchone()
    
    if not result:
        logger.warning(
            "User not found",
            function="get_user_settings_by_user_id",
            user_id=user_id
        )
        return None
    
    settings_json = result[0]
    
    # Parse JSON if it's a string
    if isinstance(settings_json, str):
        settings_dict = json.loads(settings_json)
    else:
        settings_dict = settings_json
    
    logger.info(
        "User settings retrieved successfully",
        function="get_user_settings_by_user_id",
        user_id=user_id
    )
    
    return settings_dict


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
        Dictionary with 'name' (str), 'role' (Optional[str]), and 'picture' (Optional[str])
    """
    logger.info(
        "Getting user name and role by user_id",
        function="get_user_name_and_role_by_user_id",
        user_id=user_id
    )
    
    # Get name and picture from google_user_auth_info
    name_result = db.execute(
        text("""
            SELECT given_name, family_name, picture
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
    picture = None
    if name_result:
        given_name, family_name, picture = name_result
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
        role=role,
        has_picture=bool(picture)
    )
    
    return {
        "name": name,
        "role": role,
        "picture": picture
    }


def get_user_info_with_email_by_user_id(
    db: Session,
    user_id: str
) -> Dict[str, Any]:
    """
    Get user information including name, role, and email by user_id.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with 'name' (str), 'role' (Optional[str]), and 'email' (Optional[str])
    """
    logger.info(
        "Getting user info with email by user_id",
        function="get_user_info_with_email_by_user_id",
        user_id=user_id
    )
    
    # Get name and email from google_user_auth_info
    name_result = db.execute(
        text("""
            SELECT given_name, family_name, email
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
    email = None
    if name_result:
        given_name, family_name, email = name_result
        name_parts = []
        if given_name:
            name_parts.append(given_name)
        if family_name:
            name_parts.append(family_name)
        name = " ".join(name_parts).strip() if name_parts else ""
    
    # Get role
    role = role_result[0] if role_result else None
    
    logger.info(
        "User info with email retrieved successfully",
        function="get_user_info_with_email_by_user_id",
        user_id=user_id,
        has_name=bool(name),
        has_email=bool(email),
        role=role
    )
    
    return {
        "name": name,
        "role": role,
        "email": email
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
    
    # Get user name and role
    user_info = get_user_name_and_role_by_user_id(db, created_by)
    
    comment = {
        "id": comment_id_val,
        "content": content,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "parent_comment_id": parent_comment_id,
        "visibility": visibility,
        "created_by": created_by,
        "created_by_user": {
            "id": created_by,
            "name": user_info.get("name", ""),
            "role": user_info.get("role"),
            "picture": user_info.get("picture")
        },
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
    
    # First, get root comments (parent_comment_id IS NULL) ordered by created_at ASC
    root_query = text(f"""
        SELECT id, content, entity_type, entity_id, parent_comment_id, 
               visibility, created_by, created_at, updated_at
        FROM comment
        WHERE entity_type = :entity_type 
          AND entity_id = :entity_id 
          AND parent_comment_id IS NULL
          {visibility_filter}
        ORDER BY created_at ASC
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
        user_info = user_info_map.get(user_id, {"name": "", "role": None, "picture": None})
        comment["created_by_user"] = {
            "id": user_id,
            "name": user_info.get("name", ""),
            "role": user_info.get("role"),
            "picture": user_info.get("picture")
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
            "role": user_info.get("role"),
            "picture": user_info.get("picture")
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


def check_pricing_has_subscriptions(
    db: Session,
    pricing_id: str
) -> bool:
    """
    Check if a pricing has any child subscription records.
    
    Args:
        db: Database session
        pricing_id: Pricing ID (CHAR(36) UUID)
        
    Returns:
        True if pricing has subscriptions, False otherwise
    """
    logger.info(
        "Checking if pricing has subscriptions",
        function="check_pricing_has_subscriptions",
        pricing_id=pricing_id
    )
    
    result = db.execute(
        text("SELECT COUNT(*) FROM subscription WHERE pricing_id = :pricing_id"),
        {"pricing_id": pricing_id}
    ).fetchone()
    
    has_subscriptions = result[0] > 0 if result else False
    
    logger.info(
        "Pricing subscription check completed",
        function="check_pricing_has_subscriptions",
        pricing_id=pricing_id,
        has_subscriptions=has_subscriptions
    )
    
    return has_subscriptions


def get_enabled_pricings_for_validation(
    db: Session,
    recurring_period: str,
    recurring_period_count: int
) -> List[Dict[str, Any]]:
    """
    Get ENABLED pricings for intersection validation.
    Gets all ENABLED pricings with the same recurring_period and recurring_period_count.
    
    Args:
        db: Database session
        recurring_period: Recurring period (MONTH or YEAR)
        recurring_period_count: Recurring period count
        
    Returns:
        List of dictionaries with pricing data (id, activation, expiry)
    """
    logger.info(
        "Getting ENABLED pricings for validation",
        function="get_enabled_pricings_for_validation",
        recurring_period=recurring_period,
        recurring_period_count=recurring_period_count
    )
    
    result = db.execute(
        text("""
            SELECT id, activation, expiry
            FROM pricing
            WHERE status = 'ENABLED'
            AND recurring_period = :recurring_period
            AND recurring_period_count = :recurring_period_count
        """),
        {
            "recurring_period": recurring_period,
            "recurring_period_count": recurring_period_count
        }
    ).fetchall()
    
    pricings = []
    for row in result:
        pricing_id, activation, expiry = row
        pricings.append({
            "id": pricing_id,
            "activation": activation,
            "expiry": expiry
        })
    
    logger.info(
        "ENABLED pricings retrieved for validation",
        function="get_enabled_pricings_for_validation",
        recurring_period=recurring_period,
        recurring_period_count=recurring_period_count,
        count=len(pricings)
    )
    
    return pricings


def create_pricing(
    db: Session,
    user_id: str,
    name: str,
    activation: datetime,
    expiry: datetime,
    status: str,
    features: list,
    currency: str,
    pricing_details: dict,
    description: str,
    is_highlighted: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Create a new pricing record.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID) who is creating the pricing
        name: Pricing name (VARCHAR(30))
        activation: Activation timestamp
        expiry: Expiry timestamp
        status: Pricing status (ENABLED or DISABLED)
        features: Pricing features (JSON array)
        currency: Currency (USD)
        pricing_details: Pricing details JSON (monthly/yearly prices and discounts)
        description: Pricing description (VARCHAR(500))
        is_highlighted: Whether pricing is highlighted (BOOLEAN, nullable)
        
    Returns:
        Dictionary with created pricing data including user info
    """
    import json
    
    logger.info(
        "Creating pricing",
        function="create_pricing",
        user_id=user_id,
        name=name,
        status=status,
        currency=currency
    )
    
    # Generate UUID for the new pricing
    pricing_id = str(uuid.uuid4())
    
    # Convert features list and pricing_details dict to JSON strings
    features_json = json.dumps(features)
    pricing_details_json = json.dumps(pricing_details)
    
    # Insert the new pricing
    db.execute(
        text("""
            INSERT INTO pricing (id, name, activation, expiry, status, features, currency, pricing_details, description, is_highlighted, created_by)
            VALUES (:id, :name, :activation, :expiry, :status, :features, :currency, :pricing_details, :description, :is_highlighted, :created_by)
        """),
        {
            "id": pricing_id,
            "name": name,
            "activation": activation,
            "expiry": expiry,
            "status": status,
            "features": features_json,
            "currency": currency,
            "pricing_details": pricing_details_json,
            "description": description,
            "is_highlighted": is_highlighted,
            "created_by": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    return get_pricing_by_id(db, pricing_id)


def get_pricing_by_id(
    db: Session,
    pricing_id: str
) -> Dict[str, Any]:
    """
    Get pricing by ID with user info.
    
    Args:
        db: Database session
        pricing_id: Pricing ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with pricing data including created_by user info
    """
    import json
    
    logger.info(
        "Getting pricing by ID",
        function="get_pricing_by_id",
        pricing_id=pricing_id
    )
    
    result = db.execute(
        text("""
            SELECT id, name, activation, expiry, status, features,
                   currency, pricing_details, description, is_highlighted, created_by, created_at, updated_at
            FROM pricing
            WHERE id = :id
        """),
        {"id": pricing_id}
    ).fetchone()
    
    if not result:
        logger.warning(
            "Pricing not found",
            function="get_pricing_by_id",
            pricing_id=pricing_id
        )
        return None
    
    (pricing_id_val, name_val, activation_val, expiry_val, status_val, features_val, 
     currency_val, pricing_details_val, description_val, is_highlighted_val, created_by_val, created_at, updated_at) = result
    
    # Convert timestamps to ISO format strings
    if isinstance(activation_val, datetime):
        activation_str = activation_val.isoformat() + "Z" if activation_val.tzinfo else activation_val.isoformat()
    else:
        activation_str = str(activation_val)
    
    if isinstance(expiry_val, datetime):
        expiry_str = expiry_val.isoformat() + "Z" if expiry_val.tzinfo else expiry_val.isoformat()
    else:
        expiry_str = str(expiry_val)
    
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Parse JSON fields
    features_list = json.loads(features_val) if isinstance(features_val, str) else features_val
    pricing_details_dict = json.loads(pricing_details_val) if isinstance(pricing_details_val, str) else pricing_details_val
    
    # Get user name and role
    user_info = get_user_name_and_role_by_user_id(db, created_by_val)
    
    pricing = {
        "id": pricing_id_val,
        "name": name_val,
        "activation": activation_str,
        "expiry": expiry_str,
        "status": status_val,
        "features": features_list,
        "currency": currency_val,
        "pricing_details": pricing_details_dict,
        "description": description_val,
        "is_highlighted": bool(is_highlighted_val) if is_highlighted_val is not None else None,
        "created_by": {
            "id": created_by_val,
            "name": user_info.get("name", ""),
            "role": user_info.get("role"),
            "picture": user_info.get("picture")
        },
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Pricing retrieved successfully",
        function="get_pricing_by_id",
        pricing_id=pricing_id_val
    )
    
    return pricing


def update_pricing(
    db: Session,
    pricing_id: str,
    name: Optional[str] = None,
    activation: Optional[datetime] = None,
    expiry: Optional[datetime] = None,
    status: Optional[str] = None,
    features: Optional[list] = None,
    currency: Optional[str] = None,
    pricing_details: Optional[dict] = None,
    description: Optional[str] = None,
    is_highlighted: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Update a pricing record (partial update - only non-null fields).
    
    Args:
        db: Database session
        pricing_id: Pricing ID (CHAR(36) UUID)
        name: Optional pricing name
        activation: Optional activation timestamp
        expiry: Optional expiry timestamp
        status: Optional pricing status
        features: Optional pricing features (list)
        currency: Optional currency (USD)
        pricing_details: Optional pricing details dict
        description: Optional pricing description
        is_highlighted: Optional whether pricing is highlighted
        
    Returns:
        Dictionary with updated pricing data including user info
    """
    import json
    
    logger.info(
        "Updating pricing",
        function="update_pricing",
        pricing_id=pricing_id,
        has_name=name is not None,
        has_activation=activation is not None,
        has_expiry=expiry is not None,
        has_status=status is not None,
        has_features=features is not None,
        has_currency=currency is not None,
        has_pricing_details=pricing_details is not None,
        has_description=description is not None,
        has_is_highlighted=is_highlighted is not None
    )
    
    # Build dynamic UPDATE query
    update_fields = []
    params = {"id": pricing_id}
    
    if name is not None:
        update_fields.append("name = :name")
        params["name"] = name
    
    if activation is not None:
        update_fields.append("activation = :activation")
        params["activation"] = activation
    
    if expiry is not None:
        update_fields.append("expiry = :expiry")
        params["expiry"] = expiry
    
    if status is not None:
        update_fields.append("status = :status")
        params["status"] = status
    
    if features is not None:
        update_fields.append("features = :features")
        params["features"] = json.dumps(features)
    
    if currency is not None:
        update_fields.append("currency = :currency")
        params["currency"] = currency
    
    if pricing_details is not None:
        update_fields.append("pricing_details = :pricing_details")
        params["pricing_details"] = json.dumps(pricing_details)
    
    if description is not None:
        update_fields.append("description = :description")
        params["description"] = description
    
    if is_highlighted is not None:
        update_fields.append("is_highlighted = :is_highlighted")
        params["is_highlighted"] = is_highlighted
    
    if not update_fields:
        # No fields to update, just return existing record
        return get_pricing_by_id(db, pricing_id)
    
    # Add updated_at
    update_fields.append("updated_at = CURRENT_TIMESTAMP")
    
    query = f"""
        UPDATE pricing
        SET {', '.join(update_fields)}
        WHERE id = :id
    """
    
    db.execute(text(query), params)
    db.commit()
    
    # Fetch the updated record
    return get_pricing_by_id(db, pricing_id)


def delete_pricing(
    db: Session,
    pricing_id: str
) -> bool:
    """
    Delete a pricing record.
    
    Args:
        db: Database session
        pricing_id: Pricing ID (CHAR(36) UUID)
        
    Returns:
        True if deleted successfully, False otherwise
    """
    logger.info(
        "Deleting pricing",
        function="delete_pricing",
        pricing_id=pricing_id
    )
    
    db.execute(
        text("DELETE FROM pricing WHERE id = :id"),
        {"id": pricing_id}
    )
    db.commit()
    
    logger.info(
        "Pricing deleted successfully",
        function="delete_pricing",
        pricing_id=pricing_id
    )
    
    return True


def get_all_pricings(
    db: Session
) -> List[Dict[str, Any]]:
    """
    Get all pricing records with user info.
    
    Args:
        db: Database session
        
    Returns:
        List of dictionaries with pricing data including created_by user info
    """
    import json
    
    logger.info(
        "Getting all pricings",
        function="get_all_pricings"
    )
    
    result = db.execute(
        text("""
            SELECT id, name, activation, expiry, status, features,
                   currency, pricing_details, description, is_highlighted, created_by, created_at, updated_at
            FROM pricing
            ORDER BY created_at DESC
        """)
    ).fetchall()
    
    pricings = []
    for row in result:
        (pricing_id, name_val, activation_val, expiry_val, status_val, features_val, 
         currency_val, pricing_details_val, description_val, is_highlighted_val, created_by_val, created_at, updated_at) = row
        
        # Convert timestamps to ISO format strings
        if isinstance(activation_val, datetime):
            activation_str = activation_val.isoformat() + "Z" if activation_val.tzinfo else activation_val.isoformat()
        else:
            activation_str = str(activation_val)
        
        if isinstance(expiry_val, datetime):
            expiry_str = expiry_val.isoformat() + "Z" if expiry_val.tzinfo else expiry_val.isoformat()
        else:
            expiry_str = str(expiry_val)
        
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        # Parse JSON fields
        features_list = json.loads(features_val) if isinstance(features_val, str) else features_val
        pricing_details_dict = json.loads(pricing_details_val) if isinstance(pricing_details_val, str) else pricing_details_val
        
        # Get user name and role
        user_info = get_user_name_and_role_by_user_id(db, created_by_val)
        
        pricing = {
            "id": pricing_id,
            "name": name_val,
            "activation": activation_str,
            "expiry": expiry_str,
            "status": status_val,
            "features": features_list,
            "currency": currency_val,
            "pricing_details": pricing_details_dict,
            "description": description_val,
            "is_highlighted": bool(is_highlighted_val) if is_highlighted_val is not None else None,
            "created_by": {
                "id": created_by_val,
                "name": user_info.get("name", ""),
                "role": user_info.get("role"),
                "picture": user_info.get("picture")
            },
            "created_at": created_at_str,
            "updated_at": updated_at_str
        }
        pricings.append(pricing)
    
    logger.info(
        "All pricings retrieved successfully",
        function="get_all_pricings",
        count=len(pricings)
    )
    
    return pricings


def get_live_pricings(
    db: Session
) -> List[Dict[str, Any]]:
    """
    Get live pricing records (activation < current_time < expiry AND status=ENABLED).
    
    Args:
        db: Database session
        
    Returns:
        List of dictionaries with pricing data including created_by user info
    """
    import json
    
    logger.info(
        "Getting live pricings",
        function="get_live_pricings"
    )
    
    current_time = datetime.now(timezone.utc)
    
    result = db.execute(
        text("""
            SELECT id, name, activation, expiry, status, features,
                   currency, pricing_details, description, is_highlighted, created_by, created_at, updated_at
            FROM pricing
            WHERE status = 'ENABLED'
            AND activation < :current_time
            AND expiry > :current_time
            ORDER BY created_at DESC
        """),
        {"current_time": current_time}
    ).fetchall()
    
    pricings = []
    for row in result:
        (pricing_id, name_val, activation_val, expiry_val, status_val, features_val, 
         currency_val, pricing_details_val, description_val, is_highlighted_val, created_by_val, created_at, updated_at) = row
        
        # Convert timestamps to ISO format strings
        if isinstance(activation_val, datetime):
            activation_str = activation_val.isoformat() + "Z" if activation_val.tzinfo else activation_val.isoformat()
        else:
            activation_str = str(activation_val)
        
        if isinstance(expiry_val, datetime):
            expiry_str = expiry_val.isoformat() + "Z" if expiry_val.tzinfo else expiry_val.isoformat()
        else:
            expiry_str = str(expiry_val)
        
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        # Parse JSON fields
        features_list = json.loads(features_val) if isinstance(features_val, str) else features_val
        pricing_details_dict = json.loads(pricing_details_val) if isinstance(pricing_details_val, str) else pricing_details_val
        
        # Get user name and role
        user_info = get_user_name_and_role_by_user_id(db, created_by_val)
        
        pricing = {
            "id": pricing_id,
            "name": name_val,
            "activation": activation_str,
            "expiry": expiry_str,
            "status": status_val,
            "features": features_list,
            "currency": currency_val,
            "pricing_details": pricing_details_dict,
            "description": description_val,
            "is_highlighted": bool(is_highlighted_val) if is_highlighted_val is not None else None,
            "created_by": {
                "id": created_by_val,
                "name": user_info.get("name", ""),
                "role": user_info.get("role"),
                "picture": user_info.get("picture")
            },
            "created_at": created_at_str,
            "updated_at": updated_at_str
        }
        pricings.append(pricing)
    
    logger.info(
        "Live pricings retrieved successfully",
        function="get_live_pricings",
        count=len(pricings)
    )
    
    return pricings


def create_domain(
    db: Session,
    user_id: str,
    url: str,
    status: str = "ALLOWED"
) -> Dict[str, Any]:
    """
    Create a new domain record.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID) who is creating the domain
        url: Domain URL (VARCHAR(100))
        status: Domain status (ALLOWED or BANNED, defaults to ALLOWED)
        
    Returns:
        Dictionary with created domain data
    """
    logger.info(
        "Creating domain",
        function="create_domain",
        user_id=user_id,
        url=url,
        status=status
    )
    
    # Generate UUID for the new domain
    domain_id = str(uuid.uuid4())
    
    # Insert the new domain
    db.execute(
        text("""
            INSERT INTO domain (id, url, status, created_by)
            VALUES (:id, :url, :status, :created_by)
        """),
        {
            "id": domain_id,
            "url": url,
            "status": status,
            "created_by": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, url, status, created_by, created_at, updated_at
            FROM domain
            WHERE id = :id
        """),
        {"id": domain_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created domain",
            function="create_domain",
            domain_id=domain_id
        )
        raise Exception("Failed to retrieve created domain")
    
    (domain_id_val, url_val, status_val, created_by_val, created_at, updated_at) = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Get user info with email
    user_info = get_user_info_with_email_by_user_id(db, created_by_val)
    
    domain = {
        "id": domain_id_val,
        "url": url_val,
        "status": status_val,
        "created_by": {
            "id": created_by_val,
            "name": user_info.get("name", ""),
            "role": user_info.get("role"),
            "email": user_info.get("email")
        },
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created domain successfully",
        function="create_domain",
        domain_id=domain_id_val,
        user_id=user_id
    )
    
    return domain


def get_all_domains(
    db: Session,
    offset: Optional[int] = None,
    limit: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get all domains with optional pagination, ordered by created_at DESC.
    
    Args:
        db: Database session
        offset: Pagination offset (optional, if None no pagination is applied)
        limit: Pagination limit (optional, if None no pagination is applied)
        
    Returns:
        Tuple of (list of domain dictionaries, total count)
    """
    logger.info(
        "Getting all domains",
        function="get_all_domains",
        offset=offset,
        limit=limit,
        pagination_used=offset is not None and limit is not None
    )
    
    # Get total count
    count_result = db.execute(
        text("SELECT COUNT(*) FROM domain")
    ).fetchone()
    total_count = count_result[0] if count_result else 0
    
    # Build query based on whether pagination is requested
    if offset is not None and limit is not None:
        # Get paginated results
        result = db.execute(
            text("""
                SELECT id, url, status, created_by, created_at, updated_at
                FROM domain
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {
                "limit": limit,
                "offset": offset
            }
        )
    else:
        # Get all results without pagination
        result = db.execute(
            text("""
                SELECT id, url, status, created_by, created_at, updated_at
                FROM domain
                ORDER BY created_at DESC
            """)
        )
    
    rows = result.fetchall()
    
    domains = []
    for row in rows:
        (domain_id, url_val, status_val, created_by_val, created_at, updated_at) = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        # Get user info with email
        user_info = get_user_info_with_email_by_user_id(db, created_by_val)
        
        domain = {
            "id": domain_id,
            "url": url_val,
            "status": status_val,
            "created_by": {
                "id": created_by_val,
                "name": user_info.get("name", ""),
                "role": user_info.get("role"),
                "email": user_info.get("email")
            },
            "created_at": created_at_str,
            "updated_at": updated_at_str
        }
        domains.append(domain)
    
    logger.info(
        "Retrieved all domains successfully",
        function="get_all_domains",
        domain_count=len(domains),
        total_count=total_count,
        offset=offset,
        limit=limit
    )
    
    return domains, total_count


def get_domain_by_id(
    db: Session,
    domain_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a domain by its ID.
    
    Args:
        db: Database session
        domain_id: Domain ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with domain data or None if not found
    """
    logger.info(
        "Getting domain by id",
        function="get_domain_by_id",
        domain_id=domain_id
    )
    
    result = db.execute(
        text("""
            SELECT id, url, status, created_by, created_at, updated_at
            FROM domain
            WHERE id = :domain_id
        """),
        {"domain_id": domain_id}
    )
    
    row = result.fetchone()
    
    if not row:
        logger.info(
            "Domain not found",
            function="get_domain_by_id",
            domain_id=domain_id
        )
        return None
    
    (domain_id_val, url_val, status_val, created_by_val, created_at, updated_at) = row
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Get user info with email
    user_info = get_user_info_with_email_by_user_id(db, created_by_val)
    
    domain = {
        "id": domain_id_val,
        "url": url_val,
        "status": status_val,
        "created_by": {
            "id": created_by_val,
            "name": user_info.get("name", ""),
            "role": user_info.get("role"),
            "email": user_info.get("email")
        },
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Retrieved domain successfully",
        function="get_domain_by_id",
        domain_id=domain_id
    )
    
    return domain


def update_domain(
    db: Session,
    domain_id: str,
    url: Optional[str] = None,
    status: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Update a domain's url and/or status.
    
    Args:
        db: Database session
        domain_id: Domain ID (CHAR(36) UUID)
        url: New URL value (optional)
        status: New status value (optional)
        
    Returns:
        Dictionary with updated domain data or None if not found
    """
    logger.info(
        "Updating domain",
        function="update_domain",
        domain_id=domain_id,
        has_url=url is not None,
        has_status=status is not None
    )
    
    # Check if domain exists
    existing = get_domain_by_id(db, domain_id)
    if not existing:
        return None
    
    # Build update query dynamically based on provided fields
    update_fields = []
    params = {"domain_id": domain_id}
    
    if url is not None:
        update_fields.append("url = :url")
        params["url"] = url
    
    if status is not None:
        update_fields.append("status = :status")
        params["status"] = status
    
    if not update_fields:
        # No fields to update, return existing domain
        return existing
    
    # Update the domain
    update_query = f"""
        UPDATE domain
        SET {', '.join(update_fields)}
        WHERE id = :domain_id
    """
    
    db.execute(text(update_query), params)
    db.commit()
    
    # Fetch and return updated domain
    updated_domain = get_domain_by_id(db, domain_id)
    
    logger.info(
        "Updated domain successfully",
        function="update_domain",
        domain_id=domain_id
    )
    
    return updated_domain


def delete_domain(
    db: Session,
    domain_id: str
) -> bool:
    """
    Delete a domain by its ID.
    
    Args:
        db: Database session
        domain_id: Domain ID (CHAR(36) UUID)
        
    Returns:
        True if domain was deleted, False if not found
    """
    logger.info(
        "Deleting domain",
        function="delete_domain",
        domain_id=domain_id
    )
    
    # Check if domain exists
    existing = get_domain_by_id(db, domain_id)
    if not existing:
        logger.info(
            "Domain not found for deletion",
            function="delete_domain",
            domain_id=domain_id
        )
        return False
    
    # Delete the domain
    db.execute(
        text("""
            DELETE FROM domain
            WHERE id = :domain_id
        """),
        {"domain_id": domain_id}
    )
    db.commit()
    
    logger.info(
        "Deleted domain successfully",
        function="delete_domain",
        domain_id=domain_id
    )
    
    return True


def create_pdf(
    db: Session,
    user_id: str,
    file_name: str
) -> Dict[str, Any]:
    """
    Create a new PDF record.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        file_name: File name (max 255 characters)
        
    Returns:
        Dictionary with created PDF data
    """
    logger.info(
        "Creating PDF record",
        function="create_pdf",
        user_id=user_id,
        file_name=file_name
    )
    
    # Generate UUID for the new PDF
    pdf_id = str(uuid.uuid4())
    
    # Insert the new PDF
    db.execute(
        text("""
            INSERT INTO pdf (id, file_name, created_by)
            VALUES (:id, :file_name, :created_by)
        """),
        {
            "id": pdf_id,
            "file_name": file_name,
            "created_by": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, file_name, created_by, created_at, updated_at
            FROM pdf
            WHERE id = :id
        """),
        {"id": pdf_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created PDF",
            function="create_pdf",
            pdf_id=pdf_id
        )
        raise Exception("Failed to retrieve created PDF")
    
    pdf_id_val, file_name_val, created_by_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    pdf_data = {
        "id": pdf_id_val,
        "file_name": file_name_val,
        "created_by": created_by_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created PDF record successfully",
        function="create_pdf",
        pdf_id=pdf_id_val,
        user_id=user_id
    )
    
    return pdf_data


def create_pdf_html_page(
    db: Session,
    pdf_id: str,
    page_no: int,
    html_content: str
) -> Dict[str, Any]:
    """
    Create a new PDF HTML page record.
    
    Args:
        db: Database session
        pdf_id: PDF ID (CHAR(36) UUID)
        page_no: Page number (1-indexed)
        html_content: HTML content for the page (LONGTEXT)
        
    Returns:
        Dictionary with created PDF HTML page data
    """
    logger.info(
        "Creating PDF HTML page record",
        function="create_pdf_html_page",
        pdf_id=pdf_id,
        page_no=page_no,
        html_content_length=len(html_content)
    )
    
    # Generate UUID for the new PDF HTML page
    page_id = str(uuid.uuid4())
    
    # Insert the new PDF HTML page
    db.execute(
        text("""
            INSERT INTO pdf_html_page (id, page_no, pdf_id, html_content)
            VALUES (:id, :page_no, :pdf_id, :html_content)
        """),
        {
            "id": page_id,
            "page_no": page_no,
            "pdf_id": pdf_id,
            "html_content": html_content
        }
    )
    db.commit()
    
    # Fetch the created record
    result = db.execute(
        text("""
            SELECT id, page_no, pdf_id, html_content, created_at, updated_at
            FROM pdf_html_page
            WHERE id = :id
        """),
        {"id": page_id}
    ).fetchone()
    
    if not result:
        logger.error(
            "Failed to retrieve created PDF HTML page",
            function="create_pdf_html_page",
            page_id=page_id
        )
        raise Exception("Failed to retrieve created PDF HTML page")
    
    page_id_val, page_no_val, pdf_id_val, html_content_val, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    page_data = {
        "id": page_id_val,
        "page_no": page_no_val,
        "pdf_id": pdf_id_val,
        "html_content": html_content_val,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Created PDF HTML page record successfully",
        function="create_pdf_html_page",
        page_id=page_id_val,
        pdf_id=pdf_id_val,
        page_no=page_no_val
    )
    
    return page_data


def get_pdfs_by_user_id(
    db: Session,
    user_id: str
) -> List[Dict[str, Any]]:
    """
    Get all PDF records for a user.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        List of PDF dictionaries
    """
    logger.info(
        "Getting PDFs by user_id",
        function="get_pdfs_by_user_id",
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            SELECT id, file_name, created_by, created_at, updated_at
            FROM pdf
            WHERE created_by = :user_id
            ORDER BY created_at DESC
        """),
        {"user_id": user_id}
    )
    rows = result.fetchall()
    
    pdfs = []
    for row in rows:
        pdf_id, file_name, created_by, created_at, updated_at = row
        
        # Convert timestamps to ISO format strings
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        pdfs.append({
            "id": pdf_id,
            "file_name": file_name,
            "created_by": created_by,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        })
    
    logger.info(
        "Retrieved PDFs successfully",
        function="get_pdfs_by_user_id",
        user_id=user_id,
        pdf_count=len(pdfs)
    )
    
    return pdfs


def get_pdf_by_id_and_user_id(
    db: Session,
    pdf_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get a PDF by ID and verify it belongs to the user.
    
    Args:
        db: Database session
        pdf_id: PDF ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with PDF data or None if not found or doesn't belong to user
    """
    logger.info(
        "Getting PDF by id and user_id",
        function="get_pdf_by_id_and_user_id",
        pdf_id=pdf_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            SELECT id, file_name, created_by, created_at, updated_at
            FROM pdf
            WHERE id = :pdf_id AND created_by = :user_id
        """),
        {
            "pdf_id": pdf_id,
            "user_id": user_id
        }
    ).fetchone()
    
    if not result:
        logger.warning(
            "PDF not found or doesn't belong to user",
            function="get_pdf_by_id_and_user_id",
            pdf_id=pdf_id,
            user_id=user_id
        )
        return None
    
    pdf_id_val, file_name, created_by, created_at, updated_at = result
    
    # Convert timestamps to ISO format strings
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    pdf_data = {
        "id": pdf_id_val,
        "file_name": file_name,
        "created_by": created_by,
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Retrieved PDF successfully",
        function="get_pdf_by_id_and_user_id",
        pdf_id=pdf_id_val,
        user_id=user_id
    )
    
    return pdf_data


def get_pdf_html_pages_by_pdf_id(
    db: Session,
    pdf_id: str,
    offset: int = 0,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get PDF HTML pages for a PDF with pagination, ordered by page_no ASC.
    
    Args:
        db: Database session
        pdf_id: PDF ID (CHAR(36) UUID)
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 20)
        
    Returns:
        Tuple of (list of page dictionaries, total count)
    """
    logger.info(
        "Getting PDF HTML pages by pdf_id",
        function="get_pdf_html_pages_by_pdf_id",
        pdf_id=pdf_id,
        offset=offset,
        limit=limit
    )
    
    # Get total count
    count_result = db.execute(
        text("SELECT COUNT(*) FROM pdf_html_page WHERE pdf_id = :pdf_id"),
        {"pdf_id": pdf_id}
    ).fetchone()
    
    total_count = count_result[0] if count_result else 0
    
    # Get paginated pages
    pages_result = db.execute(
        text("""
            SELECT id, page_no, pdf_id, html_content, created_at, updated_at
            FROM pdf_html_page
            WHERE pdf_id = :pdf_id
            ORDER BY page_no ASC
            LIMIT :limit OFFSET :offset
        """),
        {
            "pdf_id": pdf_id,
            "limit": limit,
            "offset": offset
        }
    )
    rows = pages_result.fetchall()
    
    pages = []
    for row in rows:
        page_id, page_no, pdf_id_val, html_content, created_at, updated_at = row
        
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
            "page_no": page_no,
            "pdf_id": pdf_id_val,
            "html_content": html_content,
            "created_at": created_at_str,
            "updated_at": updated_at_str
        })
    
    logger.info(
        "Retrieved PDF HTML pages successfully",
        function="get_pdf_html_pages_by_pdf_id",
        pdf_id=pdf_id,
        pages_count=len(pages),
        total_count=total_count,
        offset=offset,
        limit=limit
    )
    
    return pages, total_count


def delete_pdf_by_id_and_user_id(
    db: Session,
    pdf_id: str,
    user_id: str
) -> bool:
    """
    Delete a PDF by ID and verify it belongs to the user.
    Due to ON DELETE CASCADE constraint, all related pdf_html_page records will be automatically deleted.
    
    Args:
        db: Database session
        pdf_id: PDF ID (CHAR(36) UUID)
        user_id: User ID (CHAR(36) UUID)
        
    Returns:
        True if deleted, False if not found or doesn't belong to user
    """
    logger.info(
        "Deleting PDF by id and user_id",
        function="delete_pdf_by_id_and_user_id",
        pdf_id=pdf_id,
        user_id=user_id
    )
    
    result = db.execute(
        text("""
            DELETE FROM pdf
            WHERE id = :pdf_id AND created_by = :user_id
        """),
        {
            "pdf_id": pdf_id,
            "user_id": user_id
        }
    )
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "PDF not found or doesn't belong to user",
            function="delete_pdf_by_id_and_user_id",
            pdf_id=pdf_id,
            user_id=user_id
        )
        return False
    
    logger.info(
        "Deleted PDF successfully",
        function="delete_pdf_by_id_and_user_id",
        pdf_id=pdf_id,
        user_id=user_id
    )
    
    return True


def create_coupon(
    db: Session,
    user_id: str,
    code: str,
    name: str,
    description: str,
    discount: float,
    activation: datetime,
    expiry: datetime,
    status: str
) -> Dict[str, Any]:
    """
    Create a new coupon record.
    
    Args:
        db: Database session
        user_id: User ID (CHAR(36) UUID) who is creating the coupon
        code: Coupon code (VARCHAR(30))
        name: Coupon name (VARCHAR(100))
        description: Coupon description (VARCHAR(1024))
        discount: Discount percentage (FLOAT, 0 < discount <= 100)
        activation: Activation timestamp
        expiry: Expiry timestamp
        status: Coupon status (ENABLED or DISABLED)
        
    Returns:
        Dictionary with created coupon data including user info
    """
    logger.info(
        "Creating coupon",
        function="create_coupon",
        user_id=user_id,
        code=code,
        name=name,
        discount=discount,
        status=status
    )
    
    # Generate UUID for the new coupon
    coupon_id = str(uuid.uuid4())
    
    # Insert the new coupon (is_highlighted is always False for new records)
    db.execute(
        text("""
            INSERT INTO coupon (id, code, name, description, discount, activation, expiry, status, is_highlighted, created_by)
            VALUES (:id, :code, :name, :description, :discount, :activation, :expiry, :status, FALSE, :created_by)
        """),
        {
            "id": coupon_id,
            "code": code,
            "name": name,
            "description": description,
            "discount": discount,
            "activation": activation,
            "expiry": expiry,
            "status": status,
            "created_by": user_id
        }
    )
    db.commit()
    
    # Fetch the created record
    return get_coupon_by_id(db, coupon_id)


def get_coupon_by_id(
    db: Session,
    coupon_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get coupon by ID with user info.
    
    Args:
        db: Database session
        coupon_id: Coupon ID (CHAR(36) UUID)
        
    Returns:
        Dictionary with coupon data including created_by user info, or None if not found
    """
    logger.info(
        "Getting coupon by ID",
        function="get_coupon_by_id",
        coupon_id=coupon_id
    )
    
    result = db.execute(
        text("""
            SELECT id, code, name, description, discount, activation, expiry, status, is_highlighted, created_by, created_at, updated_at
            FROM coupon
            WHERE id = :id
        """),
        {"id": coupon_id}
    ).fetchone()
    
    if not result:
        logger.warning(
            "Coupon not found",
            function="get_coupon_by_id",
            coupon_id=coupon_id
        )
        return None
    
    (coupon_id_val, code_val, name_val, description_val, discount_val,
     activation_val, expiry_val, status_val, is_highlighted_val,
     created_by_val, created_at, updated_at) = result
    
    # Convert timestamps to ISO format strings
    if isinstance(activation_val, datetime):
        activation_str = activation_val.isoformat() + "Z" if activation_val.tzinfo else activation_val.isoformat()
    else:
        activation_str = str(activation_val)
    
    if isinstance(expiry_val, datetime):
        expiry_str = expiry_val.isoformat() + "Z" if expiry_val.tzinfo else expiry_val.isoformat()
    else:
        expiry_str = str(expiry_val)
    
    if isinstance(created_at, datetime):
        created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
    else:
        created_at_str = str(created_at)
    
    if isinstance(updated_at, datetime):
        updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
    else:
        updated_at_str = str(updated_at)
    
    # Get user info with email
    user_info = get_user_info_with_email_by_user_id(db, created_by_val)
    
    coupon = {
        "id": coupon_id_val,
        "code": code_val,
        "name": name_val,
        "description": description_val,
        "discount": float(discount_val),
        "activation": activation_str,
        "expiry": expiry_str,
        "status": status_val,
        "is_highlighted": bool(is_highlighted_val),
        "created_by": {
            "id": created_by_val,
            "name": user_info.get("name", ""),
            "email": user_info.get("email"),
            "role": user_info.get("role")
        },
        "created_at": created_at_str,
        "updated_at": updated_at_str
    }
    
    logger.info(
        "Coupon retrieved successfully",
        function="get_coupon_by_id",
        coupon_id=coupon_id_val
    )
    
    return coupon


def get_all_coupons(
    db: Session,
    code: Optional[str] = None,
    name: Optional[str] = None,
    status: Optional[str] = None,
    is_active: Optional[bool] = None,
    offset: int = 0,
    limit: int = 20
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Get all coupons with optional filters and pagination.
    
    Args:
        db: Database session
        code: Optional filter by exact coupon code
        name: Optional filter by name (LIKE %name%)
        status: Optional filter by status (ENABLED or DISABLED)
        is_active: Optional filter - if True, only fetch coupons where expiry > current timestamp
        offset: Pagination offset (default: 0)
        limit: Pagination limit (default: 20)
        
    Returns:
        Tuple of (list of coupon dictionaries, total count)
    """
    logger.info(
        "Getting all coupons",
        function="get_all_coupons",
        code=code,
        name=name,
        status=status,
        is_active=is_active,
        offset=offset,
        limit=limit
    )
    
    # Build WHERE clause
    where_conditions = []
    params = {}
    
    if code:
        where_conditions.append("code = :code")
        params["code"] = code
    
    if name:
        where_conditions.append("name LIKE :name")
        params["name"] = f"%{name}%"
    
    if status:
        where_conditions.append("status = :status")
        params["status"] = status
    
    if is_active is True:
        where_conditions.append("expiry > CURRENT_TIMESTAMP")
    
    where_clause = ""
    if where_conditions:
        where_clause = " WHERE " + " AND ".join(where_conditions)
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM coupon{where_clause}"
    count_result = db.execute(text(count_query), params).fetchone()
    total_count = count_result[0] if count_result else 0
    
    # Build paginated query
    base_query = f"""
        SELECT id, code, name, description, discount, activation, expiry, status, is_highlighted, created_by, created_at, updated_at
        FROM coupon{where_clause}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """
    
    # Add pagination params
    params["limit"] = limit
    params["offset"] = offset
    
    result = db.execute(text(base_query), params)
    rows = result.fetchall()
    
    coupons = []
    for row in rows:
        (coupon_id, code_val, name_val, description_val, discount_val,
         activation_val, expiry_val, status_val, is_highlighted_val,
         created_by_val, created_at, updated_at) = row
        
        # Convert timestamps to ISO format strings
        if isinstance(activation_val, datetime):
            activation_str = activation_val.isoformat() + "Z" if activation_val.tzinfo else activation_val.isoformat()
        else:
            activation_str = str(activation_val)
        
        if isinstance(expiry_val, datetime):
            expiry_str = expiry_val.isoformat() + "Z" if expiry_val.tzinfo else expiry_val.isoformat()
        else:
            expiry_str = str(expiry_val)
        
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat() + "Z" if created_at.tzinfo else created_at.isoformat()
        else:
            created_at_str = str(created_at)
        
        if isinstance(updated_at, datetime):
            updated_at_str = updated_at.isoformat() + "Z" if updated_at.tzinfo else updated_at.isoformat()
        else:
            updated_at_str = str(updated_at)
        
        # Get user info with email
        user_info = get_user_info_with_email_by_user_id(db, created_by_val)
        
        coupon = {
            "id": coupon_id,
            "code": code_val,
            "name": name_val,
            "description": description_val,
            "discount": float(discount_val),
            "activation": activation_str,
            "expiry": expiry_str,
            "status": status_val,
            "is_highlighted": bool(is_highlighted_val),
            "created_by": {
                "id": created_by_val,
                "name": user_info.get("name", ""),
                "email": user_info.get("email"),
                "role": user_info.get("role")
            },
            "created_at": created_at_str,
            "updated_at": updated_at_str
        }
        coupons.append(coupon)
    
    logger.info(
        "Retrieved all coupons successfully",
        function="get_all_coupons",
        coupon_count=len(coupons),
        total_count=total_count,
        offset=offset,
        limit=limit
    )
    
    return coupons, total_count


def check_coupon_highlighted_intersection(
    db: Session,
    activation: datetime,
    expiry: datetime,
    exclude_coupon_id: Optional[str] = None
) -> bool:
    """
    Check if a coupon's activation period intersects with other ENABLED highlighted coupons.
    
    Args:
        db: Database session
        activation: Coupon activation timestamp
        expiry: Coupon expiry timestamp
        exclude_coupon_id: Optional coupon ID to exclude from intersection check (for updates)
        
    Returns:
        True if intersection exists, False otherwise
    """
    logger.info(
        "Checking coupon highlighted intersection",
        function="check_coupon_highlighted_intersection",
        activation=activation.isoformat(),
        expiry=expiry.isoformat(),
        exclude_coupon_id=exclude_coupon_id
    )
    
    # Build query for ENABLED highlighted coupons
    query = """
        SELECT id, activation, expiry
        FROM coupon
        WHERE status = 'ENABLED' AND is_highlighted = TRUE
    """
    params = {}
    
    if exclude_coupon_id:
        query += " AND id != :exclude_coupon_id"
        params["exclude_coupon_id"] = exclude_coupon_id
    
    result = db.execute(text(query), params)
    rows = result.fetchall()
    
    # Ensure new timestamps are timezone aware
    if activation.tzinfo is None:
        activation = activation.replace(tzinfo=timezone.utc)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    
    # Check for intersection: (new_activation < existing_expiry) AND (new_expiry > existing_activation)
    for row in rows:
        existing_coupon_id, existing_activation, existing_expiry = row
        
        # Ensure timezone awareness
        if isinstance(existing_activation, datetime):
            if existing_activation.tzinfo is None:
                existing_activation = existing_activation.replace(tzinfo=timezone.utc)
        else:
            existing_activation = datetime.fromisoformat(str(existing_activation).replace('Z', '+00:00'))
            if existing_activation.tzinfo is None:
                existing_activation = existing_activation.replace(tzinfo=timezone.utc)
        
        if isinstance(existing_expiry, datetime):
            if existing_expiry.tzinfo is None:
                existing_expiry = existing_expiry.replace(tzinfo=timezone.utc)
        else:
            existing_expiry = datetime.fromisoformat(str(existing_expiry).replace('Z', '+00:00'))
            if existing_expiry.tzinfo is None:
                existing_expiry = existing_expiry.replace(tzinfo=timezone.utc)
        
        # Check intersection
        if (activation < existing_expiry) and (expiry > existing_activation):
            logger.warning(
                "Coupon highlighted intersection found",
                function="check_coupon_highlighted_intersection",
                existing_coupon_id=existing_coupon_id,
                new_activation=activation.isoformat(),
                new_expiry=expiry.isoformat(),
                existing_activation=existing_activation.isoformat(),
                existing_expiry=existing_expiry.isoformat()
            )
            return True
    
    logger.info(
        "No coupon highlighted intersection found",
        function="check_coupon_highlighted_intersection"
    )
    
    return False


def update_coupon(
    db: Session,
    coupon_id: str,
    code: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    discount: Optional[float] = None,
    activation: Optional[datetime] = None,
    expiry: Optional[datetime] = None,
    status: Optional[str] = None,
    is_highlighted: Optional[bool] = None
) -> Optional[Dict[str, Any]]:
    """
    Update a coupon record (PUT - all fields).
    
    Args:
        db: Database session
        coupon_id: Coupon ID (CHAR(36) UUID)
        code: Optional coupon code
        name: Optional coupon name
        description: Optional coupon description
        discount: Optional discount percentage
        activation: Optional activation timestamp
        expiry: Optional expiry timestamp
        status: Optional coupon status
        is_highlighted: Optional is_highlighted flag
        
    Returns:
        Dictionary with updated coupon data including user info, or None if not found
    """
    logger.info(
        "Updating coupon",
        function="update_coupon",
        coupon_id=coupon_id
    )
    
    # Check if coupon exists
    existing_coupon = get_coupon_by_id(db, coupon_id)
    if not existing_coupon:
        logger.warning(
            "Coupon not found for update",
            function="update_coupon",
            coupon_id=coupon_id
        )
        return None
    
    # Determine final values (use provided or existing)
    final_code = code if code is not None else existing_coupon["code"]
    final_name = name if name is not None else existing_coupon["name"]
    final_description = description if description is not None else existing_coupon["description"]
    final_discount = discount if discount is not None else existing_coupon["discount"]
    final_status = status if status is not None else existing_coupon["status"]
    final_is_highlighted = is_highlighted if is_highlighted is not None else existing_coupon["is_highlighted"]
    
    # Parse timestamps
    if activation is not None:
        final_activation = activation
    else:
        final_activation = datetime.fromisoformat(existing_coupon["activation"].replace('Z', '+00:00'))
        if final_activation.tzinfo is None:
            final_activation = final_activation.replace(tzinfo=timezone.utc)
    
    if expiry is not None:
        final_expiry = expiry
    else:
        final_expiry = datetime.fromisoformat(existing_coupon["expiry"].replace('Z', '+00:00'))
        if final_expiry.tzinfo is None:
            final_expiry = final_expiry.replace(tzinfo=timezone.utc)
    
    # Check intersection if status=ENABLED and is_highlighted=True
    if final_status == "ENABLED" and final_is_highlighted is True:
        has_intersection = check_coupon_highlighted_intersection(
            db,
            final_activation,
            final_expiry,
            exclude_coupon_id=coupon_id
        )
        if has_intersection:
            logger.warning(
                "Cannot update coupon: highlighted intersection detected",
                function="update_coupon",
                coupon_id=coupon_id
            )
            # Return a special indicator - the API will handle the error
            return {"error": "HIGHLIGHTED_INTERSECTION"}
    
    # Update the coupon
    db.execute(
        text("""
            UPDATE coupon
            SET code = :code, name = :name, description = :description, discount = :discount,
                activation = :activation, expiry = :expiry, status = :status, is_highlighted = :is_highlighted,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
        """),
        {
            "id": coupon_id,
            "code": final_code,
            "name": final_name,
            "description": final_description,
            "discount": final_discount,
            "activation": final_activation,
            "expiry": final_expiry,
            "status": final_status,
            "is_highlighted": final_is_highlighted
        }
    )
    db.commit()
    
    # Fetch the updated record
    logger.info(
        "Coupon updated successfully",
        function="update_coupon",
        coupon_id=coupon_id
    )
    
    return get_coupon_by_id(db, coupon_id)


def delete_coupon(
    db: Session,
    coupon_id: str
) -> bool:
    """
    Delete a coupon by ID.
    
    Args:
        db: Database session
        coupon_id: Coupon ID (CHAR(36) UUID)
        
    Returns:
        True if deleted, False if not found
    """
    logger.info(
        "Deleting coupon",
        function="delete_coupon",
        coupon_id=coupon_id
    )
    
    result = db.execute(
        text("DELETE FROM coupon WHERE id = :id"),
        {"id": coupon_id}
    )
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "Coupon not found for deletion",
            function="delete_coupon",
            coupon_id=coupon_id
        )
        return False
    
    logger.info(
        "Coupon deleted successfully",
        function="delete_coupon",
        coupon_id=coupon_id
    )
    
    return True


def get_active_highlighted_coupon(
    db: Session
) -> Optional[Dict[str, Any]]:
    """
    Get the currently active highlighted coupon.
    If multiple exist, returns the one with highest discount (most recent if tie).
    Logs a warning if multiple found.
    
    Args:
        db: Database session
        
    Returns:
        Dictionary with coupon data (excluding created_by, created_at, updated_at), or None if none found
    """
    logger.info(
        "Getting active highlighted coupon",
        function="get_active_highlighted_coupon"
    )
    
    # Use MariaDB's NOW() function instead of Python datetime to avoid timezone issues
    # Get all ENABLED highlighted coupons that are currently active (activation <= now <= expiry)
    result = db.execute(
        text("""
            SELECT id, code, name, description, discount, activation, expiry, status, is_highlighted
            FROM coupon
            WHERE status = 'ENABLED' 
              AND is_highlighted = TRUE
              AND activation <= NOW()
              AND expiry >= NOW()
            ORDER BY discount DESC, created_at DESC
        """)
    )
    rows = result.fetchall()
    
    if not rows:
        logger.info(
            "No active highlighted coupon found",
            function="get_active_highlighted_coupon"
        )
        return None
    
    if len(rows) > 1:
        logger.warning(
            "Multiple active highlighted coupons found, returning highest discount (most recent if tie)",
            function="get_active_highlighted_coupon",
            count=len(rows)
        )
    
    # Get the first row (highest discount, most recent if tie)
    (coupon_id, code_val, name_val, description_val, discount_val,
     activation_val, expiry_val, status_val, is_highlighted_val) = rows[0]
    
    # Convert timestamps to ISO format strings
    if isinstance(activation_val, datetime):
        activation_str = activation_val.isoformat() + "Z" if activation_val.tzinfo else activation_val.isoformat()
    else:
        activation_str = str(activation_val)
    
    if isinstance(expiry_val, datetime):
        expiry_str = expiry_val.isoformat() + "Z" if expiry_val.tzinfo else expiry_val.isoformat()
    else:
        expiry_str = str(expiry_val)
    
    coupon = {
        "id": coupon_id,
        "code": code_val,
        "name": name_val,
        "description": description_val,
        "discount": float(discount_val),
        "activation": activation_str,
        "expiry": expiry_str,
        "status": status_val,
        "is_highlighted": bool(is_highlighted_val)
    }
    
    logger.info(
        "Retrieved active highlighted coupon successfully",
        function="get_active_highlighted_coupon",
        coupon_id=coupon_id,
        discount=float(discount_val)
    )
    
    return coupon

