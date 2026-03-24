"""API routes for PDF note comment management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session
import structlog

from app.models import (
    CreatePdfNoteCommentRequest,
    UpdatePdfNoteCommentRequest,
    PdfNoteCommentResponse,
    GetPdfNoteCommentsResponse,
    GetPdfCommentsResponse,
    NoteWithCommentsResponse,
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    create_pdf_note_comment,
    update_pdf_note_comment,
    get_comments_by_note_id,
    get_comments_by_pdf_id,
    get_user_id_by_auth_vendor_id,
    get_pdf_notes_by_pdf,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/pdf-note-comment", tags=["PDF Note Comment"])


def _build_comment_response(c: dict) -> PdfNoteCommentResponse:
    return PdfNoteCommentResponse(
        id=c["id"],
        pdfNoteId=c["pdf_note_id"],
        userId=c["user_id"],
        content=c["content"],
        userEmail=c["user_email"],
        userName=c["user_name"],
        createdAt=c["created_at"],
        updatedAt=c["updated_at"],
    )


@router.post(
    "",
    response_model=PdfNoteCommentResponse,
    status_code=201,
    summary="Create a PDF note comment",
    description="Create a comment on a PDF note. The authenticated user becomes the comment author.",
)
async def create_comment(
    request: Request,
    response: Response,
    body: CreatePdfNoteCommentRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to create a comment",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    comment_data = create_pdf_note_comment(
        db,
        pdf_note_id=body.pdfNoteId,
        user_id=user_id,
        content=body.content,
    )

    logger.info(
        "PDF note comment created",
        comment_id=comment_data["id"],
        user_id=user_id,
        pdf_note_id=body.pdfNoteId,
    )

    return _build_comment_response(comment_data)


@router.patch(
    "/{comment_id}",
    response_model=PdfNoteCommentResponse,
    summary="Update a PDF note comment",
    description="Update the content of a comment. Only the comment author can edit it.",
)
async def update_comment(
    request: Request,
    response: Response,
    comment_id: str,
    body: UpdatePdfNoteCommentRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to update a comment",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    comment_data = update_pdf_note_comment(
        db,
        comment_id=comment_id,
        user_id=user_id,
        content=body.content,
    )

    if not comment_data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Comment not found or does not belong to the user",
            },
        )

    logger.info(
        "PDF note comment updated",
        comment_id=comment_id,
        user_id=user_id,
    )

    return _build_comment_response(comment_data)


@router.get(
    "/note/{note_id}",
    response_model=GetPdfNoteCommentsResponse,
    summary="Get all comments for a PDF note",
    description="Return all comments for the given PDF note, ordered newest first. Each comment includes the author's email and name.",
)
async def get_comments_for_note(
    request: Request,
    response: Response,
    note_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to retrieve comments",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    comments_data = get_comments_by_note_id(db, note_id=note_id)

    comments = [_build_comment_response(c) for c in comments_data]

    logger.info(
        "Returned comments for PDF note",
        user_id=user_id,
        note_id=note_id,
        count=len(comments),
    )

    return GetPdfNoteCommentsResponse(pdfNoteId=note_id, comments=comments)


@router.get(
    "/pdf/{pdf_id}",
    response_model=GetPdfCommentsResponse,
    summary="Get all comments for a PDF grouped by note",
    description="Return all comments for every note in the given PDF, grouped by note ID, ordered newest first within each note.",
)
async def get_comments_for_pdf(
    request: Request,
    response: Response,
    pdf_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to retrieve comments",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    grouped = get_comments_by_pdf_id(db, pdf_id=pdf_id)

    all_note_ids = [n["id"] for n in get_pdf_notes_by_pdf(db, pdf_id=pdf_id)]

    notes = [
        NoteWithCommentsResponse(
            noteId=note_id,
            comments=[_build_comment_response(c) for c in grouped.get(note_id, [])],
        )
        for note_id in all_note_ids
    ]

    logger.info(
        "Returned comments for PDF",
        user_id=user_id,
        pdf_id=pdf_id,
        note_count=len(notes),
    )

    return GetPdfCommentsResponse(pdfId=pdf_id, notes=notes)
