"""API routes for RAG-based PDF chat."""

import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import structlog

from app.models import (
    UpsertPdfContentPreprocessRequest,
    PdfContentPreprocessResponse,
    CreatePdfChatSessionRequest,
    RenamePdfChatSessionRequest,
    PdfChatSessionResponse,
    AskPdfRequest,
    PdfChatMessageResponse,
    GetAllPdfChatSessionsRequest,
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_pdf_by_id,
    get_pdf_by_id_and_user_id,
    get_pdf_by_id_and_unauthenticated_user_id,
    check_pdf_access_for_user,
    get_user_info_with_email_by_user_id,
    get_pdf_sharee_list,
)
from app.services.pdf_chat_db_service import (
    upsert_pdf_content_preprocess,
    get_pdf_content_preprocess_by_id,
    get_pdf_content_preprocess_by_pdf_id,
    create_pdf_chat_session,
    get_pdf_chat_session_by_id,
    rename_pdf_chat_session,
    delete_pdf_chat_session,
    clear_pdf_chat_session,
    get_all_pdf_chat_sessions,
    create_pdf_chat,
    get_chats_by_session_id,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/pdf-chat", tags=["PDF Chat"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_owner(auth_context: dict, db: Session) -> tuple:
    """Returns (user_id, unauthenticated_user_id)."""
    if auth_context.get("authenticated"):
        session_data = auth_context["session_data"]
        auth_vendor_id = session_data["auth_vendor_id"]
        user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
        return user_id, None
    return None, auth_context.get("unauthenticated_user_id")


def _get_user_id_from_auth(auth_context: dict, db: Session) -> str:
    if not auth_context.get("authenticated"):
        raise HTTPException(status_code=401, detail={"error_code": "LOGIN_REQUIRED", "error_message": "Authentication required"})
    session_data = auth_context.get("session_data", {})
    auth_vendor_id = session_data.get("auth_vendor_id")
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id) if auth_vendor_id else None
    if not user_id:
        raise HTTPException(status_code=401, detail={"error_code": "AUTH_003", "error_message": "User not found"})
    return user_id


def _get_user_email(db: Session, user_id: str) -> Optional[str]:
    info = get_user_info_with_email_by_user_id(db, user_id)
    return info.get("email") if info else None


def _assert_pdf_access(
    db: Session,
    pdf_id: str,
    user_id: Optional[str],
    unauthenticated_user_id: Optional[str],
    require_chat_permission: bool = True,
):
    """Validate that the caller can access (and optionally chat with) a PDF.

    Returns the pdf dict on success; raises HTTPException otherwise.
    """
    pdf = get_pdf_by_id(db, pdf_id)
    if not pdf:
        raise HTTPException(status_code=404, detail="PDF not found")

    if unauthenticated_user_id:
        own = get_pdf_by_id_and_unauthenticated_user_id(db, pdf_id, unauthenticated_user_id)
        if not own:
            raise HTTPException(status_code=403, detail="Access denied")
        return pdf

    if user_id:
        own = get_pdf_by_id_and_user_id(db, pdf_id, user_id)
        if own:
            return pdf
        email = _get_user_email(db, user_id)
        if email:
            shared = check_pdf_access_for_user(db, pdf_id, user_id, email)
            if shared:
                return pdf

        if pdf.get("access_level") == "PUBLIC" and not require_chat_permission:
            return pdf

        raise HTTPException(status_code=403, detail="Access denied")

    if pdf.get("access_level") == "PUBLIC" and not require_chat_permission:
        return pdf

    raise HTTPException(status_code=403, detail="Access denied")


def _is_owner_or_shared(
    db: Session,
    pdf_id: str,
    user_id: Optional[str],
) -> bool:
    """Check if the user is the PDF owner or a sharee."""
    if not user_id:
        return False
    own = get_pdf_by_id_and_user_id(db, pdf_id, user_id)
    if own:
        return True
    email = _get_user_email(db, user_id)
    if email:
        shared = check_pdf_access_for_user(db, pdf_id, user_id, email)
        return shared is not None
    return False


def _get_allowed_origin(request: Request) -> str:
    origin = request.headers.get("Origin")
    return origin if origin else "*"


# ---------------------------------------------------------------------------
# 1. POST /preprocess
# ---------------------------------------------------------------------------

