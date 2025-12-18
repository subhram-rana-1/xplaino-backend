"""Authentication API routes."""

from datetime import datetime, timezone
import traceback
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import structlog

from app.config import settings
from app.models import LoginRequest, LoginResponse, LogoutRequest, LogoutResponse, AuthVendor, UserInfo, RefreshTokenRequest, RefreshTokenResponse
from app.database.connection import get_db
from app.services.auth_service import validate_google_authentication, get_google_client_id
from app.services.jwt_service import generate_access_token, get_token_expiry, decode_access_token
from app.services.database_service import (
    get_or_create_user_by_google_sub, 
    get_or_create_user_session,
    invalidate_user_session,
    get_user_info_by_sub,
    get_user_session_by_id,
    update_user_session_refresh_token,
    get_user_role_by_user_id
)
from app.exceptions import CatenException

logger = structlog.get_logger()

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="User login with OAuth",
    description="Authenticate user using OAuth provider (Google) and return access token"
)
async def login(
    request: LoginRequest,
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Login endpoint that validates OAuth token and returns JWT access token.
    
    - Validates the auth vendor
    - For GOOGLE: validates Google ID token
    - Creates/updates user records in database
    - Generates JWT access token
    - Returns refresh token in response payload
    """
    # Entry log with request metadata
    id_token_preview = request.idToken[:8] + "..." if request.idToken and len(request.idToken) > 8 else (request.idToken if request.idToken else None)
    x_source = http_request.headers.get("X-Source", "").strip()
    logger.info(
        "Login endpoint called",
        endpoint="/api/auth/login",
        auth_vendor=request.authVendor,
        has_id_token=bool(request.idToken),
        id_token_length=len(request.idToken) if request.idToken else 0,
        id_token_preview=id_token_preview,
        x_source=x_source if x_source else "not provided"
    )
    
    try:
        
        # Check auth vendor
        if request.authVendor == AuthVendor.GOOGLE:
            # Determine which Google client ID to use based on X-Source header
            client_id = get_google_client_id(http_request)
            logger.info(
                "Using Google client ID for authentication",
                client_id=client_id,
                x_source=x_source if x_source else "not provided"
            )
            
            # Validate Google authentication
            logger.debug("Validating Google authentication token")
            google_data = validate_google_authentication(request.idToken, client_id)
            
            logger.info(
                "Google token validated successfully",
                sub=google_data.get('sub'),
                email=google_data.get('email'),
                email_verified=google_data.get('email_verified', False)
            )
            
            # Validate aud field
            if google_data.get('aud') != client_id:
                logger.warning(
                    "Token audience mismatch",
                    expected=client_id,
                    received=google_data.get('aud')
                )
                raise HTTPException(
                    status_code=401,
                    detail="Invalid token audience"
                )
            
            # Get or create user by sub
            sub = google_data.get('sub')
            if not sub:
                logger.error("Missing sub field in Google token data", google_data_keys=list(google_data.keys()))
                raise HTTPException(
                    status_code=401,
                    detail="Missing sub field in token"
                )
            
            logger.debug("Getting or creating user by Google sub", sub=sub)
            user_id, google_auth_info_id, is_new_user = get_or_create_user_by_google_sub(
                db, sub, google_data
            )
            
            logger.info(
                "User lookup/creation completed",
                user_id=user_id,
                google_auth_info_id=google_auth_info_id,
                is_new_user=is_new_user,
                sub=sub
            )
            
            # Get or create/update user session
            logger.debug(
                "Getting or creating user session",
                auth_vendor_type='GOOGLE',
                google_auth_info_id=google_auth_info_id,
                is_new_user=is_new_user
            )
            session_id, refresh_token, refresh_token_expires_at = get_or_create_user_session(
                db, 'GOOGLE', google_auth_info_id, is_new_user
            )
            
            logger.info(
                "Session created/updated",
                session_id=session_id,
                refresh_token_preview=refresh_token[:8] + "..." if refresh_token else None,
                refresh_token_expires_at=str(refresh_token_expires_at),
                expires_at_type=type(refresh_token_expires_at).__name__,
                expires_at_timezone_aware=refresh_token_expires_at.tzinfo is not None if hasattr(refresh_token_expires_at, 'tzinfo') else None
            )
            
            # Prepare user data for JWT
            given_name = google_data.get('given_name', '')
            family_name = google_data.get('family_name', '')
            name = f"{given_name} {family_name}".strip() or google_data.get('name', '')
            
            # Generate JWT access token
            issued_at = datetime.now(timezone.utc)
            expire_at = get_token_expiry(issued_at)
            
            logger.debug(
                "Generating JWT access token",
                sub=sub,
                email=google_data.get('email', ''),
                issued_at=str(issued_at),
                expire_at=str(expire_at),
                issued_at_type=type(issued_at).__name__,
                expire_at_type=type(expire_at).__name__
            )
            
            access_token = generate_access_token(
                sub=sub,
                email=google_data.get('email', ''),
                name=name,
                first_name=given_name,
                last_name=family_name,
                email_verified=google_data.get('email_verified', False),
                issued_at=issued_at,
                expire_at=expire_at,
                user_session_pk=session_id
            )
            
            logger.debug(
                "Preparing login response with refresh token in payload",
                refresh_token_preview=refresh_token[:8] + "..." if refresh_token else None,
                refresh_token_expires_at=int(refresh_token_expires_at.timestamp()) if refresh_token_expires_at else None
            )
            
            # Get user role
            user_role = get_user_role_by_user_id(db, user_id)
            
            # Construct user info
            user_info = UserInfo(
                id=user_id,
                name=name,
                firstName=given_name if given_name else None,
                lastName=family_name if family_name else None,
                email=google_data.get('email', ''),
                picture=google_data.get('picture'),
                role=user_role
            )
            
            # Prepare response with refresh token in payload
            login_response = LoginResponse(
                isLoggedIn=True,
                accessToken=access_token,
                accessTokenExpiresAt=int(expire_at.timestamp()),
                refreshToken=refresh_token,
                refreshTokenExpiresAt=int(refresh_token_expires_at.timestamp()),
                userSessionPk=session_id,
                user=user_info
            )
            
            # Exit log with success summary
            access_token_preview = access_token[:8] + "..." if access_token and len(access_token) > 8 else None
            logger.info(
                "Login completed successfully",
                endpoint="/api/auth/login",
                user_id=user_id,
                session_id=session_id,
                sub=sub,
                email=google_data.get('email'),
                is_new_user=is_new_user,
                access_token_preview=access_token_preview,
                access_token_expires_at=int(expire_at.timestamp()),
                refresh_token_preview=refresh_token[:8] + "..." if refresh_token else None,
                refresh_token_expires_at=int(refresh_token_expires_at.timestamp())
            )
            
            return login_response
        
        else:
            # Unsupported auth vendor
            logger.warning("Unsupported auth vendor", vendor=request.authVendor)
            raise HTTPException(
                status_code=404,
                detail=f"Authentication vendor '{request.authVendor}' is not supported"
            )
    
    except HTTPException as e:
        logger.warning(
            "HTTP exception during login",
            endpoint="/api/auth/login",
            status_code=e.status_code,
            detail=e.detail,
            auth_vendor=request.authVendor if hasattr(request, 'authVendor') else None
        )
        raise
    except CatenException as e:
        logger.error(
            "Authentication error during login",
            endpoint="/api/auth/login",
            error_code=e.error_code,
            error_message=e.error_message,
            status_code=e.status_code,
            details=getattr(e, 'details', None),
            auth_vendor=request.authVendor if hasattr(request, 'authVendor') else None,
            traceback=traceback.format_exc()
        )
        raise HTTPException(
            status_code=e.status_code,
            detail=e.error_message
        )
    except Exception as e:
        logger.error(
            "Unexpected error during login",
            endpoint="/api/auth/login",
            error=str(e),
            error_type=type(e).__name__,
            auth_vendor=request.authVendor if hasattr(request, 'authVendor') else None,
            traceback=traceback.format_exc()
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error during authentication"
        )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="User logout",
    description="Logout user by invalidating their session and returning logout response"
)
async def logout(
    request: LogoutRequest,
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Logout endpoint that invalidates user session.
    
    - Extracts access token from Authorization header (Bearer token)
    - Decodes the JWT access token to get user information
    - Invalidates the user session by marking it as INVALID
    - Returns response with isLoggedIn=false and user information
    """
    try:
        # Entry log with request metadata
        logger.info(
            "Logout endpoint called",
            endpoint="/api/auth/logout",
            auth_vendor=request.authVendor,
            has_authorization_header=bool(http_request.headers.get("Authorization"))
        )
        
        # Extract access token from Authorization header
        auth_header = http_request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning(
                "Missing or invalid Authorization header",
                endpoint="/api/auth/logout",
                auth_vendor=request.authVendor
            )
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid Authorization header"
            )
        
        access_token = auth_header.replace("Bearer ", "").strip()
        if not access_token:
            logger.warning(
                "Empty access token in Authorization header",
                endpoint="/api/auth/logout",
                auth_vendor=request.authVendor
            )
            raise HTTPException(
                status_code=401,
                detail="Empty access token"
            )
        
        access_token_preview = access_token[:8] + "..." if access_token and len(access_token) > 8 else None
        logger.debug(
            "Access token extracted from header",
            endpoint="/api/auth/logout",
            access_token_preview=access_token_preview,
            access_token_length=len(access_token)
        )
        
        # Decode the JWT access token
        # For logout, we allow expired tokens since user is logging out anyway
        try:
            logger.debug("Decoding JWT access token")
            token_payload = decode_access_token(access_token, verify_exp=False)
        except Exception as e:
            logger.warning(
                "Failed to decode access token",
                error=str(e),
                error_type=type(e).__name__
            )
            raise HTTPException(
                status_code=401,
                detail="Invalid access token"
            )
        
        # Extract sub from token
        sub = token_payload.get('sub')
        if not sub:
            logger.error("Missing sub field in token payload", token_keys=list(token_payload.keys()))
            raise HTTPException(
                status_code=401,
                detail="Missing sub field in token"
            )
        
        logger.info("Token decoded successfully", sub=sub)
        
        # Check auth vendor
        if request.authVendor == AuthVendor.GOOGLE:
            # Invalidate user session
            logger.debug(
                "Invalidating user session",
                auth_vendor_type='GOOGLE',
                sub=sub
            )
            session_invalidated = invalidate_user_session(
                db, 'GOOGLE', sub
            )
            
            if not session_invalidated:
                logger.warning(
                    "No valid session found to invalidate",
                    auth_vendor_type='GOOGLE',
                    sub=sub
                )
                # Continue anyway, as the token might already be invalidated
            
            # Get user information from database
            logger.debug("Fetching user information from database", sub=sub)
            user_data = get_user_info_by_sub(db, sub)
            
            if not user_data:
                logger.error("User not found in database", sub=sub)
                raise HTTPException(
                    status_code=404,
                    detail="User not found"
                )
            
            logger.info(
                "User information retrieved",
                user_id=user_data.get('user_id'),
                sub=sub,
                email=user_data.get('email')
            )
            
            # Get token expiry from decoded token
            exp_timestamp = token_payload.get('exp')
            access_token_expires_at = exp_timestamp if exp_timestamp else 0
            
            # Get user_session_pk from token
            user_session_pk = token_payload.get('user_session_pk', '')
            
            # Construct user info
            user_info = UserInfo(
                id=user_data.get('user_id'),
                name=user_data.get('name', ''),
                firstName=user_data.get('first_name'),
                lastName=user_data.get('last_name'),
                email=user_data.get('email', ''),
                picture=user_data.get('picture')
            )
            
            # Prepare response
            logout_response = LogoutResponse(
                isLoggedIn=False,
                accessToken=access_token,  # Return the same token (though it's now invalidated)
                accessTokenExpiresAt=access_token_expires_at,
                userSessionPk=user_session_pk,
                user=user_info
            )
            
            # Exit log with success summary
            logger.info(
                "Logout completed successfully",
                endpoint="/api/auth/logout",
                user_id=user_data.get('user_id'),
                session_id=user_session_pk,
                sub=sub,
                email=user_data.get('email'),
                session_invalidated=session_invalidated
            )
            
            return logout_response
        
        else:
            # Unsupported auth vendor
            logger.warning("Unsupported auth vendor", vendor=request.authVendor)
            raise HTTPException(
                status_code=404,
                detail=f"Authentication vendor '{request.authVendor}' is not supported"
            )
    
    except HTTPException as e:
        logger.warning(
            "HTTP exception during logout",
            endpoint="/api/auth/logout",
            status_code=e.status_code,
            detail=e.detail,
            auth_vendor=request.authVendor if hasattr(request, 'authVendor') else None
        )
        raise
    except CatenException as e:
        logger.error(
            "Authentication error during logout",
            endpoint="/api/auth/logout",
            error_code=e.error_code,
            error_message=e.error_message,
            status_code=e.status_code,
            details=getattr(e, 'details', None),
            auth_vendor=request.authVendor if hasattr(request, 'authVendor') else None,
            traceback=traceback.format_exc()
        )
        raise HTTPException(
            status_code=e.status_code,
            detail=e.error_message
        )
    except Exception as e:
        logger.error(
            "Unexpected error during logout",
            endpoint="/api/auth/logout",
            error=str(e),
            error_type=type(e).__name__,
            auth_vendor=request.authVendor if hasattr(request, 'authVendor') else None,
            traceback=traceback.format_exc()
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error during logout"
        )


