"""Pydantic models for request/response validation."""

from typing import List, Optional
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
    contextual_meaning: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Contextual meaning or explanation of the word (max 1000 characters)"
    )


class SavedWordResponse(BaseModel):
    """Response model for a saved word."""
    
    id: str = Field(..., description="Saved word ID (UUID)")
    word: str = Field(..., description="The saved word")
    sourceUrl: str = Field(..., description="Source URL where the word was found")
    userId: str = Field(..., description="User ID who saved the word (UUID)")
    createdAt: str = Field(..., description="ISO format timestamp when the word was saved")
    contextual_meaning: str = Field(
        ...,
        description="Contextual meaning or explanation of the word when it was saved"
    )


class GetSavedWordsResponse(BaseModel):
    """Response model for getting saved words with pagination."""
    
    words: List[SavedWordResponse] = Field(..., description="List of saved words")
    total: int = Field(..., description="Total number of saved words for the user")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")


class FolderType(str, Enum):
    """Folder type enum."""
    PAGE = "PAGE"
    PARAGRAPH = "PARAGRAPH"


class SaveParagraphRequest(BaseModel):
    """Request model for saving a paragraph."""
    
    content: str = Field(..., min_length=1, description="Paragraph content")
    source_url: str = Field(..., min_length=1, max_length=1024, description="Source URL where the paragraph was found (max 1024 characters)")
    folder_id: Optional[str] = Field(default=None, description="Folder ID to save the paragraph in (nullable)")
    name: Optional[str] = Field(default=None, max_length=50, description="Optional name for the paragraph (max 50 characters)")


class CreateParagraphFolderRequest(BaseModel):
    """Request model for creating a paragraph folder."""
    
    parent_folder_id: Optional[str] = Field(default=None, description="Parent folder ID (nullable for root folders)")
    name: str = Field(..., min_length=1, max_length=50, description="Folder name (max 50 characters)")


class FolderResponse(BaseModel):
    """Response model for a folder."""
    
    id: str = Field(..., description="Folder ID (UUID)")
    name: str = Field(..., description="Folder name")
    type: str = Field(..., description="Folder type (PAGE or PARAGRAPH)")
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
    folder_id: Optional[str] = Field(default=None, description="Folder ID the paragraph is saved in (nullable)")
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


class SavePageRequest(BaseModel):
    """Request model for saving a page."""
    
    url: str = Field(..., min_length=1, max_length=1024, description="Page URL to save (max 1024 characters)")
    folder_id: Optional[str] = Field(default=None, description="Folder ID to save the page in (nullable)")
    name: Optional[str] = Field(default=None, max_length=50, description="Optional name for the page (max 50 characters)")


class SavedPageResponse(BaseModel):
    """Response model for a saved page."""
    
    id: str = Field(..., description="Saved page ID (UUID)")
    name: Optional[str] = Field(default=None, description="Optional name for the page")
    url: str = Field(..., description="Page URL")
    folder_id: Optional[str] = Field(default=None, description="Folder ID the page is saved in (nullable)")
    user_id: str = Field(..., description="User ID who saved the page (UUID)")
    created_at: str = Field(..., description="ISO format timestamp when the page was saved")
    updated_at: str = Field(..., description="ISO format timestamp when the page was last updated")


class GetAllSavedPagesResponse(BaseModel):
    """Response model for getting saved pages with folders and pagination."""
    
    folder_id: Optional[str] = Field(default=None, description="Current folder ID (nullable for root)")
    user_id: str = Field(..., description="User ID (UUID)")
    sub_folders: List[FolderResponse] = Field(..., description="List of sub-folders in the current folder")
    saved_pages: List[SavedPageResponse] = Field(..., description="List of saved pages")
    total: int = Field(..., description="Total number of saved pages for the user in this folder")
    offset: int = Field(..., description="Pagination offset")
    limit: int = Field(..., description="Pagination limit")
    has_next: bool = Field(..., description="Whether there are more pages to fetch")


class CreatePageFolderRequest(BaseModel):
    """Request model for creating a page folder."""
    
    parent_folder_id: Optional[str] = Field(default=None, description="Parent folder ID (nullable for root folders)")
    name: str = Field(..., min_length=1, max_length=50, description="Folder name (max 50 characters)")
