"""API routes for PDF management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Path, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
import structlog

from app.models import (
    PdfResponse,
    GetAllPdfsResponse,
    CreatePdfRequest,
    CreatePdfCopyRequest,
    ShareResourceRequest,
    PdfShareResponse,
    SharedPdfItem,
    GetSharedPdfsResponse,
    GetShareeListResponse,
    ShareeItem,
    CreatePdfTextChatRequest,
    AppendPdfTextChatMessagesRequest,
    PdfTextChatResponse,
    GetAllPdfTextChatsResponse,
    PdfTextChatHistoryItemResponse,
    GetPdfTextChatHistoryResponse,
    CreatePdfTextChatResponse,
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    create_pdf,
    create_pdf_copy,
    get_pdfs_by_user_id,
    get_pdfs_by_folder_id,
    get_pdf_by_id,
    get_pdf_by_id_and_user_id,
    get_pdf_by_id_and_unauthenticated_user_id,
    check_pdf_access_for_user,
    update_pdf_access_level,
    get_file_uploads_by_entity,
    delete_file_uploads_by_entity,
    delete_pdf_by_id_and_user_id,
    get_folder_by_id_and_user_id,
    check_folder_access_for_user,
    share_pdf,
    unshare_pdf,
    get_pdfs_shared_with_email,
    get_pdf_sharee_list,
    get_user_info_with_email_by_user_id,
    create_pdf_text_chat,
    append_pdf_text_chat_messages,
    get_pdf_text_chats_by_pdf_id,
    get_pdf_text_chat_by_id,
    delete_pdf_text_chat,
    get_pdf_text_chat_history,
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


def _resolve_owner(auth_context: dict, db: Session) -> tuple:
    """Resolve owner from auth context. Returns (user_id, unauthenticated_user_id)."""
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
        return user_id, None
    return None, auth_context["unauthenticated_user_id"]


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
    if body.folder_id is not None:
        user_id = _get_user_id_from_auth(auth_context, db)
        folder = get_folder_by_id_and_user_id(db, body.folder_id, user_id)
        if not folder:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "FOLDER_NOT_FOUND", "error_message": "Folder not found or does not belong to user"}
            )
        unauthenticated_user_id = None
    else:
        user_id, unauthenticated_user_id = _resolve_owner(auth_context, db)

    pdf_data = create_pdf(
        db=db,
        file_name=body.file_name,
        user_id=user_id,
        unauthenticated_user_id=unauthenticated_user_id,
        folder_id=body.folder_id
    )

    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return PdfResponse(
        id=pdf_data["id"],
        file_name=pdf_data["file_name"],
        created_by=pdf_data["created_by"],
        unauthenticated_user_id=pdf_data["unauthenticated_user_id"],
        folder_id=pdf_data["folder_id"],
        parent_id=pdf_data.get("parent_id"),
        access_level=pdf_data["access_level"],
        created_at=pdf_data["created_at"],
        updated_at=pdf_data["updated_at"],
        file_uploads=[]
    )


@router.get(
    "",
    response_model=GetAllPdfsResponse,
    summary="Get all PDFs",
    description=(
        "Get all PDF records for the authenticated or unauthenticated user with their file uploads. "
        "If folder_id is provided, authentication is required and only PDFs in that folder are returned."
    )
)
async def get_all_pdfs_endpoint(
    request: Request,
    response: Response,
    folder_id: Optional[str] = Query(None, description="Filter PDFs by folder ID. Requires authentication; folder must belong to the user."),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get all PDFs for the authenticated or unauthenticated user with file_uploads per PDF."""
    unauthenticated_user_id = None
    if folder_id is not None:
        user_id = _get_user_id_from_auth(auth_context, db)
        user_info = get_user_info_with_email_by_user_id(db, user_id)
        user_email = user_info.get("email") if user_info else None
        folder = check_folder_access_for_user(db, folder_id, user_id, user_email or "")
        if not folder:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "NOT_FOUND", "error_message": "You don't have access to this folder"}
            )
        pdfs_data = get_pdfs_by_folder_id(db, folder_id)
    else:
        user_id, unauthenticated_user_id = _resolve_owner(auth_context, db)
        pdfs_data = get_pdfs_by_user_id(
            db,
            user_id=user_id,
            unauthenticated_user_id=unauthenticated_user_id,
            folder_id=None
        )

    pdfs = []
    for pdf in pdfs_data:
        file_uploads_data = get_file_uploads_by_entity(db, "PDF", pdf["id"])
        file_uploads = [_file_upload_to_response(fu) for fu in file_uploads_data]
        pdfs.append(
            PdfResponse(
                id=pdf["id"],
                file_name=pdf["file_name"],
                created_by=pdf["created_by"],
                unauthenticated_user_id=pdf["unauthenticated_user_id"],
                folder_id=pdf["folder_id"],
                parent_id=pdf.get("parent_id"),
                access_level=pdf["access_level"],
                created_at=pdf["created_at"],
                updated_at=pdf["updated_at"],
                file_uploads=file_uploads
            )
        )

    logger.info(
        "Retrieved all PDFs successfully",
        user_id=user_id,
        unauthenticated_user_id=unauthenticated_user_id,
        folder_id=folder_id,
        pdf_count=len(pdfs)
    )

    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return GetAllPdfsResponse(pdfs=pdfs)