@router.post(
    "/refresh-token",
    response_model=RefreshTokenResponse,
    summary="Refresh access token",
    description="Refresh the access token by validating current access token and refresh token, then issue a new refresh token. Returns the same response structure as login."
)
async def refresh_access_token(
    refresh_token_request: RefreshTokenRequest,
    http_request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    Refresh token endpoint that validates current tokens and issues a new refresh token.
    
    - Extracts access token from Authorization header (Bearer token)
    - Extracts refresh token from request body
    - Validates access token and fetches user session
    - Validates refresh token matches database and hasn't expired
    - Generates new refresh token and updates database
    - Returns new refresh token in response payload
    """
    # Entry log with request metadata
    has_auth_header = bool(http_request.headers.get("Authorization"))
    has_refresh_token = bool(refresh_token_request.refreshToken)
    logger.info(
        "Refresh token endpoint called",
        endpoint="/api/auth/refresh-token",
        has_authorization_header=has_auth_header,
        has_refresh_token=has_refresh_token,
        refresh_token_preview=refresh_token_request.refreshToken[:8] + "..." if refresh_token_request.refreshToken and len(refresh_token_request.refreshToken) > 8 else None
    )
    
    try:
        # Extract access token from Authorization header
        auth_header = http_request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.warning(
                "Missing or invalid Authorization header",
                endpoint="/api/auth/refresh-token"
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "errorCode": "LOGIN_REQUIRED",
                    "reason": "Missing or invalid Authorization header"
                }
            )
        
        access_token = auth_header.replace("Bearer ", "").strip()
        if not access_token:
            logger.warning(
                "Empty access token in Authorization header",
                endpoint="/api/auth/refresh-token"
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "errorCode": "LOGIN_REQUIRED",
                    "reason": "Empty access token"
                }
            )
        
        access_token_preview = access_token[:8] + "..." if access_token and len(access_token) > 8 else None
        logger.debug(
            "Access token extracted from header",
            endpoint="/api/auth/refresh-token",
            access_token_preview=access_token_preview,
            access_token_length=len(access_token)
        )
        
        # Extract refresh token from request body
        refresh_token_from_request = refresh_token_request.refreshToken
        if not refresh_token_from_request:
            logger.warning(
                "Missing refresh token in request body",
                endpoint="/api/auth/refresh-token"
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "errorCode": "LOGIN_REQUIRED",
                    "reason": "Missing refresh token"
                }
            )
        
        refresh_token_preview = refresh_token_from_request[:8] + "..." if refresh_token_from_request and len(refresh_token_from_request) > 8 else None
        logger.debug(
            "Refresh token extracted from request body",
            endpoint="/api/auth/refresh-token",
            refresh_token_preview=refresh_token_preview,
            refresh_token_length=len(refresh_token_from_request)
        )
        
        # Decode JWT access token to get user_session_pk
        try:
            logger.debug("Decoding JWT access token")
            token_payload = decode_access_token(access_token, verify_exp=False)
        except Exception as e:
            logger.warning(
                "Failed to decode access token",
                error=str(e),
                error_type=type(e).__name__
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "errorCode": "LOGIN_REQUIRED",
                    "reason": "Invalid access token"
                }
            )
        
        # Extract user_session_pk from token
        user_session_pk = token_payload.get("user_session_pk")
        if not user_session_pk:
            logger.error("Missing user_session_pk in token payload", token_keys=list(token_payload.keys()))
            raise HTTPException(
                status_code=401,
                detail={
                    "errorCode": "LOGIN_REQUIRED",
                    "reason": "Missing user_session_pk in token"
                }
            )
        
        logger.info("Token decoded successfully", user_session_pk=user_session_pk)
        
        # Fetch user_session record by ID
        session_data = get_user_session_by_id(db, user_session_pk)
        if not session_data:
            logger.warning("User session not found", user_session_pk=user_session_pk)
            raise HTTPException(
                status_code=401,
                detail={
                    "errorCode": "LOGIN_REQUIRED",
                    "reason": "Session not found"
                }
            )
        
        # Check if access_token_state is INVALID
        if session_data.get("access_token_state") != "VALID":
            logger.warning("User session is INVALID", user_session_pk=user_session_pk)
            raise HTTPException(
                status_code=401,
                detail={
                    "errorCode": "LOGIN_REQUIRED",
                    "reason": "Session is invalid"
                }
            )
        
        # Check if refresh_token_expires_at has expired
        refresh_token_expires_at = session_data.get("refresh_token_expires_at")
        if refresh_token_expires_at:
            if isinstance(refresh_token_expires_at, datetime):
                expires_at = refresh_token_expires_at
            else:
                # Parse if it's a string
                expires_at = datetime.fromisoformat(str(refresh_token_expires_at).replace('Z', '+00:00'))
            
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            
            current_time = datetime.now(timezone.utc)
            if expires_at < current_time:
                logger.warning(
                    "Refresh token expired",
                    user_session_pk=user_session_pk,
                    expires_at=str(expires_at),
                    current_time=str(current_time)
                )
                raise HTTPException(
                    status_code=401,
                    detail={
                        "errorCode": "LOGIN_REQUIRED",
                        "reason": "Refresh token expired"
                    }
                )
        
        # Verify refresh token from request body matches the one in database
        refresh_token_from_db = session_data.get("refresh_token")
        if refresh_token_from_request != refresh_token_from_db:
            logger.warning(
                "Refresh token mismatch",
                user_session_pk=user_session_pk
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "errorCode": "LOGIN_REQUIRED",
                    "reason": "Invalid refresh token"
                }
            )
        
        logger.info("Refresh token validated successfully", user_session_pk=user_session_pk)
        
        # Extract user info from token payload for access token generation
        sub = token_payload.get("sub", "")
        email = token_payload.get("email", "")
        name = token_payload.get("name", "")
        first_name = token_payload.get("first_name", "")
        last_name = token_payload.get("last_name", "")
        email_verified = token_payload.get("email_verified", False)
        
        # Calculate access token expiry first (before generating tokens)
        # This ensures we can update both refresh token and access token expiry in one DB call
        issued_at = datetime.now(timezone.utc)
        expire_at = get_token_expiry(issued_at)
        
        logger.debug(
            "Calculated access token expiry",
            issued_at=str(issued_at),
            expire_at=str(expire_at)
        )
        
        # Generate new refresh token and update database (including access_token_expires_at)
        new_refresh_token, new_refresh_token_expires_at = update_user_session_refresh_token(
            db, user_session_pk, access_token_expires_at=expire_at
        )
        
        logger.info(
            "New refresh token generated and session updated",
            user_session_pk=user_session_pk,
            refresh_token_preview=new_refresh_token[:8] + "..." if new_refresh_token else None,
            expires_at=str(new_refresh_token_expires_at),
            access_token_expires_at=str(expire_at)
        )
        
        logger.debug(
            "Preparing refresh token response with refresh token in payload",
            refresh_token_preview=new_refresh_token[:8] + "..." if new_refresh_token else None,
            refresh_token_expires_at=int(new_refresh_token_expires_at.timestamp()) if new_refresh_token_expires_at else None
        )
        
        # Generate new access token
        
        logger.debug(
            "Generating new access token",
            sub=sub,
            email=email,
            issued_at=str(issued_at),
            expire_at=str(expire_at)
        )
        
        new_access_token = generate_access_token(
            sub=sub,
            email=email,
            name=name,
            first_name=first_name,
            last_name=last_name,
            email_verified=email_verified,
            issued_at=issued_at,
            expire_at=expire_at,
            user_session_pk=user_session_pk
        )
        
        # Fetch user information from database to match login response structure
        logger.debug("Fetching user information from database", sub=sub)
        user_data = get_user_info_by_sub(db, sub)
        
        if not user_data:
            logger.error("User not found in database", sub=sub)
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )
        
        logger.debug(
            "User information retrieved",
            user_id=user_data.get('user_id'),
            sub=sub,
            email=user_data.get('email')
        )
        
        # Get user role
        user_id = user_data.get('user_id')
        user_role = get_user_role_by_user_id(db, user_id) if user_id else None
        
        # Construct user info to match login response structure
        user_info = UserInfo(
            id=user_data.get('user_id'),
            name=user_data.get('name', ''),
            firstName=user_data.get('first_name'),
            lastName=user_data.get('last_name'),
            email=user_data.get('email', ''),
            picture=user_data.get('picture'),
            role=user_role
        )
        
        # Prepare response with same structure as login response
        refresh_response = RefreshTokenResponse(
            isLoggedIn=True,
            accessToken=new_access_token,
            accessTokenExpiresAt=int(expire_at.timestamp()),
            refreshToken=new_refresh_token,
            refreshTokenExpiresAt=int(new_refresh_token_expires_at.timestamp()),
            userSessionPk=user_session_pk,
            user=user_info
        )
        
        # Exit log with success summary
        new_access_token_preview = new_access_token[:8] + "..." if new_access_token and len(new_access_token) > 8 else None
        logger.info(
            "Refresh token completed successfully",
            endpoint="/api/auth/refresh-token",
            user_session_pk=user_session_pk,
            user_id=user_data.get('user_id'),
            sub=sub,
            email=email,
            new_access_token_preview=new_access_token_preview,
            new_refresh_token_preview=new_refresh_token[:8] + "..." if new_refresh_token else None,
            access_token_expires_at=int(expire_at.timestamp()),
            refresh_token_expires_at=int(new_refresh_token_expires_at.timestamp())
        )
        
        return refresh_response
    
    except HTTPException as e:
        logger.warning(
            "HTTP exception during refresh token",
            endpoint="/api/auth/refresh-token",
            status_code=e.status_code,
            detail=e.detail
        )
        raise
    except Exception as e:
        logger.error(
            "Unexpected error during refresh token",
            endpoint="/api/auth/refresh-token",
            error=str(e),
            error_type=type(e).__name__,
            traceback=traceback.format_exc()
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error during token refresh"
        )

