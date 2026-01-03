"""API routes for saved words management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
import structlog

from app.models import (
    SaveWordRequest,
    SavedWordResponse,
    GetSavedWordsResponse,
    UserInfo,
    MoveSavedWordToFolderRequest
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_saved_words_by_folder_id_and_user_id,
    create_saved_word,
    delete_saved_word_by_id_and_user_id,
    get_folder_by_id_and_user_id,
    get_user_info_with_email_by_user_id,
    get_saved_word_by_id_and_user_id,
    update_saved_word_folder_id
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/saved-words", tags=["Saved Words"])


@router.get(
    "",
    response_model=GetSavedWordsResponse,
    summary="Get saved words by folder ID",
    description="Get paginated list of saved words for the authenticated user filtered by folder ID, ordered by most recent first"
)
async def get_saved_words_by_folder_id(
    request: Request,
    response: Response,
    folder_id: str = Query(..., description="Folder ID to filter by"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get saved words for authenticated or unauthenticated users filtered by folder ID with pagination."""
    # Extract user_id based on authentication status
    # authenticate() middleware has already validated these fields exist
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    else:
        user_id = auth_context["unauthenticated_user_id"]
    
    # Validate folder exists and belongs to user
    folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )
    
    # Get saved words filtered by folder_id
    words_data, total_count = get_saved_words_by_folder_id_and_user_id(db, user_id, folder_id, offset, limit)
    
    # Convert to response models with user info
    words = []
    for word_data in words_data:
        word_user_id = word_data["user_id"]
        user_info = get_user_info_with_email_by_user_id(db, word_user_id)
        if not user_info:
            logger.warning(
                "Failed to retrieve user info for saved word",
                word_id=word_data["id"],
                user_id=word_user_id
            )
            # Use empty values if user info not found
            user_obj = UserInfo(
                id=word_user_id,
                name="",
                email="",
                role=None,
                firstName=None,
                lastName=None,
                picture=None
            )
        else:
            user_obj = UserInfo(
                id=word_user_id,
                name=user_info.get("name", ""),
                email=user_info.get("email", ""),
                role=user_info.get("role"),
                firstName=None,
                lastName=None,
                picture=None
            )
        
        words.append(
            SavedWordResponse(
                id=word_data["id"],
                word=word_data["word"],
                contextualMeaning=word_data["contextual_meaning"],
                sourceUrl=word_data["source_url"],
                folderId=word_data["folder_id"],
                user=user_obj,
                createdAt=word_data["created_at"]
            )
        )
    
    logger.info(
        "Retrieved saved words by folder ID",
        user_id=user_id,
        folder_id=folder_id,
        words_count=len(words),
        total_count=total_count,
        offset=offset,
        limit=limit,
        authenticated=auth_context.get("authenticated", False)
    )
    
    # Add X-Unauthenticated-User-Id header for new unauthenticated users
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return GetSavedWordsResponse(
        words=words,
        total=total_count,
        offset=offset,
        limit=limit
    )


