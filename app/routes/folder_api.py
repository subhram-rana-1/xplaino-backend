"""API routes for folder management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Path
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Dict, Any, Optional
import structlog

from app.models import (
    GetAllFoldersResponse,
    FolderWithSubFoldersResponse,
    CreateFolderRequest,
    CreateFolderResponse,
    RenameFolderRequest,
    RenameFolderResponse,
    ShareResourceRequest,
    FolderShareResponse,
    SharedFolderItem,
    GetSharedFoldersResponse,
    GetShareeListResponse,
    ShareeItem,
    UserInfo
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_folders_by_owner_and_parent_id,
    create_paragraph_folder,
    get_folder_by_id_and_user_id,
    get_user_info_with_email_by_user_id,
    delete_folder_by_id_and_user_id,
    update_folder_name_by_id_and_user_id,
    share_folder,
    unshare_folder,
    get_folders_shared_with_email,
    get_folder_sharee_list,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/folders", tags=["Folders"])


def build_folder_hierarchy(folders: List[Dict[str, Any]]) -> List[FolderWithSubFoldersResponse]:
    """
    Build hierarchical folder structure from flat list.
    
    Args:
        folders: List of folder dictionaries with parent_id references
        
    Returns:
        List of root folders with nested subFolders
    """
    # Create a dictionary mapping parent_id -> list of child folders
    children_map: Dict[Optional[str], List[Dict[str, Any]]] = {}
    
    # Initialize map with empty lists
    for folder in folders:
        parent_id = folder.get("parent_id")
        if parent_id not in children_map:
            children_map[parent_id] = []
        children_map[parent_id].append(folder)
    
    def build_folder_tree(folder_data: Dict[str, Any]) -> FolderWithSubFoldersResponse:
        """Recursively build folder tree with subFolders."""
        folder_id = folder_data["id"]
        sub_folders_data = children_map.get(folder_id, [])
        
        # Recursively build sub-folders
        sub_folders = [build_folder_tree(sub_folder) for sub_folder in sub_folders_data]
        
        return FolderWithSubFoldersResponse(
            id=folder_data["id"],
            name=folder_data["name"],
            user_id=folder_data.get("user_id"),
            unauthenticated_user_id=folder_data.get("unauthenticated_user_id"),
            created_at=folder_data["created_at"],
            updated_at=folder_data["updated_at"],
            subFolders=sub_folders
        )
    
    # Get root folders (parent_id is None)
    root_folders = children_map.get(None, [])
    
    # Build tree structure starting from root folders
    return [build_folder_tree(folder) for folder in root_folders]


@router.get(
    "",
    response_model=GetAllFoldersResponse,
    summary="Get all folders",
    description="Get all folders for the authenticated user in hierarchical structure"
)
async def get_all_folders(
    request: Request,
    response: Response,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get all folders for authenticated or unauthenticated users in hierarchical structure."""
    # Resolve owner: exactly one of user_id / unauthenticated_user_id will be set
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
        unauthenticated_user_id = None
    else:
        user_id = None
        unauthenticated_user_id = auth_context["unauthenticated_user_id"]

    # To build the full hierarchy, we need all folders
    # Get all folders by recursively fetching from root
    all_folders = []
    def get_all_folders_recursive(parent_id):
        folders = get_folders_by_owner_and_parent_id(
            db,
            user_id=user_id,
            unauthenticated_user_id=unauthenticated_user_id,
            parent_id=parent_id,
        )
        all_folders.extend(folders)
        for folder in folders:
            get_all_folders_recursive(folder["id"])

    get_all_folders_recursive(None)

    # Build hierarchical structure
    folders = build_folder_hierarchy(all_folders)

    logger.info(
        "Retrieved folders",
        user_id=user_id,
        unauthenticated_user_id=unauthenticated_user_id,
        folders_count=len(folders),
        total_folders_count=len(all_folders),
        authenticated=auth_context.get("authenticated", False)
    )
    
    # Add X-Unauthenticated-User-Id header for new unauthenticated users
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return GetAllFoldersResponse(
        folders=folders
    )


