"""Pydantic models for request/response validation."""

from typing import List, Optional, Dict
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


class ErrorResponse(BaseModel):
    """Standard error response model."""
    
    error_code: str = Field(..., description="Error code identifier")
    error_message: str = Field(..., description="Human-readable error message")


class WordWithLocation(BaseModel):
    """Model for word location in text."""

    word: str = Field(..., description="The actual word")
    index: int = Field(..., ge=0, description="Starting index of the word in the text")
    length: int = Field(..., gt=0, description="Length of the word")


class ImportantWordsRequest(BaseModel):
    """Request model for getting important words from text."""
    
    text: str = Field(..., min_length=1, max_length=10000, description="Input text to analyze")


class ImportantWordsResponse(BaseModel):
    """Response model for important words extraction."""
    
    text: str = Field(..., description="Original input text")
    important_words_location: List[WordWithLocation] = Field(..., description="List of important word locations")


class WordInfo(BaseModel):
    """Model for word information including meaning and examples."""
    
    location: WordWithLocation = Field(..., description="Word location in original text")
    word: str = Field(..., description="The actual word")
    raw_response: str = Field(..., description="Raw formatted response from OpenAI in the format: [[[WORD_MEANING]]]:{...}[[[EXAMPLES]]]:{[[ITEM]]{...}[[ITEM]]{...}}")
    meaning: Optional[str] = Field(default=None, description="Simplified meaning of the word (deprecated - use raw_response)")
    examples: Optional[List[str]] = Field(default=None, description="Two example sentences (deprecated - use raw_response)")
    languageCode: Optional[str] = Field(default=None, alias="language_code", description="ISO 639-1 language code (e.g., 'EN', 'ES', 'DE', 'FR')")
    
    model_config = ConfigDict(populate_by_name=True)


class WordsExplanationRequest(BaseModel):
    """Request model for getting word explanations."""
    
    text: str = Field(..., min_length=1, max_length=10000, description="Original text")
    important_words_location: List[WordWithLocation] = Field(..., min_items=1, max_items=10, description="List of important word locations")


class WordsExplanationResponse(BaseModel):
    """Response model for word explanations."""
    
    text: str = Field(..., description="Original input text")
    words_info: List[WordInfo] = Field(..., description="List of word information")


class MoreExplanationsRequest(BaseModel):
    """Request model for getting more explanations."""
    
    word: str = Field(..., min_length=1, max_length=100, description="The word to get more examples for")
    meaning: str = Field(..., min_length=1, max_length=1000, description="Current meaning of the word")
    examples: List[str] = Field(..., min_items=2, max_items=2, description="Current example sentences")


class MoreExplanationsResponse(BaseModel):
    """Response model for more explanations."""
    
    word: str = Field(..., description="The word")
    meaning: str = Field(..., description="The meaning of the word")
    examples: List[str] = Field(..., min_items=4, max_items=4, description="Four example sentences (2 original + 2 new)")
    shouldAllowFetchMoreExamples: bool = Field(..., description="Whether more examples can be fetched based on current examples count")


class ImageToTextResponse(BaseModel):
    """Response model for image to text conversion."""
    
    text: str = Field(..., description="Extracted text from the image")
    topicName: str = Field(..., description="Generated topic name for the extracted text")


class PdfToTextResponse(BaseModel):
    """Response model for PDF to text conversion."""
    
    text: str = Field(..., description="Extracted text from the PDF in markdown format")
    topicName: str = Field(..., description="Generated topic name for the extracted text")


class HealthCheckResponse(BaseModel):
    """Response model for health check."""
    
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    timestamp: str = Field(..., description="Current timestamp")


class RandomParagraphResponse(BaseModel):
    """Response model for random paragraph generation."""
    
    text: str = Field(..., description="Generated random paragraph text")
    topicName: str = Field(..., description="Generated topic name for the paragraph")


class AuthVendor(str, Enum):
    """Authentication vendor enum."""
    GOOGLE = "GOOGLE"


class LoginRequest(BaseModel):
    """Request model for login."""
    
    authVendor: AuthVendor = Field(..., description="Authentication vendor")
    idToken: str = Field(..., description="ID token from OAuth provider")


class LogoutRequest(BaseModel):
    """Request model for logout."""
    
    authVendor: AuthVendor = Field(..., description="Authentication vendor")


class UserInfo(BaseModel):
    """User information model."""
    
    id: str = Field(..., description="User ID (UUID)")
    name: str = Field(..., description="User's full name")
    firstName: Optional[str] = Field(default=None, description="User's first name")
    lastName: Optional[str] = Field(default=None, description="User's last name")
    email: str = Field(..., description="User's email address")
    picture: Optional[str] = Field(default=None, description="User's profile picture URL")
    role: Optional[str] = Field(default=None, description="User role (ADMIN, SUPER_ADMIN, or None)")


class LoginResponse(BaseModel):
    """Response model for login."""
    
    isLoggedIn: bool = Field(..., description="Whether the user is logged in")
    accessToken: str = Field(..., description="JWT access token")
    accessTokenExpiresAt: int = Field(..., description="Unix timestamp when access token expires")
    refreshToken: str = Field(..., description="Refresh token for obtaining new access tokens")
    refreshTokenExpiresAt: int = Field(..., description="Unix timestamp when refresh token expires")
    userSessionPk: str = Field(..., description="User session primary key (ID from user_session table)")
    user: UserInfo = Field(..., description="User information")


class LogoutResponse(BaseModel):
    """Response model for logout."""
    
    isLoggedIn: bool = Field(..., description="Whether the user is logged in")
    accessToken: str = Field(..., description="JWT access token (invalidated)")
    accessTokenExpiresAt: int = Field(..., description="Unix timestamp when access token expires")
    userSessionPk: str = Field(..., description="User session primary key (ID from user_session table)")
    user: UserInfo = Field(..., description="User information")


class RefreshTokenRequest(BaseModel):
    """Request model for refresh token."""
    
    refreshToken: str = Field(..., description="Refresh token to validate and exchange for new tokens")


class RefreshTokenResponse(BaseModel):
    """Response model for refresh token - identical to LoginResponse."""
    
    isLoggedIn: bool = Field(..., description="Whether the user is logged in")
    accessToken: str = Field(..., description="JWT access token")
    accessTokenExpiresAt: int = Field(..., description="Unix timestamp when access token expires")
    refreshToken: str = Field(..., description="Refresh token for obtaining new access tokens")
    refreshTokenExpiresAt: int = Field(..., description="Unix timestamp when refresh token expires")
    userSessionPk: str = Field(..., description="User session primary key (ID from user_session table)")
    user: UserInfo = Field(..., description="User information")


class SaveWordRequest(BaseModel):
    """Request model for saving a word."""
    
    word: str = Field(..., min_length=1, max_length=32, description="Word to save (max 32 characters)")
    sourceUrl: str = Field(..., min_length=1, max_length=1024, description="Source URL where the word was found (max 1024 characters)")
    folderId: str = Field(..., description="Folder ID where the word will be saved (UUID)")
    contextualMeaning: Optional[str] = Field(
        None,
        max_length=1000,
        description="Contextual meaning or explanation of the word (max 1000 characters, optional)"
    )


class SavedWordResponse(BaseModel):
    """Response model for a saved word."""
    
    id: str = Field(..., description="Saved word ID (UUID)")
    word: str = Field(..., description="The saved word")
    sourceUrl: str = Field(..., description="Source URL where the word was found")
    folderId: str = Field(..., description="Folder ID where the word is saved (UUID)")
    user: UserInfo = Field(..., description="User information (id, name, email, role)")
    createdAt: str = Field(..., description="ISO format timestamp when the word was saved")
    contextualMeaning: Optional[str] = Field(
        None,
        description="Contextual meaning or explanation of the word when it was saved (optional)"
    )


