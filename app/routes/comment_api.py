"""API routes for comment management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
import structlog

from app.models import (
    CommentResponse,
    GetCommentsResponse,
    CreateCommentRequest,
    CreateCommentResponse,
    CreatedByUser,
    EntityType,
    CommentVisibility
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id,
    get_comments_by_entity,
    get_comment_by_id,
    create_comment
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/comment", tags=["Comments"])


def build_comment_tree(comments: List[Dict[str, Any]]) -> List[CommentResponse]:
    """
    Build nested comment tree from flat list.
    
    Args:
        comments: Flat list of comment dictionaries with parent_comment_id
        
    Returns:
        List of CommentResponse objects with nested child_comments
    """
    # Create a map of comment_id -> CommentResponse
    comment_map: Dict[str, CommentResponse] = {}
    root_comments: List[CommentResponse] = []
    
    # First pass: create all CommentResponse objects
    for comment_data in comments:
        comment_id = comment_data["id"]
        # Use created_by_user if available, otherwise fallback to created_by
        created_by_user_data = comment_data.get("created_by_user")
        if created_by_user_data:
            created_by_user = CreatedByUser(
                id=created_by_user_data["id"],
                name=created_by_user_data.get("name", ""),
                role=created_by_user_data.get("role")
            )
        else:
            # Fallback for backward compatibility
            created_by_user = CreatedByUser(
                id=comment_data["created_by"],
                name="",
                role=None
            )
        comment_map[comment_id] = CommentResponse(
            id=comment_data["id"],
            content=comment_data["content"],
            visibility=comment_data["visibility"],
            child_comments=[],
            created_by=created_by_user,
            created_at=comment_data["created_at"],
            updated_at=comment_data["updated_at"]
        )
    
    # Second pass: build parent-child relationships
    for comment_data in comments:
        comment_id = comment_data["id"]
        parent_comment_id = comment_data["parent_comment_id"]
        
        if parent_comment_id is None:
            # Root comment
            root_comments.append(comment_map[comment_id])
        else:
            # Child comment - add to parent's child_comments
            if parent_comment_id in comment_map:
                parent_comment = comment_map[parent_comment_id]
                parent_comment.child_comments.append(comment_map[comment_id])
    
    # Sort root comments by created_at DESC (most recent first)
    root_comments.sort(key=lambda c: c.created_at, reverse=True)
    
    # Recursively sort child comments
    def sort_children(comment: CommentResponse):
        comment.child_comments.sort(key=lambda c: c.created_at, reverse=True)
        for child in comment.child_comments:
            sort_children(child)
    
    for root_comment in root_comments:
        sort_children(root_comment)
    
    return root_comments


@router.get(
    "/",
    response_model=GetCommentsResponse,
    summary="Get comments by entity",
    description="Get hierarchical comments for an entity with pagination. Returns X root comments with all nested children."
)
async def get_comments_by_entity_endpoint(
    request: Request,
    response: Response,
    entity_type: EntityType = Query(..., description="Entity type (ISSUE)"),
    entity_id: str = Query(..., description="Entity ID (UUID)"),
    count: int = Query(default=20, ge=1, le=100, description="Number of root comments to fetch"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get comments for an entity with hierarchical structure."""
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
    
    # Get user role for visibility filtering
    user_role = get_user_role_by_user_id(db, user_id)
    
    # Get comments from database
    comments_data = get_comments_by_entity(
        db, entity_type.value, entity_id, count, user_role
    )
    
    # Build nested comment tree
    comments_tree = build_comment_tree(comments_data)
    
    logger.info(
        "Retrieved comments successfully",
        user_id=user_id,
        entity_type=entity_type.value,
        entity_id=entity_id,
        root_comments_count=len(comments_tree),
        total_comments_count=len(comments_data)
    )
    
    return GetCommentsResponse(comments=comments_tree)


@router.post(
    "/",
    response_model=CreateCommentResponse,
    status_code=201,
    summary="Create a comment",
    description="Create a new comment for an entity. INTERNAL visibility requires ADMIN or SUPER_ADMIN role."
)
async def create_comment_endpoint(
    request: Request,
    response: Response,
    body: CreateCommentRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a new comment."""
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
    
    # Get user role
    user_role = get_user_role_by_user_id(db, user_id)
    
    # Validate: if visibility is INTERNAL, user must be ADMIN or SUPER_ADMIN
    if body.visibility == CommentVisibility.INTERNAL:
        if user_role not in ("ADMIN", "SUPER_ADMIN"):
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "PERMISSION_DENIED",
                    "error_message": "Only ADMIN and SUPER_ADMIN users can create INTERNAL comments"
                }
            )
    
    # Validate content (strip and check length)
    content_stripped = body.content.strip()
    if len(content_stripped) == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Comment content cannot be empty"
            }
        )
    
    if len(content_stripped) > 1024:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_002",
                "error_message": "Comment content exceeds maximum length of 1024 characters"
            }
        )
    
    # Validate parent_comment_id exists if provided
    if body.parent_comment_id:
        parent_comment = get_comment_by_id(db, body.parent_comment_id)
        if not parent_comment:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "PARENT_COMMENT_NOT_FOUND",
                    "error_message": "Parent comment not found"
                }
            )
    
    try:
        # Create comment
        comment_data = create_comment(
            db,
            user_id,
            body.entity_type.value,
            body.entity_id,
            content_stripped,
            body.visibility.value,
            body.parent_comment_id
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_003",
                "error_message": str(e)
            }
        )
    except Exception as e:
        if "Parent comment not found" in str(e):
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "PARENT_COMMENT_NOT_FOUND",
                    "error_message": "Parent comment not found"
                }
            )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "INTERNAL_ERROR",
                "error_message": "Failed to create comment"
            }
        )
    
    logger.info(
        "Created comment successfully",
        comment_id=comment_data["id"],
        user_id=user_id,
        entity_type=body.entity_type.value,
        entity_id=body.entity_id,
        visibility=body.visibility.value
    )
    
    # Extract created_by_user from comment_data
    created_by_user_data = comment_data.get("created_by_user")
    if created_by_user_data:
        created_by_user = CreatedByUser(
            id=created_by_user_data["id"],
            name=created_by_user_data.get("name", ""),
            role=created_by_user_data.get("role")
        )
    else:
        # Fallback for backward compatibility
        created_by_user = CreatedByUser(
            id=comment_data["created_by"],
            name="",
            role=None
        )
    
    return CreateCommentResponse(
        id=comment_data["id"],
        content=comment_data["content"],
        entity_type=comment_data["entity_type"],
        entity_id=comment_data["entity_id"],
        parent_comment_id=comment_data["parent_comment_id"],
        visibility=comment_data["visibility"],
        created_by=created_by_user,
        created_at=comment_data["created_at"],
        updated_at=comment_data["updated_at"]
    )