@router.post(
    "",
    response_model=CreateFolderResponse,
    status_code=201,
    summary="Create a folder",
    description="Create a new folder for the authenticated user with optional parent folder"
)
async def create_folder(
    request: Request,
    response: Response,
    body: CreateFolderRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a folder for authenticated or unauthenticated users (unauthenticated will be blocked by rate limit)."""
    # Resolve owner: exactly one of user_id / unauthenticated_user_id will be set
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
        unauthenticated_user_id = None
    else:
        user_id = None
        unauthenticated_user_id = auth_context["unauthenticated_user_id"]

    # Validate name length (Pydantic already validates min_length=1, but we check max_length explicitly)
    if len(body.name) > 50:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Name length exceeds maximum of 50 characters"
            }
        )

    # If parentId is provided, validate it exists and belongs to the user
    if body.parentId:
        parent_folder = get_folder_by_id_and_user_id(db, body.parentId, user_id)
        if not parent_folder:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "NOT_FOUND",
                    "error_message": "Parent folder not found or does not belong to user"
                }
            )

    folder_data = create_paragraph_folder(
        db,
        user_id=user_id,
        name=body.name,
        parent_folder_id=body.parentId,
        unauthenticated_user_id=unauthenticated_user_id,
    )
    
    # Fetch user info (only available for authenticated users)
    if user_id:
        user_info_data = get_user_info_with_email_by_user_id(db, user_id)
        user_info = UserInfo(
            id=user_id,
            name=user_info_data.get("name", ""),
            email=user_info_data.get("email", ""),
            role=user_info_data.get("role"),
            firstName=None,
            lastName=None,
            picture=None
        )
    else:
        user_info = UserInfo(
            id=unauthenticated_user_id or "",
            name="",
            email="",
            role=None,
            firstName=None,
            lastName=None,
            picture=None
        )
    
    logger.info(
        "Created folder successfully",
        folder_id=folder_data["id"],
        user_id=user_id,
        name=body.name,
        has_parent_id=body.parentId is not None,
        authenticated=auth_context.get("authenticated", False)
    )
    
    # Add X-Unauthenticated-User-Id header for new unauthenticated users
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return CreateFolderResponse(
        id=folder_data["id"],
        name=folder_data["name"],
        parent_id=folder_data["parent_id"],
        user_id=folder_data["user_id"],
        created_at=folder_data["created_at"],
        updated_at=folder_data["updated_at"],
        user=user_info
    )


@router.get(
    "/shared-with-me",
    response_model=GetSharedFoldersResponse,
    summary="Get folders shared with me",
    description="Get all folders that have been shared with the authenticated user."
)
async def get_shared_folders_endpoint(
    request: Request,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Return all folders shared with the caller. Requires authentication."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication required to view shared folders"
            }
        )

    auth_vendor_id = auth_context["session_data"]["auth_vendor_id"]
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)

    user_info_data = get_user_info_with_email_by_user_id(db, user_id)
    email = user_info_data.get("email")
    if not email:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "NO_EMAIL",
                "error_message": "Authenticated user does not have an email address on record"
            }
        )

    folders_data = get_folders_shared_with_email(db, email)

    logger.info(
        "Retrieved shared folders",
        user_id=user_id,
        email=email,
        count=len(folders_data),
    )

    return GetSharedFoldersResponse(
        folders=[
            SharedFolderItem(
                id=f["id"],
                name=f["name"],
                parent_id=f["parent_id"],
                user_id=f["user_id"],
                created_at=f["created_at"],
                updated_at=f["updated_at"],
                shared_at=f["shared_at"],
            )
            for f in folders_data
        ]
    )


@router.delete(
    "/{folder_id}",
    status_code=204,
    summary="Delete a folder",
    description="Delete a folder by ID. All child folders and associated entities (saved words, paragraphs, links, images) will be automatically deleted due to CASCADE constraints."
)
async def delete_folder(
    request: Request,
    response: Response,
    folder_id: str = Path(..., description="Folder ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a folder for authenticated or unauthenticated users (unauthenticated will be blocked by rate limit)."""
    # Extract user_id based on authentication status
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    else:
        user_id = auth_context["unauthenticated_user_id"]
    
    # Verify folder exists and belongs to user
    folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )
    
    # Delete folder (CASCADE constraints will automatically delete child folders and associated entities)
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
        "Deleted folder successfully",
        folder_id=folder_id,
        user_id=user_id,
        authenticated=auth_context.get("authenticated", False)
    )
    
    # Add X-Unauthenticated-User-Id header for new unauthenticated users
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return FastAPIResponse(status_code=204)