class GetSavedWordsResponse(BaseModel):
    """Response model for getting saved words with pagination."""
    
    words: List[SavedWordResponse] = Field(..., description="List of saved words")
    total: int = Field(..., description="Total number of saved words for the user")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")


class LinkType(str, Enum):
    """Link type enum."""
    WEBPAGE = "WEBPAGE"
    YOUTUBE = "YOUTUBE"
    LINKEDIN = "LINKEDIN"
    TWITTER = "TWITTER"
    REDDIT = "REDDIT"
    FACEBOOK = "FACEBOOK"
    INSTAGRAM = "INSTAGRAM"


class SaveParagraphRequest(BaseModel):
    """Request model for saving a paragraph."""
    
    content: str = Field(..., min_length=1, description="Paragraph content")
    source_url: str = Field(..., min_length=1, max_length=1024, description="Source URL where the paragraph was found (max 1024 characters)")
    folder_id: str = Field(..., description="Folder ID to save the paragraph in (UUID)")
    name: Optional[str] = Field(default=None, max_length=50, description="Optional name for the paragraph (max 50 characters)")


class CreateParagraphFolderRequest(BaseModel):
    """Request model for creating a paragraph folder."""
    
    parent_folder_id: Optional[str] = Field(default=None, description="Parent folder ID (nullable for root folders)")
    name: str = Field(..., min_length=1, max_length=50, description="Folder name (max 50 characters)")


class FolderResponse(BaseModel):
    """Response model for a folder."""
    
    id: str = Field(..., description="Folder ID (UUID)")
    name: str = Field(..., description="Folder name")
    parent_id: Optional[str] = Field(default=None, description="Parent folder ID (nullable)")
    user_id: str = Field(..., description="User ID who owns the folder (UUID)")
    created_at: str = Field(..., description="ISO format timestamp when the folder was created")
    updated_at: str = Field(..., description="ISO format timestamp when the folder was last updated")


class SavedParagraphResponse(BaseModel):
    """Response model for a saved paragraph."""
    
    id: str = Field(..., description="Saved paragraph ID (UUID)")
    name: Optional[str] = Field(default=None, description="Optional name for the paragraph")
    source_url: str = Field(..., description="Source URL where the paragraph was found")
    content: str = Field(..., description="Paragraph content")
    folder_id: str = Field(..., description="Folder ID the paragraph is saved in (UUID)")
    user_id: str = Field(..., description="User ID who saved the paragraph (UUID)")
    created_at: str = Field(..., description="ISO format timestamp when the paragraph was saved")
    updated_at: str = Field(..., description="ISO format timestamp when the paragraph was last updated")


class GetAllSavedParagraphResponse(BaseModel):
    """Response model for getting saved paragraphs with folders and pagination."""
    
    folder_id: Optional[str] = Field(default=None, description="Current folder ID (nullable for root)")
    user_id: str = Field(..., description="User ID (UUID)")
    sub_folders: List[FolderResponse] = Field(..., description="List of sub-folders in the current folder")
    saved_paragraphs: List[SavedParagraphResponse] = Field(..., description="List of saved paragraphs")
    total: int = Field(..., description="Total number of saved paragraphs for the user in this folder")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")
    has_next: bool = Field(..., description="Whether there are more paragraphs to fetch")


class SaveLinkRequest(BaseModel):
    """Request model for saving a link."""
    
    url: str = Field(..., min_length=1, max_length=1024, description="Link URL to save (max 1024 characters)")
    folder_id: str = Field(..., description="Folder ID to save the link in (UUID)")
    name: Optional[str] = Field(default=None, max_length=100, description="Optional name for the link (max 100 characters)")
    summary: Optional[str] = Field(default=None, description="Optional summary text for the link")
    metadata: Optional[dict] = Field(default=None, description="Optional metadata JSON for the link")


class SavedLinkResponse(BaseModel):
    """Response model for a saved link."""
    
    id: str = Field(..., description="Saved link ID (UUID)")
    name: Optional[str] = Field(default=None, description="Optional name for the link")
    url: str = Field(..., description="Link URL")
    type: str = Field(..., description="Link type (WEBPAGE, YOUTUBE, LINKEDIN, TWITTER, REDDIT, FACEBOOK, INSTAGRAM)")
    summary: Optional[str] = Field(default=None, description="Optional summary text for the link")
    metadata: Optional[dict] = Field(default=None, description="Optional metadata JSON for the link")
    folder_id: str = Field(..., description="Folder ID the link is saved in (UUID)")
    user_id: str = Field(..., description="User ID who saved the link (UUID)")
    created_at: str = Field(..., description="ISO format timestamp when the link was saved")
    updated_at: str = Field(..., description="ISO format timestamp when the link was last updated")


class GetAllSavedLinksResponse(BaseModel):
    """Response model for getting saved links with folders and pagination."""
    
    folder_id: Optional[str] = Field(default=None, description="Current folder ID (nullable for root)")
    user_id: str = Field(..., description="User ID (UUID)")
    sub_folders: List[FolderResponse] = Field(..., description="List of sub-folders in the current folder")
    saved_links: List[SavedLinkResponse] = Field(..., description="List of saved links")
    total: int = Field(..., description="Total number of saved links for the user in this folder")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")
    has_next: bool = Field(..., description="Whether there are more links to fetch")


class CreateLinkFolderRequest(BaseModel):
    """Request model for creating a link folder."""
    
    parent_folder_id: Optional[str] = Field(default=None, description="Parent folder ID (nullable for root folders)")
    name: str = Field(..., min_length=1, max_length=50, description="Folder name (max 50 characters)")


class FolderWithSubFoldersResponse(BaseModel):
    """Response model for a folder with nested sub-folders (recursive structure)."""
    
    id: str = Field(..., description="Folder ID (UUID)")
    name: str = Field(..., description="Folder name")
    created_at: str = Field(..., description="ISO format timestamp when the folder was created")
    updated_at: str = Field(..., description="ISO format timestamp when the folder was last updated")
    subFolders: List["FolderWithSubFoldersResponse"] = Field(default_factory=list, description="List of sub-folders (recursive)")


class GetAllFoldersResponse(BaseModel):
    """Response model for getting all folders in hierarchical structure."""
    
    folders: List[FolderWithSubFoldersResponse] = Field(..., description="List of root folders with nested sub-folders")


class CreateFolderRequest(BaseModel):
    """Request model for creating a folder."""
    
    name: str = Field(..., min_length=1, max_length=50, description="Folder name (max 50 characters)")
    parentId: Optional[str] = Field(default=None, description="Parent folder ID (optional, UUID format)")


class CreateFolderResponse(BaseModel):
    """Response model for a created folder with user information."""
    
    id: str = Field(..., description="Folder ID (UUID)")
    name: str = Field(..., description="Folder name")
    parent_id: Optional[str] = Field(default=None, description="Parent folder ID (nullable)")
    user_id: str = Field(..., description="User ID who owns the folder (UUID)")
    created_at: str = Field(..., description="ISO format timestamp when the folder was created")
    updated_at: str = Field(..., description="ISO format timestamp when the folder was last updated")
    user: "UserInfo" = Field(..., description="User information (id, name, email, role)")


class RenameFolderRequest(BaseModel):
    """Request model for renaming a folder."""
    
    name: str = Field(..., min_length=1, max_length=50, description="New folder name (max 50 characters)")


class RenameFolderResponse(BaseModel):
    """Response model for a renamed folder."""
    
    id: str = Field(..., description="Folder ID (UUID)")
    name: str = Field(..., description="Folder name")
    parent_id: Optional[str] = Field(default=None, description="Parent folder ID (nullable)")
    user_id: str = Field(..., description="User ID who owns the folder (UUID)")
    created_at: str = Field(..., description="ISO format timestamp when the folder was created")
    updated_at: str = Field(..., description="ISO format timestamp when the folder was last updated")


