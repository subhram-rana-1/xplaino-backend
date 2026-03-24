"""API routes for the webpage chat feature.

Allows the browser extension to classify user questions and stream answers
with structured citations so the extension can highlight referenced content
on the live webpage.
"""

import json
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import structlog

from app.database.connection import get_db
from app.models import (
    AnswerQuestionRequest,
    ClassifyQuestionRequest,
    ClassifyQuestionResponse,
)
from app.services.auth_middleware import authenticate
from app.services.webpage_chat_service import (
    answer_question_stream,
    classify_question,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/webpage-chat", tags=["Webpage Chat"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_authenticated(auth_context: dict) -> None:
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={"error_code": "LOGIN_REQUIRED", "error_message": "Authentication required"},
        )


def _get_allowed_origin(request: Request) -> str:
    origin = request.headers.get("Origin")
    return origin if origin else "*"


def _sse_headers(request: Request, auth_context: dict) -> dict:
    allowed_origin = _get_allowed_origin(request)
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "Access-Control-Allow-Origin": allowed_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": (
            "Accept, Accept-Language, Content-Language, Content-Type, Authorization, "
            "X-Requested-With, X-CSRFToken, X-Forwarded-For, User-Agent, Origin, Referer, "
            "Cache-Control, Pragma, Content-Disposition, Content-Transfer-Encoding, "
            "X-File-Name, X-File-Size, X-File-Type, X-Access-Token, X-Unauthenticated-User-Id"
        ),
        "Access-Control-Expose-Headers": (
            "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, "
            "Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, "
            "Access-Control-Allow-Headers, X-Unauthenticated-User-Id"
        ),
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    return headers


# ---------------------------------------------------------------------------
# POST /classify
# ---------------------------------------------------------------------------

@router.post(
    "/classify",
    response_model=ClassifyQuestionResponse,
    summary="Classify a user question for webpage chat",
    description=(
        "Classifies the question into 'greeting', 'broad', or 'contextual'. "
        "For greeting-type questions, also returns an immediate LLM reply. "
        "Requires authentication."
    ),
)
async def classify_endpoint(
    request: Request,
    response: Response,
    body: ClassifyQuestionRequest,
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    _require_authenticated(auth_context)

    history = (
        [{"role": m.role, "content": m.content} for m in body.conversationHistory]
        if body.conversationHistory
        else None
    )

    try:
        question_type, reply = await classify_question(
            question=body.question,
            conversation_history=history,
        )
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"error": "classification_failed"},
        )
    except Exception as exc:
        logger.error("Unexpected error in /classify", error=str(exc))
        raise HTTPException(
            status_code=500,
            detail={"error_code": "INTERNAL_001", "error_message": "Internal server error"},
        )

    return ClassifyQuestionResponse(type=question_type, reply=reply)


# ---------------------------------------------------------------------------
# POST /answer
# ---------------------------------------------------------------------------

@router.post(
    "/answer",
    summary="Answer a question about a webpage (SSE streaming)",
    description=(
        "Receives a question and pre-ordered webpage chunks. Streams the LLM answer "
        "token-by-token as Server-Sent Events, then emits a final 'citations' event "
        "containing anchor metadata for every cited chunk. Requires authentication."
    ),
)
async def answer_endpoint(
    request: Request,
    response: Response,
    body: AnswerQuestionRequest,
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    _require_authenticated(auth_context)

    if not body.chunks:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "VALIDATION_001", "error_message": "chunks array must not be empty"},
        )

    if body.questionType not in ("broad", "contextual"):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "VALIDATION_002",
                "error_message": "questionType must be 'broad' or 'contextual'",
            },
        )

    chunks_raw = [
        {
            "chunkId": chunk.chunkId,
            "text": chunk.text,
            "metadata": {
                "startXPath": chunk.metadata.startXPath,
                "endXPath": chunk.metadata.endXPath,
                "startOffset": chunk.metadata.startOffset,
                "endOffset": chunk.metadata.endOffset,
                "cssSelector": chunk.metadata.cssSelector,
                "textSnippetStart": chunk.metadata.textSnippetStart,
                "textSnippetEnd": chunk.metadata.textSnippetEnd,
            },
        }
        for chunk in body.chunks
    ]

    history = (
        [{"role": m.role, "content": m.content} for m in body.conversationHistory]
        if body.conversationHistory
        else None
    )

    async def generate():
        try:
            async for sse_event in answer_question_stream(
                question=body.question,
                question_type=body.questionType,
                page_url=body.pageUrl,
                page_title=body.pageTitle,
                chunks=chunks_raw,
                conversation_history=history,
                language_code=body.languageCode,
                selected_text=body.selectedText,
            ):
                yield sse_event
        except Exception as exc:
            logger.error("Unhandled error in /answer SSE generator", error=str(exc))
            error_event = {
                "type": "error",
                "error_code": "INTERNAL_001",
                "error_message": "An unexpected error occurred",
            }
            yield f"data: {json.dumps(error_event)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=_sse_headers(request, auth_context),
    )
