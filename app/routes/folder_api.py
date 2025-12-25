"""API routes for folder management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
import structlog

from app.models import (
    GetAllFoldersResponse,
    FolderWithSubFoldersResponse
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_all_folders_by_user_id_and_type
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
    description="Get all folders for the authenticated user in hierarchical structure, filtered by type (PAGE or PARAGRAPH)"
)
async def get_all_folders(
    request: Request,
    response: Response,
    type: str = Query(..., description="Folder type (PAGE or PARAGRAPH)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get all folders for authenticated or unauthenticated users in hierarchical structure."""
    # Validate type query parameter
    if type not in ["PAGE", "PARAGRAPH"]:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "VAL_001",
                "error_message": "Type must be either 'PAGE' or 'PARAGRAPH'"
            }
        )
    
    # Extract user_id based on authentication status
    # authenticate() middleware has already validated these fields exist
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    else:
        user_id = auth_context["unauthenticated_user_id"]
    
    # Fetch all folders for the user and type
    folders_data = get_all_folders_by_user_id_and_type(db, user_id, type)
    
    # Build hierarchical structure
    folders = build_folder_hierarchy(folders_data)
    
    logger.info(
        "Retrieved folders",
        user_id=user_id,
        folder_type=type,
        folders_count=len(folders),
        total_folders_count=len(folders_data),
        authenticated=auth_context.get("authenticated", False)
    )
    
    # Add X-Unauthenticated-User-Id header for new unauthenticated users
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return GetAllFoldersResponse(
        type=type,
        folders=folders
    )

