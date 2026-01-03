"""API routes for issue management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query, UploadFile, File, Form, Path
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from typing import Optional, List, Tuple
from datetime import datetime, timezone
import structlog
import io
from PIL import Image
import PyPDF2

from app.models import (
    ReportIssueRequest,
    IssueResponse,
    GetMyIssuesResponse,
    GetAllIssuesResponse,
    GetIssueByTicketIdResponse,
    UpdateIssueRequest,
    FileUploadResponse,
    FileType,
    IssueType,
    IssueStatus,
    CreatedByUser
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id,
    create_issue,
    get_issues_by_user_id,
    get_all_issues,
    get_issue_by_id,
    get_issue_by_ticket_id,
    update_issue,
    create_file_upload,
    get_file_uploads_by_entity
)
from app.services.s3_service import s3_service
from app.exceptions import FileValidationError

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
    
    # Convert to response models with file_uploads
    issues = []
    for issue in issues_data:
        # Fetch file_uploads for this issue
        file_uploads_data = get_file_uploads_by_entity(db, "ISSUE", issue["id"])
        file_uploads = [
            FileUploadResponse(
                id=fu["id"],
                file_name=fu["file_name"],
                file_type=fu["file_type"],
                entity_type=fu["entity_type"],
                entity_id=fu["entity_id"],
                s3_url=fu["s3_url"],
                metadata=fu["metadata"],
                created_at=fu["created_at"],
                updated_at=fu["updated_at"]
            )
            for fu in file_uploads_data
        ]
        
        issues.append(
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
                updated_at=issue["updated_at"],
                file_uploads=file_uploads
            )
        )
    
    logger.info(
        "Retrieved issues successfully",
        user_id=user_id,
        issue_count=len(issues),
        has_status_filter=statuses is not None and len(statuses) > 0
    )
    
    return GetMyIssuesResponse(issues=issues)


@router.get(
    "/all",
    response_model=GetAllIssuesResponse,
    summary="Get all issues (Admin only)",
    description="Get paginated list of all issues with optional filters. Only ADMIN and SUPER_ADMIN users can access this endpoint. Results ordered by created_at ASC (oldest first)."
)
async def get_all_issues_endpoint(
    request: Request,
    response: Response,
    ticket_id: Optional[str] = Query(default=None, description="Filter by exact ticket_id"),
    type: Optional[str] = Query(default=None, description="Filter by issue type (GLITCH, SUBSCRIPTION, AUTHENTICATION, FEATURE_REQUEST, OTHERS)"),
    status: Optional[str] = Query(default=None, description="Filter by status (OPEN, WORK_IN_PROGRESS, DISCARDED, RESOLVED)"),
    closed_by: Optional[str] = Query(default=None, description="Filter by closed_by user ID (UUID)"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get all issues with optional filters. Admin only."""
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
    
    # Check admin role
    user_role = get_user_role_by_user_id(db, user_id)
    if user_role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PERMISSION_DENIED",
                "error_message": "Only ADMIN and SUPER_ADMIN users can access this endpoint"
            }
        )
    
    # Get all issues with filters and pagination
    issues_data, total_count = get_all_issues(
        db,
        ticket_id=ticket_id,
        issue_type=type,
        status=status,
        closed_by=closed_by,
        offset=offset,
        limit=limit
    )
    
    # Convert to response models with file_uploads
    issues = []
    for issue in issues_data:
        # Fetch file_uploads for this issue
        file_uploads_data = get_file_uploads_by_entity(db, "ISSUE", issue["id"])
        file_uploads = [
            FileUploadResponse(
                id=fu["id"],
                file_name=fu["file_name"],
                file_type=fu["file_type"],
                entity_type=fu["entity_type"],
                entity_id=fu["entity_id"],
                s3_url=fu["s3_url"],
                metadata=fu["metadata"],
                created_at=fu["created_at"],
                updated_at=fu["updated_at"]
            )
            for fu in file_uploads_data
        ]
        
        issues.append(
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
                updated_at=issue["updated_at"],
                file_uploads=file_uploads
            )
        )
    
    # Calculate has_next
    has_next = (offset + limit) < total_count
    
    logger.info(
        "Retrieved all issues successfully (admin)",
        user_id=user_id,
        issue_count=len(issues),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next,
        has_ticket_id_filter=ticket_id is not None,
        has_type_filter=type is not None,
        has_status_filter=status is not None,
        has_closed_by_filter=closed_by is not None
    )
    
    return GetAllIssuesResponse(
        issues=issues,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )


