"""API routes for PDF management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Path
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from typing import Optional
import structlog

from app.models import (
    PdfResponse,
    GetAllPdfsResponse,
    CreatePdfRequest,
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    create_pdf,
    get_pdfs_by_user_id,
    get_pdf_by_id_and_user_id,
    get_file_uploads_by_entity,
    delete_file_uploads_by_entity,
    delete_pdf_by_id_and_user_id,
)
from app.services.s3_service import s3_service

logger = structlog.get_logger()

router = APIRouter(prefix="/api/pdf", tags=["PDF"])


def _get_user_id_from_auth(auth_context: dict, db: Session) -> str:
    """Extract user_id from auth context; raise 401 if not authenticated."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={"error_code": "LOGIN_REQUIRED", "error_message": "Authentication required"}
        )
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "AUTH_001", "error_message": "Invalid session data"}
        )
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "AUTH_002", "error_message": "Missing auth vendor ID"}
        )
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={"error_code": "AUTH_003", "error_message": "User not found"}
        )
    return user_id


def _file_upload_to_response(fu: dict):
    """Build FileUploadResponse from file_upload row (with s3_url from s3_key)."""
    from app.models import FileUploadResponse
    s3_key = fu.get("s3_key")
    s3_url = s3_service.generate_presigned_get_url(s3_key) if s3_key else None
    return FileUploadResponse(
        id=fu["id"],
        file_name=fu["file_name"],
        file_type=fu["file_type"],
        entity_type=fu["entity_type"],
        entity_id=fu["entity_id"],
        s3_url=s3_url,
        metadata=fu.get("metadata"),
        created_at=fu["created_at"],
        updated_at=fu["updated_at"]
    )


@router.post(
    "/create-pdf",
    response_model=PdfResponse,
    status_code=201,
    summary="Create PDF record",
    description="Create a PDF record (metadata only). Returns the created PDF with empty file_uploads. Use file-upload API to attach files with entity_type=PDF and entity_id=pdf.id."
)
async def create_pdf_endpoint(
    request: Request,
    response: Response,
    body: CreatePdfRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a PDF record and return it."""
    user_id = _get_user_id_from_auth(auth_context, db)

    pdf_data = create_pdf(db=db, user_id=user_id, file_name=body.file_name)

    return PdfResponse(
        id=pdf_data["id"],
        file_name=pdf_data["file_name"],
        created_by=pdf_data["created_by"],
        created_at=pdf_data["created_at"],
        updated_at=pdf_data["updated_at"],
        file_uploads=[]
    )


@router.get(
    "",
    response_model=GetAllPdfsResponse,
    summary="Get all PDFs",
    description="Get all PDF records for the authenticated user with their file uploads (entity_type=PDF)."
)
async def get_all_pdfs_endpoint(
    request: Request,
    response: Response,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get all PDFs for the authenticated user with file_uploads per PDF."""
    user_id = _get_user_id_from_auth(auth_context, db)

    pdfs_data = get_pdfs_by_user_id(db, user_id)

    pdfs = []
    for pdf in pdfs_data:
        file_uploads_data = get_file_uploads_by_entity(db, "PDF", pdf["id"])
        file_uploads = [_file_upload_to_response(fu) for fu in file_uploads_data]
        pdfs.append(
            PdfResponse(
                id=pdf["id"],
                file_name=pdf["file_name"],
                created_by=pdf["created_by"],
                created_at=pdf["created_at"],
                updated_at=pdf["updated_at"],
                file_uploads=file_uploads
            )
        )

    logger.info(
        "Retrieved all PDFs successfully",
        user_id=user_id,
        pdf_count=len(pdfs)
    )

    return GetAllPdfsResponse(pdfs=pdfs)


@router.delete(
    "/{pdf_id}",
    status_code=204,
    summary="Delete a PDF",
    description="Delete a PDF by ID. Removes associated S3 objects and file_upload records (entity_type=PDF, entity_id=pdf_id), then deletes the PDF. Only the owner can delete their own PDFs."
)
async def delete_pdf_endpoint(
    request: Request,
    response: Response,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a PDF and its associated file uploads and S3 objects."""
    user_id = _get_user_id_from_auth(auth_context, db)

    pdf = get_pdf_by_id_and_user_id(db, pdf_id, user_id)
    if not pdf:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "PDF not found or does not belong to user"
            }
        )

    file_uploads = get_file_uploads_by_entity(db, "PDF", pdf_id)
    for fu in file_uploads:
        s3_key = fu.get("s3_key")
        if s3_key:
            try:
                s3_service.delete_object(s3_key)
            except Exception as e:
                logger.warning("Failed to delete S3 object, continuing", s3_key=s3_key, error=str(e))

    delete_file_uploads_by_entity(db, "PDF", pdf_id)
    deleted = delete_pdf_by_id_and_user_id(db, pdf_id, user_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "PDF not found or does not belong to user"
            }
        )

    logger.info("Deleted PDF successfully", pdf_id=pdf_id, user_id=user_id)
    return FastAPIResponse(status_code=204)