@router.post(
    "",
    response_model=SavedWordResponse,
    status_code=201,
    summary="Save a word",
    description="Save a word with its source URL for the authenticated user"
)
async def save_word(
    request: Request,
    response: Response,
    body: SaveWordRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Save a word for authenticated or unauthenticated users."""
    # Extract user_id based on authentication status
    # authenticate() middleware has already validated these fields exist
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    else:
        user_id = auth_context["unauthenticated_user_id"]
    
    # Validate input lengths (Pydantic handles this, but double-check)
    if len(body.word) > 32:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Word length exceeds maximum of 32 characters"
            }
        )
    
    if len(body.sourceUrl) > 1024:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_002",
                "error_message": "Source URL length exceeds maximum of 1024 characters"
            }
        )
    
    # Validate folder exists and belongs to user
    folder = get_folder_by_id_and_user_id(db, body.folderId, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )
    
    # Create saved word
    saved_word_data = create_saved_word(db, user_id, body.word, body.sourceUrl, body.folderId, body.contextualMeaning)
    
    # Fetch user info
    user_info = get_user_info_with_email_by_user_id(db, user_id)
    if not user_info:
        logger.warning(
            "Failed to retrieve user info for saved word",
            word_id=saved_word_data["id"],
            user_id=user_id
        )
        # Use empty values if user info not found
        user_obj = UserInfo(
            id=user_id,
            name="",
            email="",
            role=None,
            firstName=None,
            lastName=None,
            picture=None
        )
    else:
        user_obj = UserInfo(
            id=user_id,
            name=user_info.get("name", ""),
            email=user_info.get("email", ""),
            role=user_info.get("role"),
            firstName=None,
            lastName=None,
            picture=None
        )
    
    logger.info(
        "Saved word successfully",
        word_id=saved_word_data["id"],
        user_id=user_id,
        word=body.word,
        authenticated=auth_context.get("authenticated", False)
    )
    
    # Add X-Unauthenticated-User-Id header for new unauthenticated users
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return SavedWordResponse(
        id=saved_word_data["id"],
        word=saved_word_data["word"],
        contextualMeaning=saved_word_data["contextual_meaning"],
        sourceUrl=saved_word_data["source_url"],
        folderId=saved_word_data["folder_id"],
        user=user_obj,
        createdAt=saved_word_data["created_at"]
    )


@router.delete(
    "/{word_id}",
    status_code=204,
    summary="Remove a saved word",
    description="Delete a saved word by ID. Only the owner can delete their own words."
)
async def remove_saved_word(
    request: Request,
    response: Response,
    word_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Remove a saved word for authenticated or unauthenticated users."""
    # Extract user_id based on authentication status
    # authenticate() middleware has already validated these fields exist
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    else:
        user_id = auth_context["unauthenticated_user_id"]
    
    # Delete saved word (this will only delete if it belongs to the user)
    deleted = delete_saved_word_by_id_and_user_id(db, word_id, user_id)
    
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Saved word not found or does not belong to user"
            }
        )
    
    logger.info(
        "Deleted saved word successfully",
        word_id=word_id,
        user_id=user_id,
        authenticated=auth_context.get("authenticated", False)
    )
    
    # Add X-Unauthenticated-User-Id header for new unauthenticated users
    # Note: 204 No Content responses may not show headers in some clients, but we set it anyway
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return FastAPIResponse(status_code=204)


@router.patch(
    "/{word_id}/move-to-folder",
    response_model=SavedWordResponse,
    summary="Move saved word to folder",
    description="Move a saved word to a different folder. Only the owner can move their own words."
)
async def move_saved_word_to_folder(
    request: Request,
    response: Response,
    word_id: str,
    body: MoveSavedWordToFolderRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Move a saved word to a different folder for authenticated or unauthenticated users."""
    # Extract user_id based on authentication status
    # authenticate() middleware has already validated these fields exist
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    else:
        user_id = auth_context["unauthenticated_user_id"]
    
    # Validate saved word exists and belongs to the user
    saved_word = get_saved_word_by_id_and_user_id(db, word_id, user_id)
    if not saved_word:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Saved word not found or does not belong to user"
            }
        )
    
    # Validate target folder exists and belongs to the user
    target_folder = get_folder_by_id_and_user_id(db, body.targetFolderId, user_id)
    if not target_folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Target folder not found or does not belong to user"
            }
        )
    
    # Update folder_id
    updated_word_data = update_saved_word_folder_id(
        db, word_id, user_id, body.targetFolderId
    )
    
    if not updated_word_data:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "UPDATE_FAILED",
                "error_message": "Failed to update saved word folder"
            }
        )
    
    # Fetch user info
    user_info = get_user_info_with_email_by_user_id(db, user_id)
    if not user_info:
        logger.warning(
            "Failed to retrieve user info for saved word",
            word_id=updated_word_data["id"],
            user_id=user_id
        )
        # Use empty values if user info not found
        user_obj = UserInfo(
            id=user_id,
            name="",
            email="",
            role=None,
            firstName=None,
            lastName=None,
            picture=None
        )
    else:
        user_obj = UserInfo(
            id=user_id,
            name=user_info.get("name", ""),
            email=user_info.get("email", ""),
            role=user_info.get("role"),
            firstName=None,
            lastName=None,
            picture=None
        )
    
    logger.info(
        "Moved saved word to folder successfully",
        word_id=word_id,
        user_id=user_id,
        target_folder_id=body.targetFolderId,
        authenticated=auth_context.get("authenticated", False)
    )
    
    # Add X-Unauthenticated-User-Id header for new unauthenticated users
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return SavedWordResponse(
        id=updated_word_data["id"],
        word=updated_word_data["word"],
        contextualMeaning=updated_word_data["contextual_meaning"],
        sourceUrl=updated_word_data["source_url"],
        folderId=updated_word_data["folder_id"],
        user=user_obj,
        createdAt=updated_word_data["created_at"]
    )

