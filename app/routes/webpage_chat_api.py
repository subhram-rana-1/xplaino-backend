"""API routes for the webpage chat feature.

Allows the browser extension to classify user questions and stream answers
with structured citations so the extension can highlight referenced content
on the live webpage.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import structlog

from app.database.connection import get_db
from app.exceptions import FileValidationError
from app.models import (
    AnswerQuestionRequest,
    ClassifyQuestionRequest,
    ClassifyQuestionResponse,
)
from app.services.auth_middleware import authenticate
from app.services.image_service import ImageService
from app.services.webpage_chat_service import (
    answer_question_stream,
    answer_with_image_stream,
    classify_question,
)

image_service = ImageService()

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


# ---------------------------------------------------------------------------
# POST /answer-with-image
# ---------------------------------------------------------------------------

@router.post(
    "/answer-with-image",
    summary="Answer a question about a webpage using an image + text chunks (SSE streaming)",
    description=(
        "Accepts a multipart/form-data request containing an image (screenshot or photo) "
        "and pre-ordered webpage text chunks. The LLM uses the image as the primary source "
        "and the chunks as supporting text evidence with [[cite:chunkId]] citations. "
        "Streams the answer token-by-token as Server-Sent Events, then emits a final "
        "'citations' event with the full citationMap. Requires authentication."
    ),
)
async def answer_with_image_endpoint(
    request: Request,
    response: Response,
    question: str = Form(..., min_length=1, max_length=5000, description="The user's question"),
    question_type: str = Form(..., description="'broad' or 'contextual'"),
    page_url: str = Form(..., min_length=1, description="URL of the webpage being discussed"),
    image: UploadFile = File(..., description="Image file — screenshot or photo (jpeg/png/webp/gif/bmp, max 5 MB)"),
    page_title: Optional[str] = Form(default=None, description="Title of the webpage"),
    language_code: Optional[str] = Form(default=None, max_length=10, description="Optional language code (e.g. 'EN', 'FR'). If provided, answer prose will be in this language."),
    selected_text: Optional[str] = Form(default=None, max_length=10000, description="Text the user has annotated/selected on the webpage"),
    chunks: str = Form(..., description="JSON array of WebpageChunk objects (same schema as /answer)"),
    conversation_history: str = Form(default="[]", description="JSON array of {role, content} turns"),
    db: Session = Depends(get_db),
    auth_context: dict = Depends(authenticate),
):
    _require_authenticated(auth_context)

    if question_type not in ("broad", "contextual"):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "VALIDATION_002",
                "error_message": "questionType must be 'broad' or 'contextual'",
            },
        )

    try:
        chunks_list = json.loads(chunks)
        if not isinstance(chunks_list, list) or len(chunks_list) == 0:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail={"error_code": "VALIDATION_001", "error_message": "chunks must be a non-empty JSON array"},
        )

    try:
        history_list = json.loads(conversation_history) if conversation_history else []
        if not isinstance(history_list, list):
            history_list = []
        parsed_history = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in history_list
            if isinstance(m, dict)
        ]
    except (json.JSONDecodeError, TypeError):
        parsed_history = []

    # Validate and read the image
    try:
        image_bytes = await image.read()
        processed_image_data, image_format = image_service.validate_image_file_for_api(
            image_bytes,
            image.filename or "image",
            max_size_mb=5,
        )
    except FileValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "IMAGE_VALIDATION_ERROR", "error_message": str(exc)},
        )

    chunks_raw = [
        {
            "chunkId": c.get("chunkId", ""),
            "text": c.get("text", ""),
            "metadata": c.get("metadata", {}),
        }
        for c in chunks_list
    ]

    async def generate():
        try:
            async for sse_event in answer_with_image_stream(
                question=question,
                question_type=question_type,
                page_url=page_url,
                page_title=page_title,
                image_data=processed_image_data,
                image_format=image_format,
                chunks=chunks_raw,
                conversation_history=parsed_history or None,
                language_code=language_code,
                selected_text=selected_text,
            ):
                yield sse_event
        except Exception as exc:
            logger.error("Unhandled error in /answer-with-image SSE generator", error=str(exc))
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