@router.get(
    "/shared-with-me",
    response_model=GetSharedPdfsResponse,
    summary="Get PDFs shared with me",
    description="Get all PDFs that have been directly shared with the authenticated user. Does not include PDFs inside shared folders."
)
async def get_shared_pdfs_endpoint(
    request: Request,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Return all PDFs directly shared with the caller. Requires authentication."""
    user_id = _get_user_id_from_auth(auth_context, db)

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

    pdfs_data = get_pdfs_shared_with_email(db, email)

    logger.info(
        "Retrieved shared PDFs",
        user_id=user_id,
        email=email,
        count=len(pdfs_data),
    )

    return GetSharedPdfsResponse(
        pdfs=[
            SharedPdfItem(
                id=p["id"],
                file_name=p["file_name"],
                created_by=p["created_by"],
                folder_id=p["folder_id"],
                created_at=p["created_at"],
                updated_at=p["updated_at"],
                shared_at=p["shared_at"],
            )
            for p in pdfs_data
        ]
    )


@router.get(
    "/{pdf_id}",
    response_model=PdfResponse,
    summary="Get a PDF by ID",
    description="Get a single PDF record by ID with its file uploads (including presigned download URLs). Public PDFs are accessible without any authentication. For private PDFs, supports both authenticated (Authorization header) and unauthenticated (X-Unauthenticated-User-Id header) users — only the owner can access them."
)
async def get_pdf_by_id_endpoint(
    request: Request,
    response: Response,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get a single PDF by ID. Skips ownership validation for public PDFs."""
    pdf_data = get_pdf_by_id(db, pdf_id)

    if not pdf_data:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "PDF not found"}
        )

    if pdf_data.get("access_level") != "PUBLIC":
        user_id, unauthenticated_user_id = _resolve_owner(auth_context, db)

        if user_id:
            user_info = get_user_info_with_email_by_user_id(db, user_id)
            user_email = user_info.get("email") if user_info else None
            pdf_data = check_pdf_access_for_user(db, pdf_id, user_id, user_email or "")
        elif unauthenticated_user_id:
            pdf_data = get_pdf_by_id_and_unauthenticated_user_id(db, pdf_id, unauthenticated_user_id)
        else:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "NOT_FOUND", "error_message": "PDF not found"}
            )

        if not pdf_data:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "NOT_FOUND", "error_message": "PDF not found or does not belong to user"}
            )

    file_uploads_data = get_file_uploads_by_entity(db, "PDF", pdf_id)
    file_uploads = [_file_upload_to_response(fu) for fu in file_uploads_data]

    logger.info(
        "Retrieved PDF by ID successfully",
        pdf_id=pdf_id,
        access_level=pdf_data.get("access_level")
    )

    return PdfResponse(
        id=pdf_data["id"],
        file_name=pdf_data["file_name"],
        created_by=pdf_data.get("created_by"),
        unauthenticated_user_id=pdf_data.get("unauthenticated_user_id"),
        folder_id=pdf_data.get("folder_id"),
        parent_id=pdf_data.get("parent_id"),
        access_level=pdf_data["access_level"],
        created_at=pdf_data["created_at"],
        updated_at=pdf_data["updated_at"],
        file_uploads=file_uploads
    )


