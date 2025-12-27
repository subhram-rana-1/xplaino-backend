"""API routes for saved links management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from typing import Optional
import structlog

from app.models import (
    SaveLinkRequest,
    SavedLinkResponse,
    GetAllSavedLinksResponse,
    FolderResponse,
    CreateLinkFolderRequest
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_folders_by_user_id_and_parent_id_and_type,
    get_saved_links_by_user_id_and_folder_id,
    create_saved_link,
    get_saved_link_by_url_and_user_id,
    update_saved_link_summary_and_metadata,
    delete_saved_link_by_id_and_user_id,
    get_saved_link_by_id_and_user_id,
    get_folder_by_id_and_user_id,
    create_page_folder,
    delete_folder_by_id_and_user_id
)
from app.utils.utils import detect_link_type_from_url

logger = structlog.get_logger()

router = APIRouter(prefix="/api/saved-link", tags=["Saved Links"])


@router.get(
    "/",
    response_model=GetAllSavedLinksResponse,
    summary="Get all saved links",
    description="Get paginated list of saved links and sub-folders for the authenticated user, ordered by most recent first"
)
async def get_all_saved_links(
    request: Request,
    response: Response,
    folder_id: Optional[str] = Query(default=None, description="Folder ID to filter by (nullable for root)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get saved links and sub-folders for the authenticated user with pagination."""
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
    
    # Get saved links for the given folder_id (or root if folder_id is None)
    links_data, total_count = get_saved_links_by_user_id_and_folder_id(
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
    
    # Convert links to response models
    saved_links = [
        SavedLinkResponse(
            id=link["id"],
            name=link["name"],
            url=link["url"],
            type=link["type"],
            summary=link["summary"],
            metadata=link["metadata"],
            folder_id=link["folder_id"],
            user_id=link["user_id"],
            created_at=link["created_at"],
            updated_at=link["updated_at"]
        )
        for link in links_data
    ]
    
    # Calculate has_next
    has_next = (offset + limit) < total_count
    
    logger.info(
        "Retrieved saved links and folders",
        user_id=user_id,
        folder_id=folder_id,
        links_count=len(saved_links),
        folders_count=len(sub_folders),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )
    
    return GetAllSavedLinksResponse(
        folder_id=folder_id,
        user_id=user_id,
        sub_folders=sub_folders,
        saved_links=saved_links,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )


@router.post(
    "/",
    response_model=SavedLinkResponse,
    status_code=201,
    summary="Save a link",
    description="Save a link URL for the authenticated user"
)
async def save_link(
    request: Request,
    response: Response,
    body: SaveLinkRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Save a link for the authenticated user."""
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
    
    # Check if link with this URL already exists for this user
    existing_link = get_saved_link_by_url_and_user_id(db, body.url, user_id)
    
    if existing_link:
        # Update existing link's summary and metadata only
        saved_link_data = update_saved_link_summary_and_metadata(
            db, existing_link["id"], user_id, body.summary, body.metadata
        )
        
        if not saved_link_data:
            raise HTTPException(
                status_code=500,
                detail={
                    "error_code": "UPDATE_FAILED",
                    "error_message": "Failed to update existing link"
                }
            )
        
        logger.info(
            "Updated existing link summary and metadata",
            link_id=saved_link_data["id"],
            user_id=user_id,
            url=body.url
        )
    else:
        # Auto-detect link type from URL
        link_type = detect_link_type_from_url(body.url)
        
        # Create new saved link
        saved_link_data = create_saved_link(
            db, user_id, body.url, body.name, body.folder_id, link_type, body.summary, body.metadata
        )
        
        logger.info(
            "Created new saved link",
            link_id=saved_link_data["id"],
            user_id=user_id,
            has_name=body.name is not None,
            has_folder_id=body.folder_id is not None
        )
    
    return SavedLinkResponse(
        id=saved_link_data["id"],
        name=saved_link_data["name"],
        url=saved_link_data["url"],
        type=saved_link_data["type"],
        summary=saved_link_data["summary"],
        metadata=saved_link_data["metadata"],
        folder_id=saved_link_data["folder_id"],
        user_id=saved_link_data["user_id"],
        created_at=saved_link_data["created_at"],
        updated_at=saved_link_data["updated_at"]
    )


@router.get(
    "/{link_id}",
    response_model=SavedLinkResponse,
    summary="Get link details by ID",
    description="Get all details for a saved link by its ID. Only the owner can access their own links."
)
async def get_link_details_by_id(
    request: Request,
    response: Response,
    link_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get link details by ID for the authenticated user."""
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
    
    # Get saved link (this will only return if it belongs to the user)
    link_data = get_saved_link_by_id_and_user_id(db, link_id, user_id)
    
    if not link_data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Saved link not found or does not belong to user"
            }
        )
    
    logger.info(
        "Retrieved link details successfully",
        link_id=link_id,
        user_id=user_id
    )
    
    return SavedLinkResponse(
        id=link_data["id"],
        name=link_data["name"],
        url=link_data["url"],
        type=link_data["type"],
        summary=link_data["summary"],
        metadata=link_data["metadata"],
        folder_id=link_data["folder_id"],
        user_id=link_data["user_id"],
        created_at=link_data["created_at"],
        updated_at=link_data["updated_at"]
    )


@router.delete(
    "/{link_id}",
    status_code=204,
    summary="Remove a saved link",
    description="Delete a saved link by ID. Only the owner can delete their own links."
)
async def remove_saved_link(
    request: Request,
    response: Response,
    link_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Remove a saved link for the authenticated user."""
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
    
    # Delete saved link (this will only delete if it belongs to the user)
    deleted = delete_saved_link_by_id_and_user_id(db, link_id, user_id)
    
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Saved link not found or does not belong to user"
            }
        )
    
    logger.info(
        "Deleted saved link successfully",
        link_id=link_id,
        user_id=user_id
    )
    
    return FastAPIResponse(status_code=204)


@router.post(
    "/folder",
    response_model=FolderResponse,
    status_code=201,
    summary="Create a link folder",
    description="Create a new PAGE type folder for the authenticated user"
)
async def create_link_folder_endpoint(
    request: Request,
    response: Response,
    body: CreateLinkFolderRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a link folder for the authenticated user."""
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
    
    # Create link folder
    folder_data = create_page_folder(db, user_id, body.name, body.parent_folder_id)
    
    logger.info(
        "Created link folder successfully",
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
    summary="Delete a link folder",
    description="Delete a link folder by ID. Only the owner can delete their own folders. The folder must be of type PAGE."
)
async def delete_link_folder(
    request: Request,
    response: Response,
    folder_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a link folder for the authenticated user."""
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
        "Deleted link folder successfully",
        folder_id=folder_id,
        user_id=user_id
    )
    
    return FastAPIResponse(status_code=204)

