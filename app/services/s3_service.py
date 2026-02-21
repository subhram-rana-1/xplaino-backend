"""S3 file upload service."""

import boto3
from datetime import datetime
import re
from typing import Optional
from botocore.config import Config
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
                region_name=settings.aws_region,
                config=Config(signature_version='s3v4', s3={'addressing_style': 'virtual'}),
            )
            self.bucket_name = settings.s3_bucket_name
            self.issue_prefix = settings.s3_issue_files_prefix.rstrip('/')
            self.pdf_prefix = settings.s3_pdf_files_prefix.rstrip('/')
            
            logger.info(
                "S3 service initialized",
                bucket_name=self.bucket_name,
                region=settings.aws_region,
                issue_prefix=self.issue_prefix,
                pdf_prefix=self.pdf_prefix
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
        """Generate S3 key for issue file upload (server-side). Uses issue prefix."""
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        sanitized_filename = self._sanitize_filename(file_name)
        s3_key = f"{self.issue_prefix}/{issue_id}/{file_type}/{timestamp}_{sanitized_filename}"
        return s3_key
    
    def upload_file(
        self,
        file_data: bytes,
        file_name: str,
        file_type: str,
        issue_id: str
    ) -> str:
        """
        Upload file to S3 and return the S3 object key.
        
        Args:
            file_data: File content as bytes
            file_name: Original file name
            file_type: File type (IMAGE or PDF)
            issue_id: Issue ID (UUID)
            
        Returns:
            S3 object key for the uploaded file (store this; use generate_presigned_get_url for download URLs)
            
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
            
            logger.info(
                "File uploaded successfully to S3",
                bucket_name=self.bucket_name,
                s3_key=s3_key
            )
            
            return s3_key
            
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

    def generate_presigned_get_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """
        Generate a presigned GET URL for downloading the object.
        
        Args:
            s3_key: S3 object key
            expires_in: URL expiry in seconds (default 1 hour)
            
        Returns:
            Presigned URL for get_object
        """
        return self.s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket_name, 'Key': s3_key},
            ExpiresIn=expires_in
        )

    def generate_presigned_put_url(
        self,
        s3_key: str,
        content_type: str,
        expires_in: int = 3600
    ) -> str:
        """
        Generate a presigned PUT URL for client-side upload.
        
        Args:
            s3_key: S3 object key
            content_type: Content-Type for the upload
            expires_in: URL expiry in seconds (default 1 hour)
            
        Returns:
            Presigned URL for put_object
        """
        return self.s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': self.bucket_name,
                'Key': s3_key,
                'ContentType': content_type
            },
            ExpiresIn=expires_in
        )

    def generate_s3_key_for_upload(
        self,
        file_upload_id: str,
        file_name: str,
        entity_type: str,
        entity_id: str,
        file_type: str
    ) -> str:
        """
        Generate S3 key for the presigned-upload flow (client uploads directly).
        Used when creating a file_upload record before the client uploads.
        Uses s3_pdf_files_prefix when entity_type is PDF, else s3_issue_files_prefix.
        
        Args:
            file_upload_id: File upload record ID (UUID)
            file_name: Original file name
            entity_type: ISSUE or PDF
            entity_id: Issue id or pdf id
            file_type: IMAGE or PDF
            
        Returns:
            S3 object key
        """
        sanitized_filename = self._sanitize_filename(file_name)
        prefix = self.pdf_prefix if entity_type == "PDF" else self.issue_prefix
        return f"{prefix}/{entity_type}/{entity_id}/{file_type}/{file_upload_id}_{sanitized_filename}"

    def delete_object(self, s3_key: str) -> None:
        """
        Delete an object from S3.
        
        Args:
            s3_key: S3 object key
            
        Raises:
            S3UploadError: If delete fails (optional; can log and swallow to allow cleanup to continue)
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info("Deleted S3 object", bucket_name=self.bucket_name, s3_key=s3_key)
        except ClientError as e:
            error_message = e.response.get("Error", {}).get("Message", str(e))
            logger.error("S3 delete failed", s3_key=s3_key, error=error_message)
            raise S3UploadError(f"Failed to delete S3 object: {error_message}")


# Global service instance
s3_service = S3Service()

