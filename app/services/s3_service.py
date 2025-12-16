"""S3 file upload service."""

import boto3
from datetime import datetime
import re
from typing import Optional
from botocore.exceptions import ClientError
import structlog

from app.config import settings
from app.exceptions import CatenException

logger = structlog.get_logger()


class S3UploadError(CatenException):
    """Exception raised for S3 upload errors."""
    
    def __init__(self, error_message: str, details: Optional[dict] = None):
        super().__init__(
            error_code="S3_001",
            error_message=error_message,
            status_code=500,
            details=details
        )


class S3Service:
    """Service for S3 file uploads."""
    
    def __init__(self):
        """Initialize S3 client with credentials from config."""
        try:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region
            )
            self.bucket_name = settings.s3_bucket_name
            self.prefix = settings.s3_issue_files_prefix.rstrip('/')
            
            logger.info(
                "S3 service initialized",
                bucket_name=self.bucket_name,
                region=settings.aws_region,
                prefix=self.prefix
            )
        except Exception as e:
            logger.error("Failed to initialize S3 service", error=str(e))
            raise S3UploadError(f"Failed to initialize S3 service: {str(e)}")
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for S3 key."""
        # Remove or replace invalid characters
        sanitized = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
        # Limit length to 100 characters
        if len(sanitized) > 100:
            name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
            max_name_length = 100 - len(ext) - 1 if ext else 100
            sanitized = name[:max_name_length] + ('.' + ext if ext else '')
        return sanitized
    
    def _generate_s3_key(self, file_name: str, file_type: str, issue_id: str) -> str:
        """Generate S3 key for the file."""
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        sanitized_filename = self._sanitize_filename(file_name)
        s3_key = f"{self.prefix}/{issue_id}/{file_type}/{timestamp}_{sanitized_filename}"
        return s3_key
    
    def upload_file(
        self,
        file_data: bytes,
        file_name: str,
        file_type: str,
        issue_id: str
    ) -> str:
        """
        Upload file to S3 and return downloadable URL.
        
        Args:
            file_data: File content as bytes
            file_name: Original file name
            file_type: File type (IMAGE or PDF)
            issue_id: Issue ID (UUID)
            
        Returns:
            Downloadable URL for the uploaded file
            
        Raises:
            S3UploadError: If upload fails
        """
        try:
            # Generate S3 key
            s3_key = self._generate_s3_key(file_name, file_type, issue_id)
            
            # Determine content type
            content_type = self._get_content_type(file_name, file_type)
            
            # Upload to S3
            logger.info(
                "Uploading file to S3",
                bucket_name=self.bucket_name,
                s3_key=s3_key,
                file_size=len(file_data),
                content_type=content_type
            )
            
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=file_data,
                ContentType=content_type
            )
            
            # Generate presigned URL (valid for 7 days)
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=604800  # 7 days
            )
            
            logger.info(
                "File uploaded successfully to S3",
                bucket_name=self.bucket_name,
                s3_key=s3_key,
                url_length=len(url)
            )
            
            return url
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            logger.error(
                "S3 upload failed",
                error_code=error_code,
                error_message=error_message,
                file_name=file_name
            )
            raise S3UploadError(f"Failed to upload file to S3: {error_message}")
        except Exception as e:
            logger.error("Unexpected error during S3 upload", error=str(e), file_name=file_name)
            raise S3UploadError(f"Unexpected error during S3 upload: {str(e)}")
    
    def _get_content_type(self, file_name: str, file_type: str) -> str:
        """Get content type based on file name and type."""
        extension = file_name.lower().split('.')[-1] if '.' in file_name else ''
        
        content_type_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'heic': 'image/heic',
            'pdf': 'application/pdf'
        }
        
        return content_type_map.get(extension, 'application/octet-stream')


# Global service instance
s3_service = S3Service()

