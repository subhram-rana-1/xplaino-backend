"""API routes for issue management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import structlog

from app.models import (
    ReportIssueRequest,
    IssueResponse,
    GetMyIssuesResponse
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    create_issue,
    get_issues_by_user_id
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/issue", tags=["Issues"])


@router.get(
    "/",
    response_model=GetMyIssuesResponse,
    summary="Get my issues",
    description="Get all issues for the authenticated user, optionally filtered by status, ordered by most recent first"
)
async def get_my_issues(
    request: Request,
    response: Response,
    statuses: Optional[List[str]] = Query(default=None, description="List of status values to filter by (OPEN, WORK_IN_PROGRESS, DISCARDED, RESOLVED)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get issues for the authenticated user with optional status filter."""
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
    
    # Get issues for the user
    issues_data = get_issues_by_user_id(db, user_id, statuses)
    
    # Convert to response models
    issues = [
        IssueResponse(
            id=issue["id"],
            ticket_id=issue["ticket_id"],
            type=issue["type"],
            heading=issue["heading"],
            description=issue["description"],
            webpage_url=issue["webpage_url"],
            status=issue["status"],
            created_by=issue["created_by"],
            closed_by=issue["closed_by"],
            closed_at=issue["closed_at"],
            created_at=issue["created_at"],
            updated_at=issue["updated_at"]
        )
        for issue in issues_data
    ]
    
    logger.info(
        "Retrieved issues successfully",
        user_id=user_id,
        issue_count=len(issues),
        has_status_filter=statuses is not None and len(statuses) > 0
    )
    
    return GetMyIssuesResponse(issues=issues)


@router.post(
    "/",
    response_model=IssueResponse,
    status_code=201,
    summary="Report an issue",
    description="Create a new issue report for the authenticated user"
)
async def report_issue(
    request: Request,
    response: Response,
    body: ReportIssueRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Report a new issue for the authenticated user."""
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
    if body.heading and len(body.heading) > 100:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Heading length exceeds maximum of 100 characters"
            }
        )
    
    if body.webpage_url and len(body.webpage_url) > 1024:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_002",
                "error_message": "Webpage URL length exceeds maximum of 1024 characters"
            }
        )
    
    # Create issue
    issue_data = create_issue(
        db, user_id, body.type.value, body.heading, body.description, body.webpage_url
    )
    
    logger.info(
        "Created issue successfully",
        issue_id=issue_data["id"],
        ticket_id=issue_data["ticket_id"],
        user_id=user_id,
        issue_type=body.type.value
    )
    
    return IssueResponse(
        id=issue_data["id"],
        ticket_id=issue_data["ticket_id"],
        type=issue_data["type"],
        heading=issue_data["heading"],
        description=issue_data["description"],
        webpage_url=issue_data["webpage_url"],
        status=issue_data["status"],
        created_by=issue_data["created_by"],
        closed_by=issue_data["closed_by"],
        closed_at=issue_data["closed_at"],
        created_at=issue_data["created_at"],
        updated_at=issue_data["updated_at"]
    )