@router.get(
    "/ticket/{ticket_id}",
    response_model=GetIssueByTicketIdResponse,
    summary="Get issue by ticket ID",
    description="Get an issue by its ticket_id with all database fields. Returns CreatedByUser DTOs for created_by and closed_by fields."
)
async def get_issue_by_ticket_id_endpoint(
    request: Request,
    response: Response,
    ticket_id: str = Path(..., description="Ticket ID (14 characters)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get an issue by ticket_id with user information."""
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
    
    # Get issue by ticket_id
    issue_data = get_issue_by_ticket_id(db, ticket_id)
    if not issue_data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ISSUE_NOT_FOUND",
                "error_message": f"Issue with ticket_id {ticket_id} not found"
            }
        )
    
    # Build CreatedByUser objects
    created_by_user_data = issue_data.get("created_by_user")
    if created_by_user_data:
        created_by_user = CreatedByUser(
            id=created_by_user_data["id"],
            name=created_by_user_data.get("name", ""),
            role=created_by_user_data.get("role"),
            profileIconUrl=created_by_user_data.get("picture")
        )
    else:
        # Fallback for backward compatibility
        created_by_user = CreatedByUser(
            id=issue_data["created_by"],
            name="",
            role=None,
            profileIconUrl=None
        )
    
    closed_by_user = None
    closed_by_user_data = issue_data.get("closed_by_user")
    if closed_by_user_data:
        closed_by_user = CreatedByUser(
            id=closed_by_user_data["id"],
            name=closed_by_user_data.get("name", ""),
            role=closed_by_user_data.get("role"),
            profileIconUrl=closed_by_user_data.get("picture")
        )
    
    # Fetch file_uploads for the issue
    file_uploads_data = get_file_uploads_by_entity(db, "ISSUE", issue_data["id"])
    file_uploads = [
        FileUploadResponse(
            id=fu["id"],
            file_name=fu["file_name"],
            file_type=fu["file_type"],
            entity_type=fu["entity_type"],
            entity_id=fu["entity_id"],
            s3_url=fu["s3_url"],
            metadata=fu["metadata"],
            created_at=fu["created_at"],
            updated_at=fu["updated_at"]
        )
        for fu in file_uploads_data
    ]
    
    logger.info(
        "Retrieved issue by ticket_id successfully",
        user_id=user_id,
        ticket_id=ticket_id,
        issue_id=issue_data["id"]
    )
    
    return GetIssueByTicketIdResponse(
        id=issue_data["id"],
        ticket_id=issue_data["ticket_id"],
        type=issue_data["type"],
        heading=issue_data["heading"],
        description=issue_data["description"],
        webpage_url=issue_data["webpage_url"],
        status=issue_data["status"],
        created_by=created_by_user,
        closed_by=closed_by_user,
        closed_at=issue_data["closed_at"],
        created_at=issue_data["created_at"],
        updated_at=issue_data["updated_at"],
        file_uploads=file_uploads
    )


