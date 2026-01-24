"""API routes for domain management."""

from fastapi import APIRouter, HTTPException, Depends, Request, Response, Path, Query
from sqlalchemy.orm import Session
from typing import Optional
import structlog

from app.models import (
    CreateDomainRequest,
    UpdateDomainRequest,
    DomainResponse,
    GetAllDomainsResponse,
    DomainStatus,
    DomainCreatedByUser
)
from app.database.connection import get_db
from app.services.auth_middleware import authenticate
from app.services.database_service import (
    get_user_id_by_auth_vendor_id,
    get_user_role_by_user_id,
    create_domain,
    get_all_domains,
    get_domain_by_id,
    update_domain,
    delete_domain
)
from app.utils.utils import validate_domain_url
from sqlalchemy import text

logger = structlog.get_logger()

router = APIRouter(prefix="/api/domain", tags=["Domains"])


def _check_admin_role(user_id: str, db: Session) -> None:
    """
    Check if user has ADMIN or SUPER_ADMIN role.
    
    Args:
        user_id: User ID
        db: Database session
        
    Raises:
        HTTPException: 403 if user is not ADMIN or SUPER_ADMIN
    """
    user_role = get_user_role_by_user_id(db, user_id)
    if user_role not in ("ADMIN", "SUPER_ADMIN"):
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "PERMISSION_DENIED",
                "error_message": "Only ADMIN and SUPER_ADMIN users can access this endpoint"
            }
        )


@router.get(
    "/",
    response_model=GetAllDomainsResponse,
    summary="Get all domains",
    description="Get list of all domains. Public endpoint - no authentication required. Results ordered by created_at DESC (most recent first). Pagination is optional - if offset and limit are not provided, all domains are returned."
)
async def get_all_domains_endpoint(
    request: Request,
    response: Response,
    offset: Optional[int] = Query(default=None, ge=0, description="Pagination offset (optional)"),
    limit: Optional[int] = Query(default=None, ge=1, le=100, description="Pagination limit (optional, max 100)"),
    db: Session = Depends(get_db)
):
    """Get all domains. Public endpoint - no authentication required. Pagination is optional."""
    # Determine if pagination is requested
    use_pagination = offset is not None and limit is not None
    
    # Get all domains with optional pagination
    domains_data, total_count = get_all_domains(db, offset=offset, limit=limit)
    
    # Convert to response models
    domains = [
        DomainResponse(
            id=domain["id"],
            url=domain["url"],
            status=domain["status"],
            created_by=DomainCreatedByUser(
                id=domain["created_by"]["id"],
                name=domain["created_by"]["name"],
                role=domain["created_by"]["role"],
                email=domain["created_by"]["email"]
            ),
            created_at=domain["created_at"],
            updated_at=domain["updated_at"]
        )
        for domain in domains_data
    ]
    
    # Calculate has_next only if pagination is used
    has_next = False
    if use_pagination:
        has_next = (offset + limit) < total_count
    
    # Set offset and limit to 0 if pagination not used
    response_offset = offset if offset is not None else 0
    response_limit = limit if limit is not None else total_count
    
    logger.info(
        "Retrieved all domains successfully",
        domain_count=len(domains),
        total_count=total_count,
        offset=response_offset,
        limit=response_limit,
        has_next=has_next,
        pagination_used=use_pagination
    )
    
    return GetAllDomainsResponse(
        domains=domains,
        total=total_count,
        offset=response_offset,
        limit=response_limit,
        has_next=has_next
    )


@router.get(
    "/{domain_id}",
    response_model=DomainResponse,
    summary="Get domain by ID",
    description="Get a domain by its ID. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def get_domain_by_id_endpoint(
    request: Request,
    response: Response,
    domain_id: str = Path(..., description="Domain ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Get a domain by its ID."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Check admin role
    _check_admin_role(user_id, db)
    
    # Get domain by ID
    domain_data = get_domain_by_id(db, domain_id)
    if not domain_data:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "DOMAIN_NOT_FOUND",
                "error_message": f"Domain with ID {domain_id} not found"
            }
        )
    
    logger.info(
        "Retrieved domain successfully",
        user_id=user_id,
        domain_id=domain_id
    )
    
    return DomainResponse(
        id=domain_data["id"],
        url=domain_data["url"],
        status=domain_data["status"],
        created_by=DomainCreatedByUser(
            id=domain_data["created_by"]["id"],
            name=domain_data["created_by"]["name"],
            role=domain_data["created_by"]["role"],
            email=domain_data["created_by"]["email"]
        ),
        created_at=domain_data["created_at"],
        updated_at=domain_data["updated_at"]
    )