# Update forward reference for recursive model
FolderWithSubFoldersResponse.model_rebuild()
CreateFolderResponse.model_rebuild()


class UserRole(str, Enum):
    """User role enum."""
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


class IssueType(str, Enum):
    """Issue type enum."""
    GLITCH = "GLITCH"
    SUBSCRIPTION = "SUBSCRIPTION"
    AUTHENTICATION = "AUTHENTICATION"
    FEATURE_REQUEST = "FEATURE_REQUEST"
    OTHERS = "OTHERS"


class IssueStatus(str, Enum):
    """Issue status enum."""
    OPEN = "OPEN"
    WORK_IN_PROGRESS = "WORK_IN_PROGRESS"
    DISCARDED = "DISCARDED"
    RESOLVED = "RESOLVED"


class UpdateIssueRequest(BaseModel):
    """Request model for updating an issue (PATCH)."""
    status: IssueStatus = Field(..., description="Issue status (OPEN, WORK_IN_PROGRESS, DISCARDED, RESOLVED)")


class EntityType(str, Enum):
    """Entity type enum for file uploads."""
    ISSUE = "ISSUE"


class FileType(str, Enum):
    """File type enum for file uploads."""
    IMAGE = "IMAGE"
    PDF = "PDF"


class FileUploadResponse(BaseModel):
    """Response model for a file upload."""
    
    id: str = Field(..., description="File upload ID (UUID)")
    file_name: str = Field(..., description="File name")
    file_type: str = Field(..., description="File type (IMAGE or PDF)")
    entity_type: str = Field(..., description="Entity type (ISSUE)")
    entity_id: str = Field(..., description="Entity ID (UUID)")
    s3_url: Optional[str] = Field(default=None, description="S3 URL for the file")
    metadata: Optional[dict] = Field(default=None, description="Optional metadata JSON")
    created_at: str = Field(..., description="ISO format timestamp when the file was uploaded")
    updated_at: str = Field(..., description="ISO format timestamp when the file was last updated")


class ReportIssueRequest(BaseModel):
    """Request model for reporting an issue."""
    
    type: IssueType = Field(..., description="Issue type (mandatory)")
    heading: Optional[str] = Field(default=None, max_length=100, description="Issue heading (optional, max 100 characters)")
    description: str = Field(..., min_length=1, description="Issue description (mandatory)")
    webpage_url: Optional[str] = Field(default=None, max_length=1024, description="Webpage URL where the issue occurred (optional, max 1024 characters)")


class IssueResponse(BaseModel):
    """Response model for an issue."""
    
    id: str = Field(..., description="Issue ID (UUID)")
    ticket_id: str = Field(..., description="14-character ticket ID")
    type: str = Field(..., description="Issue type")
    heading: Optional[str] = Field(default=None, description="Issue heading")
    description: str = Field(..., description="Issue description")
    webpage_url: Optional[str] = Field(default=None, description="Webpage URL where the issue occurred")
    status: str = Field(..., description="Issue status")
    created_by: str = Field(..., description="User ID who created the issue (UUID)")
    closed_by: Optional[str] = Field(default=None, description="User ID who closed the issue (UUID)")
    closed_at: Optional[str] = Field(default=None, description="ISO format timestamp when the issue was closed")
    created_at: str = Field(..., description="ISO format timestamp when the issue was created")
    updated_at: str = Field(..., description="ISO format timestamp when the issue was last updated")
    file_uploads: List[FileUploadResponse] = Field(default_factory=list, description="List of file uploads associated with the issue")


class GetMyIssuesResponse(BaseModel):
    """Response model for getting user's issues."""
    
    issues: List[IssueResponse] = Field(..., description="List of issues")


class GetAllIssuesResponse(BaseModel):
    """Response model for getting all issues (admin endpoint)."""
    
    issues: List[IssueResponse] = Field(..., description="List of all issues")
    total: int = Field(..., description="Total number of issues matching the filters")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")
    has_next: bool = Field(..., description="Whether there are more issues to fetch")


class GetIssueByTicketIdResponse(BaseModel):
    """Response model for getting an issue by ticket_id with user information."""
    
    id: str = Field(..., description="Issue ID (UUID)")
    ticket_id: str = Field(..., description="14-character ticket ID")
    type: str = Field(..., description="Issue type")
    heading: Optional[str] = Field(default=None, description="Issue heading")
    description: str = Field(..., description="Issue description")
    webpage_url: Optional[str] = Field(default=None, description="Webpage URL where the issue occurred")
    status: str = Field(..., description="Issue status")
    created_by: "CreatedByUser" = Field(..., description="User who created the issue")
    closed_by: Optional["CreatedByUser"] = Field(default=None, description="User who closed the issue")
    closed_at: Optional[str] = Field(default=None, description="ISO format timestamp when the issue was closed")
    created_at: str = Field(..., description="ISO format timestamp when the issue was created")
    updated_at: str = Field(..., description="ISO format timestamp when the issue was last updated")
    file_uploads: List[FileUploadResponse] = Field(default_factory=list, description="List of file uploads associated with the issue")


class CommentVisibility(str, Enum):
    """Comment visibility enum."""
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"


class CreatedByUser(BaseModel):
    """Model for user who created a comment."""
    
    id: str = Field(..., description="User ID (UUID)")
    name: str = Field(..., description="User's full name")
    role: Optional[str] = Field(default=None, description="User role (ADMIN, SUPER_ADMIN, or None)")
    profileIconUrl: Optional[str] = Field(default=None, description="User's profile icon URL from Google auth")


class DomainCreatedByUser(BaseModel):
    """Model for user who created a domain."""
    
    id: str = Field(..., description="User ID (UUID)")
    name: str = Field(..., description="User's full name")
    role: Optional[str] = Field(default=None, description="User role (ADMIN, SUPER_ADMIN, or None)")
    email: Optional[str] = Field(default=None, description="User's email address")


class CommentResponse(BaseModel):
    """Response model for a comment with nested child comments."""
    
    id: str = Field(..., description="Comment ID (UUID)")
    content: str = Field(..., description="Comment content")
    visibility: str = Field(..., description="Comment visibility (PUBLIC or INTERNAL)")
    child_comments: List["CommentResponse"] = Field(default_factory=list, description="Nested child comments")
    created_by: CreatedByUser = Field(..., description="User who created the comment")
    created_at: str = Field(..., description="ISO format timestamp when the comment was created")
    updated_at: str = Field(..., description="ISO format timestamp when the comment was last updated")


class GetCommentsResponse(BaseModel):
    """Response model for getting comments by entity."""
    
    comments: List[CommentResponse] = Field(..., description="List of root comments with nested children")


class CreateCommentRequest(BaseModel):
    """Request model for creating a comment."""
    
    entity_type: EntityType = Field(..., description="Entity type (ISSUE)")
    entity_id: str = Field(..., description="Entity ID (UUID)")
    content: str = Field(..., min_length=1, max_length=1024, description="Comment content (max 1024 characters)")
    visibility: CommentVisibility = Field(..., description="Comment visibility (PUBLIC or INTERNAL)")
    parent_comment_id: Optional[str] = Field(default=None, description="Parent comment ID for nested replies (nullable)")


class CreateCommentResponse(BaseModel):
    """Response model for a created comment."""
    
    id: str = Field(..., description="Comment ID (UUID)")
    content: str = Field(..., description="Comment content")
    entity_type: str = Field(..., description="Entity type")
    entity_id: str = Field(..., description="Entity ID (UUID)")
    parent_comment_id: Optional[str] = Field(default=None, description="Parent comment ID (nullable)")
    visibility: str = Field(..., description="Comment visibility (PUBLIC or INTERNAL)")
    created_by: CreatedByUser = Field(..., description="User who created the comment")
    created_at: str = Field(..., description="ISO format timestamp when the comment was created")
    updated_at: str = Field(..., description="ISO format timestamp when the comment was last updated")


