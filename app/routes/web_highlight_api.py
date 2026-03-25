"""API routes for web highlight management (browser extension text highlights)."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
import structlog

from app.database.connection import get_db
from app.models import (
    AnchorData,
    CreateWebHighlightRequest,
    CreatedWebHighlightResponse,
    GetWebHighlightsResponse,
    HighlightedPageSummary,
    PaginatedHighlightedPagesResponse,
    WebHighlightResponse,
)
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    create_web_highlight,
    delete_web_highlight_by_id_and_user_id,
    get_highlighted_pages_by_user,
    get_user_id_by_auth_vendor_id,
    get_web_highlights_by_user_and_url_hash,
)
from app.utils.url_utils import hash_url, normalize_url

logger = structlog.get_logger()

router = APIRouter(prefix="/api/web-highlights", tags=["Web Highlights"])

_EMPTY_HIGHLIGHTS = GetWebHighlightsResponse(highlights=[])


def _require_user_id(auth_context: dict, db: Session) -> str:
    """
    Extract and return the authenticated user's UUID.
    Raises HTTP 401 LOGIN_REQUIRED if the request is not authenticated.
    """
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "errorCode": "LOGIN_REQUIRED",
                "message": "Please login",
            },
        )
    session_data = auth_context["session_data"]
    return get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])


def _row_to_response(row: dict) -> WebHighlightResponse:
    """Convert a database row dict to a WebHighlightResponse."""
    anchor_raw = row["anchor"]
    if isinstance(anchor_raw, str):
        anchor_dict = json.loads(anchor_raw)
    else:
        anchor_dict = anchor_raw

    return WebHighlightResponse(
        id=row["id"],
        pageUrl=row["page_url"],
        selectedText=row["selected_text"],
        anchor=AnchorData(**anchor_dict),
        color=row["color"],
        note=row["note"],
        createdAt=row["created_at"].isoformat() + "Z" if row["created_at"] else "",
        updatedAt=row["updated_at"].isoformat() + "Z" if row["updated_at"] else "",
    )


@router.get(
    "/pages",
    response_model=PaginatedHighlightedPagesResponse,
    summary="Get paginated list of highlighted pages (dashboard)",
    description=(
        "Returns a paginated list of distinct webpages on which the authenticated user has created highlights, "
        "ordered by most recent highlight activity. Intended for the user's personal dashboard. "
        "Requires authentication."
    ),
)
def get_highlighted_pages_endpoint(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50, description="Number of pages to return (1–50)"),
    offset: int = Query(default=0, ge=0, description="Zero-based offset for pagination"),
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={"error_code": "AUTH_001", "error_message": "Authentication required"},
        )

    user_id = get_user_id_by_auth_vendor_id(db, auth_context["session_data"]["auth_vendor_id"])

    pages_raw, total = get_highlighted_pages_by_user(db, user_id=user_id, limit=limit, offset=offset)

    pages = [
        HighlightedPageSummary(
            pageUrl=row["page_url"],
            pageUrlHash=row["page_url_hash"],
            highlightCount=row["highlight_count"],
            lastHighlightedAt=(
                row["last_highlighted_at"].isoformat()
                if hasattr(row["last_highlighted_at"], "isoformat")
                else str(row["last_highlighted_at"])
            ),
        )
        for row in pages_raw
    ]

    return PaginatedHighlightedPagesResponse(
        pages=pages,
        total=total,
        limit=limit,
        offset=offset,
        hasMore=(offset + len(pages)) < total,
    )


@router.get(
    "",
    response_model=GetWebHighlightsResponse,
    summary="Get web highlights for a URL",
    description=(
        "Return all highlights created by the authenticated user on a specific webpage. "
        "If the request is unauthenticated, returns 200 with an empty list."
    ),
)
async def get_web_highlights(
    request: Request,
    response: Response,
    url: str = Query(default=None, description="Raw page URL (URL-encoded)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Fetch highlights for the authenticated user on a given page URL."""
    if not auth_context.get("authenticated"):
        return _EMPTY_HIGHLIGHTS

    if not url or not url.strip():
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "VALIDATION_ERROR",
                "error_message": "url query param is required",
            },
        )

    user_id = get_user_id_by_auth_vendor_id(
        db, auth_context["session_data"]["auth_vendor_id"]
    )

    normalized = normalize_url(url)
    url_hash = hash_url(normalized)

    rows = get_web_highlights_by_user_and_url_hash(db, user_id, url_hash)

    highlights = [_row_to_response(row) for row in rows]

    logger.info(
        "Web highlights fetched",
        user_id=user_id,
        url_hash=url_hash,
        count=len(highlights),
    )

    return GetWebHighlightsResponse(highlights=highlights)


@router.post(
    "",
    response_model=CreatedWebHighlightResponse,
    status_code=201,
    summary="Create a web highlight",
    description="Save a new text highlight created by the authenticated user on a webpage.",
)
async def create_highlight(
    request: Request,
    response: Response,
    body: CreateWebHighlightRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Create a web highlight for the authenticated user."""
    user_id = _require_user_id(auth_context, db)

    normalized = normalize_url(body.pageUrl)
    url_hash = hash_url(normalized)

    anchor_json = body.anchor.model_dump_json()

    row = create_web_highlight(
        db,
        user_id=user_id,
        page_url=normalized,
        page_url_hash=url_hash,
        selected_text=body.selectedText,
        anchor=anchor_json,
        color=body.color,
        note=body.note,
    )

    logger.info(
        "Web highlight created",
        highlight_id=row["id"],
        user_id=user_id,
    )

    return CreatedWebHighlightResponse(highlight=_row_to_response(row))


@router.delete(
    "/{highlight_id}",
    status_code=204,
    summary="Delete a web highlight",
    description=(
        "Delete a specific highlight. Only the owner can delete it. "
        "Returns 404 whether the highlight doesn't exist or belongs to another user."
    ),
)
async def delete_highlight(
    request: Request,
    response: Response,
    highlight_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    """Delete a web highlight owned by the authenticated user."""
    user_id = _require_user_id(auth_context, db)

    deleted = delete_web_highlight_by_id_and_user_id(db, highlight_id, user_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Highlight not found",
            },
        )

    logger.info(
        "Web highlight deleted",
        highlight_id=highlight_id,
        user_id=user_id,
    )

    return Response(status_code=204)
