"""API routes for web note management (browser extension notes on text selections)."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
import structlog

from app.database.connection import get_db
from app.models import (
    AnchorData,
    CreateWebNoteRequest,
    GetWebNotesResponse,
    UpdateWebNoteRequest,
    WebNoteResponse,
    WebNoteWriteResponse,
)
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    create_web_note,
    delete_web_note_by_id_and_user_id,
    get_user_id_by_auth_vendor_id,
    get_web_notes_by_user_and_url_hash,
    update_web_note_content,
)
from app.utils.url_utils import hash_url, normalize_url

logger = structlog.get_logger()

router = APIRouter(prefix="/api/web-notes", tags=["Web Notes"])

_EMPTY_NOTES = GetWebNotesResponse(notes=[])
_EMPTY_WRITE = WebNoteWriteResponse(note=None)


def _get_user_id(auth_context: dict, db: Session) -> str:
    """Return the authenticated user's UUID from auth context."""
    session_data = auth_context["session_data"]
    return get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])


def _row_to_response(row: dict) -> WebNoteResponse:
    """Convert a database row dict to a WebNoteResponse."""
    anchor_raw = row["anchor"]
    if isinstance(anchor_raw, str):
        anchor_dict = json.loads(anchor_raw)
    else:
        anchor_dict = anchor_raw

    return WebNoteResponse(
        id=row["id"],
        pageUrl=row["page_url"],
        selectedText=row["selected_text"],
        anchor=AnchorData(**anchor_dict),
        content=row["content"],
        createdAt=row["created_at"].isoformat() + "Z" if row["created_at"] else "",
        updatedAt=row["updated_at"].isoformat() + "Z" if row["updated_at"] else "",
    )


@router.get(
    "",
    response_model=GetWebNotesResponse,
    summary="Get web notes for a URL",
    description=(
        "Return all notes created by the authenticated user on a specific webpage. "
        "Unauthenticated requests return 200 with an empty list."
    ),
)
async def get_web_notes(
    request: Request,
    response: Response,
    url: str = Query(default=None, description="Raw page URL (URL-encoded)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Fetch all notes for the authenticated user on a given page URL."""
    if not auth_context.get("authenticated"):
        return _EMPTY_NOTES

    if not url or not url.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "VALIDATION_ERROR",
                "error_message": "url query param is required",
            },
        )

    user_id = _get_user_id(auth_context, db)
    normalized = normalize_url(url)
    url_hash = hash_url(normalized)

    rows = get_web_notes_by_user_and_url_hash(db, user_id, url_hash)
    notes = [_row_to_response(row) for row in rows]

    logger.info(
        "Web notes fetched",
        user_id=user_id,
        url_hash=url_hash,
        count=len(notes),
    )

    return GetWebNotesResponse(notes=notes)


@router.post(
    "",
    response_model=WebNoteWriteResponse,
    summary="Create a web note",
    description=(
        "Save a new note anchored to a text selection on a webpage. "
        "Unauthenticated requests return 200 with null note."
    ),
)
async def create_note(
    request: Request,
    response: Response,
    body: CreateWebNoteRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Create a web note for the authenticated user."""
    if not auth_context.get("authenticated"):
        return _EMPTY_WRITE

    user_id = _get_user_id(auth_context, db)
    normalized = normalize_url(body.pageUrl)
    url_hash = hash_url(normalized)
    anchor_json = body.anchor.model_dump_json()

    row = create_web_note(
        db,
        user_id=user_id,
        page_url=normalized,
        page_url_hash=url_hash,
        selected_text=body.selectedText,
        anchor=anchor_json,
        content=body.content,
    )

    logger.info(
        "Web note created",
        note_id=row["id"],
        user_id=user_id,
    )

    response.status_code = 201
    return WebNoteWriteResponse(note=_row_to_response(row))


@router.patch(
    "/{note_id}",
    response_model=WebNoteWriteResponse,
    summary="Update a web note",
    description=(
        "Update the content of an existing note. Only the owner can update it. "
        "Unauthenticated requests return 200 with null note."
    ),
)
async def update_note(
    request: Request,
    response: Response,
    note_id: str,
    body: UpdateWebNoteRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Update the content of a web note owned by the authenticated user."""
    if not auth_context.get("authenticated"):
        return _EMPTY_WRITE

    user_id = _get_user_id(auth_context, db)

    row = update_web_note_content(db, note_id=note_id, user_id=user_id, content=body.content)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Note not found",
            },
        )

    logger.info(
        "Web note updated",
        note_id=note_id,
        user_id=user_id,
    )

    return WebNoteWriteResponse(note=_row_to_response(row))


@router.delete(
    "/{note_id}",
    summary="Delete a web note",
    description=(
        "Delete a specific note. Only the owner can delete it. "
        "Returns 404 whether the note doesn't exist or belongs to another user. "
        "Unauthenticated requests return 200 with an empty body."
    ),
)
async def delete_note(
    request: Request,
    response: Response,
    note_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Delete a web note owned by the authenticated user."""
    if not auth_context.get("authenticated"):
        return Response(status_code=200)

    user_id = _get_user_id(auth_context, db)

    deleted = delete_web_note_by_id_and_user_id(db, note_id=note_id, user_id=user_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Note not found",
            },
        )

    logger.info(
        "Web note deleted",
        note_id=note_id,
        user_id=user_id,
    )

    return Response(status_code=204)
