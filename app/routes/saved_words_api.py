"""API routes for saved words management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
import structlog

from app.models import (
    SaveWordRequest,
    SavedWordResponse,
    GetSavedWordsResponse
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_saved_words_by_user_id,
    create_saved_word,
    delete_saved_word_by_id_and_user_id
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/saved-words", tags=["Saved Words"])


@router.get(
    "",
    response_model=GetSavedWordsResponse,
    summary="Get saved words",
    description="Get paginated list of saved words for the authenticated user, ordered by most recent first"
)
async def get_saved_words(
    request: Request,
    response: Response,
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get saved words for authenticated or unauthenticated users with pagination."""
    # Extract user_id based on authentication status
    # authenticate() middleware has already validated these fields exist
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    else:
        user_id = auth_context["unauthenticated_user_id"]
    
    # Get saved words
    words_data, total_count = get_saved_words_by_user_id(db, user_id, offset, limit)
    
    # Convert to response models
    words = [
        SavedWordResponse(
            id=word["id"],
            word=word["word"],
            contextual_meaning = word["contextual_meaning"],
            sourceUrl=word["source_url"],
            userId=word["user_id"],
            createdAt=word["created_at"]
        )
        for word in words_data
    ]
    
    logger.info(
        "Retrieved saved words",
        user_id=user_id,
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
    
    # Create saved word
    saved_word_data = create_saved_word(db, user_id, body.word, body.sourceUrl, body.contextual_meaning)
    
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
        contextual_meaning=saved_word_data["contextual_meaning"],
        sourceUrl=saved_word_data["source_url"],
        userId=saved_word_data["user_id"],
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

