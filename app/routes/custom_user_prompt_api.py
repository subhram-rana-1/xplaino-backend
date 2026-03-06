"""API routes for custom user prompt management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
import structlog

from app.models import (
    CreateCustomUserPromptRequest,
    UpdateCustomUserPromptRequest,
    CustomUserPromptResponse,
    GetAllCustomUserPromptsResponse,
    ShareCustomUserPromptRequest,
    CustomUserPromptShareResponse,
    GetSharedCustomUserPromptsResponse,
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    create_custom_user_prompt,
    update_custom_user_prompt,
    get_custom_user_prompt_by_id,
    set_custom_user_prompt_hidden,
    delete_custom_user_prompt,
    get_all_custom_user_prompts_by_user_id,
    create_custom_user_prompt_share,
    delete_custom_user_prompt_share,
    set_custom_user_prompt_share_hidden,
    get_shared_custom_user_prompts_for_user,
    get_custom_user_prompt_share_by_id,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/custom-user-prompts", tags=["Custom User Prompts"])


def _require_authenticated_user_id(auth_context: dict, db: Session) -> str:
    """
    Extract the authenticated user_id from auth_context.
    Raises 401 if the caller is not authenticated.
    """
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "UNAUTHORIZED",
                "error_message": "Authentication is required to use custom user prompts",
            },
        )
    session_data = auth_context["session_data"]
    return get_user_id_by_auth_vendor_id(db, session_data["auth_vendor_id"])


def _build_prompt_response(data: dict) -> CustomUserPromptResponse:
    return CustomUserPromptResponse(
        id=data["id"],
        userId=data["user_id"],
        title=data["title"],
        description=data["description"],
        isHidden=data["is_hidden"],
        createdAt=data["created_at"],
        updatedAt=data["updated_at"],
    )


def _build_share_response(share: dict) -> CustomUserPromptShareResponse:
    return CustomUserPromptShareResponse(
        id=share["id"],
        customUserPromptId=share["custom_user_prompt_id"],
        sharedTo=share["shared_to"],
        isHidden=share["is_hidden"],
        createdAt=share["created_at"],
        prompt=_build_prompt_response(share["prompt"]),
    )


# ---------------------------------------------------------------------------
# Custom User Prompt CRUD
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=CustomUserPromptResponse,
    status_code=201,
    summary="Create a custom user prompt",
    description="Create a new custom prompt template. Only authenticated users can create prompts.",
)
async def create_prompt(
    request: Request,
    body: CreateCustomUserPromptRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    prompt_data = create_custom_user_prompt(db, user_id, body.title, body.description)

    logger.info(
        "Created custom user prompt",
        prompt_id=prompt_data["id"],
        user_id=user_id,
    )

    return _build_prompt_response(prompt_data)


@router.get(
    "",
    response_model=GetAllCustomUserPromptsResponse,
    summary="List my custom user prompts",
    description="Return a paginated list of all non-hidden custom prompts owned by the authenticated user.",
)
async def list_prompts(
    request: Request,
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    prompts, total = get_all_custom_user_prompts_by_user_id(db, user_id, offset, limit)

    logger.info(
        "Listed custom user prompts",
        user_id=user_id,
        count=len(prompts),
        total=total,
    )

    return GetAllCustomUserPromptsResponse(
        prompts=[_build_prompt_response(p) for p in prompts],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{prompt_id}",
    response_model=CustomUserPromptResponse,
    summary="Get a custom user prompt by ID",
    description=(
        "Retrieve a single custom prompt. "
        "Accessible by the owner or any user the prompt has been shared with."
    ),
)
async def get_prompt(
    request: Request,
    prompt_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    prompt_data = get_custom_user_prompt_by_id(db, prompt_id)

    if not prompt_data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Custom user prompt not found",
            },
        )

    is_owner = prompt_data["user_id"] == user_id

    if not is_owner:
        share = db.execute(
            text("SELECT id FROM custom_user_prompt_share WHERE custom_user_prompt_id = :pid AND shared_to = :uid"),
            {"pid": prompt_id, "uid": user_id},
        ).fetchone()

        if not share:
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "FORBIDDEN",
                    "error_message": "You do not have access to this custom user prompt",
                },
            )

    logger.info(
        "Retrieved custom user prompt by id",
        prompt_id=prompt_id,
        user_id=user_id,
        is_owner=is_owner,
    )

    return _build_prompt_response(prompt_data)


@router.patch(
    "/{prompt_id}",
    response_model=CustomUserPromptResponse,
    summary="Update a custom user prompt",
    description="Update the title and/or description of a custom prompt. Only the owner can update it.",
)
async def update_prompt(
    request: Request,
    prompt_id: str,
    body: UpdateCustomUserPromptRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    if body.title is None and body.description is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_001",
                "error_message": "At least one of title or description must be provided",
            },
        )

    updated = update_custom_user_prompt(db, prompt_id, user_id, body.title, body.description)

    if not updated:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Custom user prompt not found or you are not the owner",
            },
        )

    logger.info(
        "Updated custom user prompt",
        prompt_id=prompt_id,
        user_id=user_id,
    )

    return _build_prompt_response(updated)


@router.patch(
    "/{prompt_id}/hide",
    response_model=CustomUserPromptResponse,
    summary="Hide or unhide a custom user prompt",
    description=(
        "Toggle the is_hidden flag on a custom prompt. "
        "Only the owner can hide/unhide their own prompts. "
        "Pass `is_hidden: true` to hide or `false` to unhide."
    ),
)
async def hide_prompt(
    request: Request,
    prompt_id: str,
    is_hidden: bool = Query(..., description="True to hide the prompt, false to unhide it"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    updated = set_custom_user_prompt_hidden(db, prompt_id, user_id, is_hidden)

    if not updated:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Custom user prompt not found or you are not the owner",
            },
        )

    prompt_data = get_custom_user_prompt_by_id(db, prompt_id)

    logger.info(
        "Set custom user prompt hidden flag",
        prompt_id=prompt_id,
        user_id=user_id,
        is_hidden=is_hidden,
    )

    return _build_prompt_response(prompt_data)


@router.delete(
    "/{prompt_id}",
    status_code=204,
    summary="Delete a custom user prompt",
    description="Permanently delete a custom prompt and all its shares. Only the owner can delete it.",
)
async def delete_prompt(
    request: Request,
    prompt_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    deleted = delete_custom_user_prompt(db, prompt_id, user_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Custom user prompt not found or you are not the owner",
            },
        )

    logger.info(
        "Deleted custom user prompt",
        prompt_id=prompt_id,
        user_id=user_id,
    )

    return FastAPIResponse(status_code=204)


# ---------------------------------------------------------------------------
# Custom User Prompt Sharing
# ---------------------------------------------------------------------------

@router.post(
    "/{prompt_id}/shares",
    response_model=CustomUserPromptShareResponse,
    status_code=201,
    summary="Share a custom user prompt with another user",
    description=(
        "Share one of your custom prompts with another user by their user ID. "
        "Only the prompt owner can share it. "
        "Sharing the same prompt to the same user twice returns 409."
    ),
)
async def share_prompt(
    request: Request,
    prompt_id: str,
    body: ShareCustomUserPromptRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    prompt_data = get_custom_user_prompt_by_id(db, prompt_id)

    if not prompt_data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Custom user prompt not found",
            },
        )

    if prompt_data["user_id"] != user_id:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "FORBIDDEN",
                "error_message": "Only the owner can share this custom user prompt",
            },
        )

    if body.sharedToUserId == user_id:
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "VAL_002",
                "error_message": "You cannot share a prompt with yourself",
            },
        )

    share_data = create_custom_user_prompt_share(db, prompt_id, body.sharedToUserId)

    if not share_data:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "ALREADY_SHARED",
                "error_message": "This prompt has already been shared with that user",
            },
        )

    share_data["prompt"] = prompt_data

    logger.info(
        "Shared custom user prompt",
        prompt_id=prompt_id,
        owner_user_id=user_id,
        shared_to=body.sharedToUserId,
    )

    return _build_share_response(share_data)


@router.get(
    "/shares/received",
    response_model=GetSharedCustomUserPromptsResponse,
    summary="List custom user prompts shared with me",
    description="Return a paginated list of all non-hidden custom prompt shares where the authenticated user is the recipient.",
)
async def list_received_shares(
    request: Request,
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    limit: int = Query(default=20, ge=1, le=100, description="Pagination limit (max 100)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    shares, total = get_shared_custom_user_prompts_for_user(db, user_id, offset, limit)

    logger.info(
        "Listed received custom user prompt shares",
        user_id=user_id,
        count=len(shares),
        total=total,
    )

    return GetSharedCustomUserPromptsResponse(
        shares=[_build_share_response(s) for s in shares],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.delete(
    "/shares/{share_id}",
    status_code=204,
    summary="Remove a received custom user prompt share",
    description=(
        "The recipient (shared_to user) can delete a share record to remove the prompt from their received list. "
        "The prompt owner cannot delete share records via this endpoint."
    ),
)
async def delete_share(
    request: Request,
    share_id: str,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    deleted = delete_custom_user_prompt_share(db, share_id, user_id)

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Share record not found or you are not the recipient",
            },
        )

    logger.info(
        "Deleted custom user prompt share",
        share_id=share_id,
        user_id=user_id,
    )

    return FastAPIResponse(status_code=204)


@router.patch(
    "/shares/{share_id}/hide",
    response_model=CustomUserPromptShareResponse,
    summary="Hide or unhide a received custom user prompt share",
    description=(
        "The recipient can hide or unhide a shared prompt from their list. "
        "Only the recipient (shared_to) can do this; the owner cannot."
        " Pass `is_hidden: true` to hide or `false` to unhide."
    ),
)
async def hide_share(
    request: Request,
    share_id: str,
    is_hidden: bool = Query(..., description="True to hide the share, false to unhide it"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db),
):
    user_id = _require_authenticated_user_id(auth_context, db)

    updated = set_custom_user_prompt_share_hidden(db, share_id, user_id, is_hidden)

    if not updated:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "NOT_FOUND",
                "error_message": "Share record not found or you are not the recipient",
            },
        )

    share = get_custom_user_prompt_share_by_id(db, share_id)

    logger.info(
        "Set custom user prompt share hidden flag",
        share_id=share_id,
        user_id=user_id,
        is_hidden=is_hidden,
    )

    return _build_share_response(share)
