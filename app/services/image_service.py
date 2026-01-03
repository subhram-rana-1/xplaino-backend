"""Image processing and validation service."""

import io
from typing import Tuple
from PIL import Image, ImageOps
import structlog

from app.config import settings
from app.exceptions import FileValidationError, ImageProcessingError

logger = structlog.get_logger()


class ImageService:
    """Service for image processing and validation."""
    
    def __init__(self):
        self.max_file_size = settings.max_file_size_bytes
        self.allowed_types = settings.allowed_image_types_list
    
    def validate_image_file(self, file_data: bytes, filename: str) -> Tuple[bytes, str]:
        """Validate uploaded image file."""
        # Check file size
        if len(file_data) > self.max_file_size:
            raise FileValidationError(
                f"File size {len(file_data)} bytes exceeds maximum allowed size of {self.max_file_size} bytes"
            )
        
        # Extract file extension
        file_extension = filename.lower().split('.')[-1] if '.' in filename else ''
        
        # Check file type
        if file_extension not in self.allowed_types:
            raise FileValidationError(
                f"File type '{file_extension}' not allowed. Supported types: {', '.join(self.allowed_types)}"
            )
        
        # Validate that the file is actually an image
        try:
            image = Image.open(io.BytesIO(file_data))
            image.verify()  # Verify that it's a valid image
            
            # Re-open the image since verify() closes it
            image = Image.open(io.BytesIO(file_data))
            
            # Convert to RGB if necessary (for HEIC and other formats)
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            
            # Auto-rotate based on EXIF data
            image = ImageOps.exif_transpose(image)
            
            # Save processed image back to bytes
            processed_image_io = io.BytesIO()
            image_format = 'JPEG' if file_extension in ['jpg', 'jpeg', 'heic'] else 'PNG'
            image.save(processed_image_io, format=image_format, quality=95)
            processed_image_data = processed_image_io.getvalue()
            
            logger.info(
                "Successfully validated and processed image",
                filename=filename,
                original_size=len(file_data),
                processed_size=len(processed_image_data),
                format=image_format,
                dimensions=f"{image.width}x{image.height}"
            )
            
            return processed_image_data, image_format.lower()
            
        except Exception as e:
            logger.error("Image validation failed", filename=filename, error=str(e))
            raise ImageProcessingError(f"Invalid image file: {str(e)}")
    
    def validate_image_file_for_api(self, file_data: bytes, filename: str, max_size_mb: int = 5) -> Tuple[bytes, str]:
        """Validate uploaded image file for API endpoints (supports extended formats and larger size).
        
        Args:
            file_data: Raw image file data
            filename: Original filename
            max_size_mb: Maximum file size in MB (default: 5MB)
        
        Returns:
            Tuple of (processed_image_data, image_format)
        
        Raises:
            FileValidationError: If validation fails
            ImageProcessingError: If image processing fails
        """
        max_size_bytes = max_size_mb * 1024 * 1024
        
        # Check file size
        if len(file_data) > max_size_bytes:
            file_size_mb = len(file_data) / (1024 * 1024)
            raise FileValidationError(
                f"File size {file_size_mb:.2f}MB exceeds maximum allowed size of {max_size_mb}MB"
            )
        
        # Extract file extension
        file_extension = filename.lower().split('.')[-1] if '.' in filename else ''
        
        # Extended allowed types for API endpoints (web formats)
        allowed_types = ['jpeg', 'jpg', 'png', 'heic', 'webp', 'gif', 'bmp']
        
        # Check file type
        if file_extension not in allowed_types:
            raise FileValidationError(
                f"File type '{file_extension}' not allowed. Supported types: {', '.join(allowed_types)}"
            )
        
        # Validate that the file is actually an image
        try:
            image = Image.open(io.BytesIO(file_data))
            image.verify()  # Verify that it's a valid image
            
            # Re-open the image since verify() closes it
            image = Image.open(io.BytesIO(file_data))
            
            # Convert to RGB if necessary (for formats that need conversion)
            if image.mode not in ('RGB', 'L', 'RGBA'):
                image = image.convert('RGB')
            elif image.mode == 'RGBA':
                # For RGBA images, convert to RGB with white background
                background = Image.new('RGB', image.size, (255, 255, 255))
                background.paste(image, mask=image.split()[3])  # Use alpha channel as mask
                image = background
            
            # Auto-rotate based on EXIF data
            image = ImageOps.exif_transpose(image)
            
            # Convert to format compatible with OpenAI API (jpeg, png, gif, webp)
            # OpenAI supports: jpeg, png, gif, webp
            # Convert bmp, heic to JPEG/PNG
            processed_image_io = io.BytesIO()
            processed_image_data = None
            
            if file_extension in ['jpg', 'jpeg']:
                # Keep as JPEG
                image_format = 'JPEG'
                image.save(processed_image_io, format='JPEG', quality=95)
                processed_image_data = processed_image_io.getvalue()
            elif file_extension == 'webp':
                # Keep as WebP (OpenAI supports WebP)
                image_format = 'WEBP'
                # Try to save as WebP, fallback to PNG if needed
                try:
                    image.save(processed_image_io, format='WEBP', quality=95)
                    processed_image_data = processed_image_io.getvalue()
                except Exception:
                    # Fallback to PNG if WebP save fails
                    processed_image_io = io.BytesIO()
                    image_format = 'PNG'
                    image.save(processed_image_io, format='PNG')
                    processed_image_data = processed_image_io.getvalue()
            elif file_extension == 'gif':
                # Keep original GIF data (OpenAI supports GIF)
                image_format = 'GIF'
                processed_image_data = file_data  # Use original GIF data
            elif file_extension == 'png':
                # Keep as PNG
                image_format = 'PNG'
                image.save(processed_image_io, format='PNG')
                processed_image_data = processed_image_io.getvalue()
            else:
                # Convert others (heic, bmp) to PNG
                image_format = 'PNG'
                image.save(processed_image_io, format='PNG')
                processed_image_data = processed_image_io.getvalue()
            
            logger.info(
                "Successfully validated and processed image for API",
                filename=filename,
                original_size=len(file_data),
                processed_size=len(processed_image_data),
                format=image_format,
                dimensions=f"{image.width}x{image.height}"
            )
            
            return processed_image_data, image_format.lower()
            
        except Exception as e:
            logger.error("Image validation failed for API", filename=filename, error=str(e))
            raise ImageProcessingError(f"Invalid image file: {str(e)}")
    
    def preprocess_image_for_ocr(self, image_data: bytes) -> bytes:
        """Preprocess image for better OCR results."""
        try:
            image = Image.open(io.BytesIO(image_data))
            
            # Convert to grayscale for better OCR
            if image.mode != 'L':
                image = image.convert('L')
            
            # Enhance contrast
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.5)
            
            # Resize if too small (minimum 300px on smallest side)
            width, height = image.size
            min_dimension = min(width, height)
            if min_dimension < 300:
                scale_factor = 300 / min_dimension
                new_width = int(width * scale_factor)
                new_height = int(height * scale_factor)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Save processed image
            processed_io = io.BytesIO()
            image.save(processed_io, format='PNG')
            processed_data = processed_io.getvalue()
            
            logger.info("Successfully preprocessed image for OCR", 
                       original_size=len(image_data), 
                       processed_size=len(processed_data))
            
            return processed_data
            
        except Exception as e:
            logger.error("Image preprocessing failed", error=str(e))
            raise ImageProcessingError(f"Failed to preprocess image: {str(e)}")


# Global service instance
image_service = ImageService()
