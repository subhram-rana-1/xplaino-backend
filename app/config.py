"""Configuration management for the FastAPI application."""

import sys
from typing import List, FrozenSet
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
    gpt4o_mini_model: str = Field(default="gpt-4o-mini", description="GPT-4o Mini model for text-only operations")
    gpt4o_model: str = Field(default="gpt-4o", description="GPT-4o model for vision and complex tasks")
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
    google_oauth_client_id_xplaino_extension: str = Field(..., description="Google OAuth Client ID for chrome extension as the source")
    google_oauth_client_id_xplaino_web: str = Field(..., description="Google OAuth Client ID for XPLAINO_WEB source")
    jwt_secret_key: str = Field(..., description="JWT secret key for signing tokens")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    access_token_expiry_hours: int = Field(default=24, description="Access token expiry in hours")
    refresh_token_expiry_days: int = Field(default=30, description="Refresh token expiry in days")
    unlimited_allowed_user_emails: str = Field(default="", description="Comma-separated list of user emails that bypass subscription and API limits")

    @property
    def unlimited_allowed_user_emails_set(self) -> FrozenSet[str]:
        """Get unlimited allowed user emails as a frozenset (normalized, in memory at startup)."""
        if not self.unlimited_allowed_user_emails or not self.unlimited_allowed_user_emails.strip():
            return frozenset()
        return frozenset(
            e.strip().lower()
            for e in self.unlimited_allowed_user_emails.split(",")
            if e and e.strip()
        )

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
    unauth_user_image_to_text_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated image-to-text API")
    unauth_user_pdf_to_text_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated pdf-to-text API")
    unauth_user_important_words_from_text_v1_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated v1 important-words-from-text API")
    unauth_user_words_explanation_v1_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated v1 words-explanation API")
    unauth_user_get_more_explanations_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated get-more-explanations API")
    unauth_user_get_random_paragraph_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated get-random-paragraph API")
    
    # v2 API Limits
    unauth_user_words_explanation_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated v2 words-explanation API")
    unauth_user_simplify_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated simplify API")
    unauth_user_important_words_from_text_v2_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated v2 important-words-from-text API")
    unauth_user_ask_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated ask API")
    unauth_user_pronunciation_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated pronunciation API")
    unauth_user_voice_to_text_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated voice-to-text API")
    unauth_user_translate_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated translate API")
    unauth_user_summarise_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated summarise API")
    unauth_user_web_search_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated web-search API")
    unauth_user_web_search_stream_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated web-search-stream API")
    unauth_user_synonyms_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated synonyms API")
    unauth_user_antonyms_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated antonyms API")
    unauth_user_simplify_image_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated simplify-image API")
    unauth_user_ask_image_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated ask-image API")
    
    # Unauthenticated saved words API limits (method-specific)
    unauth_user_saved_words_get_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated GET saved-words API")
    unauth_user_saved_words_post_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated POST saved-words API")
    unauth_user_saved_words_move_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated PATCH saved-words move-to-folder API")
    unauth_user_saved_words_delete_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated DELETE saved-words API")
    
    # Unauthenticated saved paragraph API limits (method-specific)
    unauth_user_saved_paragraph_get_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated GET saved-paragraph API")
    unauth_user_saved_paragraph_post_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated POST saved-paragraph API")
    unauth_user_saved_paragraph_move_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated PATCH saved-paragraph move-to-folder API")
    unauth_user_saved_paragraph_delete_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated DELETE saved-paragraph API")
    unauth_user_saved_paragraph_folder_post_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated POST saved-paragraph folder API")
    unauth_user_saved_paragraph_folder_delete_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated DELETE saved-paragraph folder API")
    
    # Unauthenticated saved link API limits (method-specific)
    unauth_user_saved_link_get_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated GET saved-link API")
    unauth_user_saved_link_post_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated POST saved-link API")
    unauth_user_saved_link_move_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated PATCH saved-link move-to-folder API")
    unauth_user_saved_link_delete_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated DELETE saved-link API")
    unauth_user_saved_link_folder_post_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated POST saved-link folder API")
    unauth_user_saved_link_folder_delete_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated DELETE saved-link folder API")
    
    # Unauthenticated folders API limits (method-specific)
    unauth_user_folders_get_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated GET folders API")
    unauth_user_folders_post_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated POST folders API")
    unauth_user_folders_delete_api_max_limit: int = Field(default=0, description="Max limit for unauthenticated DELETE folders API")
    
    # API Usage Limits for Authenticated Users (Unsubscribed)
    # v1 API Limits
    authenticated_unsubscribed_image_to_text_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed image-to-text API")
    authenticated_unsubscribed_pdf_to_text_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed pdf-to-text API")
    authenticated_unsubscribed_important_words_from_text_v1_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed v1 important-words-from-text API")
    authenticated_unsubscribed_words_explanation_v1_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed v1 words-explanation API")
    authenticated_unsubscribed_get_more_explanations_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed get-more-explanations API")
    authenticated_unsubscribed_get_random_paragraph_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed get-random-paragraph API")
    
    # v2 API Limits
    authenticated_unsubscribed_words_explanation_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed v2 words-explanation API")
    authenticated_unsubscribed_simplify_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed simplify API")
    authenticated_unsubscribed_important_words_from_text_v2_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed v2 important-words-from-text API")
    authenticated_unsubscribed_ask_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed ask API")
    authenticated_unsubscribed_pronunciation_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed pronunciation API")
    authenticated_unsubscribed_voice_to_text_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed voice-to-text API")
    authenticated_unsubscribed_translate_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed translate API")
    authenticated_unsubscribed_summarise_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed summarise API")
    authenticated_unsubscribed_web_search_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed web-search API")
    authenticated_unsubscribed_web_search_stream_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed web-search-stream API")
    authenticated_unsubscribed_synonyms_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed synonyms API")
    authenticated_unsubscribed_antonyms_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed antonyms API")
    authenticated_unsubscribed_simplify_image_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed simplify-image API")
    authenticated_unsubscribed_ask_image_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed ask-image API")
    
    # Authenticated unsubscribed saved words API limits (method-specific)
    authenticated_unsubscribed_saved_words_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed GET saved-words API")
    authenticated_unsubscribed_saved_words_post_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed POST saved-words API")
    authenticated_unsubscribed_saved_words_move_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed PATCH saved-words move-to-folder API")
    authenticated_unsubscribed_saved_words_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed DELETE saved-words API")
    
    # Authenticated unsubscribed saved paragraph API limits (method-specific)
    authenticated_unsubscribed_saved_paragraph_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed GET saved-paragraph API")
    authenticated_unsubscribed_saved_paragraph_post_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed POST saved-paragraph API")
    authenticated_unsubscribed_saved_paragraph_move_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed PATCH saved-paragraph move-to-folder API")
    authenticated_unsubscribed_saved_paragraph_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed DELETE saved-paragraph API")
    authenticated_unsubscribed_saved_paragraph_folder_post_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed POST saved-paragraph folder API")
    authenticated_unsubscribed_saved_paragraph_folder_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed DELETE saved-paragraph folder API")
    
    # Authenticated unsubscribed saved link API limits (method-specific)
    authenticated_unsubscribed_saved_link_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed GET saved-link API")
    authenticated_unsubscribed_saved_link_post_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed POST saved-link API")
    authenticated_unsubscribed_saved_link_move_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed PATCH saved-link move-to-folder API")
    authenticated_unsubscribed_saved_link_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed DELETE saved-link API")
    authenticated_unsubscribed_saved_link_folder_post_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed POST saved-link folder API")
    authenticated_unsubscribed_saved_link_folder_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed DELETE saved-link folder API")
    
    # Authenticated unsubscribed folders API limits (method-specific)
    authenticated_unsubscribed_folders_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed GET folders API")
    authenticated_unsubscribed_folders_post_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed POST folders API")
    authenticated_unsubscribed_folders_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed DELETE folders API")

    # Authenticated unsubscribed saved image API limits (method-specific)
    authenticated_unsubscribed_saved_image_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed GET saved-image API")
    authenticated_unsubscribed_saved_image_post_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed POST saved-image API")
    authenticated_unsubscribed_saved_image_move_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed PATCH saved-image move-to-folder API")
    authenticated_unsubscribed_saved_image_delete_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed DELETE saved-image API")

    # Plus subscriber saved items API limits (method-specific)
    plus_subscriber_saved_words_post_api_max_limit: int = Field(default=5, description="Max limit for Plus subscriber POST saved-words API")
    plus_subscriber_saved_paragraph_post_api_max_limit: int = Field(default=5, description="Max limit for Plus subscriber POST saved-paragraph API")
    plus_subscriber_saved_link_post_api_max_limit: int = Field(default=5, description="Max limit for Plus subscriber POST saved-link API")
    plus_subscriber_saved_image_post_api_max_limit: int = Field(default=5, description="Max limit for Plus subscriber POST saved-image API")

    # Authenticated unsubscribed issue API limits (method-specific)
    authenticated_unsubscribed_issue_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed GET issue API")
    authenticated_unsubscribed_issue_get_all_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed GET issue/all API")
    authenticated_unsubscribed_issue_patch_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed PATCH issue API")
    authenticated_unsubscribed_issue_post_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed POST issue API")

    # Authenticated unsubscribed PDF API limits (method-specific)
    authenticated_unsubscribed_pdf_to_html_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed PDF to HTML API")
    authenticated_unsubscribed_pdf_get_api_max_limit: int = Field(default=sys.maxsize, description="Max limit for authenticated unsubscribed GET PDF API")
    authenticated_unsubscribed_pdf_get_html_api_max_limit: int = Field(default=0, description="Max limit for authenticated unsubscribed GET PDF HTML API")
    
    # Paddle Billing Configuration
    paddle_webhook_secret: str = Field(default="", description="Paddle webhook secret key for signature verification")
    paddle_environment: str = Field(default="sandbox", description="Paddle environment: 'sandbox' or 'production'")
    paddle_api_key: str = Field(default="", description="Paddle API key for direct API calls")
    paddle_api_url: str = Field(default="https://sandbox-api.paddle.com", description="Paddle API base URL (use https://api.paddle.com for production)")
    
    @property
    def database_url(self) -> str:
        """Construct database connection URL from individual fields."""
        if self.db_password:
            return f"mysql+pymysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
        else:
            return f"mysql+pymysql://{self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}"


# Global settings instance
settings = Settings()