# Rebuild models to resolve forward references
CommentResponse.model_rebuild()
GetIssueByTicketIdResponse.model_rebuild()


class RecurringPeriod(str, Enum):
    """Recurring period enum."""
    MONTH = "MONTH"
    YEAR = "YEAR"


class PricingStatus(str, Enum):
    """Pricing status enum."""
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class Currency(str, Enum):
    """Currency enum."""
    USD = "USD"


class MaxAllowedType(str, Enum):
    """Max allowed type enum for pricing features."""
    FIXED = "FIXED"
    UNLIMITED = "UNLIMITED"


class PricingFeature(BaseModel):
    """Model for a pricing feature."""
    
    name: str = Field(..., min_length=1, description="Feature name")
    is_allowed: bool = Field(..., description="Whether the feature is allowed")
    max_allowed_type: Optional[MaxAllowedType] = Field(default=None, description="Max allowed type (FIXED or UNLIMITED), null if is_allowed is false")
    max_allowed_count: Optional[int] = Field(default=None, gt=0, description="Max allowed count (must be > 0), null if max_allowed_type is UNLIMITED or is_allowed is false")


class Discount(BaseModel):
    """Model for discount information."""
    
    discount_percentage: float = Field(..., ge=0, le=100, description="Discount percentage (0-100)")
    discount_valid_till: str = Field(..., description="Discount valid until timestamp (ISO format)")


class PricingDetails(BaseModel):
    """Model for pricing details JSON structure."""
    
    monthly_price: float = Field(..., gt=0, description="Monthly price (must be > 0)")
    monthly_discount: Discount = Field(..., description="Monthly discount details")
    is_yearly_enabled: bool = Field(..., description="Whether yearly pricing is enabled")
    yearly_discount: Optional[Discount] = Field(default=None, description="Yearly discount details (null if is_yearly_enabled is false)")


class CreatePricingRequest(BaseModel):
    """Request model for creating a pricing."""
    
    name: str = Field(..., min_length=1, max_length=30, description="Pricing name (max 30 characters)")
    activation: str = Field(..., description="Activation timestamp (ISO format)")
    expiry: str = Field(..., description="Expiry timestamp (ISO format)")
    status: PricingStatus = Field(..., description="Pricing status (ENABLED or DISABLED)")
    features: List[PricingFeature] = Field(..., min_items=1, description="Pricing features (array of feature objects)")
    currency: Currency = Field(..., description="Currency (USD)")
    pricing_details: PricingDetails = Field(..., description="Pricing details including monthly/yearly prices and discounts")
    description: str = Field(..., min_length=1, max_length=500, description="Pricing description (max 500 characters)")
    is_highlighted: Optional[bool] = Field(default=None, description="Whether this pricing plan is highlighted")


class UpdatePricingRequest(BaseModel):
    """Request model for updating a pricing (PATCH - all fields optional)."""
    
    name: Optional[str] = Field(default=None, min_length=1, max_length=30, description="Pricing name (max 30 characters)")
    activation: Optional[str] = Field(default=None, description="Activation timestamp (ISO format)")
    expiry: Optional[str] = Field(default=None, description="Expiry timestamp (ISO format)")
    status: Optional[PricingStatus] = Field(default=None, description="Pricing status (ENABLED or DISABLED)")
    features: Optional[List[PricingFeature]] = Field(default=None, min_items=1, description="Pricing features (array of feature objects)")
    currency: Optional[Currency] = Field(default=None, description="Currency (USD)")
    pricing_details: Optional[PricingDetails] = Field(default=None, description="Pricing details including monthly/yearly prices and discounts")
    description: Optional[str] = Field(default=None, min_length=1, max_length=500, description="Pricing description (max 500 characters)")
    is_highlighted: Optional[bool] = Field(default=None, description="Whether this pricing plan is highlighted")


class PricingResponse(BaseModel):
    """Response model for a pricing."""
    
    id: str = Field(..., description="Pricing ID (UUID)")
    name: str = Field(..., description="Pricing name")
    activation: str = Field(..., description="Activation timestamp (ISO format)")
    expiry: str = Field(..., description="Expiry timestamp (ISO format)")
    status: str = Field(..., description="Pricing status (ENABLED or DISABLED)")
    features: List[Dict] = Field(..., description="Pricing features (array of feature objects)")
    currency: str = Field(..., description="Currency (USD)")
    pricing_details: Dict = Field(..., description="Pricing details including monthly/yearly prices and discounts")
    description: str = Field(..., description="Pricing description")
    is_highlighted: Optional[bool] = Field(default=None, description="Whether this pricing plan is highlighted")
    created_by: CreatedByUser = Field(..., description="User who created the pricing")
    created_at: str = Field(..., description="ISO format timestamp when the pricing was created")
    updated_at: str = Field(..., description="ISO format timestamp when the pricing was last updated")


class GetAllPricingsResponse(BaseModel):
    """Response model for getting all pricings."""
    
    pricings: List[PricingResponse] = Field(..., description="List of all pricings")


class GetLivePricingsResponse(BaseModel):
    """Response model for getting live pricings."""
    
    pricings: List[PricingResponse] = Field(..., description="List of live pricings")


class DomainStatus(str, Enum):
    """Domain status enum."""
    ALLOWED = "ALLOWED"
    BANNED = "BANNED"


class CreateDomainRequest(BaseModel):
    """Request model for creating a domain."""
    
    url: str = Field(..., min_length=1, max_length=100, description="Domain URL (max 100 characters, no http/https or paths)")
    status: Optional[DomainStatus] = Field(default=DomainStatus.ALLOWED, description="Domain status (ALLOWED or BANNED, defaults to ALLOWED)")


class UpdateDomainRequest(BaseModel):
    """Request model for updating a domain (PATCH - all fields optional)."""
    
    url: Optional[str] = Field(default=None, min_length=1, max_length=100, description="Domain URL (max 100 characters, no http/https or paths)")
    status: Optional[DomainStatus] = Field(default=None, description="Domain status (ALLOWED or BANNED)")


class DomainResponse(BaseModel):
    """Response model for a domain."""
    
    id: str = Field(..., description="Domain ID (UUID)")
    url: str = Field(..., description="Domain URL")
    status: str = Field(..., description="Domain status (ALLOWED or BANNED)")
    created_by: DomainCreatedByUser = Field(..., description="User who created the domain")
    created_at: str = Field(..., description="ISO format timestamp when the domain was created")
    updated_at: str = Field(..., description="ISO format timestamp when the domain was last updated")


class GetAllDomainsResponse(BaseModel):
    """Response model for getting all domains."""
    
    domains: List[DomainResponse] = Field(..., description="List of all domains")
    total: int = Field(..., description="Total number of domains")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")
    has_next: bool = Field(..., description="Whether there are more domains to fetch")


class CreateSavedImageRequest(BaseModel):
    """Request model for creating a saved image."""
    
    imageUrl: str = Field(..., min_length=1, max_length=1024, description="Image URL (max 1024 characters)")
    sourceUrl: str = Field(..., min_length=1, max_length=1024, description="Source URL where the image was found (max 1024 characters)")
    folderId: str = Field(..., description="Folder ID where the image will be saved (UUID)")
    name: Optional[str] = Field(default=None, max_length=100, description="Optional name for the image (max 100 characters)")


class SavedImageCreatedByUser(BaseModel):
    """Model for user who created a saved image."""
    
    id: str = Field(..., description="User ID (UUID)")
    email: str = Field(..., description="User's email address")
    name: str = Field(..., description="User's full name")