@router.post(
    "/{pdf_id}/make-public",
    response_model=PdfResponse,
    summary="Make a PDF public",
    description="Mark a PDF as publicly accessible. Only the authenticated owner can perform this action. Once public, the PDF can be retrieved by anyone without authentication."
)
async def make_pdf_public_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Set access_level to PUBLIC for the given PDF. Only the owner can do this."""
    user_id = _get_user_id_from_auth(auth_context, db)

    pdf_data = update_pdf_access_level(db, pdf_id, user_id, "PUBLIC")
    if not pdf_data:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "PDF not found or does not belong to user"}
        )

    file_uploads_data = get_file_uploads_by_entity(db, "PDF", pdf_id)
    file_uploads = [_file_upload_to_response(fu) for fu in file_uploads_data]

    logger.info(
        "PDF marked as public",
        pdf_id=pdf_id,
        user_id=user_id
    )

    return PdfResponse(
        id=pdf_data["id"],
        file_name=pdf_data["file_name"],
        created_by=pdf_data.get("created_by"),
        unauthenticated_user_id=pdf_data.get("unauthenticated_user_id"),
        folder_id=pdf_data.get("folder_id"),
        parent_id=pdf_data.get("parent_id"),
        access_level=pdf_data["access_level"],
        created_at=pdf_data["created_at"],
        updated_at=pdf_data["updated_at"],
        file_uploads=file_uploads
    )


@router.post(
    "/{pdf_id}/make-private",
    response_model=PdfResponse,
    summary="Make a PDF private",
    description="Mark a PDF as private. Only the authenticated owner can perform this action. Once private, the PDF can only be retrieved by the owner or users it has been shared with."
)
async def make_pdf_private_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Set access_level to PRIVATE for the given PDF. Only the owner can do this."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={"error_code": "LOGIN_REQUIRED_TO_MAKE_PRIVATE", "error_message": "You must be logged in to make a PDF private"}
        )
    user_id = _get_user_id_from_auth(auth_context, db)

    pdf_data = update_pdf_access_level(db, pdf_id, user_id, "PRIVATE")
    if not pdf_data:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "PDF not found or does not belong to user"}
        )

    file_uploads_data = get_file_uploads_by_entity(db, "PDF", pdf_id)
    file_uploads = [_file_upload_to_response(fu) for fu in file_uploads_data]

    logger.info(
        "PDF marked as private",
        pdf_id=pdf_id,
        user_id=user_id
    )

    return PdfResponse(
        id=pdf_data["id"],
        file_name=pdf_data["file_name"],
        created_by=pdf_data.get("created_by"),
        unauthenticated_user_id=pdf_data.get("unauthenticated_user_id"),
        folder_id=pdf_data.get("folder_id"),
        parent_id=pdf_data.get("parent_id"),
        access_level=pdf_data["access_level"],
        created_at=pdf_data["created_at"],
        updated_at=pdf_data["updated_at"],
        file_uploads=file_uploads
    )


@router.post(
    "/{pdf_id}/create-copy",
    response_model=PdfResponse,
    status_code=201,
    summary="Create a copy of a public PDF",
    description=(
        "Create a private copy of a PUBLIC PDF under the authenticated user's ownership. "
        "The copy will have file_name='copy - {original_name}', access_level=PRIVATE, and parent_id set to the source PDF's ID. "
        "A corresponding file_upload record (with the same s3_key and metadata as the source) is created atomically in the same transaction. "
        "Only PUBLIC PDFs can be copied via this endpoint."
    )
)
async def create_pdf_copy_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="Source PDF ID (UUID). Must be a PUBLIC PDF."),
    body: CreatePdfCopyRequest = None,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a private copy of a PUBLIC PDF. Requires authentication."""
    user_id = _get_user_id_from_auth(auth_context, db)

    source_pdf = get_pdf_by_id(db, pdf_id)
    if not source_pdf:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "PDF not found"}
        )

    if source_pdf.get("access_level") != "PUBLIC":
        raise HTTPException(
            status_code=403,
            detail={"error_code": "PDF_NOT_PUBLIC", "error_message": "Only PUBLIC PDFs can be copied"}
        )

    folder_id = body.folder_id if body else None
    if folder_id is not None:
        folder = get_folder_by_id_and_user_id(db, folder_id, user_id)
        if not folder:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "FOLDER_NOT_FOUND", "error_message": "Folder not found or does not belong to user"}
            )

    source_file_uploads = get_file_uploads_by_entity(db, "PDF", pdf_id)
    source_file_upload = source_file_uploads[0] if source_file_uploads else None

    if not source_file_upload:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "NO_FILE_UPLOAD", "error_message": "Source PDF has no file upload record to copy"}
        )

    new_pdf_data, new_file_upload_data = create_pdf_copy(
        db=db,
        source_pdf_id=pdf_id,
        source_file_name=source_pdf["file_name"],
        source_file_upload=source_file_upload,
        user_id=user_id,
        folder_id=folder_id
    )

    logger.info(
        "Created PDF copy successfully",
        source_pdf_id=pdf_id,
        new_pdf_id=new_pdf_data["id"],
        user_id=user_id,
        folder_id=folder_id
    )

    return PdfResponse(
        id=new_pdf_data["id"],
        file_name=new_pdf_data["file_name"],
        created_by=new_pdf_data.get("created_by"),
        unauthenticated_user_id=new_pdf_data.get("unauthenticated_user_id"),
        folder_id=new_pdf_data.get("folder_id"),
        parent_id=new_pdf_data.get("parent_id"),
        access_level=new_pdf_data["access_level"],
        created_at=new_pdf_data["created_at"],
        updated_at=new_pdf_data["updated_at"],
        file_uploads=[_file_upload_to_response(new_file_upload_data)]
    )


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