@router.post(
    "/preprocess",
    response_model=PdfContentPreprocessResponse,
    status_code=202,
    summary="Upsert PDF content preprocessing",
)
async def upsert_preprocess(
    request: Request,
    response: Response,
    body: UpsertPdfContentPreprocessRequest,
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    user_id, unauth_id = _resolve_owner(auth_context, db)
    _assert_pdf_access(db, body.pdf_id, user_id, unauth_id)

    record = upsert_pdf_content_preprocess(db, body.pdf_id)
    is_new = record["status"] == "PENDING"

    if is_new:
        from app.services.pdf_preprocess_task import preprocess_pdf
        preprocess_pdf.delay(record["id"], body.pdf_id)
        logger.info("Enqueued PDF preprocessing", preprocess_id=record["id"], pdf_id=body.pdf_id)

    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return PdfContentPreprocessResponse(**record)


# ---------------------------------------------------------------------------
# 2. GET /preprocess/{id}
# ---------------------------------------------------------------------------

@router.get(
    "/preprocess/{preprocess_id}",
    response_model=PdfContentPreprocessResponse,
    summary="Get PDF content preprocess status",
)
async def get_preprocess_status(
    preprocess_id: str,
    response: Response,
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    record = get_pdf_content_preprocess_by_id(db, preprocess_id)
    if not record:
        raise HTTPException(status_code=404, detail="Preprocess record not found")

    user_id, unauth_id = _resolve_owner(auth_context, db)
    _assert_pdf_access(db, record["pdf_id"], user_id, unauth_id, require_chat_permission=False)

    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return PdfContentPreprocessResponse(**record)


# ---------------------------------------------------------------------------
# 3. POST /sessions
# ---------------------------------------------------------------------------

@router.post(
    "/sessions",
    response_model=PdfChatSessionResponse,
    status_code=201,
    summary="Create a PDF chat session",
)
async def create_session(
    request: Request,
    response: Response,
    body: CreatePdfChatSessionRequest,
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    preprocess = get_pdf_content_preprocess_by_id(db, body.pdf_content_preprocess_id)
    if not preprocess:
        raise HTTPException(status_code=404, detail="Preprocess record not found")

    user_id, unauth_id = _resolve_owner(auth_context, db)
    _assert_pdf_access(db, preprocess["pdf_id"], user_id, unauth_id)

    session = create_pdf_chat_session(db, body.pdf_content_preprocess_id, user_id, unauth_id)

    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return PdfChatSessionResponse(**session)


# ---------------------------------------------------------------------------
# 4. PATCH /sessions/{id}/rename
# ---------------------------------------------------------------------------

@router.patch(
    "/sessions/{session_id}/rename",
    status_code=200,
    summary="Rename a PDF chat session",
)
async def rename_session(
    session_id: str,
    body: RenamePdfChatSessionRequest,
    response: Response,
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    session = get_pdf_chat_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_id, unauth_id = _resolve_owner(auth_context, db)
    if user_id and session["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if unauth_id and session["unauthenticated_user_id"] != unauth_id:
        raise HTTPException(status_code=403, detail="Access denied")

    rename_pdf_chat_session(db, session_id, body.name)

    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    updated = get_pdf_chat_session_by_id(db, session_id)
    return PdfChatSessionResponse(**updated)


# ---------------------------------------------------------------------------
# 5. POST /sessions/{id}/ask  (SSE)
# ---------------------------------------------------------------------------

@router.post(
    "/sessions/{session_id}/ask",
    summary="Ask a question about a PDF (SSE streaming)",
)
async def ask_pdf(
    request: Request,
    response: Response,
    session_id: str,
    body: AskPdfRequest,
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    session = get_pdf_chat_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if body.pdf_chat_session_id != session_id:
        raise HTTPException(status_code=400, detail="Session ID in body must match URL")

    preprocess = get_pdf_content_preprocess_by_id(db, session["pdf_content_preprocess_id"])
    if not preprocess or preprocess["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail="PDF preprocessing is not complete")

    user_id, unauth_id = _resolve_owner(auth_context, db)
    _assert_pdf_access(db, preprocess["pdf_id"], user_id, unauth_id)

    existing_chats = get_chats_by_session_id(db, session_id, limit=20)
    chat_history = existing_chats.get("messages", [])

    from app.services.pdf_chat_service import ask_pdf_stream

    async def generate():
        accumulated_answer = ""
        citations_list = None
        try:
            async for sse_event in ask_pdf_stream(
                question=body.question,
                preprocess_id=session["pdf_content_preprocess_id"],
                chat_history=chat_history,
                selected_text=body.selected_text,
            ):
                yield sse_event

                if sse_event.startswith("data: "):
                    raw = sse_event[6:].strip()
                    if raw and raw != "[DONE]":
                        try:
                            parsed = json.loads(raw)
                            if parsed.get("type") == "complete":
                                accumulated_answer = parsed.get("answer", "")
                                citations_list = parsed.get("citations")
                        except (json.JSONDecodeError, TypeError):
                            pass

            if accumulated_answer:
                create_pdf_chat(db, session_id, "USER", body.question)
                create_pdf_chat(db, session_id, "SYSTEM", accumulated_answer, citations_list)

        except Exception as e:
            logger.error("Error in ask_pdf stream", error=str(e))
            error_event = {"type": "error", "error_code": "RAG_001", "error_message": str(e)}
            yield f"data: {json.dumps(error_event)}\n\n"

    allowed_origin = _get_allowed_origin(request)
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": allowed_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-CSRFToken, X-Forwarded-For, User-Agent, Origin, Referer, Cache-Control, Pragma, Content-Disposition, Content-Transfer-Encoding, X-File-Name, X-File-Size, X-File-Type, X-Access-Token, X-Unauthenticated-User-Id",
        "Access-Control-Expose-Headers": "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, Access-Control-Allow-Headers, X-Unauthenticated-User-Id",
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)


# ---------------------------------------------------------------------------
# 6. DELETE /sessions/{id}/chats
# ---------------------------------------------------------------------------

@router.delete(
    "/sessions/{session_id}/chats",
    status_code=200,
    summary="Clear all chats in a session",
)
async def clear_session_chats(
    session_id: str,
    response: Response,
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    session = get_pdf_chat_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_id, unauth_id = _resolve_owner(auth_context, db)
    if user_id and session["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if unauth_id and session["unauthenticated_user_id"] != unauth_id:
        raise HTTPException(status_code=403, detail="Access denied")

    deleted = clear_pdf_chat_session(db, session_id)

    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return {"deleted_count": deleted}


# ---------------------------------------------------------------------------
# 7. DELETE /sessions/{id}
# ---------------------------------------------------------------------------

@router.delete(
    "/sessions/{session_id}",
    status_code=200,
    summary="Delete a PDF chat session",
)
async def delete_session(
    session_id: str,
    response: Response,
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    session = get_pdf_chat_session_by_id(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_id, unauth_id = _resolve_owner(auth_context, db)
    if user_id and session["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    if unauth_id and session["unauthenticated_user_id"] != unauth_id:
        raise HTTPException(status_code=403, detail="Access denied")

    delete_pdf_chat_session(db, session_id)

    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return {"deleted": True}


# ---------------------------------------------------------------------------
# 8. GET /sessions
# ---------------------------------------------------------------------------

@router.get(
    "/sessions",
    response_model=List[PdfChatSessionResponse],
    summary="List PDF chat sessions",
)
async def list_sessions(
    request: Request,
    response: Response,
    pdf_content_preprocess_id: str = Query(..., min_length=1, max_length=36),
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    preprocess = get_pdf_content_preprocess_by_id(db, pdf_content_preprocess_id)
    if not preprocess:
        raise HTTPException(status_code=404, detail="Preprocess record not found")

    pdf_id = preprocess["pdf_id"]
    user_id, unauth_id = _resolve_owner(auth_context, db)

    _assert_pdf_access(db, pdf_id, user_id, unauth_id, require_chat_permission=False)

    if unauth_id:
        sessions = get_all_pdf_chat_sessions(
            db, pdf_content_preprocess_id, unauthenticated_user_id=unauth_id
        )
    elif user_id:
        include_all = _is_owner_or_shared(db, pdf_id, user_id)
        sessions = get_all_pdf_chat_sessions(
            db, pdf_content_preprocess_id, user_id=user_id, include_all_shared=include_all
        )
    else:
        sessions = []

    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return [PdfChatSessionResponse(**s) for s in sessions]