class SavedImageResponse(BaseModel):
    """Response model for a saved image."""
    
    id: str = Field(..., description="Saved image ID (UUID)")
    sourceUrl: str = Field(..., description="Source URL where the image was found")
    imageUrl: str = Field(..., description="Image URL")
    name: Optional[str] = Field(default=None, description="Optional name for the image")
    folderId: str = Field(..., description="Folder ID where the image is saved (UUID)")
    userId: str = Field(..., description="User ID who saved the image (UUID)")
    createdAt: str = Field(..., description="ISO format timestamp when the image was saved")
    updatedAt: str = Field(..., description="ISO format timestamp when the image was last updated")
    createdBy: SavedImageCreatedByUser = Field(..., description="User who created the saved image")


class GetAllSavedImagesResponse(BaseModel):
    """Response model for getting all saved images."""
    
    images: List[SavedImageResponse] = Field(..., description="List of saved images")
    total: int = Field(..., description="Total number of saved images for the user in this folder")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")
    has_next: bool = Field(..., description="Whether there are more images to fetch")


class MoveSavedImageToFolderRequest(BaseModel):
    """Request model for moving a saved image to a different folder."""
    
    newFolderId: str = Field(..., description="New folder ID to move the image to (UUID)")


class MoveSavedWordToFolderRequest(BaseModel):
    """Request model for moving a saved word to a different folder."""
    
    targetFolderId: str = Field(..., description="Target folder ID to move the word to (UUID)")


class MoveSavedParagraphToFolderRequest(BaseModel):
    """Request model for moving a saved paragraph to a different folder."""
    
    targetFolderId: str = Field(..., description="Target folder ID to move the paragraph to (UUID)")


class MoveSavedLinkToFolderRequest(BaseModel):
    """Request model for moving a saved link to a different folder."""
    
    targetFolderId: str = Field(..., description="Target folder ID to move the link to (UUID)")


class NativeLanguage(str, Enum):
    """Native language enum with all supported language codes."""
    EN = "EN"
    ES = "ES"
    FR = "FR"
    DE = "DE"
    HI = "HI"
    JA = "JA"
    ZH = "ZH"
    AR = "AR"
    IT = "IT"
    PT = "PT"
    RU = "RU"
    KO = "KO"
    NL = "NL"
    PL = "PL"
    TR = "TR"
    VI = "VI"
    TH = "TH"
    ID = "ID"
    CS = "CS"
    SV = "SV"
    DA = "DA"
    NO = "NO"
    FI = "FI"
    EL = "EL"
    HE = "HE"
    UK = "UK"
    RO = "RO"
    HU = "HU"
    BG = "BG"  # Bulgarian
    HR = "HR"  # Croatian
    SK = "SK"  # Slovak
    SL = "SL"  # Slovenian
    ET = "ET"  # Estonian
    LV = "LV"  # Latvian
    LT = "LT"  # Lithuanian
    IS = "IS"  # Icelandic
    GA = "GA"  # Irish
    MT = "MT"  # Maltese
    EU = "EU"  # Basque
    CA = "CA"  # Catalan
    FA = "FA"  # Persian
    UR = "UR"  # Urdu
    BN = "BN"  # Bengali
    TA = "TA"  # Tamil
    TE = "TE"  # Telugu
    ML = "ML"  # Malayalam
    KN = "KN"  # Kannada
    GU = "GU"  # Gujarati
    MR = "MR"  # Marathi
    PA = "PA"  # Punjabi
    NE = "NE"  # Nepali
    SI = "SI"  # Sinhala
    OR = "OR"  # Odia
    MY = "MY"  # Burmese
    KM = "KM"  # Khmer
    LO = "LO"  # Lao
    MS = "MS"  # Malay
    TL = "TL"  # Tagalog
    SW = "SW"  # Swahili
    AF = "AF"  # Afrikaans
    ZU = "ZU"  # Zulu
    XH = "XH"  # Xhosa


class PageTranslationView(str, Enum):
    """Page translation view enum."""
    APPEND = "APPEND"
    REPLACE = "REPLACE"


class Theme(str, Enum):
    """Theme enum."""
    LIGHT = "LIGHT"
    DARK = "DARK"


class Settings(BaseModel):
    """User settings model."""
    
    nativeLanguage: Optional[NativeLanguage] = Field(default=None, description="Native language code (e.g., 'EN', 'ES', 'FR', 'DE', 'HI')")
    pageTranslationView: PageTranslationView = Field(..., description="Page translation view mode (APPEND or REPLACE)")
    theme: Theme = Field(..., description="Theme preference (LIGHT or DARK)")


class UpdateSettingsRequest(BaseModel):
    """Request model for updating user settings (PATCH)."""
    
    nativeLanguage: Optional[NativeLanguage] = Field(default=None, description="Native language code (e.g., 'EN', 'ES', 'FR', 'DE', 'HI')")
    pageTranslationView: PageTranslationView = Field(..., description="Page translation view mode (APPEND or REPLACE)")
    theme: Theme = Field(..., description="Theme preference (LIGHT or DARK)")


class SettingsResponse(BaseModel):
    """Response model for user settings."""
    
    nativeLanguage: Optional[NativeLanguage] = Field(default=None, description="Native language code (e.g., 'EN', 'ES', 'FR', 'DE', 'HI')")
    pageTranslationView: PageTranslationView = Field(..., description="Page translation view mode (APPEND or REPLACE)")
    theme: Theme = Field(..., description="Theme preference (LIGHT or DARK)")


# Default user settings constant
DEFAULT_USER_SETTINGS = {
    "nativeLanguage": None,
    "pageTranslationView": "REPLACE",
    "theme": "LIGHT"
}


class UserSettingsResponse(BaseModel):
    """Response model for getting user settings with user ID."""
    
    userId: str = Field(..., description="User ID (UUID)")
    settings: SettingsResponse = Field(..., description="User settings")


class LanguageInfo(BaseModel):
    """Language information model."""
    
    languageCode: str = Field(..., description="ISO 639-1 language code (e.g., 'EN', 'ES', 'FR')")
    languageNameInEnglish: str = Field(..., description="Language name in English")
    languageNameInNative: str = Field(..., description="Language name in that particular language")


class GetAllLanguagesResponse(BaseModel):
    """Response model for getting all languages."""
    
    languages: List[LanguageInfo] = Field(..., description="List of all supported languages")