@router.patch(
    "/{folder_id}",
    response_model=RenameFolderResponse,
    summary="Rename a folder",
    description="Rename a folder by ID. The folder must belong to the authenticated user."
)
async def rename_folder(
    request: Request,
    response: Response,
    folder_id: str = Path(..., description="Folder ID (UUID)"),
    body: RenameFolderRequest = None,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Rename a folder for authenticated or unauthenticated users (unauthenticated will be blocked by rate limit)."""
    # Extract user_id based on authentication status
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    else:
        user_id = auth_context["unauthenticated_user_id"]
    
    # Validate name length (Pydantic already validates min_length=1, but we check max_length explicitly)
    if len(body.name) > 50:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Name length exceeds maximum of 50 characters"
            }
        )
    
    # Verify folder exists and belongs to user
    folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )
    
    # Update folder name
    updated_folder = update_folder_name_by_id_and_user_id(db, folder_id, user_id, body.name)
    
    if not updated_folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )
    
    logger.info(
        "Renamed folder successfully",
        folder_id=folder_id,
        user_id=user_id,
        new_name=body.name,
        authenticated=auth_context.get("authenticated", False)
    )
    
    # Add X-Unauthenticated-User-Id header for new unauthenticated users
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return RenameFolderResponse(
        id=updated_folder["id"],
        name=updated_folder["name"],
        parent_id=updated_folder["parent_id"],
        user_id=updated_folder["user_id"],
        created_at=updated_folder["created_at"],
        updated_at=updated_folder["updated_at"]
    )


@router.post(
    "/{folder_id}/share",
    response_model=FolderShareResponse,
    status_code=201,
    summary="Share a folder",
    description="Share a folder with another user by their email address. Only the folder owner can share it."
)
async def share_folder_endpoint(
    request: Request,
    folder_id: str = Path(..., description="Folder ID (UUID)"),
    body: ShareResourceRequest = None,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Share a folder with another user by email. Requires authentication."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication required to share a folder"
            }
        )

    auth_vendor_id = auth_context["session_data"]["auth_vendor_id"]
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)

    folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )

    try:
        share_data = share_folder(db, folder_id, body.email)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "ALREADY_SHARED",
                "error_message": "Folder is already shared with this email"
            }
        )

    logger.info(
        "Shared folder successfully",
        folder_id=folder_id,
        user_id=user_id,
        shared_to_email=body.email,
    )

    return FolderShareResponse(
        id=share_data["id"],
        folder_id=share_data["folder_id"],
        shared_to_email=share_data["shared_to_email"],
        created_at=share_data["created_at"],
    )


@router.delete(
    "/{folder_id}/share",
    status_code=204,
    summary="Unshare a folder",
    description="Remove a share for a folder with a specific user by their email address. Only the folder owner can unshare it."
)
async def unshare_folder_endpoint(
    request: Request,
    folder_id: str = Path(..., description="Folder ID (UUID)"),
    body: ShareResourceRequest = None,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Unshare a folder from a user by email. Requires authentication."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication required to unshare a folder"
            }
        )

    auth_vendor_id = auth_context["session_data"]["auth_vendor_id"]
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)

    folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )

    deleted = unshare_folder(db, folder_id, body.email)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SHARE_NOT_FOUND",
                "error_message": "Share record not found for this folder and email"
            }
        )

    logger.info(
        "Unshared folder successfully",
        folder_id=folder_id,
        user_id=user_id,
        shared_to_email=body.email,
    )

    return FastAPIResponse(status_code=204)


@router.get(
    "/{folder_id}/share",
    response_model=GetShareeListResponse,
    summary="Get sharee list for a folder",
    description="Get all email addresses the owner has shared this folder with. Only the folder owner can view this list."
)
async def get_folder_sharee_list_endpoint(
    request: Request,
    folder_id: str = Path(..., description="Folder ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Return all recipients this folder has been shared with. Requires authentication and ownership."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication required to view folder sharee list"
            }
        )

    auth_vendor_id = auth_context["session_data"]["auth_vendor_id"]
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)

    folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )

    sharees_data = get_folder_sharee_list(db, folder_id)

    logger.info(
        "Retrieved folder sharee list",
        folder_id=folder_id,
        user_id=user_id,
        count=len(sharees_data),
    )

    return GetShareeListResponse(
        sharees=[
            ShareeItem(email=s["email"], shared_at=s["shared_at"])
            for s in sharees_data
        ]
    )

