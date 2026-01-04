"""API routes for user settings management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy import text
import structlog
import json

from app.models import (
    UpdateSettingsRequest,
    SettingsResponse,
    UserSettingsResponse,
    LanguageSettings,
    Theme,
    NativeLanguage,
    PageTranslationView,
    GetAllLanguagesResponse,
    LanguageInfo,
    LANGUAGE_MAPPER
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import get_user_id_by_auth_vendor_id, get_user_settings_by_user_id

logger = structlog.get_logger()

router = APIRouter(prefix="/api/user-settings", tags=["User Settings"])


@router.get(
    "",
    response_model=UserSettingsResponse,
    summary="Get user settings",
    description="Get user settings (language, theme) for the authenticated user"
)
async def get_user_settings(
    request: Request,
    response: Response,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get user settings for authenticated users."""
    # Extract user_id from auth context
    # authenticate() middleware has already validated these fields exist
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication required to get settings"
            }
        )
    
    session_data = auth_context["session_data"]
    auth_vendor_id = session_data["auth_vendor_id"]
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "USER_NOT_FOUND",
                "error_message": "User not found"
            }
        )
    
    logger.info(
        "Getting user settings",
        user_id=user_id
    )
    
    # Get user settings from database
    settings_dict = get_user_settings_by_user_id(db, user_id)
    
    if not settings_dict:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "USER_NOT_FOUND",
                "error_message": "User not found"
            }
        )
    
    # Parse settings from dictionary
    language_dict = settings_dict.get("language", {})
    native_language_value = language_dict.get("nativeLanguage")
    native_language = None
    if native_language_value:
        try:
            native_language = NativeLanguage(native_language_value)
        except ValueError:
            logger.warning(
                "Invalid native language value in settings",
                user_id=user_id,
                native_language_value=native_language_value
            )
            native_language = None
    
    page_translation_view_value = language_dict.get("pageTranslationView", "REPLACE")
    try:
        page_translation_view = PageTranslationView(page_translation_view_value)
    except ValueError:
        logger.warning(
            "Invalid page translation view value in settings",
            user_id=user_id,
            page_translation_view_value=page_translation_view_value
        )
        page_translation_view = PageTranslationView.REPLACE
    
    theme_value = settings_dict.get("theme", "LIGHT")
    try:
        theme = Theme(theme_value)
    except ValueError:
        logger.warning(
            "Invalid theme value in settings",
            user_id=user_id,
            theme_value=theme_value
        )
        theme = Theme.LIGHT
    
    logger.info(
        "User settings retrieved successfully",
        user_id=user_id
    )
    
    return UserSettingsResponse(
        userId=user_id,
        settings=SettingsResponse(
            language=LanguageSettings(
                nativeLanguage=native_language,
                pageTranslationView=page_translation_view
            ),
            theme=theme
        )
    )


@router.get(
    "/languages",
    response_model=GetAllLanguagesResponse,
    summary="Get all languages",
    description="Get all supported languages with their codes, English names, and native names. This is an unauthenticated endpoint."
)
async def get_all_languages(
    request: Request,
    response: Response
):
    """Get all supported languages (unauthenticated endpoint)."""
    logger.info("Getting all languages")
    
    # Build list of language info from mapper
    languages = []
    for language_code, language_info in LANGUAGE_MAPPER.items():
        languages.append(LanguageInfo(
            languageCode=language_code,
            languageNameInEnglish=language_info["nameInEnglish"],
            languageNameInNative=language_info["nameInNative"]
        ))
    
    # Sort by English name for better UX
    languages.sort(key=lambda x: x.languageNameInEnglish)
    
    logger.info(
        "Retrieved all languages",
        count=len(languages)
    )
    
    return GetAllLanguagesResponse(languages=languages)


@router.patch(
    "",
    response_model=SettingsResponse,
    summary="Update user settings",
    description="Update user settings (language, theme) for the authenticated user"
)
async def update_user_settings(
    request: Request,
    response: Response,
    body: UpdateSettingsRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update user settings for authenticated users."""
    # Extract user_id from auth context
    # authenticate() middleware has already validated these fields exist
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication required to update settings"
            }
        )
    
    session_data = auth_context["session_data"]
    auth_vendor_id = session_data["auth_vendor_id"]
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    
    if not user_id:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "USER_NOT_FOUND",
                "error_message": "User not found"
            }
        )
    
    logger.info(
        "Updating user settings",
        user_id=user_id,
        theme=body.theme.value,
        nativeLanguage=body.language.nativeLanguage.value if body.language.nativeLanguage else None,
        pageTranslationView=body.language.pageTranslationView.value
    )
    
    # Convert settings to JSON
    settings_dict = {
        "language": {
            "nativeLanguage": body.language.nativeLanguage.value if body.language.nativeLanguage else None,
            "pageTranslationView": body.language.pageTranslationView.value
        },
        "theme": body.theme.value
    }
    settings_json = json.dumps(settings_dict)
    
    # Update user settings in database
    result = db.execute(
        text("""
            UPDATE user
            SET settings = :settings, updated_at = CURRENT_TIMESTAMP
            WHERE id = :user_id
        """),
        {
            "user_id": user_id,
            "settings": settings_json
        }
    )
    db.commit()
    
    if result.rowcount == 0:
        logger.warning(
            "User not found when updating settings",
            user_id=user_id
        )
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "USER_NOT_FOUND",
                "error_message": "User not found"
            }
        )
    
    logger.info(
        "User settings updated successfully",
        user_id=user_id
    )
    
    # Return the updated settings
    return SettingsResponse(
        language=LanguageSettings(
            nativeLanguage=body.language.nativeLanguage,
            pageTranslationView=body.language.pageTranslationView
        ),
        theme=body.theme
    )