@router.patch(
    "/{issue_id}",
    response_model=IssueResponse,
    summary="Update issue (Admin only)",
    description="Update an issue's status. Only ADMIN and SUPER_ADMIN users can access this endpoint. When status changes to RESOLVED or DISCARDED, closed_by and closed_at are automatically set."
)
async def update_issue_endpoint(
    request: Request,
    response: Response,
    issue_id: str = Path(..., description="Issue ID (UUID)"),
    body: UpdateIssueRequest = ...,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update an issue's status. Admin only."""
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
    
    # Check admin role
    user_role = get_user_role_by_user_id(db, user_id)
    if user_role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PERMISSION_DENIED",
                "error_message": "Only ADMIN and SUPER_ADMIN users can access this endpoint"
            }
        )
    
    # Check if issue exists
    existing_issue = get_issue_by_id(db, issue_id)
    if not existing_issue:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "ISSUE_NOT_FOUND",
                "error_message": f"Issue with ID {issue_id} not found"
            }
        )
    
    # Determine closed_by and closed_at based on status
    new_status = body.status.value
    closed_by = None
    closed_at = None
    
    if new_status in (IssueStatus.RESOLVED.value, IssueStatus.DISCARDED.value):
        # Set closed_by and closed_at when closing an issue
        closed_by = user_id
        closed_at = datetime.now(timezone.utc)
    # For OPEN or WORK_IN_PROGRESS, closed_by and closed_at remain None (clearing them)
    
    # Update the issue
    updated_issue = update_issue(
        db,
        issue_id=issue_id,
        status=new_status,
        closed_by=closed_by,
        closed_at=closed_at
    )
    
    # Fetch file_uploads for the issue
    file_uploads_data = get_file_uploads_by_entity(db, "ISSUE", issue_id)
    file_uploads = [
        FileUploadResponse(
            id=fu["id"],
            file_name=fu["file_name"],
            file_type=fu["file_type"],
            entity_type=fu["entity_type"],
            entity_id=fu["entity_id"],
            s3_url=fu["s3_url"],
            metadata=fu["metadata"],
            created_at=fu["created_at"],
            updated_at=fu["updated_at"]
        )
        for fu in file_uploads_data
    ]
    
    logger.info(
        "Issue updated successfully",
        user_id=user_id,
        issue_id=issue_id,
        new_status=new_status,
        closed_by=closed_by,
        has_closed_at=closed_at is not None
    )
    
    return IssueResponse(
        id=updated_issue["id"],
        ticket_id=updated_issue["ticket_id"],
        type=updated_issue["type"],
        heading=updated_issue["heading"],
        description=updated_issue["description"],
        webpage_url=updated_issue["webpage_url"],
        status=updated_issue["status"],
        created_by=updated_issue["created_by"],
        closed_by=updated_issue["closed_by"],
        closed_at=updated_issue["closed_at"],
        created_at=updated_issue["created_at"],
        updated_at=updated_issue["updated_at"],
        file_uploads=file_uploads
    )


def _validate_file(file: UploadFile, max_size_bytes: int = 5 * 1024 * 1024) -> Tuple[str, bytes]:
    """
    Validate uploaded file (IMAGE or PDF).
    
    Args:
        file: UploadFile object
        max_size_bytes: Maximum file size in bytes (default 5MB)
        
    Returns:
        Tuple of (file_type, file_data)
        
    Raises:
        FileValidationError: If validation fails
    """
    if not file.filename:
        raise FileValidationError("No file uploaded")
    
    # Read file data
    file_data = file.file.read()
    file.file.seek(0)  # Reset file pointer
    
    # Check file size
    if len(file_data) > max_size_bytes:
        file_size_mb = len(file_data) / (1024 * 1024)
        max_size_mb = max_size_bytes / (1024 * 1024)
        raise FileValidationError(
            f"File size {file_size_mb:.2f}MB exceeds maximum allowed size of {max_size_mb}MB"
        )
    
    # Extract file extension
    file_extension = file.filename.lower().split('.')[-1] if '.' in file.filename else ''
    
    # Allowed image types
    allowed_image_types = ['jpg', 'jpeg', 'png', 'heic']
    # Allowed PDF types
    allowed_pdf_types = ['pdf']
    
    file_type = None
    
    # Validate image files
    if file_extension in allowed_image_types:
        try:
            # Validate that it's actually an image
            image = Image.open(io.BytesIO(file_data))
            image.verify()
            file_type = FileType.IMAGE.value
        except Exception as e:
            raise FileValidationError(f"Invalid image file: {str(e)}")
    
    # Validate PDF files
    elif file_extension in allowed_pdf_types:
        try:
            # Validate that it's actually a PDF
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_data))
            if len(pdf_reader.pages) == 0:
                raise FileValidationError("PDF file contains no pages")
            file_type = FileType.PDF.value
        except Exception as e:
            raise FileValidationError(f"Invalid PDF file: {str(e)}")
    
    else:
        raise FileValidationError(
            f"File type '{file_extension}' not allowed. Supported types: "
            f"Images: {', '.join(allowed_image_types)}; PDFs: {', '.join(allowed_pdf_types)}"
        )
    
    return file_type, file_data


