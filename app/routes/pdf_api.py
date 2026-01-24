"""API routes for PDF management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query, File, UploadFile, Path
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from typing import Optional
import structlog
import io
import PyPDF2

from app.models import (
    PdfResponse,
    PdfHtmlPageResponse,
    GetAllPdfsResponse,
    GetPdfHtmlPagesResponse
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    create_pdf,
    create_pdf_html_page,
    get_pdfs_by_user_id,
    get_pdf_by_id_and_user_id,
    get_pdf_html_pages_by_pdf_id,
    delete_pdf_by_id_and_user_id
)
from app.services.pdf_service import pdf_service, PdfProcessingError
from app.exceptions import FileValidationError

logger = structlog.get_logger()

router = APIRouter(prefix="/api/pdf", tags=["PDF"])


@router.post(
    "/to-html",
    response_model=PdfResponse,
    status_code=201,
    summary="Convert PDF to HTML",
    description="Convert a PDF file to HTML format with embedded images. Maximum file size: 5MB"
)
async def convert_pdf_to_html_endpoint(
    request: Request,
    response: Response,
    file: UploadFile = File(..., description="PDF file to convert (max 5MB)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Convert PDF to HTML and store in database."""
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

    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "FILE_SIZE_EXCEEDED",
                "error_message": "No file uploaded"
            }
        )

    # Check file size (max 5MB)
    max_file_size_bytes = 5 * 1024 * 1024  # 5MB
    file_data = await file.read()
    
    if len(file_data) > max_file_size_bytes:
        file_size_mb = len(file_data) / (1024 * 1024)
        max_size_mb = max_file_size_bytes / (1024 * 1024)
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "FILE_SIZE_EXCEEDED",
                "error_message": f"File size {file_size_mb:.2f}MB exceeds maximum allowed size of {max_size_mb}MB"
            }
        )

    # Validate PDF file type
    file_extension = file.filename.lower().split('.')[-1] if '.' in file.filename else ''
    if file_extension != 'pdf':
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_PDF",
                "error_message": f"File type '{file_extension}' not allowed. Only PDF files are supported."
            }
        )

    # Validate that it's actually a PDF
    try:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_data))
        if len(pdf_reader.pages) == 0:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "INVALID_PDF",
                    "error_message": "PDF file contains no pages"
                }
            )
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_PDF",
                "error_message": f"Invalid PDF file: {str(e)}"
            }
        )

    try:
        # Convert PDF to HTML using GPT-4 Vision
        html_pages = await pdf_service.convert_pdf_to_html(file_data)
        
        if not html_pages:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "INVALID_PDF",
                    "error_message": "Failed to convert PDF to HTML"
                }
            )

        # Create PDF record
        pdf_data = create_pdf(
            db=db,
            user_id=user_id,
            file_name=file.filename
        )
        pdf_id = pdf_data["id"]

        # Create PDF HTML page records
        for page_no, html_content in enumerate(html_pages, start=1):
            create_pdf_html_page(
                db=db,
                pdf_id=pdf_id,
                page_no=page_no,
                html_content=html_content
            )

        logger.info(
            "Converted PDF to HTML successfully",
            pdf_id=pdf_id,
            user_id=user_id,
            file_name=file.filename,
            total_pages=len(html_pages)
        )

        return PdfResponse(
            id=pdf_data["id"],
            file_name=pdf_data["file_name"],
            created_by=pdf_data["created_by"],
            created_at=pdf_data["created_at"],
            updated_at=pdf_data["updated_at"]
        )

    except PdfProcessingError as e:
        logger.error(
            "PDF processing error",
            error=str(e),
            file_name=file.filename,
            user_id=user_id
        )
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_PDF",
                "error_message": str(e)
            }
        )
    except Exception as e:
        logger.error(
            "Unexpected error during PDF conversion",
            error=str(e),
            file_name=file.filename,
            user_id=user_id
        )
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "INTERNAL_ERROR",
                "error_message": "An unexpected error occurred during PDF conversion"
            }
        )


@router.get(
    "",
    response_model=GetAllPdfsResponse,
    summary="Get all PDFs",
    description="Get all PDF records for the authenticated user"
)
async def get_all_pdfs_endpoint(
    request: Request,
    response: Response,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get all PDFs for the authenticated user."""
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

    # Get all PDFs for the user
    pdfs_data = get_pdfs_by_user_id(db, user_id)

    # Convert to response models
    pdfs = [
        PdfResponse(
            id=pdf["id"],
            file_name=pdf["file_name"],
            created_by=pdf["created_by"],
            created_at=pdf["created_at"],
            updated_at=pdf["updated_at"]
        )
        for pdf in pdfs_data
    ]

    logger.info(
        "Retrieved all PDFs successfully",
        user_id=user_id,
        pdf_count=len(pdfs)
    )

    return GetAllPdfsResponse(pdfs=pdfs)


@router.get(
    "/{pdf_id}/html",
    response_model=GetPdfHtmlPagesResponse,
    summary="Get PDF HTML pages",
    description="Get paginated HTML pages for a specific PDF. Only the owner can access their PDFs."
)
async def get_pdf_html_pages_endpoint(
    request: Request,
    response: Response,
    pdf_id: str,
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get paginated HTML pages for a PDF."""
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

    # Validate PDF exists and belongs to the user
    pdf = get_pdf_by_id_and_user_id(db, pdf_id, user_id)
    if not pdf:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "PDF not found or does not belong to user"
            }
        )

    # Get paginated HTML pages
    pages_data, total_count = get_pdf_html_pages_by_pdf_id(
        db, pdf_id, offset, limit
    )

    # Convert to response models
    pages = [
        PdfHtmlPageResponse(
            id=page["id"],
            page_no=page["page_no"],
            pdf_id=page["pdf_id"],
            html_content=page["html_content"],
            created_at=page["created_at"],
            updated_at=page["updated_at"]
        )
        for page in pages_data
    ]

    # Calculate has_next
    has_next = (offset + limit) < total_count

    logger.info(
        "Retrieved PDF HTML pages successfully",
        user_id=user_id,
        pdf_id=pdf_id,
        pages_count=len(pages),
        total_count=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )

    return GetPdfHtmlPagesResponse(
        pages=pages,
        total=total_count,
        offset=offset,
        limit=limit,
        has_next=has_next
    )


@router.delete(
    "/{pdf_id}",
    status_code=204,
    summary="Delete a PDF",
    description="Delete a PDF by ID. Only the owner can delete their own PDFs. All related PDF HTML pages will be automatically deleted due to CASCADE constraint."
)
async def delete_pdf_endpoint(
    request: Request,
    response: Response,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a PDF for the authenticated user."""
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

    # Verify PDF exists and belongs to the user
    pdf = get_pdf_by_id_and_user_id(db, pdf_id, user_id)
    if not pdf:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "PDF not found or does not belong to user"
            }
        )

    # Delete PDF (CASCADE constraints will automatically delete related pdf_html_page records)
    deleted = delete_pdf_by_id_and_user_id(db, pdf_id, user_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "PDF not found or does not belong to user"
            }
        )

    logger.info(
        "Deleted PDF successfully",
        pdf_id=pdf_id,
        user_id=user_id
    )

    return FastAPIResponse(status_code=204)
