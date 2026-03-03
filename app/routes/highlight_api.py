"""API routes for PDF highlight management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from sqlalchemy.orm import Session
import structlog

from app.models import (
    CreatePdfHighlightRequest,
    GetAllHighlightColoursResponse,
    GetPdfHighlightsResponse,
    HighlightColourResponse,
    PdfHighlightResponse,
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_all_highlight_colours,
    get_highlight_colour_by_id,
    create_pdf_highlight,
    get_pdf_highlights_by_pdf_and_user,
    delete_pdf_highlight_by_id_and_user_id,
    get_pdf_by_id_and_user_id,
    get_user_id_by_auth_vendor_id,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/highlight", tags=["Highlight"])


@router.get(
    "/colours",
    response_model=GetAllHighlightColoursResponse,
    summary="Get all highlight colours",
    description="Returns all available highlight colours. No authentication required.",
)
async def get_highlight_colours(db: Session = Depends(get_db)):
    """Return all pre-seeded highlight colour options."""
    colours_data = get_all_highlight_colours(db)
    colours = [
        HighlightColourResponse(id=c["id"], hexcode=c["hexcode"])
        for c in colours_data
    ]
    logger.info("Returned highlight colours", count=len(colours))
    return GetAllHighlightColoursResponse(colours=colours)


@router.post(
    "/pdf",
    response_model=PdfHighlightResponse,
    status_code=201,
    summary="Create a PDF highlight",
    description="Create a highlight on a PDF that belongs to the authenticated user.",
)
async def create_highlight(
    request: Request,
    response: Response,
    body: CreatePdfHighlightRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Create a PDF highlight for the authenticated user."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to create a highlight",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    # Validate highlight colour exists
    colour = get_highlight_colour_by_id(db, body.highlightColourId)
    if not colour:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Highlight colour not found",
            },
        )

    # Validate PDF exists and belongs to this user
    pdf = get_pdf_by_id_and_user_id(db, body.pdfId, user_id)
    if not pdf:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "PDF not found or does not belong to the user",
            },
        )

    highlight_data = create_pdf_highlight(
        db,
        user_id=user_id,
        highlight_colour_id=body.highlightColourId,
        pdf_id=body.pdfId,
        start_text=body.startText,
        end_text=body.endText,
    )

    logger.info(
        "PDF highlight created",
        highlight_id=highlight_data["id"],
        user_id=user_id,
        pdf_id=body.pdfId,
    )

    return PdfHighlightResponse(
        id=highlight_data["id"],
        highlightColourId=highlight_data["highlight_colour_id"],
        startText=highlight_data["start_text"],
        endText=highlight_data["end_text"],
    )


@router.get(
    "/pdf/{pdf_id}",
    response_model=GetPdfHighlightsResponse,
    summary="Get highlights for a PDF",
    description="Return paginated highlights created by the authenticated user on the given PDF.",
)
async def get_pdf_highlights(
    request: Request,
    response: Response,
    pdf_id: str,
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Get paginated highlights for a PDF belonging to the authenticated user."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to retrieve highlights",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    # Validate PDF exists and belongs to this user
    pdf = get_pdf_by_id_and_user_id(db, pdf_id, user_id)
    if not pdf:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "PDF not found or does not belong to the user",
            },
        )

    highlights_data, total_count = get_pdf_highlights_by_pdf_and_user(
        db, pdf_id=pdf_id, user_id=user_id, offset=offset, limit=limit
    )

    highlights = [
        PdfHighlightResponse(
            id=h["id"],
            highlightColourId=h["highlight_colour_id"],
            startText=h["start_text"],
            endText=h["end_text"],
        )
        for h in highlights_data
    ]

    logger.info(
        "Returned PDF highlights",
        user_id=user_id,
        pdf_id=pdf_id,
        count=len(highlights),
        total=total_count,
        offset=offset,
        limit=limit,
    )

    return GetPdfHighlightsResponse(
        pdfId=pdf_id,
        highlights=highlights,
        total=total_count,
        offset=offset,
        limit=limit,
    )


@router.delete(
    "/pdf/{highlight_id}",
    status_code=204,
    summary="Delete a PDF highlight",
    description="Delete a highlight by its ID. The highlight must belong to the authenticated user.",
)
async def delete_highlight(
    request: Request,
    response: Response,
    highlight_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Delete a PDF highlight owned by the authenticated user."""
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to delete a highlight",
            },
        )

    session_data = auth_context["session_data"]
    user_id = get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])

    deleted = delete_pdf_highlight_by_id_and_user_id(db, highlight_id, user_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Highlight not found or does not belong to the user",
            },
        )

    logger.info(
        "PDF highlight deleted",
        highlight_id=highlight_id,
        user_id=user_id,
    )

    return Response(status_code=204)