# Language mapper: language code -> {name in English, name in native language}
LANGUAGE_MAPPER: Dict[str, Dict[str, str]] = {
    "EN": {"nameInEnglish": "English", "nameInNative": "English"},
    "ES": {"nameInEnglish": "Spanish", "nameInNative": "Español"},
    "FR": {"nameInEnglish": "French", "nameInNative": "Français"},
    "DE": {"nameInEnglish": "German", "nameInNative": "Deutsch"},
    "HI": {"nameInEnglish": "Hindi", "nameInNative": "हिन्दी"},
    "JA": {"nameInEnglish": "Japanese", "nameInNative": "日本語"},
    "ZH": {"nameInEnglish": "Chinese", "nameInNative": "中文"},
    "AR": {"nameInEnglish": "Arabic", "nameInNative": "العربية"},
    "IT": {"nameInEnglish": "Italian", "nameInNative": "Italiano"},
    "PT": {"nameInEnglish": "Portuguese", "nameInNative": "Português"},
    "RU": {"nameInEnglish": "Russian", "nameInNative": "Русский"},
    "KO": {"nameInEnglish": "Korean", "nameInNative": "한국어"},
    "NL": {"nameInEnglish": "Dutch", "nameInNative": "Nederlands"},
    "PL": {"nameInEnglish": "Polish", "nameInNative": "Polski"},
    "TR": {"nameInEnglish": "Turkish", "nameInNative": "Türkçe"},
    "VI": {"nameInEnglish": "Vietnamese", "nameInNative": "Tiếng Việt"},
    "TH": {"nameInEnglish": "Thai", "nameInNative": "ไทย"},
    "ID": {"nameInEnglish": "Indonesian", "nameInNative": "Bahasa Indonesia"},
    "CS": {"nameInEnglish": "Czech", "nameInNative": "Čeština"},
    "SV": {"nameInEnglish": "Swedish", "nameInNative": "Svenska"},
    "DA": {"nameInEnglish": "Danish", "nameInNative": "Dansk"},
    "NO": {"nameInEnglish": "Norwegian", "nameInNative": "Norsk"},
    "FI": {"nameInEnglish": "Finnish", "nameInNative": "Suomi"},
    "EL": {"nameInEnglish": "Greek", "nameInNative": "Ελληνικά"},
    "HE": {"nameInEnglish": "Hebrew", "nameInNative": "עברית"},
    "UK": {"nameInEnglish": "Ukrainian", "nameInNative": "Українська"},
    "RO": {"nameInEnglish": "Romanian", "nameInNative": "Română"},
    "HU": {"nameInEnglish": "Hungarian", "nameInNative": "Magyar"},
    "BG": {"nameInEnglish": "Bulgarian", "nameInNative": "Български"},
    "HR": {"nameInEnglish": "Croatian", "nameInNative": "Hrvatski"},
    "SK": {"nameInEnglish": "Slovak", "nameInNative": "Slovenčina"},
    "SL": {"nameInEnglish": "Slovenian", "nameInNative": "Slovenščina"},
    "ET": {"nameInEnglish": "Estonian", "nameInNative": "Eesti"},
    "LV": {"nameInEnglish": "Latvian", "nameInNative": "Latviešu"},
    "LT": {"nameInEnglish": "Lithuanian", "nameInNative": "Lietuvių"},
    "IS": {"nameInEnglish": "Icelandic", "nameInNative": "Íslenska"},
    "GA": {"nameInEnglish": "Irish", "nameInNative": "Gaeilge"},
    "MT": {"nameInEnglish": "Maltese", "nameInNative": "Malti"},
    "EU": {"nameInEnglish": "Basque", "nameInNative": "Euskara"},
    "CA": {"nameInEnglish": "Catalan", "nameInNative": "Català"},
    "FA": {"nameInEnglish": "Persian", "nameInNative": "فارسی"},
    "UR": {"nameInEnglish": "Urdu", "nameInNative": "اردو"},
    "BN": {"nameInEnglish": "Bengali", "nameInNative": "বাংলা"},
    "TA": {"nameInEnglish": "Tamil", "nameInNative": "தமிழ்"},
    "TE": {"nameInEnglish": "Telugu", "nameInNative": "తెలుగు"},
    "ML": {"nameInEnglish": "Malayalam", "nameInNative": "മലയാളം"},
    "KN": {"nameInEnglish": "Kannada", "nameInNative": "ಕನ್ನಡ"},
    "GU": {"nameInEnglish": "Gujarati", "nameInNative": "ગુજરાતી"},
    "MR": {"nameInEnglish": "Marathi", "nameInNative": "मराठी"},
    "PA": {"nameInEnglish": "Punjabi", "nameInNative": "ਪੰਜਾਬੀ"},
    "NE": {"nameInEnglish": "Nepali", "nameInNative": "नेपाली"},
    "SI": {"nameInEnglish": "Sinhala", "nameInNative": "සිංහල"},
    "OR": {"nameInEnglish": "Odia", "nameInNative": "ଓଡ଼ିଆ"},
    "MY": {"nameInEnglish": "Burmese", "nameInNative": "မြန်မာ"},
    "KM": {"nameInEnglish": "Khmer", "nameInNative": "ខ្មែរ"},
    "LO": {"nameInEnglish": "Lao", "nameInNative": "ລາວ"},
    "MS": {"nameInEnglish": "Malay", "nameInNative": "Bahasa Melayu"},
    "TL": {"nameInEnglish": "Tagalog", "nameInNative": "Tagalog"},
    "SW": {"nameInEnglish": "Swahili", "nameInNative": "Kiswahili"},
    "AF": {"nameInEnglish": "Afrikaans", "nameInNative": "Afrikaans"},
    "ZU": {"nameInEnglish": "Zulu", "nameInNative": "isiZulu"},
    "XH": {"nameInEnglish": "Xhosa", "nameInNative": "isiXhosa"},
}


class PdfResponse(BaseModel):
    """Response model for PDF record."""
    
    id: str = Field(..., description="PDF ID (UUID)")
    file_name: str = Field(..., description="File name")
    created_by: str = Field(..., description="User ID who created the PDF (UUID)")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")


class PdfHtmlPageResponse(BaseModel):
    """Response model for PDF HTML page."""
    
    id: str = Field(..., description="PDF HTML page ID (UUID)")
    page_no: int = Field(..., description="Page number (1-indexed)")
    pdf_id: str = Field(..., description="PDF ID (UUID)")
    html_content: str = Field(..., description="HTML content for the page")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")


class GetAllPdfsResponse(BaseModel):
    """Response model for getting all PDFs."""
    
    pdfs: List[PdfResponse] = Field(..., description="List of PDF records")


class GetPdfHtmlPagesResponse(BaseModel):
    """Response model for getting paginated PDF HTML pages."""
    
    pages: List[PdfHtmlPageResponse] = Field(..., description="List of PDF HTML pages")
    total: int = Field(..., description="Total number of pages")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")
    has_next: bool = Field(..., description="Whether there are more pages")


class CouponStatus(str, Enum):
    """Coupon status enum."""
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class CreateCouponRequest(BaseModel):
    """Request model for creating a coupon."""
    
    code: str = Field(..., min_length=1, max_length=30, description="Coupon code (max 30 characters)")
    name: str = Field(..., min_length=1, max_length=100, description="Coupon name (max 100 characters)")
    description: str = Field(..., min_length=1, max_length=1024, description="Coupon description (max 1024 characters)")
    discount: float = Field(..., gt=0, le=100, description="Discount percentage (must be > 0 and <= 100)")
    activation: str = Field(..., description="Activation timestamp (ISO format)")
    expiry: str = Field(..., description="Expiry timestamp (ISO format)")
    status: CouponStatus = Field(..., description="Coupon status (ACTIVE or INACTIVE)")


class UpdateCouponRequest(BaseModel):
    """Request model for updating a coupon (PUT - all fields)."""
    
    code: Optional[str] = Field(default=None, min_length=1, max_length=30, description="Coupon code (max 30 characters)")
    name: Optional[str] = Field(default=None, min_length=1, max_length=100, description="Coupon name (max 100 characters)")
    description: Optional[str] = Field(default=None, min_length=1, max_length=1024, description="Coupon description (max 1024 characters)")
    discount: Optional[float] = Field(default=None, gt=0, le=100, description="Discount percentage (must be > 0 and <= 100)")
    activation: Optional[str] = Field(default=None, description="Activation timestamp (ISO format)")
    expiry: Optional[str] = Field(default=None, description="Expiry timestamp (ISO format)")
    status: Optional[CouponStatus] = Field(default=None, description="Coupon status (ACTIVE or INACTIVE)")
    is_highlighted: Optional[bool] = Field(default=None, description="Whether the coupon is highlighted")


class CouponResponse(BaseModel):
    """Response model for a coupon."""
    
    id: str = Field(..., description="Coupon ID (UUID)")
    code: str = Field(..., description="Coupon code")
    name: str = Field(..., description="Coupon name")
    description: str = Field(..., description="Coupon description")
    discount: float = Field(..., description="Discount percentage")
    activation: str = Field(..., description="Activation timestamp (ISO format)")
    expiry: str = Field(..., description="Expiry timestamp (ISO format)")
    status: str = Field(..., description="Coupon status (ACTIVE or INACTIVE)")
    is_highlighted: bool = Field(..., description="Whether the coupon is highlighted")
    created_by: UserInfo = Field(..., description="User who created the coupon")
    created_at: str = Field(..., description="ISO format timestamp when the coupon was created")
    updated_at: str = Field(..., description="ISO format timestamp when the coupon was last updated")


