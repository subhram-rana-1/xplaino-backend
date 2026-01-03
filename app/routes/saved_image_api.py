"""API routes for saved images management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from typing import Optional
import structlog

from app.models import (
    CreateSavedImageRequest,
    SavedImageResponse,
    GetAllSavedImagesResponse,
    MoveSavedImageToFolderRequest,
    SavedImageCreatedByUser
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_saved_images_by_folder_id_and_user_id,
    create_saved_image,
    get_saved_image_by_id_and_user_id,
    update_saved_image_folder_id,
    delete_saved_image_by_id_and_user_id,
    get_folder_by_id_and_user_id,
    get_user_info_with_email_by_user_id
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/saved-image", tags=["Saved Images"])


@router.post(
    "",
    response_model=SavedImageResponse,
    status_code=201,
    summary="Create a saved image",
    description="Create a new saved image for the authenticated user"
)
async def create_saved_image_endpoint(
    request: Request,
    response: Response,
    body: CreateSavedImageRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a saved image for the authenticated user."""
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
    if len(body.imageUrl) > 1024:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Image URL length exceeds maximum of 1024 characters"
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

    if body.name and len(body.name) > 100:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_003",
                "error_message": "Name length exceeds maximum of 100 characters"
            }
        )

    # Validate folder exists and belongs to the user
    folder = get_folder_by_id_and_user_id(db, body.folderId, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )

    # Create saved image
    saved_image_data = create_saved_image(
        db, user_id, body.sourceUrl, body.imageUrl, body.folderId, body.name
    )

    # Get user info for createdBy field
    user_info = get_user_info_with_email_by_user_id(db, user_id)
    if not user_info:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "USER_INFO_ERROR",
                "error_message": "Failed to retrieve user information"
            }
        )

    created_by = SavedImageCreatedByUser(
        id=user_id,
        email=user_info.get("email", ""),
        name=user_info.get("name", "")
    )

    logger.info(
        "Created saved image successfully",
        image_id=saved_image_data["id"],
        user_id=user_id
    )

    return SavedImageResponse(
        id=saved_image_data["id"],
        sourceUrl=saved_image_data["source_url"],
        imageUrl=saved_image_data["image_url"],
        name=saved_image_data["name"],
        folderId=saved_image_data["folder_id"],
        userId=saved_image_data["user_id"],
        createdAt=saved_image_data["created_at"],
        updatedAt=saved_image_data["updated_at"],
        createdBy=created_by
    )


@router.get(
    "",
    response_model=GetAllSavedImagesResponse,
    summary="Get all saved images by folder ID",
    description="Get paginated list of saved images for the authenticated user in a specific folder, ordered by most recent first"
)
async def get_all_saved_images_by_folder_id(
    request: Request,
    response: Response,
    folder_id: str = Query(..., alias="folder-id", description="Folder ID to filter by"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get saved images for the authenticated user with pagination."""
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

    # Validate folder exists and belongs to the user
    folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
    if not folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Folder not found or does not belong to user"
            }
        )

    # Get saved images for the folder
    images_data, total_count = get_saved_images_by_folder_id_and_user_id(
        db, user_id, folder_id, offset, limit
    )

    # Get user info for each image's user_id (all should be the same user_id, but we'll fetch for each)
    images = []
    for image_data in images_data:
        image_user_id = image_data["user_id"]
        user_info = get_user_info_with_email_by_user_id(db, image_user_id)
        if not user_info:
            logger.warning(
                "Failed to retrieve user info for image",
                image_id=image_data["id"],
                user_id=image_user_id
            )
            # Use empty values if user info not found
            created_by = SavedImageCreatedByUser(
                id=image_user_id,
                email="",
                name=""
            )
        else:
            created_by = SavedImageCreatedByUser(
                id=image_user_id,
                email=user_info.get("email", ""),
                name=user_info.get("name", "")
            )

        images.append(
            SavedImageResponse(
                id=image_data["id"],
                sourceUrl=image_data["source_url"],
                imageUrl=image_data["image_url"],
                name=image_data["name"],
                folderId=image_data["folder_id"],
                userId=image_data["user_id"],
                createdAt=image_data["created_at"],
                updatedAt=image_data["updated_at"],
                createdBy=created_by
            )
        )

    # Calculate has_next
    has_next = (offset + limit) < total_count

    logger.info(
        "Retrieved saved images successfully",
        user_id=user_id,
        folder_id=folder_id,
        images_count=len(images),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )

    return GetAllSavedImagesResponse(
        images=images,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )


@router.patch(
    "/{saved_image_id}/move-to-folder",
    response_model=SavedImageResponse,
    summary="Move saved image to folder",
    description="Move a saved image to a different folder. Only the owner can move their own images."
)
async def move_saved_image_to_folder(
    request: Request,
    response: Response,
    saved_image_id: str,
    body: MoveSavedImageToFolderRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Move a saved image to a different folder for the authenticated user."""
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

    # Validate saved image exists and belongs to the user
    saved_image = get_saved_image_by_id_and_user_id(db, saved_image_id, user_id)
    if not saved_image:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Saved image not found or does not belong to user"
            }
        )

    # Validate new folder exists and belongs to the user
    new_folder = get_folder_by_id_and_user_id(db, body.newFolderId, user_id)
    if not new_folder:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "New folder not found or does not belong to user"
            }
        )

    # Update folder_id
    updated_image_data = update_saved_image_folder_id(
        db, saved_image_id, user_id, body.newFolderId
    )

    if not updated_image_data:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "UPDATE_FAILED",
                "error_message": "Failed to update saved image folder"
            }
        )

    # Get user info for createdBy field
    user_info = get_user_info_with_email_by_user_id(db, user_id)
    if not user_info:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "USER_INFO_ERROR",
                "error_message": "Failed to retrieve user information"
            }
        )

    created_by = SavedImageCreatedByUser(
        id=user_id,
        email=user_info.get("email", ""),
        name=user_info.get("name", "")
    )

    logger.info(
        "Moved saved image to folder successfully",
        image_id=saved_image_id,
        user_id=user_id,
        new_folder_id=body.newFolderId
    )

    return SavedImageResponse(
        id=updated_image_data["id"],
        sourceUrl=updated_image_data["source_url"],
        imageUrl=updated_image_data["image_url"],
        name=updated_image_data["name"],
        folderId=updated_image_data["folder_id"],
        userId=updated_image_data["user_id"],
        createdAt=updated_image_data["created_at"],
        updatedAt=updated_image_data["updated_at"],
        createdBy=created_by
    )


@router.delete(
    "/{saved_image_id}",
    status_code=204,
    summary="Delete a saved image",
    description="Delete a saved image by ID. Only the owner can delete their own images."
)
async def delete_saved_image(
    request: Request,
    response: Response,
    saved_image_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a saved image for the authenticated user."""
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

    # Delete saved image (this will only delete if it belongs to the user)
    deleted = delete_saved_image_by_id_and_user_id(db, saved_image_id, user_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Saved image not found or does not belong to user"
            }
        )

    logger.info(
        "Deleted saved image successfully",
        image_id=saved_image_id,
        user_id=user_id
    )

    return FastAPIResponse(status_code=204)