@router.post(
    "/{pdf_id}/share",
    response_model=PdfShareResponse,
    status_code=201,
    summary="Share a PDF",
    description="Share a PDF with another user by their email address. Only the PDF owner can share it."
)
async def share_pdf_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    body: ShareResourceRequest = None,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Share a PDF with another user by email. Requires authentication."""
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

    try:
        share_data = share_pdf(db, pdf_id, body.email)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "ALREADY_SHARED",
                "error_message": "PDF is already shared with this email"
            }
        )

    logger.info(
        "Shared PDF successfully",
        pdf_id=pdf_id,
        user_id=user_id,
        shared_to_email=body.email,
    )

    return PdfShareResponse(
        id=share_data["id"],
        pdf_id=share_data["pdf_id"],
        shared_to_email=share_data["shared_to_email"],
        created_at=share_data["created_at"],
    )


@router.delete(
    "/{pdf_id}/share",
    status_code=204,
    summary="Unshare a PDF",
    description="Remove a share for a PDF with a specific user by their email address. Only the PDF owner can unshare it."
)
async def unshare_pdf_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    body: ShareResourceRequest = None,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Unshare a PDF from a user by email. Requires authentication."""
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

    deleted = unshare_pdf(db, pdf_id, body.email)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "SHARE_NOT_FOUND",
                "error_message": "Share record not found for this PDF and email"
            }
        )

    logger.info(
        "Unshared PDF successfully",
        pdf_id=pdf_id,
        user_id=user_id,
        shared_to_email=body.email,
    )

    return FastAPIResponse(status_code=204)


