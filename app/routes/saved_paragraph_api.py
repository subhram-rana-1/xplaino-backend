"""API routes for saved paragraphs management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from typing import Optional
import structlog

from app.models import (
    SaveParagraphRequest,
    SavedParagraphResponse,
    GetAllSavedParagraphResponse,
    FolderResponse,
    CreateParagraphFolderRequest,
    MoveSavedParagraphToFolderRequest
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_folders_by_user_id_and_parent_id,
    get_saved_paragraphs_by_user_id_and_folder_id,
    create_saved_paragraph,
    delete_saved_paragraph_by_id_and_user_id,
    get_folder_by_id_and_user_id,
    create_paragraph_folder,
    delete_folder_by_id_and_user_id,
    get_saved_paragraph_by_id_and_user_id,
    update_saved_paragraph_folder_id
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/saved-paragraph", tags=["Saved Paragraphs"])


@router.get(
    "/",
    response_model=GetAllSavedParagraphResponse,
    summary="Get all saved paragraphs",
    description="Get paginated list of saved paragraphs and sub-folders for the authenticated user, ordered by most recent first"
)
async def get_all_saved_paragraphs(
    request: Request,
    response: Response,
    folder_id: Optional[str] = Query(default=None, description="Folder ID to filter by (nullable for root)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get saved paragraphs and sub-folders for the authenticated user with pagination."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Get sub-folders for the given folder_id (or root if folder_id is None)
    sub_folders_data = get_folders_by_user_id_and_parent_id(db, user_id, folder_id)
    
    # Get saved paragraphs for the given folder_id (or root if folder_id is None)
    paragraphs_data, total_count = get_saved_paragraphs_by_user_id_and_folder_id(
        db, user_id, folder_id, offset, limit
    )
    
    # Convert folders to response models
    sub_folders = [
        FolderResponse(
            id=folder["id"],
            name=folder["name"],
            parent_id=folder["parent_id"],
            user_id=folder["user_id"],
            created_at=folder["created_at"],
            updated_at=folder["updated_at"]
        )
        for folder in sub_folders_data
    ]
    
    # Convert paragraphs to response models
    saved_paragraphs = [
        SavedParagraphResponse(
            id=para["id"],
            name=para["name"],
            source_url=para["source_url"],
            content=para["content"],
            folder_id=para["folder_id"],
            user_id=para["user_id"],
            created_at=para["created_at"],
            updated_at=para["updated_at"]
        )
        for para in paragraphs_data
    ]
    
    # Calculate has_next
    has_next = (offset + limit) < total_count
    
    logger.info(
        "Retrieved saved paragraphs and folders",
        user_id=user_id,
        folder_id=folder_id,
        paragraphs_count=len(saved_paragraphs),
        folders_count=len(sub_folders),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )
    
    return GetAllSavedParagraphResponse(
        folder_id=folder_id,
        user_id=user_id,
        sub_folders=sub_folders,
        saved_paragraphs=saved_paragraphs,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )


@router.post(
    "/",
    response_model=SavedParagraphResponse,
    status_code=201,
    summary="Save a paragraph",
    description="Save a paragraph with its source URL for the authenticated user"
)
async def save_paragraph(
    request: Request,
    response: Response,
    body: SaveParagraphRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Save a paragraph for the authenticated user."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Validate input lengths
    if len(body.source_url) > 1024:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Source URL length exceeds maximum of 1024 characters"
            }
        )
    
    if body.name and len(body.name) > 50:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_002",
                "error_message": "Name length exceeds maximum of 50 characters"
            }
        )
    
    # Validate folder exists and belongs to the user
    folder = get_folder_by_id_and_user_id(db, body.folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )
    
    # Create saved paragraph
    saved_paragraph_data = create_saved_paragraph(
        db, user_id, body.content, body.source_url, body.folder_id, body.name
    )
    
    logger.info(
        "Saved paragraph successfully",
        paragraph_id=saved_paragraph_data["id"],
        user_id=user_id,
        has_name=body.name is not None
    )
    
    return SavedParagraphResponse(
        id=saved_paragraph_data["id"],
        name=saved_paragraph_data["name"],
        source_url=saved_paragraph_data["source_url"],
        content=saved_paragraph_data["content"],
        folder_id=saved_paragraph_data["folder_id"],
        user_id=saved_paragraph_data["user_id"],
        created_at=saved_paragraph_data["created_at"],
        updated_at=saved_paragraph_data["updated_at"]
    )


@router.delete(
    "/{paragraph_id}",
    status_code=204,
    summary="Remove a saved paragraph",
    description="Delete a saved paragraph by ID. Only the owner can delete their own paragraphs."
)
async def remove_saved_paragraph(
    request: Request,
    response: Response,
    paragraph_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Remove a saved paragraph for the authenticated user."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Delete saved paragraph (this will only delete if it belongs to the user)
    deleted = delete_saved_paragraph_by_id_and_user_id(db, paragraph_id, user_id)
    
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Saved paragraph not found or does not belong to user"
            }
        )
    
    logger.info(
        "Deleted saved paragraph successfully",
        paragraph_id=paragraph_id,
        user_id=user_id
    )
    
    return FastAPIResponse(status_code=204)


@router.patch(
    "/{paragraph_id}/move-to-folder",
    response_model=SavedParagraphResponse,
    summary="Move saved paragraph to folder",
    description="Move a saved paragraph to a different folder. Only the owner can move their own paragraphs."
)
async def move_saved_paragraph_to_folder(
    request: Request,
    response: Response,
    paragraph_id: str,
    body: MoveSavedParagraphToFolderRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Move a saved paragraph to a different folder for the authenticated user."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Validate saved paragraph exists and belongs to the user
    saved_paragraph = get_saved_paragraph_by_id_and_user_id(db, paragraph_id, user_id)
    if not saved_paragraph:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Saved paragraph not found or does not belong to user"
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
    updated_paragraph_data = update_saved_paragraph_folder_id(
        db, paragraph_id, user_id, body.targetFolderId
    )
    
    if not updated_paragraph_data:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "UPDATE_FAILED",
                "error_message": "Failed to update saved paragraph folder"
            }
        )
    
    logger.info(
        "Moved saved paragraph to folder successfully",
        paragraph_id=paragraph_id,
        user_id=user_id,
        target_folder_id=body.targetFolderId
    )
    
    return SavedParagraphResponse(
        id=updated_paragraph_data["id"],
        name=updated_paragraph_data["name"],
        source_url=updated_paragraph_data["source_url"],
        content=updated_paragraph_data["content"],
        folder_id=updated_paragraph_data["folder_id"],
        user_id=updated_paragraph_data["user_id"],
        created_at=updated_paragraph_data["created_at"],
        updated_at=updated_paragraph_data["updated_at"]
    )


@router.post(
    "/folder",
    response_model=FolderResponse,
    status_code=201,
    summary="Create a paragraph folder",
    description="Create a new PARAGRAPH type folder for the authenticated user"
)
async def create_paragraph_folder_endpoint(
    request: Request,
    response: Response,
    body: CreateParagraphFolderRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a paragraph folder for the authenticated user."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Validate input length
    if len(body.name) > 50:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Name length exceeds maximum of 50 characters"
            }
        )
    
    # If parent_folder_id is provided, validate it belongs to the user
    if body.parent_folder_id:
        parent_folder = get_folder_by_id_and_user_id(db, body.parent_folder_id, user_id)
        if not parent_folder:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "NOT_FOUND",
                    "error_message": "Parent folder not found or does not belong to user"
                }
            )
        
    
    # Create paragraph folder
    folder_data = create_paragraph_folder(db, user_id, body.name, body.parent_folder_id)
    
    logger.info(
        "Created paragraph folder successfully",
        folder_id=folder_data["id"],
        user_id=user_id,
        name=body.name,
        has_parent_folder_id=body.parent_folder_id is not None
    )
    
    return FolderResponse(
        id=folder_data["id"],
        name=folder_data["name"],
        parent_id=folder_data["parent_id"],
        user_id=folder_data["user_id"],
        created_at=folder_data["created_at"],
        updated_at=folder_data["updated_at"]
    )


@router.delete(
    "/folder/{folder_id}",
    status_code=204,
    summary="Delete a paragraph folder",
    description="Delete a paragraph folder by ID. Only the owner can delete their own folders."
)
async def delete_paragraph_folder(
    request: Request,
    response: Response,
    folder_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a paragraph folder for the authenticated user."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Get folder to verify ownership
    folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )
    
    
    # Delete folder
    deleted = delete_folder_by_id_and_user_id(db, folder_id, user_id)
    
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )
    
    logger.info(
        "Deleted paragraph folder successfully",
        folder_id=folder_id,
        user_id=user_id
    )
    
    return FastAPIResponse(status_code=204)

