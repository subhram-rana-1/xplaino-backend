"""API routes for PDF note management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session
import structlog

from app.models import (
    CreatePdfNoteRequest,
    UpdatePdfNoteRequest,
    PdfNoteResponse,
    GetPdfNotesResponse,
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    create_pdf_note,
    update_pdf_note_content,
    delete_pdf_note_by_id_and_user_id,
    get_pdf_notes_by_pdf_and_user,
    get_pdf_by_id_and_user_id,
    get_user_id_by_auth_vendor_id,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/pdf-note", tags=["PDF Note"])


@router.post(
    "",
    response_model=PdfNoteResponse,
    status_code=201,
    summary="Create a PDF note",
    description="Create a note on a PDF that belongs to the authenticated user.",
)
async def create_note(
    request: Request,
    response: Response,
    body: CreatePdfNoteRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Create a PDF note for the authenticated user."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to create a note",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    pdf = get_pdf_by_id_and_user_id(db, body.pdfId, user_id)
    if not pdf:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "PDF not found or does not belong to the user",
            },
        )

    note_data = create_pdf_note(
        db,
        user_id=user_id,
        pdf_id=body.pdfId,
        start_text=body.startText,
        end_text=body.endText,
        content=body.content,
    )

    logger.info(
        "PDF note created",
        note_id=note_data["id"],
        user_id=user_id,
        pdf_id=body.pdfId,
    )

    return PdfNoteResponse(
        id=note_data["id"],
        pdfId=note_data["pdf_id"],
        userId=note_data["user_id"],
        startText=note_data["start_text"],
        endText=note_data["end_text"],
        content=note_data["content"],
        createdAt=note_data["created_at"],
        updatedAt=note_data["updated_at"],
    )


@router.patch(
    "/{note_id}",
    response_model=PdfNoteResponse,
    summary="Update a PDF note",
    description="Update the content of a note owned by the authenticated user.",
)
async def update_note(
    request: Request,
    response: Response,
    note_id: str,
    body: UpdatePdfNoteRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Update a PDF note's content for the authenticated user."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to update a note",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    note_data = update_pdf_note_content(db, note_id=note_id, user_id=user_id, content=body.content)

    if not note_data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Note not found or does not belong to the user",
            },
        )

    logger.info(
        "PDF note updated",
        note_id=note_id,
        user_id=user_id,
    )

    return PdfNoteResponse(
        id=note_data["id"],
        pdfId=note_data["pdf_id"],
        userId=note_data["user_id"],
        startText=note_data["start_text"],
        endText=note_data["end_text"],
        content=note_data["content"],
        createdAt=note_data["created_at"],
        updatedAt=note_data["updated_at"],
    )


@router.delete(
    "/{note_id}",
    status_code=204,
    summary="Delete a PDF note",
    description="Delete a note by its ID. The note must belong to the authenticated user.",
)
async def delete_note(
    request: Request,
    response: Response,
    note_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Delete a PDF note owned by the authenticated user."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to delete a note",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    deleted = delete_pdf_note_by_id_and_user_id(db, note_id=note_id, user_id=user_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Note not found or does not belong to the user",
            },
        )

    logger.info(
        "PDF note deleted",
        note_id=note_id,
        user_id=user_id,
    )

    return Response(status_code=204)


@router.get(
    "/pdf/{pdf_id}",
    response_model=GetPdfNotesResponse,
    summary="Get all notes for a PDF",
    description="Return all notes created by the authenticated user on the given PDF.",
)
async def get_notes_by_pdf(
    request: Request,
    response: Response,
    pdf_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Get all notes for a PDF belonging to the authenticated user."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to retrieve notes",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    pdf = get_pdf_by_id_and_user_id(db, pdf_id, user_id)
    if not pdf:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "PDF not found or does not belong to the user",
            },
        )

    notes_data = get_pdf_notes_by_pdf_and_user(db, pdf_id=pdf_id, user_id=user_id)

    notes = [
        PdfNoteResponse(
            id=n["id"],
            pdfId=n["pdf_id"],
            userId=n["user_id"],
            startText=n["start_text"],
            endText=n["end_text"],
            content=n["content"],
            createdAt=n["created_at"],
            updatedAt=n["updated_at"],
        )
        for n in notes_data
    ]

    logger.info(
        "Returned PDF notes",
        user_id=user_id,
        pdf_id=pdf_id,
        count=len(notes),
    )

    return GetPdfNotesResponse(pdfId=pdf_id, notes=notes)