@router.get(
    "/{pdf_id}/share",
    response_model=GetShareeListResponse,
    summary="Get sharee list for a PDF",
    description="Get all email addresses the owner has shared this PDF with. Only the PDF owner can view this list."
)
async def get_pdf_sharee_list_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Return all recipients this PDF has been shared with. Requires authentication and ownership."""
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

    sharees_data = get_pdf_sharee_list(db, pdf_id)

    logger.info(
        "Retrieved PDF sharee list",
        pdf_id=pdf_id,
        user_id=user_id,
        count=len(sharees_data),
    )

    return GetShareeListResponse(
        sharees=[
            ShareeItem(email=s["email"], shared_at=s["shared_at"])
            for s in sharees_data
        ]
    )


def _assert_pdf_access(db: Session, pdf_id: str, user_id: str) -> None:
    """Raise 404 if the user neither owns nor has been shared the PDF."""
    user_info = get_user_info_with_email_by_user_id(db, user_id)
    user_email = user_info.get("email", "") if user_info else ""
    pdf_data = check_pdf_access_for_user(db, pdf_id, user_id, user_email)
    if not pdf_data:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "PDF not found or access denied"}
        )


def _chat_to_response(c: dict) -> PdfTextChatResponse:
    return PdfTextChatResponse(
        id=c["id"],
        pdf_id=c["pdf_id"],
        user_id=c["user_id"],
        start_text_pdf_page_number=c["start_text_pdf_page_number"],
        end_text_pdf_page_number=c["end_text_pdf_page_number"],
        start_text=c["start_text"],
        end_text=c["end_text"],
        created_at=c["created_at"],
        updated_at=c["updated_at"],
    )


def _msg_to_response(m: dict) -> PdfTextChatHistoryItemResponse:
    return PdfTextChatHistoryItemResponse(
        id=m["id"],
        pdf_text_chat_id=m["pdf_text_chat_id"],
        who=m["who"],
        content=m["content"],
        created_at=m["created_at"],
    )


@router.post(
    "/{pdf_id}/text-chat",
    response_model=CreatePdfTextChatResponse,
    status_code=201,
    summary="Create a PDF text chat conversation",
    description=(
        "Create a pdf_text_chat record anchored to a text selection on a PDF page range. "
        "An optional ordered batch of initial messages (USER or SYSTEM) may be included and will be "
        "inserted in the given order. "
        "The caller must be the PDF owner or a sharee."
    ),
)
async def create_pdf_text_chat_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    body: CreatePdfTextChatRequest = None,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Create a new pdf_text_chat conversation (with optional initial messages)."""
    user_id = _get_user_id_from_auth(auth_context, db)
    _assert_pdf_access(db, pdf_id, user_id)

    chats_payload = (
        [{"who": msg.who.value, "content": msg.content} for msg in body.chats]
        if body and body.chats
        else None
    )

    result = create_pdf_text_chat(
        db=db,
        pdf_id=pdf_id,
        user_id=user_id,
        start_text_pdf_page_number=body.start_text_pdf_page_number,
        end_text_pdf_page_number=body.end_text_pdf_page_number,
        start_text=body.start_text,
        end_text=body.end_text,
        chats=chats_payload,
    )

    logger.info(
        "Created PDF text chat",
        pdf_id=pdf_id,
        user_id=user_id,
        chat_id=result["chat"]["id"],
        message_count=len(result["messages"]),
    )

    return CreatePdfTextChatResponse(
        chat=_chat_to_response(result["chat"]),
        messages=[_msg_to_response(m) for m in result["messages"]],
    )