class GetAllCouponsResponse(BaseModel):
    """Response model for getting all coupons with pagination."""
    
    coupons: List[CouponResponse] = Field(..., description="List of coupons")
    total: int = Field(..., description="Total number of coupons matching the filters")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")
    has_next: bool = Field(..., description="Whether there are more coupons to fetch")


class GetActiveHighlightedCouponResponse(BaseModel):
    """Response model for getting active highlighted coupon."""
    
    code: Optional[str] = Field(default=None, description="Response code: 'NO_ACTIVE_HIGHLIGHTED_COUPON' if no coupon found, otherwise None")
    id: Optional[str] = Field(default=None, description="Coupon ID (UUID)")
    coupon_code: Optional[str] = Field(default=None, description="Coupon code")
    name: Optional[str] = Field(default=None, description="Coupon name")
    description: Optional[str] = Field(default=None, description="Coupon description")
    discount: Optional[float] = Field(default=None, description="Discount percentage")
    activation: Optional[str] = Field(default=None, description="Activation timestamp (ISO format)")
    expiry: Optional[str] = Field(default=None, description="Expiry timestamp (ISO format)")
    status: Optional[str] = Field(default=None, description="Coupon status (ACTIVE or INACTIVE)")
    is_highlighted: Optional[bool] = Field(default=None, description="Whether the coupon is highlighted")


class ChatMessage(BaseModel):
    """Model for chat message in ask API."""
    
    role: str = Field(..., description="Role of the message sender (user/assistant)")
    content: str = Field(..., description="Content of the message")


class UserQuestionType(str, Enum):
    """User question type enum for ask-ai endpoint."""
    SHORT_SUMMARY = "SHORT_SUMMARY"
    DESCRIPTIVE_NOTE = "DESCRIPTIVE_NOTE"
    CUSTOM = "CUSTOM"


