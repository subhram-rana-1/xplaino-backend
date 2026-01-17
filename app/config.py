"""Configuration management for the FastAPI application."""

import sys
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore extra fields from environment variables
    )
    
    # OpenAI Configuration
    openai_api_key: str = Field(..., description="OpenAI API key")
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    debug: bool = Field(default=False, description="Debug mode")
    log_level: str = Field(default="INFO", description="Logging level")
    
    # Rate Limiting Configuration
    enable_rate_limiting: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_requests_per_window: int = Field(default=10, description="Maximum number of requests allowed per time window")
    rate_limit_window_size_seconds: int = Field(default=10, description="Time window size in seconds for rate limiting")
    
    # File Upload Configuration
    max_file_size_mb: int = Field(default=2, description="Maximum file size in MB")
    max_image_file_size_mb: int = Field(default=5, description="Maximum image file size in MB for image-based APIs")
    allowed_image_types: str = Field(default="jpeg,jpg,png,heic,webp,gif,bmp", description="Allowed image types")
    allowed_pdf_types: str = Field(default="pdf", description="Allowed PDF types")
    
    @property
    def allowed_image_types_list(self) -> List[str]:
        """Get allowed image types as a list."""
        return [ext.strip().lower() for ext in self.allowed_image_types.split(",")]
    
    @property
    def allowed_pdf_types_list(self) -> List[str]:
        """Get allowed PDF types as a list."""
        return [ext.strip().lower() for ext in self.allowed_pdf_types.split(",")]
    
    @property
    def max_file_size_bytes(self) -> int:
        """Get maximum file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024
    
    @property
    def max_image_file_size_bytes(self) -> int:
        """Get maximum image file size in bytes for image-based APIs."""
        return self.max_image_file_size_mb * 1024 * 1024
    
    # LLM Configuration
    gpt4_turbo_model: str = Field(default="gpt-4o-mini", description="GPT-4 Turbo model name")
    gpt4o_model: str = Field(default="gpt-4o-mini", description="GPT-4o model name")
    max_tokens: int = Field(default=2000, description="Maximum tokens for LLM responses")
    temperature: float = Field(default=0.7, description="Temperature for LLM responses")
    
    # Tesseract Configuration
    tesseract_cmd: str = Field(default="/usr/bin/tesseract", description="Tesseract command path")
    
    # Random Paragraph Configuration
    random_paragraph_word_count: int = Field(default=50, description="Number of words in random paragraph")
    random_paragraph_difficulty_percentage: int = Field(default=60, description="Percentage of difficult words in random paragraph")
    
    # Text Simplification Configuration
    max_simplification_attempts: int = Field(default=1, description="Maximum number of simplification attempts allowed")
    
    # More Examples Configuration
    more_examples_threshold: int = Field(default=2, description="Maximum number of examples to allow fetching more examples")
    
    # Monitoring
    enable_metrics: bool = Field(default=True, description="Enable Prometheus metrics")
    metrics_port: int = Field(default=9090, description="Metrics server port")
    
    # Authentication Configuration
    google_oauth_client_id: str = Field(..., description="Google OAuth Client ID")
    google_oauth_client_id_xplaino_web: str = Field(
        default="355884005048-ad7r1e3hdmkehnq4qvmaa56c2f8gmqpd.apps.googleusercontent.com",
        description="Google OAuth Client ID for XPLAINO_WEB source"
    )
    jwt_secret_key: str = Field(..., description="JWT secret key for signing tokens")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expiry_hours: int = Field(default=24, description="Access token expiry in hours")
    refresh_token_expiry_days: int = Field(default=30, description="Refresh token expiry in days")
    
    # Database Configuration
    db_host: str = Field(..., description="Database host")
    db_user: str = Field(default="root", description="Database user")
    db_password: str = Field(default="", description="Database password")
    db_name: str = Field(..., description="Database name")
    db_port: int = Field(default=3306, description="Database port")
    
    # AWS S3 Configuration
    aws_access_key_id: str = Field(..., description="AWS access key ID")
    aws_secret_access_key: str = Field(..., description="AWS secret access key")
    aws_region: str = Field(default="us-east-1", description="AWS region")
    s3_bucket_name: str = Field(..., description="S3 bucket name")
    s3_issue_files_prefix: str = Field(default="issues/", description="S3 prefix for issue files")
    
    # API Usage Limits for Unauthenticated Users
    # v1 API Limits
    image_to_text_api_max_limit: int = Field(default=10, description="Max limit for image-to-text API")
    pdf_to_text_api_max_limit: int = Field(default=10, description="Max limit for pdf-to-text API")
    important_words_from_text_v1_api_max_limit: int = Field(default=10, description="Max limit for v1 important-words-from-text API")
    words_explanation_v1_api_max_limit: int = Field(default=10, description="Max limit for v1 words-explanation API")
    get_more_explanations_api_max_limit: int = Field(default=7, description="Max limit for get-more-explanations API")
    get_random_paragraph_api_max_limit: int = Field(default=10, description="Max limit for get-random-paragraph API")
    
    # v2 API Limits
    words_explanation_api_max_limit: int = Field(default=5, description="Max limit for v2 words-explanation API")
    simplify_api_max_limit: int = Field(default=5, description="Max limit for simplify API")
    important_words_from_text_v2_api_max_limit: int = Field(default=5, description="Max limit for v2 important-words-from-text API")
    ask_api_max_limit: int = Field(default=10, description="Max limit for ask API")
    pronunciation_api_max_limit: int = Field(default=5, description="Max limit for pronunciation API")
    voice_to_text_api_max_limit: int = Field(default=5, description="Max limit for voice-to-text API")
    translate_api_max_limit: int = Field(default=5, description="Max limit for translate API")
    summarise_api_max_limit: int = Field(default=3, description="Max limit for summarise API")
    web_search_api_max_limit: int = Field(default=5, description="Max limit for web-search API")
    web_search_stream_api_max_limit: int = Field(default=5, description="Max limit for web-search-stream API")
    synonyms_api_max_limit: int = Field(default=5, description="Max limit for synonyms API")
    antonyms_api_max_limit: int = Field(default=5, description="Max limit for antonyms API")
    simplify_image_api_max_limit: int = Field(default=5, description="Max limit for simplify-image API")
    ask_image_api_max_limit: int = Field(default=10, description="Max limit for ask-image API")
    
    # Saved words API limits (method-specific)
    saved_words_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for GET saved-words API")
    saved_words_post_api_max_limit: int = Field(default=0, description="Max limit for POST saved-words API")
    saved_words_move_api_max_limit: int = Field(default=0, description="Max limit for PATCH saved-words move-to-folder API")
    saved_words_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for DELETE saved-words API")
    
    # Saved paragraph API limits (method-specific)
    saved_paragraph_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for GET saved-paragraph API")
    saved_paragraph_post_api_max_limit: int = Field(default=0, description="Max limit for POST saved-paragraph API")
    saved_paragraph_move_api_max_limit: int = Field(default=0, description="Max limit for PATCH saved-paragraph move-to-folder API")
    saved_paragraph_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for DELETE saved-paragraph API")
    saved_paragraph_folder_post_api_max_limit: int = Field(default=0, description="Max limit for POST saved-paragraph folder API")
    saved_paragraph_folder_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for DELETE saved-paragraph folder API")
    
    # Saved link API limits (method-specific)
    saved_link_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for GET saved-link API")
    saved_link_post_api_max_limit: int = Field(default=0, description="Max limit for POST saved-link API")
    saved_link_move_api_max_limit: int = Field(default=0, description="Max limit for PATCH saved-link move-to-folder API")
    saved_link_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for DELETE saved-link API")
    saved_link_folder_post_api_max_limit: int = Field(default=0, description="Max limit for POST saved-link folder API")
    saved_link_folder_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for DELETE saved-link folder API")
    
    # Folders API limits (method-specific)
    folders_get_api_max_limit: int = Field(default=0, description="Max limit for GET folders API")
    folders_post_api_max_limit: int = Field(default=0, description="Max limit for POST folders API")
    folders_delete_api_max_limit: int = Field(default=0, description="Max limit for DELETE folders API")
    
    # API Usage Limits for Authenticated Users (Unsubscribed)
    # v1 API Limits
    authenticated_image_to_text_api_max_limit: int = Field(default=10, description="Max limit for authenticated image-to-text API")
    authenticated_pdf_to_text_api_max_limit: int = Field(default=10, description="Max limit for authenticated pdf-to-text API")
    authenticated_important_words_from_text_v1_api_max_limit: int = Field(default=10, description="Max limit for authenticated v1 important-words-from-text API")
    authenticated_words_explanation_v1_api_max_limit: int = Field(default=10, description="Max limit for authenticated v1 words-explanation API")
    authenticated_get_more_explanations_api_max_limit: int = Field(default=7, description="Max limit for authenticated get-more-explanations API")
    authenticated_get_random_paragraph_api_max_limit: int = Field(default=10, description="Max limit for authenticated get-random-paragraph API")
    
    # v2 API Limits
    authenticated_words_explanation_api_max_limit: int = Field(default=5, description="Max limit for authenticated v2 words-explanation API")
    authenticated_simplify_api_max_limit: int = Field(default=5, description="Max limit for authenticated simplify API")
    authenticated_important_words_from_text_v2_api_max_limit: int = Field(default=5, description="Max limit for authenticated v2 important-words-from-text API")
    authenticated_ask_api_max_limit: int = Field(default=10, description="Max limit for authenticated ask API")
    authenticated_pronunciation_api_max_limit: int = Field(default=5, description="Max limit for authenticated pronunciation API")
    authenticated_voice_to_text_api_max_limit: int = Field(default=5, description="Max limit for authenticated voice-to-text API")
    authenticated_translate_api_max_limit: int = Field(default=5, description="Max limit for authenticated translate API")
    authenticated_summarise_api_max_limit: int = Field(default=3, description="Max limit for authenticated summarise API")
    authenticated_web_search_api_max_limit: int = Field(default=5, description="Max limit for authenticated web-search API")
    authenticated_web_search_stream_api_max_limit: int = Field(default=5, description="Max limit for authenticated web-search-stream API")
    authenticated_synonyms_api_max_limit: int = Field(default=5, description="Max limit for authenticated synonyms API")
    authenticated_antonyms_api_max_limit: int = Field(default=5, description="Max limit for authenticated antonyms API")
    authenticated_simplify_image_api_max_limit: int = Field(default=5, description="Max limit for authenticated simplify-image API")
    authenticated_ask_image_api_max_limit: int = Field(default=10, description="Max limit for authenticated ask-image API")
    
    # Authenticated saved words API limits (method-specific)
    authenticated_saved_words_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated GET saved-words API")
    authenticated_saved_words_post_api_max_limit: int = Field(default=10, description="Max limit for authenticated POST saved-words API")
    authenticated_saved_words_move_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated PATCH saved-words move-to-folder API")
    authenticated_saved_words_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated DELETE saved-words API")
    
    # Authenticated saved paragraph API limits (method-specific)
    authenticated_saved_paragraph_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated GET saved-paragraph API")
    authenticated_saved_paragraph_post_api_max_limit: int = Field(default=5, description="Max limit for authenticated POST saved-paragraph API")
    authenticated_saved_paragraph_move_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated PATCH saved-paragraph move-to-folder API")
    authenticated_saved_paragraph_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated DELETE saved-paragraph API")
    authenticated_saved_paragraph_folder_post_api_max_limit: int = Field(default=3, description="Max limit for authenticated POST saved-paragraph folder API")
    authenticated_saved_paragraph_folder_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated DELETE saved-paragraph folder API")
    
    # Authenticated saved link API limits (method-specific)
    authenticated_saved_link_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated GET saved-link API")
    authenticated_saved_link_post_api_max_limit: int = Field(default=10, description="Max limit for authenticated POST saved-link API")
    authenticated_saved_link_move_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated PATCH saved-link move-to-folder API")
    authenticated_saved_link_delete_api_max_limit: int = Field(default=10, description="Max limit for authenticated DELETE saved-link API")
    authenticated_saved_link_folder_post_api_max_limit: int = Field(default=5, description="Max limit for authenticated POST saved-link folder API")
    authenticated_saved_link_folder_delete_api_max_limit: int = Field(default=5, description="Max limit for authenticated DELETE saved-link folder API")
    
    # Authenticated folders API limits (method-specific)
    authenticated_folders_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated GET folders API")
    authenticated_folders_post_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated POST folders API")
    authenticated_folders_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated DELETE folders API")
    
    # Saved image API limits (method-specific)
    saved_image_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for GET saved-image API")
    saved_image_post_api_max_limit: int = Field(default=5, description="Max limit for POST saved-image API")
    saved_image_move_api_max_limit: int = Field(default=5, description="Max limit for PATCH saved-image move-to-folder API")
    saved_image_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for DELETE saved-image API")
    
    # Authenticated saved image API limits (method-specific)
    authenticated_saved_image_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated GET saved-image API")
    authenticated_saved_image_post_api_max_limit: int = Field(default=5, description="Max limit for authenticated POST saved-image API")
    authenticated_saved_image_move_api_max_limit: int = Field(default=5, description="Max limit for authenticated PATCH saved-image move-to-folder API")
    authenticated_saved_image_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated DELETE saved-image API")
    
    # Issue API limits (method-specific)
    issue_get_api_max_limit: int = Field(default=0, description="Max limit for GET issue API")
    issue_get_all_api_max_limit: int = Field(default=0, description="Max limit for GET issue/all API")
    issue_patch_api_max_limit: int = Field(default=0, description="Max limit for PATCH issue API")
    issue_post_api_max_limit: int = Field(default=0, description="Max limit for POST issue API")
    
    # Authenticated issue API limits (method-specific)
    authenticated_issue_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated GET issue API")
    authenticated_issue_get_all_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated GET issue/all API")
    authenticated_issue_patch_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated PATCH issue API")
    authenticated_issue_post_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated POST issue API")
    
    @property
    def database_url(self) -> str:
        """Construct database connection URL from individual fields."""
        if self.db_password:
            return f"mysql+pymysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        else:
            return f"mysql+pymysql://{self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}"


# Global settings instance
settings = Settings()