@router.post(
    "/{pdf_id}/text-chat/{text_chat_id}/messages",
    response_model=List[PdfTextChatHistoryItemResponse],
    status_code=201,
    summary="Append messages to a PDF text chat conversation",
    description=(
        "Append an ordered batch of messages (USER or SYSTEM) to an existing pdf_text_chat conversation. "
        "Messages are inserted in the exact order supplied. "
        "Only the user who created the conversation may append messages."
    ),
)
async def append_pdf_text_chat_messages_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    text_chat_id: str = Path(..., description="Text chat conversation ID (UUID)"),
    body: AppendPdfTextChatMessagesRequest = None,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Append a batch of messages to an existing conversation. Only the conversation creator may do this."""
    user_id = _get_user_id_from_auth(auth_context, db)

    chat = get_pdf_text_chat_by_id(db, text_chat_id)
    if not chat or chat["pdf_id"] != pdf_id:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "Text chat not found"}
        )
    if chat["user_id"] != user_id:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "FORBIDDEN", "error_message": "Only the conversation creator may append messages"}
        )

    chats_payload = [{"who": msg.who.value, "content": msg.content} for msg in body.chats]
    messages = append_pdf_text_chat_messages(db, pdf_text_chat_id=text_chat_id, chats=chats_payload)

    logger.info(
        "Appended messages to PDF text chat",
        pdf_id=pdf_id,
        text_chat_id=text_chat_id,
        user_id=user_id,
        appended_count=len(messages),
    )

    return [_msg_to_response(m) for m in messages]


@router.get(
    "/{pdf_id}/text-chat",
    response_model=GetAllPdfTextChatsResponse,
    summary="Get all text chat conversations for a PDF",
    description=(
        "Return all pdf_text_chat records for a PDF (without message history). "
        "Accessible to the PDF owner and any user the PDF has been shared with."
    ),
)
async def get_pdf_text_chats_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """List all conversations for a PDF. Public PDFs are accessible without authentication."""
    pdf_data = get_pdf_by_id(db, pdf_id)
    if not pdf_data:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "PDF not found"}
        )

    if pdf_data.get("access_level") != "PUBLIC":
        user_id = _get_user_id_from_auth(auth_context, db)
        _assert_pdf_access(db, pdf_id, user_id)
        log_user_id = user_id
    else:
        log_user_id = None

    chats_data = get_pdf_text_chats_by_pdf_id(db, pdf_id=pdf_id)

    logger.info(
        "Retrieved PDF text chats",
        pdf_id=pdf_id,
        user_id=log_user_id,
        count=len(chats_data),
    )

    return GetAllPdfTextChatsResponse(
        pdf_id=pdf_id,
        chats=[_chat_to_response(c) for c in chats_data],
    )


@router.delete(
    "/{pdf_id}/text-chat/{text_chat_id}",
    status_code=204,
    summary="Delete a PDF text chat conversation",
    description=(
        "Delete a pdf_text_chat record and all its associated messages. "
        "Only the user who created the conversation may delete it."
    ),
)
async def delete_pdf_text_chat_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    text_chat_id: str = Path(..., description="Text chat conversation ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Delete a conversation and all its messages. Only the conversation creator may do this."""
    user_id = _get_user_id_from_auth(auth_context, db)

    chat = get_pdf_text_chat_by_id(db, text_chat_id)
    if not chat or chat["pdf_id"] != pdf_id:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "Text chat not found"}
        )
    if chat["user_id"] != user_id:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "FORBIDDEN", "error_message": "Only the conversation creator may delete it"}
        )

    delete_pdf_text_chat(db, text_chat_id=text_chat_id, user_id=user_id)

    logger.info(
        "Deleted PDF text chat",
        pdf_id=pdf_id,
        text_chat_id=text_chat_id,
        user_id=user_id,
    )

    return FastAPIResponse(status_code=204)


@router.get(
    "/{pdf_id}/text-chat/{text_chat_id}/messages",
    response_model=GetPdfTextChatHistoryResponse,
    summary="Get paginated message history for a PDF text chat",
    description=(
        "Return messages for a pdf_text_chat conversation in descending created_at order "
        "(most recent first). "
        "Accessible to the PDF owner and any user the PDF has been shared with."
    ),
)
async def get_pdf_text_chat_history_endpoint(
    request: Request,
    pdf_id: str = Path(..., description="PDF ID (UUID)"),
    text_chat_id: str = Path(..., description="Text chat conversation ID (UUID)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=200, description="Pagination limit (max 200)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Fetch paginated messages for a conversation. Public PDFs are accessible without authentication."""
    pdf_data = get_pdf_by_id(db, pdf_id)
    if not pdf_data:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "PDF not found"}
        )

    if pdf_data.get("access_level") != "PUBLIC":
        user_id = _get_user_id_from_auth(auth_context, db)
        _assert_pdf_access(db, pdf_id, user_id)
        log_user_id = user_id
    else:
        log_user_id = None

    chat = get_pdf_text_chat_by_id(db, text_chat_id)
    if not chat or chat["pdf_id"] != pdf_id:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "NOT_FOUND", "error_message": "Text chat not found"}
        )

    history = get_pdf_text_chat_history(db, text_chat_id=text_chat_id, offset=offset, limit=limit)

    logger.info(
        "Retrieved PDF text chat history",
        pdf_id=pdf_id,
        text_chat_id=text_chat_id,
        user_id=log_user_id,
        total=history["total"],
        returned=len(history["messages"]),
    )

    return GetPdfTextChatHistoryResponse(
        pdf_text_chat_id=text_chat_id,
        messages=[_msg_to_response(m) for m in history["messages"]],
        total=history["total"],
        offset=history["offset"],
        limit=history["limit"],
    )
