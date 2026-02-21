"""API routes for file upload (presigned S3 upload and download URL by id)."""

import uuid
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Path
from sqlalchemy.orm import Session
import structlog
from pydantic import BaseModel, Field

from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    create_file_upload,
    get_file_upload_by_id,
    get_pdf_by_id_and_user_id,
)
from app.services.s3_service import s3_service

logger = structlog.get_logger()

router = APIRouter(prefix="/api/file-upload", tags=["File upload"])

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_FILE_NAME_LENGTH = 255  # Match CreatePdfRequest file_name limit
PRESIGNED_UPLOAD_EXPIRES_IN = 3600  # 1 hour
PRESIGNED_DOWNLOAD_EXPIRES_IN = 3600  # 1 hour


class PresignedUploadRequest(BaseModel):
    """Request body for getting a presigned upload URL."""
    file_name: str = Field(..., max_length=MAX_FILE_NAME_LENGTH, description="File name (max 255 characters)")
    file_type: str = Field(..., description="File type: IMAGE or PDF")
    entity_type: str = Field(..., description="Entity type: ISSUE or PDF")
    entity_id: str = Field(..., description="Entity ID (issue id or pdf id)")


class PresignedUploadResponse(BaseModel):
    """Response for presigned upload URL."""
    upload_url: str = Field(..., description="Presigned PUT URL for uploading the file")
    file_upload_id: str = Field(..., description="File upload record ID (use for download-url endpoint)")
    content_type: str = Field(..., description="Content-Type to use when PUTting the file to upload_url")
    expires_in: int = Field(..., description="URL expiry in seconds")
    max_file_size_bytes: int = Field(..., description="Maximum allowed file size in bytes (5 MB)")


class DownloadUrlResponse(BaseModel):
    """Response for download presigned URL by file_upload id."""
    download_url: str = Field(..., description="Presigned GET URL for downloading the file")
    expires_in: int = Field(..., description="URL expiry in seconds")


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


@router.post(
    "/presigned-upload",
    response_model=PresignedUploadResponse,
    summary="Get presigned upload URL",
    description="Returns a presigned S3 PUT URL and creates a file_upload record. Client must PUT the file to upload_url with the same Content-Type. Max file size 5 MB."
)
async def get_presigned_upload_url(
    request: Request,
    response: Response,
    body: PresignedUploadRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get a presigned S3 URL for client-side file upload and create file_upload record."""
    user_id = _get_user_id_from_auth(auth_context, db)

    # Validate file_type
    if body.file_type not in ("IMAGE", "PDF"):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INVALID_FILE_TYPE", "error_message": "file_type must be IMAGE or PDF"}
        )
    # Validate entity_type
    if body.entity_type not in ("ISSUE", "PDF"):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "INVALID_ENTITY_TYPE", "error_message": "entity_type must be ISSUE or PDF"}
        )

    # When entity_type is PDF, validate that the pdf exists and belongs to the user
    if body.entity_type == "PDF":
        pdf = get_pdf_by_id_and_user_id(db, body.entity_id, user_id)
        if not pdf:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "PDF_NOT_FOUND", "error_message": "PDF not found or access denied"}
            )

    # Generate file_upload id and s3_key before creating record
    file_upload_id = str(uuid.uuid4())
    s3_key = s3_service.generate_s3_key_for_upload(
        file_upload_id=file_upload_id,
        file_name=body.file_name,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        file_type=body.file_type
    )

    # Create file_upload record with the chosen id and s3_key
    create_file_upload(
        db=db,
        file_name=body.file_name,
        file_type=body.file_type,
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        s3_key=s3_key,
        metadata=None,
        file_upload_id=file_upload_id
    )

    content_type = s3_service._get_content_type(body.file_name, body.file_type)
    upload_url = s3_service.generate_presigned_put_url(
        s3_key=s3_key,
        content_type=content_type,
        expires_in=PRESIGNED_UPLOAD_EXPIRES_IN
    )

    return PresignedUploadResponse(
        upload_url=upload_url,
        file_upload_id=file_upload_id,
        content_type=content_type,
        expires_in=PRESIGNED_UPLOAD_EXPIRES_IN,
        max_file_size_bytes=MAX_FILE_SIZE_BYTES
    )


@router.get(
    "/download-url/{file_upload_id}",
    response_model=DownloadUrlResponse,
    summary="Get download presigned URL",
    description="Returns a fresh presigned S3 GET URL for the file by file_upload id."
)
async def get_download_url(
    request: Request,
    response: Response,
    file_upload_id: str = Path(..., description="File upload ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get a presigned download URL for a file_upload by id."""
    _get_user_id_from_auth(auth_context, db)

    record = get_file_upload_by_id(db, file_upload_id)
    if not record:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "FILE_UPLOAD_NOT_FOUND", "error_message": "File upload not found"}
        )

    s3_key = record.get("s3_key")
    if not s3_key:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "NO_S3_KEY", "error_message": "File upload has no S3 key (legacy record)"}
        )

    download_url = s3_service.generate_presigned_get_url(
        s3_key=s3_key,
        expires_in=PRESIGNED_DOWNLOAD_EXPIRES_IN
    )

    return DownloadUrlResponse(
        download_url=download_url,
        expires_in=PRESIGNED_DOWNLOAD_EXPIRES_IN
    )