@router.post(
    "/",
    response_model=DomainResponse,
    status_code=201,
    summary="Create a domain",
    description="Create a new domain. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def create_domain_endpoint(
    request: Request,
    response: Response,
    body: CreateDomainRequest,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Create a new domain."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Check admin role
    _check_admin_role(user_id, db)
    
    # Validate URL format
    if not validate_domain_url(body.url):
        raise HTTPException(
            status_code=422,
            detail={
                "error_code": "INVALID_DOMAIN_URL",
                "error_message": "Invalid domain URL format. Domain must not include http/https or paths. Examples: example.com, www.example.com, sub.example.com, example.co.uk"
            }
        )
    
    # Check for duplicate URL
    existing_domain = db.execute(
        text("SELECT id FROM domain WHERE LOWER(url) = LOWER(:url)"),
        {"url": body.url}
    ).fetchone()
    if existing_domain:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "DOMAIN_ALREADY_EXISTS",
                "error_message": f"Domain with URL '{body.url}' already exists"
            }
        )
    
    # Determine status
    status = body.status.value if body.status else DomainStatus.ALLOWED.value
    
    # Create domain
    domain_data = create_domain(
        db,
        user_id=user_id,
        url=body.url,
        status=status
    )
    
    logger.info(
        "Created domain successfully",
        user_id=user_id,
        domain_id=domain_data["id"],
        url=body.url
    )
    
    return DomainResponse(
        id=domain_data["id"],
        url=domain_data["url"],
        status=domain_data["status"],
        created_by=DomainCreatedByUser(
            id=domain_data["created_by"]["id"],
            name=domain_data["created_by"]["name"],
            role=domain_data["created_by"]["role"],
            email=domain_data["created_by"]["email"]
        ),
        created_at=domain_data["created_at"],
        updated_at=domain_data["updated_at"]
    )


@router.patch(
    "/{domain_id}",
    response_model=DomainResponse,
    summary="Update a domain",
    description="Update a domain's URL and/or status. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def update_domain_endpoint(
    request: Request,
    response: Response,
    domain_id: str = Path(..., description="Domain ID (UUID)"),
    body: UpdateDomainRequest = ...,
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Update a domain."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Check admin role
    _check_admin_role(user_id, db)
    
    # Check if domain exists
    existing_domain = get_domain_by_id(db, domain_id)
    if not existing_domain:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "DOMAIN_NOT_FOUND",
                "error_message": f"Domain with ID {domain_id} not found"
            }
        )
    
    # Validate URL format if provided
    url_to_update = None
    if body.url is not None:
        if not validate_domain_url(body.url):
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "INVALID_DOMAIN_URL",
                    "error_message": "Invalid domain URL format. Domain must not include http/https or paths. Examples: example.com, www.example.com, sub.example.com, example.co.uk"
                }
            )
        url_to_update = body.url
        
        # Check for duplicate URL (excluding current domain)
        existing_domain = db.execute(
            text("SELECT id FROM domain WHERE LOWER(url) = LOWER(:url) AND id != :domain_id"),
            {"url": body.url, "domain_id": domain_id}
        ).fetchone()
        if existing_domain:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "DOMAIN_ALREADY_EXISTS",
                    "error_message": f"Domain with URL '{body.url}' already exists"
                }
            )
    
    # Determine status
    status_to_update = None
    if body.status is not None:
        status_to_update = body.status.value
    
    # Update domain
    updated_domain = update_domain(
        db,
        domain_id=domain_id,
        url=url_to_update,
        status=status_to_update
    )
    
    logger.info(
        "Updated domain successfully",
        user_id=user_id,
        domain_id=domain_id,
        has_url_update=url_to_update is not None,
        has_status_update=status_to_update is not None
    )
    
    return DomainResponse(
        id=updated_domain["id"],
        url=updated_domain["url"],
        status=updated_domain["status"],
        created_by=DomainCreatedByUser(
            id=updated_domain["created_by"]["id"],
            name=updated_domain["created_by"]["name"],
            role=updated_domain["created_by"]["role"],
            email=updated_domain["created_by"]["email"]
        ),
        created_at=updated_domain["created_at"],
        updated_at=updated_domain["updated_at"]
    )


@router.delete(
    "/{domain_id}",
    status_code=204,
    summary="Delete a domain",
    description="Delete a domain by its ID. Only ADMIN and SUPER_ADMIN users can access this endpoint."
)
async def delete_domain_endpoint(
    request: Request,
    response: Response,
    domain_id: str = Path(..., description="Domain ID (UUID)"),
    auth_context: dict = Depends(authenticate),
    db: Session = Depends(get_db)
):
    """Delete a domain."""
    # Verify user is authenticated
    if not auth_context.get("authenticated"):
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "LOGIN_REQUIRED",
                "error_message": "Authentication required"
            }
        )
    
    # Get user_id from auth_context
    session_data = auth_context.get("session_data")
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_001",
                "error_message": "Invalid session data"
            }
        )
    
    auth_vendor_id = session_data.get("auth_vendor_id")
    if not auth_vendor_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_002",
                "error_message": "Missing auth vendor ID"
            }
        )
    
    # Get user_id from auth_vendor_id
    user_id = get_user_id_by_auth_vendor_id(db, auth_vendor_id)
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "AUTH_003",
                "error_message": "User not found"
            }
        )
    
    # Check admin role
    _check_admin_role(user_id, db)
    
    # Check if domain exists
    existing_domain = get_domain_by_id(db, domain_id)
    if not existing_domain:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "DOMAIN_NOT_FOUND",
                "error_message": f"Domain with ID {domain_id} not found"
            }
        )
    
    # Delete domain
    deleted = delete_domain(db, domain_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "DOMAIN_NOT_FOUND",
                "error_message": f"Domain with ID {domain_id} not found"
            }
        )
    
    logger.info(
        "Deleted domain successfully",
        user_id=user_id,
        domain_id=domain_id
    )
    
    return Response(status_code=204)

