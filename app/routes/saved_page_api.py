"""API routes for saved pages management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from typing import Optional
import structlog

from app.models import (
    SavePageRequest,
    SavedPageResponse,
    GetAllSavedPagesResponse,
    FolderResponse,
    CreatePageFolderRequest
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_folders_by_user_id_and_parent_id_and_type,
    get_saved_pages_by_user_id_and_folder_id,
    create_saved_page,
    delete_saved_page_by_id_and_user_id,
    get_folder_by_id_and_user_id,
    create_page_folder,
    delete_folder_by_id_and_user_id
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/saved-page", tags=["Saved Pages"])


@router.get(
    "/",
    response_model=GetAllSavedPagesResponse,
    summary="Get all saved pages",
    description="Get paginated list of saved pages and sub-folders for the authenticated user, ordered by most recent first"
)
async def get_all_saved_pages(
    request: Request,
    response: Response,
    folder_id: Optional[str] = Query(default=None, description="Folder ID to filter by (nullable for root)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get saved pages and sub-folders for the authenticated user with pagination."""
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
    
    # Get sub-folders for the given folder_id (or root if folder_id is None) with type='PAGE'
    sub_folders_data = get_folders_by_user_id_and_parent_id_and_type(
        db, user_id, folder_id, folder_type="PAGE"
    )
    
    # Get saved pages for the given folder_id (or root if folder_id is None)
    pages_data, total_count = get_saved_pages_by_user_id_and_folder_id(
        db, user_id, folder_id, offset, limit
    )
    
    # Convert folders to response models
    sub_folders = [
        FolderResponse(
            id=folder["id"],
            name=folder["name"],
            type=folder["type"],
            parent_id=folder["parent_id"],
            user_id=folder["user_id"],
            created_at=folder["created_at"],
            updated_at=folder["updated_at"]
        )
        for folder in sub_folders_data
    ]
    
    # Convert pages to response models
    saved_pages = [
        SavedPageResponse(
            id=page["id"],
            name=page["name"],
            url=page["url"],
            folder_id=page["folder_id"],
            user_id=page["user_id"],
            created_at=page["created_at"],
            updated_at=page["updated_at"]
        )
        for page in pages_data
    ]
    
    # Calculate has_next
    has_next = (offset + limit) < total_count
    
    logger.info(
        "Retrieved saved pages and folders",
        user_id=user_id,
        folder_id=folder_id,
        pages_count=len(saved_pages),
        folders_count=len(sub_folders),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )
    
    return GetAllSavedPagesResponse(
        folder_id=folder_id,
        user_id=user_id,
        sub_folders=sub_folders,
        saved_pages=saved_pages,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )


@router.post(
    "/",
    response_model=SavedPageResponse,
    status_code=201,
    summary="Save a page",
    description="Save a page URL for the authenticated user"
)
async def save_page(
    request: Request,
    response: Response,
    body: SavePageRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Save a page for the authenticated user."""
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
    if len(body.url) > 1024:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "URL length exceeds maximum of 1024 characters"
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
    
    # If folder_id is provided, validate it belongs to the user
    if body.folder_id:
        folder = get_folder_by_id_and_user_id(db, body.folder_id, user_id)
        if not folder:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "NOT_FOUND",
                    "error_message": "Folder not found or does not belong to user"
                }
            )
        
        # Validate that the folder is of type PAGE
        if folder.get("type") != "PAGE":
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "VAL_003",
                    "error_message": "Folder must be of type PAGE"
                }
            )
    
    # Create saved page
    saved_page_data = create_saved_page(
        db, user_id, body.url, body.name, body.folder_id
    )
    
    logger.info(
        "Saved page successfully",
        page_id=saved_page_data["id"],
        user_id=user_id,
        has_name=body.name is not None,
        has_folder_id=body.folder_id is not None
    )
    
    return SavedPageResponse(
        id=saved_page_data["id"],
        name=saved_page_data["name"],
        url=saved_page_data["url"],
        folder_id=saved_page_data["folder_id"],
        user_id=saved_page_data["user_id"],
        created_at=saved_page_data["created_at"],
        updated_at=saved_page_data["updated_at"]
    )


@router.delete(
    "/{page_id}",
    status_code=204,
    summary="Remove a saved page",
    description="Delete a saved page by ID. Only the owner can delete their own pages."
)
async def remove_saved_page(
    request: Request,
    response: Response,
    page_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Remove a saved page for the authenticated user."""
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
    
    # Delete saved page (this will only delete if it belongs to the user)
    deleted = delete_saved_page_by_id_and_user_id(db, page_id, user_id)
    
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Saved page not found or does not belong to user"
            }
        )
    
    logger.info(
        "Deleted saved page successfully",
        page_id=page_id,
        user_id=user_id
    )
    
    return FastAPIResponse(status_code=204)


@router.post(
    "/folder",
    response_model=FolderResponse,
    status_code=201,
    summary="Create a page folder",
    description="Create a new PAGE type folder for the authenticated user"
)
async def create_page_folder_endpoint(
    request: Request,
    response: Response,
    body: CreatePageFolderRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a page folder for the authenticated user."""
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
    
    # If parent_folder_id is provided, validate it belongs to the user and is type PAGE
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
        
        # Validate that the parent folder is of type PAGE
        if parent_folder.get("type") != "PAGE":
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "VAL_002",
                    "error_message": "Parent folder must be of type PAGE"
                }
            )
    
    # Create page folder
    folder_data = create_page_folder(db, user_id, body.name, body.parent_folder_id)
    
    logger.info(
        "Created page folder successfully",
        folder_id=folder_data["id"],
        user_id=user_id,
        name=body.name,
        has_parent_folder_id=body.parent_folder_id is not None
    )
    
    return FolderResponse(
        id=folder_data["id"],
        name=folder_data["name"],
        type=folder_data["type"],
        parent_id=folder_data["parent_id"],
        user_id=folder_data["user_id"],
        created_at=folder_data["created_at"],
        updated_at=folder_data["updated_at"]
    )


@router.delete(
    "/folder/{folder_id}",
    status_code=204,
    summary="Delete a page folder",
    description="Delete a page folder by ID. Only the owner can delete their own folders. The folder must be of type PAGE."
)
async def delete_page_folder(
    request: Request,
    response: Response,
    folder_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a page folder for the authenticated user."""
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
    
    # Get folder to verify ownership and type
    folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )
    
    # Validate that the folder is of type PAGE
    if folder.get("type") != "PAGE":
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Folder must be of type PAGE"
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
        "Deleted page folder successfully",
        folder_id=folder_id,
        user_id=user_id
    )
    
    return FastAPIResponse(status_code=204)

