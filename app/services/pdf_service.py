"""PDF processing and validation service."""

import io
import tempfile
import os
from typing import Tuple, List
import PyPDF2
import pdfplumber
from pdf2markdown4llm import PDF2Markdown4LLM
from pdf2image import convert_from_bytes
import structlog

from app.config import settings
from app.exceptions import FileValidationError, ValidationError

logger = structlog.get_logger()


class PdfProcessingError(ValidationError):
    """Exception raised for PDF processing errors."""
    pass


class PdfService:
    """Service for PDF processing and text extraction."""
    
    def __init__(self):
        self.max_file_size = settings.max_file_size_bytes
        self.allowed_types = settings.allowed_pdf_types_list
    
    def validate_pdf_file(self, file_data: bytes, filename: str) -> Tuple[bytes, str]:
        """Validate uploaded PDF file."""
        file_size = len(file_data)
        max_size_mb = self.max_file_size // (1024 * 1024)  # Convert to MB for display
        
        # Check file size
        if file_size > self.max_file_size:
            file_size_mb = file_size / (1024 * 1024)
            raise FileValidationError(
                f"PDF file size {file_size_mb:.2f}MB exceeds maximum allowed size of {max_size_mb}MB. "
                f"Please upload a smaller PDF file."
            )
        
        # Check minimum file size (PDFs should be at least a few KB)
        min_size = 1024  # 1KB minimum
        if file_size < min_size:
            raise FileValidationError(
                f"PDF file size {file_size} bytes is too small. Please upload a valid PDF file."
            )
        
        # Extract file extension
        file_extension = filename.lower().split('.')[-1] if '.' in filename else ''
        
        # Check file type
        if file_extension not in self.allowed_types:
            raise FileValidationError(
                f"File type '{file_extension}' not allowed. Supported types: {', '.join(self.allowed_types)}"
            )
        
        # Validate that the file is actually a PDF
        try:
            # Try to read the PDF with PyPDF2 to validate it's a proper PDF
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_data))
            num_pages = len(pdf_reader.pages)
            
            if num_pages == 0:
                raise PdfProcessingError("PDF file contains no pages")
            
            logger.info(
                "Successfully validated PDF file",
                filename=filename,
                file_size=len(file_data),
                num_pages=num_pages
            )
            
            return file_data, file_extension
            
        except Exception as e:
            logger.error("PDF validation failed", filename=filename, error=str(e))
            raise PdfProcessingError(f"Invalid PDF file: {str(e)}")
    
    def extract_text_from_pdf(self, pdf_data: bytes) -> str:
        """Extract text from PDF and convert to markdown format with bold text preservation."""
        try:
            # Create a temporary file to store the PDF data
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_file.write(pdf_data)
                temp_file_path = temp_file.name
            
            try:
                # First try pdf2markdown4llm for structure preservation
                def progress_callback(progress):
                    """Callback function to handle progress updates."""
                    logger.info(
                        f"PDF conversion progress: {progress.phase.value}, "
                        f"Page {progress.current_page}/{progress.total_pages}, "
                        f"Progress: {progress.percentage:.1f}%, "
                        f"Message: {progress.message}"
                    )
                
                # Configure converter with optimal settings for LLM processing
                converter = PDF2Markdown4LLM(
                    remove_headers=False,  # Keep headers for better structure
                    skip_empty_tables=True,  # Skip empty tables to reduce noise
                    table_header="### Table",  # Use consistent table headers
                    progress_callback=progress_callback
                )
                
                # Convert PDF to Markdown
                logger.info("Starting PDF to Markdown conversion using pdf2markdown4llm")
                markdown_content = converter.convert(temp_file_path)
                
                if not markdown_content or not markdown_content.strip():
                    raise PdfProcessingError("No readable text found in the PDF")
                
                # Now enhance with bold text detection and indentation using pdfplumber
                logger.info("Enhancing markdown with bold text formatting and indentation")
                enhanced_content = self._enhance_with_formatting(temp_file_path, markdown_content)
                
                logger.info(
                    "Successfully converted PDF to Markdown with bold formatting",
                    content_length=len(enhanced_content)
                )
                
                return enhanced_content
                
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except OSError:
                    logger.warning(f"Failed to delete temporary file: {temp_file_path}")
            
        except Exception as e:
            logger.error("PDF to Markdown conversion failed", error=str(e))
            raise PdfProcessingError(f"Failed to convert PDF to Markdown: {str(e)}")
    
    def _enhance_with_formatting(self, pdf_path: str, markdown_content: str) -> str:
        """Enhance markdown content with bold text formatting and proper indentation."""
        try:
            import re
            
            # Extract text with formatting information using pdfplumber
            bold_texts = []
            indentation_info = []
            
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    # Extract text objects with font information
                    text_objects = page.chars
                    
                    # Group characters by font weight to identify bold text
                    current_text = ""
                    current_font_weight = None
                    current_x = None
                    
                    for char in text_objects:
                        font_name = char.get('fontname', '').lower()
                        font_size = char.get('size', 0)
                        text = char.get('text', '')
                        x0 = char.get('x0', 0)
                        
                        # Detect bold fonts (common patterns)
                        is_bold = any(keyword in font_name for keyword in [
                            'bold', 'black', 'heavy', 'demibold', 'semibold'
                        ]) or font_name.endswith('-b') or font_name.endswith('bold')
                        
                        # If font weight changed, process the previous text
                        if current_font_weight is not None and current_font_weight != is_bold:
                            if current_font_weight and current_text.strip():
                                bold_texts.append(current_text.strip())
                            current_text = ""
                        
                        current_font_weight = is_bold
                        current_text += text
                        
                        # Track indentation for bullet points and multi-line text
                        if text.strip() and current_x is None:
                            current_x = x0
                        elif text == '\n' or text == ' ':
                            # Reset x position tracking for new lines
                            if text == '\n':
                                current_x = None
                    
                    # Process the last text segment
                    if current_font_weight and current_text.strip():
                        bold_texts.append(current_text.strip())
                    
                    # Extract indentation patterns from text objects
                    self._extract_indentation_patterns(page, indentation_info)
            
            # Remove duplicates and sort by length (longest first) to avoid partial replacements
            bold_texts = list(set(bold_texts))
            bold_texts.sort(key=len, reverse=True)
            
            # Apply bold formatting to markdown content
            enhanced_content = markdown_content
            
            for bold_text in bold_texts:
                if bold_text and len(bold_text) > 1:  # Skip single characters
                    # Escape special regex characters
                    escaped_text = re.escape(bold_text)
                    # Replace with markdown bold formatting, but avoid double-wrapping
                    pattern = f'(?<!\\*\\*){escaped_text}(?!\\*\\*)'
                    replacement = f'**{bold_text}**'
                    enhanced_content = re.sub(pattern, replacement, enhanced_content)
            
            # Apply indentation fixes
            enhanced_content = self._fix_indentation(enhanced_content)
            
            logger.info(f"Enhanced markdown with {len(bold_texts)} bold text segments and indentation fixes")
            return enhanced_content
            
        except Exception as e:
            logger.warning(f"Failed to enhance with formatting: {str(e)}")
            # Return original content if enhancement fails
            return markdown_content
    
    def _extract_indentation_patterns(self, page, indentation_info):
        """Extract indentation patterns from page text objects."""
        try:
            # Get text objects sorted by y position (top to bottom)
            chars = sorted(page.chars, key=lambda x: (-x['top'], x['x0']))
            
            current_line_x = None
            current_line_text = ""
            bullet_patterns = []
            
            for char in chars:
                text = char.get('text', '')
                x0 = char.get('x0', 0)
                
                if text == '\n':
                    if current_line_text.strip():
                        # Check if this line starts with a bullet point
                        if any(current_line_text.strip().startswith(bullet) for bullet in ['●', '•', '▪', '-', '*']):
                            bullet_patterns.append({
                                'text': current_line_text.strip(),
                                'x0': current_line_x,
                                'indent_level': self._calculate_indent_level(current_line_x, bullet_patterns)
                            })
                    current_line_x = None
                    current_line_text = ""
                else:
                    if current_line_x is None:
                        current_line_x = x0
                    current_line_text += text
            
            # Process the last line
            if current_line_text.strip():
                if any(current_line_text.strip().startswith(bullet) for bullet in ['●', '•', '▪', '-', '*']):
                    bullet_patterns.append({
                        'text': current_line_text.strip(),
                        'x0': current_line_x,
                        'indent_level': self._calculate_indent_level(current_line_x, bullet_patterns)
                    })
            
            indentation_info.extend(bullet_patterns)
            
        except Exception as e:
            logger.warning(f"Failed to extract indentation patterns: {str(e)}")
    
    def _calculate_indent_level(self, x0, existing_patterns):
        """Calculate indentation level based on x position."""
        if not existing_patterns:
            return 0
        
        # Find the closest x position to determine indentation level
        x_positions = sorted([p['x0'] for p in existing_patterns])
        
        for i, x_pos in enumerate(x_positions):
            if abs(x0 - x_pos) < 10:  # Within 10 points, consider same level
                return i
        
        return len(x_positions)  # New indentation level
    
    def _fix_indentation(self, content: str) -> str:
        """Fix indentation issues in markdown content."""
        import re
        
        lines = content.split('\n')
        fixed_lines = []
        
        for line in lines:
            # Handle bullet points with proper indentation
            if re.match(r'^[●•▪\-\*]\s+', line.strip()):
                # This is a bullet point
                bullet_match = re.match(r'^([●•▪\-\*])\s+(.+)', line.strip())
                if bullet_match:
                    bullet_char = bullet_match.group(1)
                    bullet_text = bullet_match.group(2)
                    
                    # Check if this is a multi-line bullet point
                    if len(bullet_text) > 50:  # Likely to wrap
                        # Split long text and add proper hanging indent
                        words = bullet_text.split()
                        if len(words) > 8:  # Split into multiple lines
                            first_line = f"{bullet_char} {' '.join(words[:8])}"
                            remaining_words = words[8:]
                            
                            # Create hanging indent for continuation lines
                            indent_spaces = " " * (len(bullet_char) + 1)  # Space after bullet
                            continuation_lines = []
                            
                            # Split remaining words into chunks
                            for i in range(0, len(remaining_words), 8):
                                chunk = remaining_words[i:i+8]
                                continuation_lines.append(f"{indent_spaces}{' '.join(chunk)}")
                            
                            fixed_lines.append(first_line)
                            fixed_lines.extend(continuation_lines)
                        else:
                            fixed_lines.append(line.strip())
                    else:
                        fixed_lines.append(line.strip())
                else:
                    fixed_lines.append(line.strip())
            else:
                fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)
    
    async def convert_pdf_to_html(self, pdf_data: bytes, save_debug_images: bool = True) -> List[str]:
        """
        Convert PDF to HTML using GPT-4 Vision for accurate layout preservation.
        
        This method converts each PDF page to an image using pdf2image, then
        sends each image to GPT-4 Vision to generate HTML that accurately
        replicates the original PDF layout.
        
        Args:
            pdf_data: PDF file data as bytes
            save_debug_images: Whether to save intermediate images for debugging (default: True)
            
        Returns:
            List of HTML strings, one per page
        """
        # Import OpenAI service here to avoid circular imports
        from app.services.llm.open_ai import OpenAIService
        import uuid
        from datetime import datetime
        
        try:
            logger.info("Starting PDF to HTML conversion using GPT-4 Vision")
            
            # Convert PDF pages to images using pdf2image
            # Using DPI of 300 for higher quality (better for Vision API)
            # PNG format for lossless quality
            try:
                images = convert_from_bytes(
                    pdf_data,
                    dpi=300,  # Increased DPI for better quality
                    fmt='png',
                    thread_count=2  # Limit threads for memory efficiency
                )
            except Exception as e:
                logger.error("Failed to convert PDF to images", error=str(e))
                raise PdfProcessingError(f"Failed to convert PDF pages to images: {str(e)}")
            
            if not images:
                raise PdfProcessingError("PDF contains no pages or could not be converted to images")
            
            total_pages = len(images)
            logger.info(f"Converted PDF to {total_pages} images, processing with GPT-4 Vision")
            
            # Create debug directory for intermediate images
            debug_dir = None
            if save_debug_images:
                debug_dir = os.path.join(tempfile.gettempdir(), "pdf_to_html_debug")
                os.makedirs(debug_dir, exist_ok=True)
                # Create a unique folder for this conversion session
                session_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
                session_dir = os.path.join(debug_dir, session_id)
                os.makedirs(session_dir, exist_ok=True)
                logger.info(f"Saving debug images to: {session_dir}")
            
            # Initialize OpenAI service
            openai_service = OpenAIService()
            
            html_pages = []
            
            # Process each page image through GPT-4 Vision
            for page_num, image in enumerate(images, start=1):
                try:
                    # Convert PIL Image to PNG bytes
                    img_buffer = io.BytesIO()
                    image.save(img_buffer, format='PNG', optimize=True)
                    img_bytes = img_buffer.getvalue()
                    
                    # Save intermediate image for debugging
                    if save_debug_images and session_dir:
                        debug_image_path = os.path.join(session_dir, f"page_{page_num}.png")
                        with open(debug_image_path, 'wb') as f:
                            f.write(img_bytes)
                        logger.info(f"Saved debug image: {debug_image_path}")
                    
                    logger.debug(
                        "Processing page with GPT-4 Vision",
                        page_num=page_num,
                        total_pages=total_pages,
                        image_size_kb=len(img_bytes) / 1024
                    )
                    
                    # Call OpenAI Vision API to generate HTML
                    html_content = await openai_service.convert_image_to_html(
                        image_data=img_bytes,
                        image_format="png"
                    )
                    
                    # Save generated HTML for debugging
                    if save_debug_images and session_dir:
                        debug_html_path = os.path.join(session_dir, f"page_{page_num}.html")
                        with open(debug_html_path, 'w', encoding='utf-8') as f:
                            f.write(html_content)
                        logger.info(f"Saved debug HTML: {debug_html_path}")
                    
                    html_pages.append(html_content)
                    
                    logger.debug(
                        "Successfully converted page to HTML",
                        page_num=page_num,
                        html_size=len(html_content)
                    )
                    
                except Exception as e:
                    logger.error(
                        "Failed to convert page to HTML",
                        page_num=page_num,
                        error=str(e)
                    )
                    # Add fallback HTML for failed pages
                    fallback_html = self._create_fallback_html(page_num, str(e))
                    html_pages.append(fallback_html)
            
            log_data = {
                "total_pages": total_pages,
                "total_html_size": sum(len(html) for html in html_pages)
            }
            if save_debug_images and session_dir:
                log_data["debug_folder"] = session_dir
            
            logger.info(
                "Successfully converted PDF to HTML using GPT-4 Vision",
                **log_data
            )
            
            return html_pages
                
        except PdfProcessingError:
            raise
        except Exception as e:
            logger.error("PDF to HTML conversion failed", error=str(e))
            raise PdfProcessingError(f"Failed to convert PDF to HTML: {str(e)}")
    
    def _create_fallback_html(self, page_num: int, error_message: str) -> str:
        """Create fallback HTML when page conversion fails."""
        import html as html_escape
        escaped_error = html_escape.escape(error_message)
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Page {page_num}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 40px 20px;
            color: #333;
        }}
        .error-container {{
            background-color: #fff3cd;
            border: 1px solid #ffc107;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}
        .error-title {{
            color: #856404;
            margin: 0 0 10px 0;
        }}
        .error-message {{
            color: #666;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="error-container">
        <h2 class="error-title">Page {page_num} - Conversion Error</h2>
        <p class="error-message">Unable to convert this page to HTML. Error: {escaped_error}</p>
    </div>
</body>
</html>"""
    
    def _create_html_document(self, page_num: int, body_content: str) -> str:
        """Create a complete HTML document with proper structure and styling."""
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Page {page_num}</title>
    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{
            margin: 0;
            padding: 20px;
            background-color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
        }}
        .page-container {{
            max-width: 900px;
            margin: 0 auto;
            background-color: white;
            padding: 40px;
        }}
        h1, h2, h3, h4, h5, h6 {{
            margin-top: 1.2em;
            margin-bottom: 0.6em;
            font-weight: bold;
            line-height: 1.3;
            color: inherit;
        }}
        h1 {{
            margin-top: 0.8em;
        }}
        h1:first-child, h2:first-child, h3:first-child {{
            margin-top: 0;
        }}
        p {{
            margin: 0.8em 0;
            line-height: 1.6;
        }}
        p:first-child {{
            margin-top: 0;
        }}
        p:last-child {{
            margin-bottom: 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1.5em 0;
            border: 1px solid #ddd;
        }}
        table th, table td {{
            border: 1px solid #ddd;
            padding: 10px 12px;
            text-align: left;
        }}
        table th {{
            background-color: #f8f9fa;
            font-weight: bold;
        }}
        table tr:nth-child(even) {{
            background-color: #fafafa;
        }}
        img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 1.5em 0;
        }}
        strong {{
            font-weight: bold;
        }}
        em {{
            font-style: italic;
        }}
        span {{
            /* Preserve inline color styles */
        }}
        /* Responsive adjustments */
        @media (max-width: 768px) {{
            body {{
                padding: 10px;
            }}
            .page-container {{
                padding: 20px;
            }}
        }}
    </style>
</head>
<body>
    <div class="page-container">
        {body_content}
    </div>
</body>
</html>"""
    
    def _analyze_page_statistics(self, page) -> dict:
        """Analyze page to extract global statistics for better text classification."""
        try:
            from collections import Counter
            import statistics
            
            if not page.chars:
                return {
                    'base_font_size': 12.0,
                    'avg_line_height': 15.0,
                    'font_size_distribution': {},
                    'colors': [],
                    'page_height': 792.0
                }
            
            # Collect all font sizes
            font_sizes = [c.get('size', 0) for c in page.chars if c.get('size', 0) > 0]
            
            if not font_sizes:
                return {
                    'base_font_size': 12.0,
                    'avg_line_height': 15.0,
                    'font_size_distribution': {},
                    'colors': [],
                    'page_height': page.height if hasattr(page, 'height') else 792.0
                }
            
            # Calculate base font size (most common size in the document)
            size_counts = Counter(font_sizes)
            base_font_size = size_counts.most_common(1)[0][0]
            
            # Calculate font size statistics
            font_size_stats = {
                'mean': statistics.mean(font_sizes),
                'median': statistics.median(font_sizes),
                'mode': base_font_size,
                'min': min(font_sizes),
                'max': max(font_sizes)
            }
            
            # Calculate average line height
            sorted_chars = sorted(page.chars, key=lambda c: (-c.get('top', 0), c.get('x0', 0)))
            line_heights = []
            prev_bottom = None
            
            for char in sorted_chars:
                char_top = char.get('top', 0)
                char_bottom = char.get('bottom', 0)
                
                if prev_bottom is not None:
                    gap = char_top - prev_bottom
                    if 0 < gap < 50:  # Reasonable line spacing
                        line_heights.append(gap)
                
                prev_bottom = char_bottom
            
            avg_line_height = statistics.mean(line_heights) if line_heights else 15.0
            
            # Extract colors (for future use)
            colors = []
            for char in page.chars:
                # Extract color information if available
                if 'non_stroking_color' in char:
                    colors.append(char['non_stroking_color'])
            
            return {
                'base_font_size': base_font_size,
                'avg_line_height': avg_line_height,
                'font_size_stats': font_size_stats,
                'font_size_distribution': size_counts,
                'colors': list(set(colors)),
                'page_height': page.height if hasattr(page, 'height') else 792.0
            }
            
        except Exception as e:
            logger.warning(f"Failed to analyze page statistics: {str(e)}")
            return {
                'base_font_size': 12.0,
                'avg_line_height': 15.0,
                'font_size_distribution': {},
                'colors': [],
                'page_height': 792.0
            }
    
    def _extract_text_blocks(self, page) -> List[str]:
        """Extract text blocks (paragraphs and headings) from a PDF page."""
        try:
            import html as html_escape
            
            if not page.chars:
                return []
            
            # First, analyze the entire page to get global statistics
            page_stats = self._analyze_page_statistics(page)
            
            # Group characters into lines based on y-coordinate
            lines = []
            current_line = []
            current_y = None
            y_tolerance = 3  # Points tolerance for same line
            
            # Sort characters by y position (top to bottom) and x position (left to right)
            sorted_chars = sorted(page.chars, key=lambda c: (-c.get('top', 0), c.get('x0', 0)))
            
            for char in sorted_chars:
                char_y = char.get('top', 0)
                char_text = char.get('text', '')
                
                if current_y is None:
                    current_y = char_y
                    current_line.append(char)
                elif abs(char_y - current_y) <= y_tolerance:
                    # Same line
                    current_line.append(char)
                else:
                    # New line
                    if current_line:
                        lines.append(current_line)
                    current_line = [char]
                    current_y = char_y
            
            # Add the last line
            if current_line:
                lines.append(current_line)
            
            # Group lines into paragraphs based on vertical spacing (using dynamic threshold)
            paragraphs = []
            current_paragraph = []
            prev_bottom = None
            dynamic_threshold = page_stats['avg_line_height'] * 1.2  # More conservative threshold
            
            for line in lines:
                if not line:
                    continue
                
                # Calculate line bounds
                line_top = min(c.get('top', 0) for c in line)
                line_bottom = max(c.get('bottom', 0) for c in line)
                line_height = line_bottom - line_top
                
                # Check if this line starts a new paragraph
                if prev_bottom is not None:
                    vertical_gap = line_top - prev_bottom
                    # Use dynamic threshold based on page statistics
                    # Large gap indicates new paragraph
                    if vertical_gap > dynamic_threshold:
                        if current_paragraph:
                            paragraphs.append(current_paragraph)
                        current_paragraph = [line]
                    else:
                        current_paragraph.append(line)
                else:
                    current_paragraph.append(line)
                
                prev_bottom = line_bottom
            
            # Add the last paragraph
            if current_paragraph:
                paragraphs.append(current_paragraph)
            
            # Convert paragraphs to HTML
            html_blocks = []
            for para_lines in paragraphs:
                if not para_lines:
                    continue
                
                # Get all characters in this paragraph
                para_chars = []
                for line in para_lines:
                    para_chars.extend(line)
                
                if not para_chars:
                    continue
                
                # Apply formatting and create HTML (with color support)
                formatted_text, avg_font_size = self._apply_text_formatting(para_chars, page_stats)
                
                # Skip empty or very short blocks
                text_content = formatted_text.replace('<strong>', '').replace('</strong>', '').replace('<em>', '').replace('</em>', '').strip()
                if len(text_content) < 3:
                    continue
                
                # Calculate position on page (for heading detection)
                para_top = min(c.get('top', 0) for c in para_chars)
                position_ratio = para_top / page_stats['page_height']
                
                # Determine heading level using enhanced detection
                heading_level = self._detect_heading_level(
                    para_chars=para_chars,
                    para_lines=para_lines,
                    text_content=text_content,
                    page_stats=page_stats,
                    position_ratio=position_ratio
                )
                
                # Create HTML with inline styles for font size
                if heading_level:
                    # Headings should not be too long
                    if len(text_content) > 150:
                        # Too long to be a heading, make it a paragraph
                        html_blocks.append(f'<p style="font-size: {avg_font_size:.1f}pt;">{formatted_text}</p>')
                    else:
                        html_blocks.append(f'<h{heading_level} style="font-size: {avg_font_size:.1f}pt;">{formatted_text}</h{heading_level}>')
                else:
                    html_blocks.append(f'<p style="font-size: {avg_font_size:.1f}pt;">{formatted_text}</p>')
            
            return html_blocks
            
        except Exception as e:
            logger.warning(f"Failed to extract text blocks: {str(e)}")
            return []
    
    def _detect_heading_level(self, para_chars: List[dict], para_lines: List[List[dict]], 
                              text_content: str, page_stats: dict, position_ratio: float) -> int:
        """Determine heading level using multi-factor analysis."""
        try:
            if not para_chars:
                return 0
            
            # Get font sizes
            font_sizes = [c.get('size', 0) for c in para_chars if c.get('size', 0) > 0]
            if not font_sizes:
                return 0
            
            max_font_size = max(font_sizes)
            avg_font_size = sum(font_sizes) / len(font_sizes)
            base_font_size = page_stats['base_font_size']
            
            if base_font_size <= 0:
                return 0
            
            # Factor 1: Font size ratio
            ratio = max_font_size / base_font_size
            
            # Factor 2: Text length (headings are typically short)
            text_length = len(text_content)
            
            # Factor 3: Number of lines (headings are typically 1-3 lines)
            num_lines = len(para_lines)
            
            # Factor 4: Bold/weight detection
            is_bold = False
            for char in para_chars:
                font_name = char.get('fontname', '').lower()
                if any(keyword in font_name for keyword in ['bold', 'black', 'heavy', 'demibold', 'semibold']):
                    is_bold = True
                    break
            
            # Factor 5: Position on page (headings near top more likely)
            is_near_top = position_ratio < 0.3
            
            # Apply rules with multiple factors
            
            # Rule out headings that are too long
            if text_length > 150:
                return 0
            
            # Rule out multi-line paragraphs (more than 4 lines unlikely to be heading)
            if num_lines > 4:
                return 0
            
            # H1: Large font (1.5x+), short text, bold, or near top
            if ratio >= 1.5 and text_length < 100:
                return 1
            
            # H2: Medium-large font (1.25x+), reasonable length
            if ratio >= 1.3 and text_length < 120:
                # More likely if bold or near top
                if is_bold or is_near_top:
                    return 2
                elif ratio >= 1.4:
                    return 2
            
            # H3: Slightly larger font (1.15x+), short text
            if ratio >= 1.15 and text_length < 100:
                # More likely if bold
                if is_bold:
                    return 3
                elif ratio >= 1.2 and num_lines <= 2:
                    return 3
            
            # H3: Bold text that's reasonably short, even if same size
            if is_bold and text_length < 80 and num_lines <= 2 and ratio >= 1.0:
                return 3
            
            # Default: Regular paragraph
            return 0
            
        except Exception as e:
            logger.warning(f"Failed to detect heading level: {str(e)}")
            return 0
    
    def _apply_text_formatting(self, chars: List[dict], page_stats: dict) -> tuple:
        """Apply HTML formatting (bold, italic, color) to text based on character properties.
        
        Returns:
            tuple: (formatted_text, average_font_size)
        """
        try:
            import html as html_escape
            
            if not chars:
                return "", 12.0
            
            result = []
            current_segment = []
            current_bold = None
            current_italic = None
            current_color = None
            
            # Collect font sizes for average calculation
            font_sizes = [c.get('size', 0) for c in chars if c.get('size', 0) > 0]
            avg_font_size = sum(font_sizes) / len(font_sizes) if font_sizes else 12.0
            
            for char in chars:
                text = char.get('text', '')
                if not text:
                    continue
                
                font_name = char.get('fontname', '').lower()
                
                # Detect bold
                is_bold = any(keyword in font_name for keyword in [
                    'bold', 'black', 'heavy', 'demibold', 'semibold'
                ]) or font_name.endswith('-b') or font_name.endswith('bold')
                
                # Detect italic (common patterns)
                is_italic = 'italic' in font_name or 'oblique' in font_name or font_name.endswith('-i')
                
                # Extract color information
                color = self._extract_color_from_char(char)
                
                # Check if formatting changed
                if current_bold != is_bold or current_italic != is_italic or current_color != color:
                    # Close previous segment
                    if current_segment:
                        segment_text = ''.join(current_segment)
                        escaped_text = html_escape.escape(segment_text)
                        
                        # Apply color styling if non-default
                        if current_color and current_color != '#000000':
                            escaped_text = f'<span style="color: {current_color};">{escaped_text}</span>'
                        
                        # Apply formatting
                        if current_bold:
                            escaped_text = f"<strong>{escaped_text}</strong>"
                        if current_italic:
                            escaped_text = f"<em>{escaped_text}</em>"
                        
                        result.append(escaped_text)
                        current_segment = []
                    
                    current_bold = is_bold
                    current_italic = is_italic
                    current_color = color
                
                current_segment.append(text)
            
            # Process the last segment
            if current_segment:
                segment_text = ''.join(current_segment)
                escaped_text = html_escape.escape(segment_text)
                
                # Apply color styling if non-default
                if current_color and current_color != '#000000':
                    escaped_text = f'<span style="color: {current_color};">{escaped_text}</span>'
                
                if current_bold:
                    escaped_text = f"<strong>{escaped_text}</strong>"
                if current_italic:
                    escaped_text = f"<em>{escaped_text}</em>"
                
                result.append(escaped_text)
            
            return ''.join(result), avg_font_size
            
        except Exception as e:
            logger.warning(f"Failed to apply text formatting: {str(e)}")
            # Fallback: just escape and return text
            import html as html_escape
            text = ''.join(c.get('text', '') for c in chars)
            return html_escape.escape(text), 12.0
    
    def _extract_color_from_char(self, char: dict) -> str:
        """Extract color from character and convert to hex format."""
        try:
            # Try to get non_stroking_color (text fill color)
            color = char.get('non_stroking_color')
            
            if color is None:
                # Try stroking_color as fallback
                color = char.get('stroking_color')
            
            if color is None:
                return '#000000'  # Default black
            
            # Handle different color formats
            if isinstance(color, (list, tuple)):
                if len(color) == 3:
                    # RGB format (0-1 range)
                    r = int(color[0] * 255)
                    g = int(color[1] * 255)
                    b = int(color[2] * 255)
                    return f'#{r:02x}{g:02x}{b:02x}'
                elif len(color) == 1:
                    # Grayscale (0-1 range)
                    gray = int(color[0] * 255)
                    return f'#{gray:02x}{gray:02x}{gray:02x}'
            elif isinstance(color, (int, float)):
                # Single value grayscale
                gray = int(color * 255) if color <= 1 else int(color)
                return f'#{gray:02x}{gray:02x}{gray:02x}'
            
            return '#000000'  # Default black
            
        except Exception as e:
            logger.debug(f"Failed to extract color: {str(e)}")
            return '#000000'
    
    def _extract_tables_as_html(self, page) -> List[str]:
        """Extract tables from PDF page and convert to HTML table elements."""
        try:
            import html as html_escape
            
            tables = page.extract_tables()
            if not tables:
                return []
            
            html_tables = []
            for table in tables:
                if not table or len(table) == 0:
                    continue
                
                # Build HTML table
                html_rows = []
                
                # First row is typically header
                if len(table) > 0:
                    header_row = table[0]
                    if header_row and any(cell and str(cell).strip() for cell in header_row):
                        header_cells = []
                        for cell in header_row:
                            cell_text = str(cell).strip() if cell else ""
                            escaped_text = html_escape.escape(cell_text)
                            header_cells.append(f"<th>{escaped_text}</th>")
                        html_rows.append(f"<tr>{''.join(header_cells)}</tr>")
                
                # Remaining rows are data rows
                for row in table[1:]:
                    if not row:
                        continue
                    data_cells = []
                    for cell in row:
                        cell_text = str(cell).strip() if cell else ""
                        escaped_text = html_escape.escape(cell_text)
                        data_cells.append(f"<td>{escaped_text}</td>")
                    if data_cells:
                        html_rows.append(f"<tr>{''.join(data_cells)}</tr>")
                
                if html_rows:
                    table_html = f"<table>{''.join(html_rows)}</table>"
                    html_tables.append(table_html)
            
            return html_tables
            
        except Exception as e:
            logger.warning(f"Failed to extract tables: {str(e)}")
            return []
    
    def _extract_images_as_html(self, page, pdf_path: str, page_num: int) -> List[str]:
        """Extract images from PDF page and convert to base64 HTML img elements."""
        try:
            import base64
            import fitz
            
            images = page.images
            if not images:
                return []
            
            html_images = []
            
            # Open PDF with PyMuPDF for image extraction
            pdf_document = fitz.open(pdf_path)
            try:
                pdf_page = pdf_document[page_num]
                
                # Get image list from the page
                image_list = pdf_page.get_images()
                
                for img_index, img in enumerate(image_list):
                    try:
                        # Get image data
                        xref = img[0]
                        base_image = pdf_document.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]
                        
                        # Convert to base64
                        img_base64 = base64.b64encode(image_bytes).decode('utf-8')
                        
                        # Determine MIME type
                        mime_type = f"image/{image_ext}" if image_ext in ['png', 'jpg', 'jpeg', 'gif'] else "image/png"
                        
                        # Create HTML img tag
                        img_html = f'<img src="data:{mime_type};base64,{img_base64}" alt="Image {img_index + 1}" />'
                        html_images.append(img_html)
                        
                    except Exception as e:
                        logger.warning(f"Failed to extract image {img_index}: {str(e)}")
                        continue
                
            finally:
                pdf_document.close()
            
            return html_images
            
        except ImportError:
            logger.warning("PyMuPDF (fitz) not available for image extraction, skipping images")
            return []
        except Exception as e:
            logger.warning(f"Failed to extract images: {str(e)}")
            return []


# Global service instance
pdf_service = PdfService()