@router.post(
    "/",
    response_model=IssueResponse,
    status_code=201,
    summary="Report an issue",
    description="Create a new issue report for the authenticated user with optional file uploads (IMAGE: jpg, jpeg, png, heic; PDF: pdf; max 5MB per file)"
)
async def report_issue(
    request: Request,
    response: Response,
    type: IssueType = Form(..., description="Issue type (mandatory)"),
    heading: Optional[str] = Form(default=None, description="Issue heading (optional, max 100 characters)"),
    description: str = Form(..., description="Issue description (mandatory)"),
    webpage_url: Optional[str] = Form(default=None, description="Webpage URL where the issue occurred (optional, max 1024 characters)"),
    files: Optional[List[UploadFile]] = File(default=None, description="Optional files to upload (IMAGE or PDF, max 5MB each)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Report a new issue for the authenticated user with optional file uploads."""
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
    if heading and len(heading) > 100:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "Heading length exceeds maximum of 100 characters"
            }
        )
    
    if webpage_url and len(webpage_url) > 1024:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_002",
                "error_message": "Webpage URL length exceeds maximum of 1024 characters"
            }
        )
    
    # Validate all files before creating issue
    validated_files = []
    max_file_size_bytes = 5 * 1024 * 1024  # 5MB
    
    # Handle optional files
    files_list = files if files is not None else []
    
    for file in files_list:
        file_type, file_data = _validate_file(file, max_file_size_bytes)
        validated_files.append({
            "file": file,
            "file_type": file_type,
            "file_data": file_data,
            "file_name": file.filename
        })
    
    # Create issue record first
    issue_data = create_issue(
        db, user_id, type.value, heading, description, webpage_url
    )
    issue_id = issue_data["id"]
    
    logger.info(
        "Created issue successfully",
        issue_id=issue_id,
        ticket_id=issue_data["ticket_id"],
        user_id=user_id,
        issue_type=type.value,
        file_count=len(validated_files)
    )
    
    # Upload files to S3 and create file_upload records
    file_uploads = []
    for validated_file in validated_files:
        try:
            # Upload to S3
            s3_url = s3_service.upload_file(
                file_data=validated_file["file_data"],
                file_name=validated_file["file_name"],
                file_type=validated_file["file_type"],
                issue_id=issue_id
            )
            
            # Create file_upload record
            file_upload_data = create_file_upload(
                db=db,
                file_name=validated_file["file_name"],
                file_type=validated_file["file_type"],
                entity_type="ISSUE",
                entity_id=issue_id,
                s3_url=s3_url,
                metadata=None
            )
            
            file_uploads.append(
                FileUploadResponse(
                    id=file_upload_data["id"],
                    file_name=file_upload_data["file_name"],
                    file_type=file_upload_data["file_type"],
                    entity_type=file_upload_data["entity_type"],
                    entity_id=file_upload_data["entity_id"],
                    s3_url=file_upload_data["s3_url"],
                    metadata=file_upload_data["metadata"],
                    created_at=file_upload_data["created_at"],
                    updated_at=file_upload_data["updated_at"]
                )
            )
            
            logger.info(
                "File uploaded and record created",
                file_upload_id=file_upload_data["id"],
                file_name=validated_file["file_name"],
                issue_id=issue_id
            )
            
        except Exception as e:
            logger.error(
                "Failed to upload file or create record",
                error=str(e),
                file_name=validated_file["file_name"],
                issue_id=issue_id
            )
            # Continue with other files even if one fails
            # In production, you might want to rollback the issue creation
    
    # Fetch all file_uploads for the issue (to ensure we return all, including any created outside this request)
    all_file_uploads_data = get_file_uploads_by_entity(db, "ISSUE", issue_id)
    all_file_uploads = [
        FileUploadResponse(
            id=fu["id"],
            file_name=fu["file_name"],
            file_type=fu["file_type"],
            entity_type=fu["entity_type"],
            entity_id=fu["entity_id"],
            s3_url=fu["s3_url"],
            metadata=fu["metadata"],
            created_at=fu["created_at"],
            updated_at=fu["updated_at"]
        )
        for fu in all_file_uploads_data
    ]
    
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
        updated_at=issue_data["updated_at"],
        file_uploads=all_file_uploads
    )