class AskSavedParagraphsRequest(BaseModel):
    """Request model for asking AI about saved paragraphs."""
    
    initialContext: List[str] = Field(..., min_items=1, description="Array of strings containing the context/content to analyze")
    chatHistory: List[ChatMessage] = Field(default=[], description="Previous chat history for context (can be empty)")
    userQuestionType: UserQuestionType = Field(..., description="Type of question: SHORT_SUMMARY, DESCRIPTIVE_NOTE, or CUSTOM")
    userQuestion: Optional[str] = Field(default=None, description="Custom user question (required when userQuestionType is CUSTOM, must have length > 0)")
    languageCode: Optional[str] = Field(default=None, max_length=10, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected.")


class AskSavedParagraphsResponse(BaseModel):
    """Response model for ask-ai endpoint."""
    
    answer: str = Field(..., description="AI-generated answer")


class Feature(BaseModel):
    """Model for a single feature."""
    
    name: str = Field(..., description="Feature name")
    description: str = Field(..., description="Feature description")


# =====================================================
# PADDLE BILLING MODELS
# =====================================================

class PaddleCustomerStatus(str, Enum):
    """Paddle customer status enum."""
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class PaddleSubscriptionStatus(str, Enum):
    """Paddle subscription status enum."""
    ACTIVE = "ACTIVE"
    CANCELED = "CANCELED"
    PAST_DUE = "PAST_DUE"
    PAUSED = "PAUSED"
    TRIALING = "TRIALING"


class PaddleTransactionStatus(str, Enum):
    """Paddle transaction status enum."""
    DRAFT = "DRAFT"
    READY = "READY"
    BILLED = "BILLED"
    PAID = "PAID"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    PAST_DUE = "PAST_DUE"


class PaddleBillingCycleInterval(str, Enum):
    """Paddle billing cycle interval enum."""
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    YEAR = "YEAR"


class PaddleAdjustmentAction(str, Enum):
    """Paddle adjustment action enum."""
    REFUND = "REFUND"
    CREDIT = "CREDIT"
    CHARGEBACK = "CHARGEBACK"
    CHARGEBACK_REVERSE = "CHARGEBACK_REVERSE"
    CHARGEBACK_WARNING = "CHARGEBACK_WARNING"


class PaddleAdjustmentStatus(str, Enum):
    """Paddle adjustment status enum."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PaddleWebhookEventType(str, Enum):
    """Paddle webhook event types that we handle."""
    # Subscription events
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_ACTIVATED = "subscription.activated"
    SUBSCRIPTION_CANCELED = "subscription.canceled"
    SUBSCRIPTION_PAST_DUE = "subscription.past_due"
    SUBSCRIPTION_PAUSED = "subscription.paused"
    SUBSCRIPTION_RESUMED = "subscription.resumed"
    SUBSCRIPTION_TRIALING = "subscription.trialing"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    SUBSCRIPTION_IMPORTED = "subscription.imported"
    
    # Transaction events
    TRANSACTION_BILLED = "transaction.billed"
    TRANSACTION_CANCELED = "transaction.canceled"
    TRANSACTION_COMPLETED = "transaction.completed"
    TRANSACTION_CREATED = "transaction.created"
    TRANSACTION_PAID = "transaction.paid"
    TRANSACTION_PAST_DUE = "transaction.past_due"
    TRANSACTION_PAYMENT_FAILED = "transaction.payment_failed"
    TRANSACTION_READY = "transaction.ready"
    TRANSACTION_UPDATED = "transaction.updated"
    TRANSACTION_REVISED = "transaction.revised"
    
    # Customer events
    CUSTOMER_CREATED = "customer.created"
    CUSTOMER_UPDATED = "customer.updated"
    CUSTOMER_IMPORTED = "customer.imported"
    
    # Adjustment events
    ADJUSTMENT_CREATED = "adjustment.created"
    ADJUSTMENT_UPDATED = "adjustment.updated"


class PaddleWebhookProcessingStatus(str, Enum):
    """Paddle webhook processing status enum."""
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class PaddleCustomerResponse(BaseModel):
    """Response model for Paddle customer."""
    
    id: str = Field(..., description="Internal ID (UUID)")
    paddle_customer_id: str = Field(..., description="Paddle customer ID")
    user_id: Optional[str] = Field(default=None, description="Linked user ID (UUID)")
    email: str = Field(..., description="Customer email")
    name: Optional[str] = Field(default=None, description="Customer name")
    locale: Optional[str] = Field(default=None, description="Customer locale")
    status: str = Field(..., description="Customer status (ACTIVE or ARCHIVED)")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")


class PaddleSubscriptionResponse(BaseModel):
    """Response model for Paddle subscription."""
    
    id: str = Field(..., description="Internal ID (UUID)")
    paddle_subscription_id: str = Field(..., description="Paddle subscription ID")
    paddle_customer_id: str = Field(..., description="Paddle customer ID")
    user_id: Optional[str] = Field(default=None, description="Linked user ID (UUID)")
    status: str = Field(..., description="Subscription status")
    currency_code: str = Field(..., description="Currency code (e.g., USD)")
    billing_cycle_interval: str = Field(..., description="Billing interval (DAY, WEEK, MONTH, YEAR)")
    billing_cycle_frequency: int = Field(..., description="Billing frequency")
    current_billing_period_starts_at: Optional[str] = Field(default=None, description="Current period start (ISO format)")
    current_billing_period_ends_at: Optional[str] = Field(default=None, description="Current period end (ISO format)")
    next_billed_at: Optional[str] = Field(default=None, description="Next billing date (ISO format)")
    paused_at: Optional[str] = Field(default=None, description="Pause date (ISO format)")
    canceled_at: Optional[str] = Field(default=None, description="Cancel date (ISO format)")
    items: List[Dict] = Field(..., description="Subscription items/products")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")


class PaddleTransactionResponse(BaseModel):
    """Response model for Paddle transaction."""
    
    id: str = Field(..., description="Internal ID (UUID)")
    paddle_transaction_id: str = Field(..., description="Paddle transaction ID")
    paddle_subscription_id: Optional[str] = Field(default=None, description="Paddle subscription ID")
    paddle_customer_id: str = Field(..., description="Paddle customer ID")
    user_id: Optional[str] = Field(default=None, description="Linked user ID (UUID)")
    status: str = Field(..., description="Transaction status")
    currency_code: str = Field(..., description="Currency code")
    subtotal: str = Field(..., description="Subtotal amount")
    tax: str = Field(..., description="Tax amount")
    total: str = Field(..., description="Total amount")
    grand_total: str = Field(..., description="Grand total")
    billed_at: Optional[str] = Field(default=None, description="Billing date (ISO format)")
    items: List[Dict] = Field(..., description="Transaction items")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")
    updated_at: str = Field(..., description="Last update timestamp (ISO format)")


class PaddleWebhookEventResponse(BaseModel):
    """Response model for Paddle webhook event."""
    
    id: str = Field(..., description="Internal ID (UUID)")
    paddle_event_id: str = Field(..., description="Paddle event ID")
    event_type: str = Field(..., description="Event type")
    occurred_at: str = Field(..., description="Event occurrence time (ISO format)")
    processing_status: str = Field(..., description="Processing status")
    processing_error: Optional[str] = Field(default=None, description="Processing error message")
    processed_at: Optional[str] = Field(default=None, description="Processing completion time (ISO format)")
    created_at: str = Field(..., description="Creation timestamp (ISO format)")


class PaddleWebhookResponse(BaseModel):
    """Response model for webhook acknowledgment."""
    
    status: str = Field(..., description="Processing status")
    event_id: Optional[str] = Field(default=None, description="Paddle event ID")
    message: Optional[str] = Field(default=None, description="Optional message")


class GetUserSubscriptionResponse(BaseModel):
    """Response model for getting user's active subscription."""
    
    has_active_subscription: bool = Field(..., description="Whether user has an active subscription")
    subscription: Optional[PaddleSubscriptionResponse] = Field(default=None, description="Active subscription details")
    customer: Optional[PaddleCustomerResponse] = Field(default=None, description="Customer details")


class EffectiveFrom(str, Enum):
    """When a subscription action takes effect."""
    IMMEDIATELY = "immediately"
    NEXT_BILLING_PERIOD = "next_billing_period"


class ProrationBillingMode(str, Enum):
    """How Paddle handles proration for subscription changes."""
    PRORATED_IMMEDIATELY = "prorated_immediately"
    PRORATED_NEXT_BILLING_PERIOD = "prorated_next_billing_period"
    FULL_IMMEDIATELY = "full_immediately"
    FULL_NEXT_BILLING_PERIOD = "full_next_billing_period"
    DO_NOT_BILL = "do_not_bill"


class CancelSubscriptionRequest(BaseModel):
    """Request model for cancelling a subscription."""
    
    effective_from: EffectiveFrom = Field(
        default=EffectiveFrom.NEXT_BILLING_PERIOD,
        description="When cancellation takes effect: 'immediately' or 'next_billing_period'"
    )


class SubscriptionItem(BaseModel):
    """Model for a subscription item (price + quantity)."""
    
    price_id: str = Field(..., description="Paddle price ID (pri_xxx)")
    quantity: int = Field(default=1, ge=1, description="Quantity of this item")


class UpdateSubscriptionRequest(BaseModel):
    """Request model for updating/upgrading/downgrading a subscription."""
    
    items: List[SubscriptionItem] = Field(
        ...,
        min_length=1,
        description="List of subscription items with price_id and quantity"
    )
    proration_billing_mode: ProrationBillingMode = Field(
        default=ProrationBillingMode.PRORATED_IMMEDIATELY,
        description="How to handle proration for the change"
    )


class PauseSubscriptionRequest(BaseModel):
    """Request model for pausing a subscription."""
    
    effective_from: EffectiveFrom = Field(
        default=EffectiveFrom.NEXT_BILLING_PERIOD,
        description="When pause takes effect: 'immediately' or 'next_billing_period'"
    )
    resume_at: Optional[str] = Field(
        default=None,
        description="Optional RFC 3339 datetime to automatically resume the subscription"
    )


class ResumeSubscriptionRequest(BaseModel):
    """Request model for resuming a paused subscription."""
    
    effective_from: EffectiveFrom = Field(
        default=EffectiveFrom.IMMEDIATELY,
        description="When resume takes effect: 'immediately' or 'next_billing_period'"
    )


class ScheduledChangeInfo(BaseModel):
    """Model for scheduled change information."""
    
    action: str = Field(..., description="Scheduled action (cancel, pause, resume)")
    effective_at: str = Field(..., description="When the change takes effect (ISO format)")
    resume_at: Optional[str] = Field(default=None, description="When subscription resumes (for pause)")


class SubscriptionActionResponse(BaseModel):
    """Response model for subscription action operations."""
    
    success: bool = Field(..., description="Whether the action was successful")
    paddle_subscription_id: str = Field(..., description="Paddle subscription ID")
    status: str = Field(..., description="Current subscription status")
    scheduled_change: Optional[ScheduledChangeInfo] = Field(
        default=None,
        description="Details of any scheduled change"
    )
    message: Optional[str] = Field(default=None, description="Additional information")


class PreviewSubscriptionUpdateRequest(BaseModel):
    """Request model for previewing a subscription update."""
    
    items: List[SubscriptionItem] = Field(
        ...,
        min_length=1,
        description="List of subscription items with price_id and quantity"
    )
    proration_billing_mode: ProrationBillingMode = Field(
        default=ProrationBillingMode.PRORATED_IMMEDIATELY,
        description="How to handle proration for the change"
    )


class PreviewSubscriptionUpdateResponse(BaseModel):
    """Response model for subscription update preview."""
    
    paddle_subscription_id: str = Field(..., description="Paddle subscription ID")
    immediate_transaction: Optional[Dict] = Field(
        default=None,
        description="Transaction that would be created immediately"
    )
    next_transaction: Optional[Dict] = Field(
        default=None,
        description="Preview of next scheduled transaction"
    )
    update_summary: Optional[Dict] = Field(
        default=None,
        description="Summary of prorated credits and charges"
    )


class FeaturesResponse(BaseModel):
    """Response model for features list."""
    
    features: List[Feature] = Field(..., description="List of available features")


class CreatePreLaunchUserRequest(BaseModel):
    """Request model for creating a pre-launch user."""
    
    email: str = Field(..., description="Email address of the pre-launch user")
    metaInfo: Optional[dict] = Field(default=None, description="Optional metadata information for the pre-launch user")


class PreLaunchUserResponse(BaseModel):
    """Response model for a pre-launch user."""
    
    id: str = Field(..., description="Pre-launch user ID (UUID)")
    email: str = Field(..., description="Email address of the pre-launch user")
    metaInfo: Optional[dict] = Field(default=None, description="Optional metadata information for the pre-launch user")
    createdAt: str = Field(..., description="ISO format timestamp when the pre-launch user was created")
    updatedAt: str = Field(..., description="ISO format timestamp when the pre-launch user was last updated")


class CreatePreLaunchUserApiResponse(BaseModel):
    """API response model for creating a pre-launch user, including duplicate-email handling."""
    
    code: Optional[str] = Field(
        default=None,
        description="Optional status/error code. 'EMAIL_ALREADY_EXISTS' when email is already registered."
    )
    user: Optional[PreLaunchUserResponse] = Field(
        default=None,
        description="Created or existing pre-launch user record"
    )
