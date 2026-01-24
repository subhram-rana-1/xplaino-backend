"""OpenAI service for LLM operations with improved error handling and diagnostics."""

import asyncio
import base64
import json
import re

import httpx
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
import structlog
from PIL import Image
import io
from pydub import AudioSegment

from app.config import settings
from app.exceptions import LLMServiceError

logger = structlog.get_logger()


def get_language_name(language_code: Optional[str]) -> Optional[str]:
    """Convert language code to full language name for prompts.

    Args:
        language_code: ISO 639-1 language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI')

    Returns:
        Full language name (e.g., 'English', 'French', 'Spanish') or None if code is invalid/None
    """
    if not language_code:
        return None

    language_map = {
        "EN": "English",
        "ES": "Spanish",
        "FR": "French",
        "DE": "German",
        "HI": "Hindi",
        "JA": "Japanese",
        "ZH": "Chinese",
        "AR": "Arabic",
        "IT": "Italian",
        "PT": "Portuguese",
        "RU": "Russian",
        "KO": "Korean",
        "NL": "Dutch",
        "PL": "Polish",
        "TR": "Turkish",
        "VI": "Vietnamese",
        "TH": "Thai",
        "ID": "Indonesian",
        "CS": "Czech",
        "SV": "Swedish",
        "DA": "Danish",
        "NO": "Norwegian",
        "FI": "Finnish",
        "EL": "Greek",
        "HE": "Hebrew",
        "UK": "Ukrainian",
        "RO": "Romanian",
        "HU": "Hungarian",
        "BG": "Bulgarian",
        "HR": "Croatian",
        "SK": "Slovak",
        "SL": "Slovenian",
        "ET": "Estonian",
        "LV": "Latvian",
        "LT": "Lithuanian",
        "IS": "Icelandic",
        "GA": "Irish",
        "MT": "Maltese",
        "EU": "Basque",
        "CA": "Catalan",
        "FA": "Persian",
        "UR": "Urdu",
        "BN": "Bengali",
        "TA": "Tamil",
        "TE": "Telugu",
        "ML": "Malayalam",
        "KN": "Kannada",
        "GU": "Gujarati",
        "MR": "Marathi",
        "PA": "Punjabi",
        "NE": "Nepali",
        "SI": "Sinhala",
        "OR": "Odia",
        "MY": "Burmese",
        "KM": "Khmer",
        "LO": "Lao",
        "MS": "Malay",
        "TL": "Tagalog",
        "SW": "Swahili",
        "AF": "Afrikaans",
        "ZU": "Zulu",
        "XH": "Xhosa",
    }

    return language_map.get(language_code.upper())


class OpenAIService:
    """Service for interacting with OpenAI models."""

    def __init__(self):
        try:
            # Check if API key is available
            if not settings.openai_api_key:
                logger.error("OpenAI API key is not set")
                raise LLMServiceError("OpenAI API key is not configured")

            # Validate API key format
            if not settings.openai_api_key.startswith('sk-'):
                logger.error("Invalid OpenAI API key format - should start with 'sk-'")
                raise LLMServiceError("Invalid OpenAI API key format")

            # Log key information (partial, for debugging)
            key_start = settings.openai_api_key[:10] if len(settings.openai_api_key) > 10 else "***"
            key_end = settings.openai_api_key[-4:] if len(settings.openai_api_key) > 4 else "***"
            logger.info(f"Initializing OpenAI client with API key: {key_start}...{key_end}")

            # Create HTTP client with SSL verification disabled for testing
            http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                verify=True,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
            )

            # Create the OpenAI client with custom HTTP client
            self.client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                timeout=60.0,
                max_retries=2,
                http_client=http_client,
            )
            logger.info("OpenAI client initialized successfully with custom HTTP client")

        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}")
            raise LLMServiceError(f"Failed to initialize OpenAI client: {str(e)}")

    async def test_connection(self) -> bool:
        """Test the OpenAI API connection."""
        try:
            logger.info("Testing OpenAI API connection...")

            # Simple test call to verify connection
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5,
                temperature=0
            )

            logger.info("OpenAI API connection test successful")
            return True

        except Exception as e:
            logger.error(f"OpenAI API connection test failed: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")

            # Log specific error details
            if hasattr(e, 'response'):
                logger.error(f"Response status: {e.response.status_code if e.response else 'No response'}")
            if hasattr(e, 'request'):
                logger.error(f"Request URL: {e.request.url if e.request else 'No request'}")

            return False

    async def extract_text_from_image(self, image_data: bytes, image_format: str) -> str:
        """Extract text from image using GPT-4 Turbo with Vision."""
        try:
            # Convert image to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')

            # Prepare the message with image
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """Extract all readable text from this image. The image might be a screenshot, scanned document, or similar. 
                            
                            Requirements:
                            - Return only the extracted text, no additional commentary
                            - Handle tilted/rotated images (±5°, 90°, 180°, etc.)
                            - Adjust for transparent overlays if text is still readable
                            - If no readable text is detected or the image is invalid, return 'NO_TEXT_DETECTED'
                            - Only process images that look like screenshots, scanned pages, or documents with text
                            - Organize the text in paragraph format when possible"""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{image_format};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]

            response = await self._make_api_call(
                model=settings.gpt4o_model,
                messages=messages,
                max_tokens=settings.max_tokens,
                temperature=settings.temperature
            )

            extracted_text = response.choices[0].message.content.strip()

            if extracted_text == "NO_TEXT_DETECTED":
                raise LLMServiceError("No readable text detected in the image")

            logger.info("Successfully extracted text from image", text_length=len(extracted_text))
            return extracted_text

        except Exception as e:
            logger.error("Failed to extract text from image", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to process image: {str(e)}")

    async def convert_image_to_html(self, image_data: bytes, image_format: str = "png") -> str:
        """Convert a PDF page image to HTML using GPT-4 Vision.
        
        This method takes an image of a PDF page and generates accurate HTML
        that preserves the original layout, formatting, and structure.
        
        Args:
            image_data: Image bytes of the PDF page
            image_format: Image format (default: png)
            
        Returns:
            Complete HTML document string with embedded CSS
        """
        try:
            # Convert image to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')

            # Optimized prompt for PDF to HTML conversion - layout preservation is critical
            prompt = """You are an expert HTML/CSS developer who converts PDF page images into pixel-perfect HTML replicas. Your PRIMARY goal is to EXACTLY replicate the visual layout, positioning, colors, and formatting of the original PDF.

MOST CRITICAL REQUIREMENT - LAYOUT PRESERVATION:

The HTML output MUST look IDENTICAL to the input image. If the PDF has:
- TWO COLUMNS → Create TWO COLUMNS using CSS Grid or Flexbox
- THREE COLUMNS → Create THREE COLUMNS
- Sidebar on left → Put sidebar content on LEFT
- Content on right → Put main content on RIGHT

DETAILED INSTRUCTIONS:

1. LAYOUT REPLICATION (HIGHEST PRIORITY)
   - CAREFULLY analyze the page layout BEFORE generating HTML
   - If content is in MULTIPLE COLUMNS, you MUST use CSS Grid or Flexbox:
     * Two-column layout example:
       .page-container { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; }
       .left-column { } .right-column { }
     * Or with flexbox:
       .page-container { display: flex; gap: 40px; }
       .left-column { flex: 1; } .right-column { flex: 1; }
   - Match the EXACT column widths as seen in the image (e.g., 40%-60% split)
   - Preserve the vertical alignment of sections across columns
   - DO NOT convert a two-column layout into a single-column layout

2. COLOR PRESERVATION (VERY IMPORTANT)
   - Extract and use the EXACT colors from the image:
     * Headings often have specific colors (blue, dark gray, etc.)
     * Some text may be colored (orange, blue, etc.) for emphasis
     * Use hex color codes: #2B547E for blue, #CC5500 for orange, etc.
   - Apply colors using CSS: color: #hexcode;
   - Bold colored text should use: <strong style="color: #hexcode;">text</strong>
   - Or define CSS classes: .text-blue { color: #2B547E; }

3. TEXT FORMATTING (VERY IMPORTANT)
   - BOLD text MUST be wrapped in <strong> tags
   - Italic text MUST be wrapped in <em> tags
   - Preserve ALL formatting visible in the image:
     * If "CCTV" appears bold → <strong>CCTV</strong>
     * If "fire alerts" appears bold and colored → <strong class="text-orange">fire alerts</strong>
   - Use CSS font-weight: 600 or 700 for bold headings
   - Preserve SMALL CAPS if present: font-variant: small-caps;

4. OUTPUT FORMAT
   - Generate complete HTML: <!DOCTYPE html><html><head>...</head><body>...</body></html>
   - Include all CSS in a <style> block
   - Output ONLY raw HTML - no explanations, no markdown code blocks

5. STRUCTURE & COMPONENTS
   - Use semantic HTML: <header>, <main>, <section>, <article>, <aside>
   - Each section (Education, Experience, Skills) should be in its own container
   - Nest elements properly:
     <section class="education-section">
       <h2>EDUCATION</h2>
       <article class="education-item">
         <h3>School Name</h3>
         <div class="details">
           <p><span class="label">Course:</span> <span class="value">Course Name</span></p>
         </div>
       </article>
     </section>

6. TYPOGRAPHY
   - Match font sizes relatively (headings larger than body)
   - Section headings: font-size: 1.3em; font-weight: bold; text-transform: uppercase;
   - Subsection headings: font-size: 1.1em; font-weight: bold;
   - Body text: font-size: 1em; line-height: 1.5;
   - Use letter-spacing if headings appear spaced out

7. SPACING & ALIGNMENT
   - Match margins and padding to replicate whitespace
   - Align text as seen: left, center, or right
   - Use consistent spacing between sections
   - Preserve indentation for nested content and lists

8. LISTS
   - Use <ul> for bullet lists with proper <li> items
   - Style bullets to match: list-style-type: disc; or custom bullets
   - Preserve indentation levels for nested lists

9. KEY-VALUE PAIRS (like "Course: Engineering")
   - Structure as: <div class="field"><span class="label">Course:</span> <span class="value">Engineering</span></div>
   - Style labels differently: font-weight: bold; or font-variant: small-caps;

10. CSS ORGANIZATION
    - Define CSS variables for colors: --primary-color: #2B547E; --accent-color: #CC5500;
    - Create layout classes: .two-column, .left-column, .right-column
    - Create text utility classes: .text-bold, .text-blue, .text-orange, .small-caps

EXAMPLE CSS FOR TWO-COLUMN RESUME:
```css
.page-container {
  display: grid;
  grid-template-columns: 35% 65%;
  gap: 30px;
  max-width: 900px;
  margin: 0 auto;
  padding: 20px;
}
.left-column { }
.right-column { }
.section-title {
  color: #2B547E;
  font-size: 1.2em;
  font-weight: bold;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 15px;
}
```

REMEMBER: The final HTML when rendered should look EXACTLY like the input PDF image - same columns, same colors, same bold text, same alignment. Output ONLY the HTML document."""

            # Prepare the message with image
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{image_format};base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ]

            # Use GPT-4o for best vision capabilities
            response = await self._make_api_call(
                model=settings.gpt4o_model,
                messages=messages,
                max_tokens=4096,  # Higher token limit for complete HTML output
                temperature=0.2  # Lower temperature for more consistent output
            )

            html_content = response.choices[0].message.content.strip()

            # Clean up the response - remove markdown code blocks if present
            if html_content.startswith("```html"):
                html_content = html_content[7:]
            elif html_content.startswith("```"):
                html_content = html_content[3:]
            if html_content.endswith("```"):
                html_content = html_content[:-3]
            html_content = html_content.strip()

            # Validate that we got HTML
            if not html_content or not html_content.startswith("<!DOCTYPE") and not html_content.startswith("<html"):
                # If response doesn't look like HTML, wrap it
                if html_content and not html_content.startswith("<"):
                    logger.warning("OpenAI returned non-HTML response, wrapping in basic HTML")
                    html_content = self._wrap_text_in_html(html_content)

            logger.info("Successfully converted image to HTML", html_length=len(html_content))
            return html_content

        except Exception as e:
            logger.error("Failed to convert image to HTML", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to convert PDF page to HTML: {str(e)}")

    def _wrap_text_in_html(self, text: str) -> str:
        """Wrap plain text in a basic HTML document structure."""
        import html as html_escape
        escaped_text = html_escape.escape(text)
        paragraphs = escaped_text.split('\n\n')
        body_content = '\n'.join(f'<p>{p}</p>' for p in paragraphs if p.strip())
        
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
        }}
        p {{
            margin: 1em 0;
        }}
    </style>
</head>
<body>
    {body_content}
</body>
</html>"""

    async def get_important_words(self, text: str, language_code: Optional[str] = None) -> List[str]:
        """Get top 10 most important/difficult words from text in the order they appear."""
        try:
            # Build language requirement section (for response format, not content language)
            language_note = ""
            if language_code:
                language_name = get_language_name(language_code)
                if language_name:
                    language_note = f"\n\nNote: The text is in {language_name} ({language_code})."

            prompt = f"""
            Analyze the following text and identify the top 10 most important and contextually significant words.
            {language_note}

            Requirements:
            - Remove obvious stopwords (a, the, to, and, or, but, etc.)
            - Focus on content-heavy, contextually important words
            - Return words in order of decreasing importance
            - For each word, find its exact starting character index in the original text (0-based indexing)
            - The index must be calculated **based on the original raw character positions** in the text, including punctuation and whitespace
            - Also include the word's length in characters
            - Return the result as a JSON array with 10 objects, each containing: 'word', 'index', and 'length'

            Text:
            \"\"\"{text}\"\"\"

            Important:
            - All words must be present in the original text
            - If fewer than 10 important words are found, return as many as possible
            - Ensure the index corresponds to the first occurrence of the word in the text
            - If a word appears multiple times, use the index of its first occurrence
            - Do not approximate or guess the index — it must match the position in the original text exactly
            - Return only the JSON array. No explanation, no code blocks, no markdown formatting
            """

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.3
            )

            result = response.choices[0].message.content.strip()

            try:
                if result.startswith("```"):
                    result = re.sub(r"^```(?:json)?\n|\n```$", "", result.strip())

                words_data = json.loads(result)
                if not isinstance(words_data, list):
                    raise ValueError("Expected JSON array")

                # Validate entries
                validated_words = []
                for word_info in words_data[:10]:
                    if all(key in word_info for key in ['word', 'index', 'length']):
                        start_idx = word_info['index']
                        length = word_info['length']
                        if 0 <= start_idx < len(text) and start_idx + length <= len(text):
                            validated_words.append({
                                'word': word_info['word'],
                                'index': start_idx
                            })

                # Sort by index to ensure order of appearance in original text
                validated_words.sort(key=lambda w: w['index'])

                # Return only the words in order
                ordered_words = [w['word'].lower() for w in validated_words]

                logger.info("Successfully extracted important words", count=len(ordered_words))
                return ordered_words

            except json.JSONDecodeError as e:
                logger.error("Failed to parse LLM response as JSON", error=str(e), response=result)
                raise LLMServiceError("Failed to parse important words response")

        except Exception as e:
            logger.error("Failed to get important words", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to analyze text for important words: {str(e)}")

    async def get_word_explanation(self, word: str, context: str, language_code: Optional[str] = None) -> str:
        """Get explanation and examples for a single word in context.
        Returns the raw formatted response string that the frontend will parse.
        
        Args:
            word: The word to explain
            context: The context in which the word appears
            language_code: Optional target language code. If provided, response will be in this language.
                          If None, language will be detected from the context.
        
        Returns:
            Raw formatted string in the format: [[[WORD_MEANING]]]:{...}[[[EXAMPLES]]]:{[[ITEM]]{...}[[ITEM]]{...}}
        """
        try:
            # Build language requirement section
            if language_code:
                # Case 2: languageCode is provided - use it directly in prompt
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in {language_name} ({language_code})
            - The meaning and examples MUST be in {language_name} ONLY
            - Do NOT use any other language - ONLY {language_name}
            - This is MANDATORY and NON-NEGOTIABLE"""
                else:
                    language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in the language specified by code: {language_code.upper()}
            - The meaning and examples MUST be in this language ONLY
            - Do NOT use any other language"""
            else:
                # Case 1: languageCode is None - detect language from context
                detected_language_code = await self.detect_text_language_code(context)
                detected_language_name = get_language_name(detected_language_code)
                language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in {detected_language_name or detected_language_code} ({detected_language_code})
            - The meaning and examples MUST be in {detected_language_name or detected_language_code} ONLY
            - Do NOT use any other language - ONLY {detected_language_name or detected_language_code}
            - This is MANDATORY and NON-NEGOTIABLE"""

            prompt = f"""Provide a simplified explanation and exactly 2 example sentences for the word "{word}" in the given context.

            Context: "{context}"
            Word: "{word}"
            {language_requirement}
            
            Requirements:
            - Provide a simple, clear meaning of the word as used in this context
            - Create exactly 2 simple example sentences showing how to use the word
            - Keep explanations accessible for language learners
            
            CRITICAL FORMAT REQUIREMENT - YOU MUST FOLLOW THIS EXACT FORMAT:
            The response MUST be in this exact format (no deviations allowed):
            [[[WORD_MEANING]]]:{{text explaining the meaning of the word}}[[[EXAMPLES]]]:{{[[ITEM]]{{example sentence 1}}[[ITEM]]{{example sentence 2}}}}
            
            Format rules:
            1. WORD_MEANING must be surrounded by [[[ and ]]]
            2. After [[[WORD_MEANING]]]: provide the meaning text
            3. EXAMPLES must be surrounded by [[[ and ]]]
            4. Each example sentence must start with [[ITEM]] followed by the example sentence
            5. There must be exactly 2 examples, each wrapped in [[ITEM]]{{...}}
            6. The format is: [[[WORD_MEANING]]]:{{meaning}}[[[EXAMPLES]]]:{{[[ITEM]]{{example1}}[[ITEM]]{{example2}}}}
            
            Example of correct format:
            [[[WORD_MEANING]]]:{{A word that means something important}}[[[EXAMPLES]]]:{{[[ITEM]]{{This is the first example sentence.}}[[ITEM]]{{This is the second example sentence.}}}}
            
            Return ONLY the formatted response in the exact format specified above. No additional text, no JSON, no explanations."""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=settings.temperature
            )

            result = response.choices[0].message.content.strip()

            # Return the raw response string - frontend will parse it
            logger.info("Successfully got word explanation", word=word, language_code=language_code)
            return result

        except Exception as e:
            logger.error("Failed to get word explanation", word=word, error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to get explanation for word '{word}': {str(e)}")

    async def get_more_examples(self, word: str, meaning: str, existing_examples: List[str]) -> List[str]:
        """Generate 2 additional, simpler example sentences for a word."""
        try:
            existing_examples_text = "\n".join(f"- {ex}" for ex in existing_examples)

            prompt = f"""Generate exactly 2 additional, even simpler example sentences for the word "{word}".

            Word: "{word}"
            Meaning: "{meaning}"
            
            Existing examples:
            {existing_examples_text}
            
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST detect the language of the existing examples and respond in the EXACT SAME LANGUAGE
            - If the existing examples are in English, provide new examples in English
            - If the existing examples are in Hindi, provide new examples in Hindi
            - If the existing examples are in Spanish, provide new examples in Spanish
            - This applies to ALL languages - always match the language of the existing examples
            - Do NOT default to English - always match the language of the input
            
            Requirements:
            - Create exactly 2 NEW example sentences (different from existing ones)
            - Since the existing examples were hard to understand, make them simpler and more accessible
            - Show clear usage of the word in context
            - Keep sentences easy to understand
            - Return as a JSON array of exactly 2 strings
            
            Return only the JSON array, no additional text."""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=settings.temperature
            )

            result = response.choices[0].message.content.strip()
            logger.debug("Raw response from OpenAI", result=result)

            # Strip Markdown code block (e.g., ```json\n...\n```)
            if result.startswith("```"):
                result = re.sub(r"^```(?:json)?\n|\n```$", "", result.strip())

            # Parse the JSON response
            new_examples = json.loads(result)

            if not isinstance(new_examples, list) or len(new_examples) != 2:
                logger.warning("Invalid response format from OpenAI", result=result)
                raise ValueError("Expected JSON array of exactly 2 items")

            logger.info("Successfully generated more examples", word=word)
            return new_examples

        except Exception as e:
            logger.error("Failed to get more examples", word=word, error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to generate more examples for word '{word}': {str(e)}")

    async def get_synonyms_of_word(self, word: str) -> List[str]:
        """Get up to 3 accurate synonyms for a word. Returns at least 1 synonym."""
        try:
            prompt = f"""Find accurate synonyms for the word "{word}".

            Word: "{word}"
            
            CRITICAL REQUIREMENTS - ACCURACY IS PARAMOUNT:
            - Provide up to 3 synonyms (at least 1 is required)
            - Prioritize accuracy over quantity - only include synonyms that are truly accurate
            - Synonyms must be words that can be used in the same context as the given word
            - Do not include words that are only loosely related - they must be true synonyms
            - Return as a JSON array of strings
            - If you can only find 1 accurate synonym, return an array with just that one word
            - If you find 2 accurate synonyms, return an array with those 2 words
            - If you find 3 accurate synonyms, return an array with those 3 words
            - Maximum 3 synonyms, minimum 1 synonym
            
            Return only the JSON array, no additional text or explanation."""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=settings.temperature
            )

            result = response.choices[0].message.content.strip()
            logger.debug("Raw response from OpenAI for synonyms", word=word, result=result)

            # Strip Markdown code block (e.g., ```json\n...\n```)
            if result.startswith("```"):
                result = re.sub(r"^```(?:json)?\n|\n```$", "", result.strip())

            # Parse the JSON response
            synonyms = json.loads(result)

            if not isinstance(synonyms, list):
                logger.warning("Invalid response format from OpenAI", word=word, result=result)
                raise ValueError("Expected JSON array")

            # Validate that all items are strings
            if not all(isinstance(syn, str) for syn in synonyms):
                logger.warning("Invalid response format - not all items are strings", word=word, result=result)
                raise ValueError("All items in the array must be strings")

            # Validate count (1-3 synonyms)
            if len(synonyms) == 0:
                logger.warning("No synonyms returned", word=word, result=result)
                raise ValueError("At least 1 synonym is required")
            
            if len(synonyms) > 3:
                logger.warning("Too many synonyms returned, truncating to 3", word=word, count=len(synonyms))
                synonyms = synonyms[:3]

            # Filter out empty strings
            synonyms = [syn.strip() for syn in synonyms if syn.strip()]

            if len(synonyms) == 0:
                logger.warning("No valid synonyms after filtering", word=word, result=result)
                raise ValueError("At least 1 valid synonym is required")

            logger.info("Successfully got synonyms", word=word, count=len(synonyms))
            return synonyms

        except Exception as e:
            logger.error("Failed to get synonyms", word=word, error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to get synonyms for word '{word}': {str(e)}")

    async def get_opposite_of_word(self, word: str) -> List[str]:
        """Get up to 2 accurate antonyms (opposites) for a word. Returns at least 1 antonym."""
        try:
            prompt = f"""Find accurate antonyms (opposites) for the word "{word}".

            Word: "{word}"
            
            CRITICAL REQUIREMENTS - ACCURACY IS PARAMOUNT:
            - Provide up to 2 antonyms (at least 1 is required)
            - Prioritize accuracy over quantity - only include antonyms that are truly accurate
            - Antonyms must be words that are direct opposites of the given word
            - Do not include words that are only loosely related - they must be true antonyms
            - Return as a JSON array of strings
            - If you can only find 1 accurate antonym, return an array with just that one word
            - If you find 2 accurate antonyms, return an array with those 2 words
            - Maximum 2 antonyms, minimum 1 antonym
            
            Return only the JSON array, no additional text or explanation."""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=settings.temperature
            )

            result = response.choices[0].message.content.strip()
            logger.debug("Raw response from OpenAI for antonyms", word=word, result=result)

            # Strip Markdown code block (e.g., ```json\n...\n```)
            if result.startswith("```"):
                result = re.sub(r"^```(?:json)?\n|\n```$", "", result.strip())

            # Parse the JSON response
            antonyms = json.loads(result)

            if not isinstance(antonyms, list):
                logger.warning("Invalid response format from OpenAI", word=word, result=result)
                raise ValueError("Expected JSON array")

            # Validate that all items are strings
            if not all(isinstance(ant, str) for ant in antonyms):
                logger.warning("Invalid response format - not all items are strings", word=word, result=result)
                raise ValueError("All items in the array must be strings")

            # Validate count (1-2 antonyms)
            if len(antonyms) == 0:
                logger.warning("No antonyms returned", word=word, result=result)
                raise ValueError("At least 1 antonym is required")
            
            if len(antonyms) > 2:
                logger.warning("Too many antonyms returned, truncating to 2", word=word, count=len(antonyms))
                antonyms = antonyms[:2]

            # Filter out empty strings
            antonyms = [ant.strip() for ant in antonyms if ant.strip()]

            if len(antonyms) == 0:
                logger.warning("No valid antonyms after filtering", word=word, result=result)
                raise ValueError("At least 1 valid antonym is required")

            logger.info("Successfully got antonyms", word=word, count=len(antonyms))
            return antonyms

        except Exception as e:
            logger.error("Failed to get antonyms", word=word, error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to get antonyms for word '{word}': {str(e)}")

    async def generate_random_paragraph(self, word_count: int, difficulty_percentage: int) -> str:
        """Generate a random paragraph with specified word count and difficulty level."""
        try:
            prompt = f"""Generate a random paragraph with approximately {word_count} words where {difficulty_percentage}% of the words are difficult to understand (advanced vocabulary).

            Requirements:
            - Target approximately {word_count} words (don't worry about exact count)
            - {difficulty_percentage}% of words should be challenging/advanced vocabulary
            - The remaining {100 - difficulty_percentage}% should be common, easy words
            - Create a coherent, meaningful paragraph (not just a list of words)
            - Choose a random topic (science, literature, history, technology, etc.)
            - Make it educational and engaging for vocabulary learning
            - Return only the paragraph text, no additional commentary or formatting
            - Focus on natural flow and coherence rather than exact word count
            
            The paragraph should help users improve their vocabulary skills by encountering challenging words in context."""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.8  # Higher temperature for more creative/random content
            )

            generated_text = response.choices[0].message.content.strip()
            
            # Count actual words for logging purposes only
            word_count_actual = len(generated_text.split())

            logger.info("Successfully generated random paragraph", 
                       word_count=word_count_actual, difficulty_percentage=difficulty_percentage)
            return generated_text

        except Exception as e:
            logger.error("Failed to generate random paragraph", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to generate random paragraph: {str(e)}")

    async def generate_random_paragraph_with_topics(self, topics: List[str], word_count: int, difficulty_percentage: int) -> str:
        """Generate a random paragraph with specified topics/keywords, word count and difficulty level."""
        try:
            # Build topics section for the prompt
            topics_section = ""
            if topics:
                topics_list = ", ".join(f'"{topic}"' for topic in topics)
                topics_section = f"""
            Topics/Keywords to include: {topics_list}
            - Incorporate these topics naturally into the paragraph
            - Use them as themes or central concepts
            - Make sure the paragraph revolves around these topics"""
            else:
                topics_section = """
            - Choose any random topic (science, literature, history, technology, nature, etc.)
            - Make it interesting and educational"""

            prompt = f"""Generate a random paragraph with approximately {word_count} words where {difficulty_percentage}% of the words are difficult to understand (advanced vocabulary).
            {topics_section}

            Requirements:
            - Target approximately {word_count} words (don't worry about exact count)
            - {difficulty_percentage}% of words should be challenging/advanced vocabulary
            - The remaining {100 - difficulty_percentage}% should be common, easy words
            - Create a coherent, meaningful paragraph (not just a list of words)
            - Make it educational and engaging for vocabulary learning
            - Return only the paragraph text, no additional commentary or formatting
            - Focus on natural flow and coherence rather than exact word count
            
            The paragraph should help users improve their vocabulary skills by encountering challenging words in context."""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.8  # Higher temperature for more creative/random content
            )

            generated_text = response.choices[0].message.content.strip()
            
            # Count actual words for logging purposes only
            word_count_actual = len(generated_text.split())

            logger.info("Successfully generated random paragraph with topics", 
                       word_count=word_count_actual, 
                       difficulty_percentage=difficulty_percentage,
                       topics_count=len(topics),
                       topics=topics)
            return generated_text

        except Exception as e:
            logger.error("Failed to generate random paragraph with topics", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to generate random paragraph with topics: {str(e)}")

    async def _make_api_call(self, **kwargs):
        """Make an API call with robust error handling and retry logic."""
        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                logger.info("Making OpenAI API call", attempt=attempt + 1, max_retries=max_retries)

                response = await self.client.chat.completions.create(**kwargs)

                logger.info("OpenAI API call successful", response_id=response.id, attempt=attempt + 1)
                return response

            except Exception as api_error:
                error_type = type(api_error).__name__
                error_msg = str(api_error)

                logger.error("OpenAI API call failed",
                            error=error_msg,
                            error_type=error_type,
                            attempt=attempt + 1)

                # Log additional error details
                if hasattr(api_error, 'response') and api_error.response:
                    logger.error(f"API Response status: {api_error.response.status_code}")
                    logger.error(f"API Response headers: {dict(api_error.response.headers)}")

                if hasattr(api_error, 'request') and api_error.request:
                    logger.error(f"Request URL: {api_error.request.url}")

                # Don't retry on certain error types
                if error_type in ['AuthenticationError', 'PermissionDeniedError', 'BadRequestError']:
                    logger.error(f"Non-retryable error: {error_type}")
                    raise LLMServiceError(f"API Error: {error_msg}")

                if attempt == max_retries - 1:
                    raise LLMServiceError(f"Connection error after {max_retries} attempts: {error_msg}")

                # Wait before retrying, except on the last attempt
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...", attempt=attempt + 1)
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff

    async def simplify_text(self, text: str, previous_simplified_texts: List[str], language_code: Optional[str] = None) -> str:
        """Simplify text using OpenAI with context from previous simplifications."""
        try:
            # Build context from previous simplifications
            context_section = ""
            if previous_simplified_texts:
                context_section = f"""
            Previous simplified versions for reference:
            {chr(10).join(f"- {simplified}" for simplified in previous_simplified_texts)}
            
            These previous versions are still too complex. Create a MUCH simpler version with:
            - Even shorter sentences (5-8 words maximum)
            - Even simpler words (basic vocabulary only)
            - More broken-up sentence structure
            - Avoid any complex phrases or grammar
            """
            else:
                context_section = """
            This is the first simplification attempt. Make it EXTREMELY simple with very short sentences and basic words.
            """

            # Build language requirement section
            if language_code:
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in {language_name} ({language_code})
            - The simplified text MUST be in {language_name} ONLY
            - Do NOT use any other language - ONLY {language_name}
            - This is MANDATORY and NON-NEGOTIABLE"""
                else:
                    language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in the language specified by code: {language_code.upper()}
            - The simplified text MUST be in this language ONLY
            - Do NOT use any other language"""
            else:
                language_requirement = """
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST detect the language of the input text and respond in the EXACT SAME LANGUAGE
            - If the input is in English, respond in English
            - If the input is in Hindi, respond in Hindi
            - If the input is in Spanish, respond in Spanish
            - This applies to ALL languages - always match the input language
            - Do NOT default to English - always match the language of the input text"""

            prompt = f"""Simplify the following text to make it EXTREMELY easy to understand. Use the simplest possible language and sentence structure.

            {context_section}

            Original text:
            "{text}"
            {language_requirement}

            CRITICAL REQUIREMENTS:
            - Use ONLY basic, everyday words (like "big" instead of "enormous", "old" instead of "ancient")
            - Write in VERY short, simple sentences (maximum 8-10 words per sentence)
            - Use simple sentence patterns: Subject + Verb + Object
            - Avoid complex grammar, clauses, and fancy words
            - Break long ideas into multiple short sentences
            - Use common words that a 10-year-old would understand
            - If previous simplified versions exist, make this one MUCH simpler with even shorter sentences
            - Replace complex phrases with simple ones (e.g., "as if" → "like", "in order to" → "to")
            - Use active voice instead of passive voice
            - Return only the simplified text, no additional commentary

            Simplified text:"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.3
            )

            simplified_text = response.choices[0].message.content.strip()
            
            logger.info("Successfully simplified text", 
                       original_length=len(text),
                       simplified_length=len(simplified_text),
                       has_previous_context=bool(previous_simplified_texts))
            
            return simplified_text

        except Exception as e:
            logger.error("Failed to simplify text", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to simplify text: {str(e)}")

    async def simplify_text_stream(self, text: str, previous_simplified_texts: List[str], language_code: Optional[str] = None, context: Optional[str] = None):
        """Simplify text with streaming using OpenAI with context from previous simplifications.

        Yields chunks of simplified text as they are generated by OpenAI.

        Args:
            text: The text to simplify
            previous_simplified_texts: Previous simplified versions for context
            language_code: Optional target language code. If provided, response will be in this language.
                          If None, language will be detected from the input text.
            context: Optional full context surrounding the text (prefix + text + suffix). 
                    This helps the AI better understand the meaning and simplify appropriately.
        """
        try:
            # Build context from previous simplifications
            context_section = ""
            if previous_simplified_texts:
                context_section = f"""
            Previous simplified versions for reference:
            {chr(10).join(f"- {simplified}" for simplified in previous_simplified_texts)}
            
            These previous versions are still too complex. Create a MUCH simpler version with:
            - Even shorter sentences (5-8 words maximum)
            - Even simpler words (basic vocabulary only)
            - More broken-up sentence structure
            - Avoid any complex phrases or grammar
            """
            else:
                context_section = """
            This is the first simplification attempt. Make it EXTREMELY simple with very short sentences and basic words.
            """

            # Build language requirement section
            if language_code:
                # Case 2: languageCode is provided - use it directly in prompt
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in {language_name} ({language_code})
            - The simplified text MUST be in {language_name} ONLY
            - Do NOT use any other language - ONLY {language_name}
            - This is MANDATORY and NON-NEGOTIABLE"""
                else:
                    language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in the language specified by code: {language_code.upper()}
            - The simplified text MUST be in this language ONLY
            - Do NOT use any other language"""
            else:
                # Case 1: languageCode is None - detect language from input text
                detected_language_code = await self.detect_text_language_code(text)
                detected_language_name = get_language_name(detected_language_code)
                language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in {detected_language_name or detected_language_code} ({detected_language_code})
            - The simplified text MUST be in {detected_language_name or detected_language_code} ONLY
            - Do NOT use any other language - ONLY {detected_language_name or detected_language_code}
            - This is MANDATORY and NON-NEGOTIABLE"""

            # Build surrounding context section if provided
            surrounding_context_section = ""
            if context:
                surrounding_context_section = f"""
            ⚠️ CRITICAL: FULL CONTEXT PROVIDED - YOU MUST SIMPLIFY IN THE CONTEXT OF THIS ⚠️
            
            The following is the FULL CONTEXT surrounding the text you need to simplify. This includes:
            - The text BEFORE (prefix) the text to simplify
            - The text itself (which you need to simplify)
            - The text AFTER (suffix) the text to simplify
            
            Full Context:
            "{context}"
            
            🔑 MANDATORY INSTRUCTIONS FOR CONTEXT-AWARE SIMPLIFICATION:
            - You MUST simplify the text IN THE CONTEXT OF this full context
            - The simplified explanation MUST make sense within this broader narrative
            - Use the surrounding context to understand:
              * What happened before (prefix) - this sets up the situation
              * What happens after (suffix) - this shows the consequences or continuation
              * The overall meaning, tone, and purpose of the text within this context
            - When simplifying, ensure the simplified version:
              * Maintains logical flow with what comes before and after
              * Preserves important connections to the surrounding narrative
              * Fits naturally within the broader context
              * Makes sense in relation to the events/ideas described before and after
            - The simplified text should be understandable both on its own AND as part of this larger context
            - DO NOT simplify in isolation - always consider how it relates to the full context
            
            """
            
            # Update the main prompt based on whether context is provided
            if context:
                main_instruction = f"""Simplify the following text IN THE CONTEXT OF the full context provided above. Make it EXTREMELY easy to understand while ensuring it makes perfect sense within the broader narrative context."""
            else:
                main_instruction = f"""Simplify the following text to make it EXTREMELY easy to understand. Use the simplest possible language and sentence structure."""
            
            prompt = f"""{main_instruction}

            {surrounding_context_section}{context_section}

            Text to simplify:
            "{text}"
            {language_requirement}

            CRITICAL REQUIREMENTS:
            - Use ONLY basic, everyday words (like "big" instead of "enormous", "old" instead of "ancient")
            - Write in VERY short, simple sentences (maximum 8-10 words per sentence)
            - Use simple sentence patterns: Subject + Verb + Object
            - Avoid complex grammar, clauses, and fancy words
            - Break long ideas into multiple short sentences
            - Use common words that a 10-year-old would understand
            - If previous simplified versions exist, make this one MUCH simpler with even shorter sentences
            - Replace complex phrases with simple ones (e.g., "as if" → "like", "in order to" → "to")
            - Use active voice instead of passive voice
            {"- ⚠️ CONTEXT-AWARE SIMPLIFICATION: The full context has been provided above. You MUST simplify the text IN THE CONTEXT OF that context. The simplified version must:" if context else ""}
            {"  * Make sense within the broader narrative (considering what comes before and after)" if context else ""}
            {"  * Maintain logical flow and connections to the surrounding text" if context else ""}
            {"  * Preserve the meaning and intent as it relates to the full context" if context else ""}
            {"  * Be coherent both standalone AND as part of the larger context" if context else ""}
            - Return only the simplified text, no additional commentary

            Simplified text:"""

            # Create streaming response
            stream = await self.client.chat.completions.create(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.3,
                stream=True
            )

            # Yield chunks as they arrive (streaming directly from OpenAI)
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content

            logger.info("Successfully streamed simplified text",
                       original_length=len(text),
                       has_previous_context=bool(previous_simplified_texts),
                       has_surrounding_context=bool(context),
                       language_code=language_code)

        except Exception as e:
            logger.error("Failed to stream simplified text", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to stream simplified text: {str(e)}")

    async def simplify_image_stream(self, image_data: bytes, image_format: str, previous_simplified_texts: List[str], language_code: Optional[str] = None):
        """Simplify image content with streaming using OpenAI Vision API.

        Yields chunks of simplified explanation as they are generated by OpenAI.

        Args:
            image_data: The image file data (bytes)
            image_format: Image format (jpeg, png, gif, webp)
            previous_simplified_texts: Previous simplified versions for context
            language_code: Optional target language code. If provided, response will be in this language.
                          If None, language will be auto-detected.
        """
        try:
            # Convert image to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')

            # Build context from previous simplifications
            context_section = ""
            if previous_simplified_texts:
                context_section = f"""
            Previous simplified versions for reference:
            {chr(10).join(f"- {simplified}" for simplified in previous_simplified_texts)}
            
            These previous versions are still too complex. Create a MUCH simpler version with:
            - Even shorter sentences (5-8 words maximum)
            - Even simpler words (basic vocabulary only)
            - More broken-up sentence structure
            - Avoid any complex phrases or grammar
            """
            else:
                context_section = """
            This is the first simplification attempt. Make it EXTREMELY simple with very short sentences and basic words.
            """

            # Build language requirement section
            if language_code:
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in {language_name} ({language_code})
            - The simplified explanation MUST be in {language_name} ONLY
            - Do NOT use any other language - ONLY {language_name}
            - This is MANDATORY and NON-NEGOTIABLE"""
                else:
                    language_requirement = f"""
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST respond STRICTLY in the language specified by code: {language_code.upper()}
            - The simplified explanation MUST be in this language ONLY
            - Do NOT use any other language"""
            else:
                # Auto-detect language from image content (will be handled by model)
                language_requirement = """
            CRITICAL LANGUAGE REQUIREMENT:
            - You MUST detect the language from the image content and respond in the SAME language
            - If the image contains text in English, respond in English
            - If the image contains text in another language, respond in that language
            - If no text is detected, respond in English by default
            - This is MANDATORY and NON-NEGOTIABLE"""

            prompt = f"""Analyze this image and provide a simplified explanation of what you see. Make it EXTREMELY easy to understand.

            {context_section}

            {language_requirement}

            CRITICAL REQUIREMENTS:
            - Use ONLY basic, everyday words (like "big" instead of "enormous", "old" instead of "ancient")
            - Write in VERY short, simple sentences (maximum 8-10 words per sentence)
            - Use simple sentence patterns: Subject + Verb + Object
            - Avoid complex grammar, clauses, and fancy words
            - Break long ideas into multiple short sentences
            - Use common words that a 10-year-old would understand
            - If previous simplified versions exist, make this one MUCH simpler with even shorter sentences
            - Replace complex phrases with simple ones (e.g., "as if" → "like", "in order to" → "to")
            - Use active voice instead of passive voice
            - Describe what you see in the image in the simplest way possible
            - If the image contains text, explain what the text says in simple terms
            - If the image shows a concept or diagram, explain it in very simple language
            - Return only the simplified explanation, no additional commentary

            Simplified explanation:"""

            # Prepare the message with image
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{image_format};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]

            # Create streaming response
            stream = await self.client.chat.completions.create(
                model=settings.gpt4o_model,
                messages=messages,
                max_tokens=settings.max_tokens,
                temperature=0.3,
                stream=True
            )

            # Yield chunks as they arrive (streaming directly from OpenAI)
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content

            logger.info("Successfully streamed simplified image explanation",
                       has_previous_context=bool(previous_simplified_texts),
                       language_code=language_code)

        except Exception as e:
            logger.error("Failed to stream simplified image explanation", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to stream simplified image explanation: {str(e)}")

    async def generate_contextual_answer(self, question: str, chat_history: List, initial_context: Optional[str] = None, language_code: Optional[str] = None) -> str:
        """Generate contextual answer using chat history for ongoing conversations."""
        try:
            # Build messages from chat history
            messages = []
            
            # Build language requirement section
            if language_code:
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in {language_name} ({language_code})
- Your answer MUST be in {language_name} ONLY
- Do NOT use any other language - ONLY {language_name}
- This is MANDATORY and NON-NEGOTIABLE"""
                else:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in the language specified by code: {language_code.upper()}
- Your answer MUST be in this language ONLY
- Do NOT use any other language"""
            else:
                language_requirement = """
CRITICAL LANGUAGE REQUIREMENT:
- You MUST detect the language of the user's question and respond in the EXACT SAME LANGUAGE
- If the user asks in English, respond in English
- If the user asks in Hindi, respond in Hindi
- If the user asks in Spanish, respond in Spanish
- This applies to ALL languages - always match the user's input language
- The language of your response should dynamically change based on each question's language
- Do NOT default to English - always match the language of the current question"""
            
            # Add system message for context
            system_content = f"""You are a helpful AI assistant that provides clear, accurate, and contextual answers. Use the conversation history to maintain context and provide relevant responses.

{language_requirement}

CRITICAL CONTEXT VALIDATION REQUIREMENTS:
- You MUST carefully evaluate whether the user's question is related to the provided context (initial context and conversation history)
- If the user's question is COMPLETELY UNRELATED to the given context:
  * You MUST STRICTLY and CLEARLY point this out to the user
  * Use a polite but direct approach (e.g., "⚠️ This question is not related to the context provided" or "This question is outside the scope of the given context")
  * Explain that you can only answer questions based on the provided context
  * Do NOT attempt to answer unrelated questions - instead, redirect the user to ask questions relevant to the context
- If the user's question is SOMEWHAT RELEVANT but unclear or ambiguous:
  * You MUST ask clarifying questions to better understand what the user wants to know
  * Ask 1-2 specific, helpful clarifying questions that will help you provide a better answer
  * Examples: "Could you clarify what aspect of [topic] you're interested in?", "Are you asking about [option A] or [option B]?"
  * Do NOT guess or provide vague answers - always ask for clarification when needed
- If the question is CLEARLY RELATED and well-defined:
  * Provide a comprehensive, accurate answer based on the context
- Always prioritize accuracy and relevance over attempting to answer every question"""

            # Add initial context if provided
            if initial_context:
                system_content += f"\n\nInitial Context: {initial_context}\n\nPlease use this context to provide more informed and relevant answers to questions about this topic."
            
            messages.append({
                "role": "system", 
                "content": system_content
            })
            
            # Add chat history
            for message in chat_history:
                messages.append({
                    "role": message.role,
                    "content": message.content
                })
            
            # Add current question
            messages.append({
                "role": "user",
                "content": question
            })

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=messages,
                max_tokens=settings.max_tokens,
                temperature=0.7
            )

            answer = response.choices[0].message.content.strip()
            
            logger.info("Successfully generated contextual answer", 
                       question_length=len(question),
                       chat_history_length=len(chat_history),
                       answer_length=len(answer),
                       has_initial_context=bool(initial_context))
            
            return answer

        except Exception as e:
            logger.error("Failed to generate contextual answer", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to generate contextual answer: {str(e)}")

    async def generate_contextual_answer_stream(self, question: str, chat_history: List, initial_context: Optional[str] = None, language_code: Optional[str] = None, context_type: Optional[str] = "TEXT"):
        """Generate contextual answer with streaming using chat history for ongoing conversations.

        Yields chunks of text as they are generated by OpenAI.

        Args:
            question: The user's question
            chat_history: Previous chat history for context
            initial_context: Optional initial context or background information
            language_code: Optional target language code. If provided, response will be in this language.
                          If None, language will be detected from the question/context.
            context_type: Type of context - "PAGE" (for page/document context with source references) or "TEXT" (standard text context). Default is "TEXT".
        """
        try:
            # Build messages from chat history
            messages = []

            # Build language requirement section
            if language_code:
                # Case 2: languageCode is provided - use it directly in prompt
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in {language_name} ({language_code})
- Your answer MUST be in {language_name} ONLY
- Do NOT use any other language - ONLY {language_name}
- This is MANDATORY and NON-NEGOTIABLE"""
                else:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in the language specified by code: {language_code.upper()}
- Your answer MUST be in this language ONLY
- Do NOT use any other language"""
            else:
                # Case 1: languageCode is None - detect language from question/context
                text_to_detect = question
                if initial_context:
                    text_to_detect += " " + initial_context
                # Add recent chat history messages (last 3 messages) for better detection
                if chat_history:
                    recent_messages = chat_history[-3:] if len(chat_history) > 3 else chat_history
                    for msg in recent_messages:
                        if hasattr(msg, 'content'):
                            text_to_detect += " " + msg.content
                        elif isinstance(msg, dict):
                            text_to_detect += " " + msg.get('content', '')
                
                detected_language_code = await self.detect_text_language_code(text_to_detect)
                detected_language_name = get_language_name(detected_language_code)
                language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in {detected_language_name or detected_language_code} ({detected_language_code})
- Your answer MUST be in {detected_language_name or detected_language_code} ONLY
- Do NOT use any other language - ONLY {detected_language_name or detected_language_code}
- This is MANDATORY and NON-NEGOTIABLE"""

            # Add system message for context
            system_content = f"""You are a helpful AI assistant that provides clear, accurate, and contextual answers. Use the conversation history to maintain context and provide relevant responses.

{language_requirement}

CONTEXT USAGE GUIDELINES:
- You should try your best to answer the user's question using the provided context (initial context and conversation history) when it is relevant
- If the user's question is related to the provided context:
  * Prioritize using information from the context to provide a comprehensive, accurate answer
  * Reference specific details from the context when relevant
  * If the question is somewhat relevant but unclear, you may ask 1-2 clarifying questions if needed, but still attempt to provide a helpful answer based on what you understand
- If the user's question is NOT related to the provided context or goes beyond it:
  * You should still answer the question using your general knowledge
  * It is perfectly fine to answer questions that are out of context
  * Do NOT refuse to answer or redirect the user - simply provide a helpful answer based on your knowledge
  * You can mention if the question is outside the provided context, but still proceed to answer it
- Always prioritize being helpful and providing accurate information, whether from the context or your general knowledge

FORMATTING AND STRUCTURE GUIDELINES:
- Format your answers using Markdown syntax for better readability
- Use **bold** formatting for key terms, important concepts, names, or critical information (use sparingly, only for emphasis)
- Use *italic* formatting for emphasis on specific words or phrases when it adds clarity (use judiciously)
- When your answer naturally contains multiple points, items, steps, or explanations, use bullet points (•) or numbered lists
- Use point-by-point format when listing concepts, features, benefits, steps, causes, effects, or any structured information
- Structure longer answers with clear paragraphs or sections when appropriate
- Use appropriate icons/emojis SPARINGLY and PURPOSEFULLY to enhance understanding:
  * Use icons only when they genuinely add value (e.g., 📊 for data/statistics, ⚠️ for warnings, ✅ for key points, 💡 for insights, 🔍 for analysis, 📝 for notes)
  * Do NOT overuse icons - maximum 2-4 icons per answer, only when they enhance comprehension
  * Avoid using icons in every sentence or paragraph
  * Choose icons that are universally understood and relevant to the content
  * Icons should help users quickly identify important sections or types of information
- Balance is key: prioritize clarity, accuracy, and readability over decorative elements
- Make the answer engaging and easy to understand, but maintain professionalism
- Format complex information in a way that makes it easy to scan and digest"""

            # Add source reference instructions for PAGE context type
            source_reference_instructions = ""
            if context_type == "PAGE" and initial_context:
                source_reference_instructions = f"""

⚠️⚠️⚠️ CRITICAL: SOURCE REFERENCE REQUIREMENTS (context_type = PAGE) - THIS IS MANDATORY ⚠️⚠️⚠️

When you mention important points, facts, claims, or specific information in your answer that the user should verify or view in the original context, you MUST include source references.

SOURCE REFERENCE FORMAT (USE EXACTLY 3 BRACKETS [[[):
- After mentioning an important point that needs verification, immediately include a source reference
- Format: [[[(N)exact substring from initial_context]]]
- Use EXACTLY THREE opening brackets [[[ and THREE closing brackets ]]]
- Where N is the reference number (1, 2, 3, etc.) - increment for each new reference
- The substring should be approximately 10 words from the initial_context that contains the source information
- The substring MUST be an exact quote or very close paraphrase from the initial_context
- Stream the reference as a SINGLE complete event: [[[(N)substring]]] - do not break it up
- The format is: [[[(N)substring]]] - note the THREE brackets on each side

EXAMPLES (CORRECT FORMAT WITH 3 BRACKETS):
- "The discovery was made in 1923. [[[(1)discovery was made in 1923 during the expedition]]]"
- "The population increased by 25%. [[[(2)population increased by 25 percent over the last decade]]]"
- "The theory suggests multiple factors. [[[(3)theory suggests that multiple factors contribute to this phenomenon]]]"

IMPORTANT RULES:
- You MUST include source references for important, verifiable points - this is NOT optional when context_type = PAGE
- Include references for key facts, statistics, claims, important dates, names, or specific data
- Do NOT include references for every sentence - focus on important, verifiable information
- The substring should be meaningful and help users locate the information in the initial_context
- Number references sequentially: (1), (2), (3), etc.
- Each reference should be a complete, standalone substring from the initial_context
- Stream each reference as a single complete event immediately after the relevant sentence/point
- ALWAYS use THREE brackets: [[[ and ]]] - never use two brackets [[

INITIAL CONTEXT FOR SOURCE REFERENCES:
{initial_context}

REMEMBER: When context_type = PAGE, you MUST include source references in the format [[[(N)substring]]] for important points. This is MANDATORY."""

            # Add initial context if provided
            if initial_context:
                if context_type == "PAGE":
                    system_content += f"\n\nInitial Context (SOURCE FOR REFERENCES): {initial_context}\n\nPlease use this context to provide more informed and relevant answers. When you mention important points that users should verify, include source references in the format [[[(N)substring from initial_context]]]."
                else:
                    system_content += f"\n\nInitial Context: {initial_context}\n\nPlease use this context to provide more informed and relevant answers to questions about this topic."
            
            # Add source reference instructions if context_type is PAGE
            if source_reference_instructions:
                system_content += source_reference_instructions

            messages.append({
                "role": "system",
                "content": system_content
            })

            # Add chat history
            for message in chat_history:
                messages.append({
                    "role": message.role if hasattr(message, 'role') else message.get('role', 'user'),
                    "content": message.content if hasattr(message, 'content') else message.get('content', '')
                })

            # Add current question
            messages.append({
                "role": "user",
                "content": question
            })

            # Create streaming response
            stream = await self.client.chat.completions.create(
                model=settings.gpt4o_mini_model,
                messages=messages,
                max_tokens=settings.max_tokens,
                temperature=0.7,
                stream=True
            )

            # Yield chunks as they arrive (streaming directly from OpenAI)
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content

            logger.info("Successfully streamed contextual answer",
                       question_length=len(question),
                       chat_history_length=len(chat_history),
                       has_initial_context=bool(initial_context),
                       context_type=context_type,
                       language_code=language_code)

        except Exception as e:
            logger.error("Failed to stream contextual answer", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to stream contextual answer: {str(e)}")

    async def generate_contextual_answer_with_image_stream(self, question: str, image_data: bytes, image_format: str, chat_history: List, language_code: Optional[str] = None, context_type: Optional[str] = "TEXT"):
        """Generate contextual answer with streaming using image as context for ongoing conversations.

        Yields chunks of text as they are generated by OpenAI.

        Args:
            question: The user's question
            image_data: The image file data (bytes) to use as context
            image_format: Image format (jpeg, png, gif, webp)
            chat_history: Previous chat history for context
            language_code: Optional target language code. If provided, response will be in this language.
                          If None, language will be detected from the question/context.
            context_type: Type of context - "PAGE" (for page/document context with source references) or "TEXT" (standard text context). Default is "TEXT".
        """
        try:
            # Convert image to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')

            # Build messages from chat history
            messages = []

            # Build language requirement section
            if language_code:
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in {language_name} ({language_code})
- Your answer MUST be in {language_name} ONLY
- Do NOT use any other language - ONLY {language_name}
- This is MANDATORY and NON-NEGOTIABLE"""
                else:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in the language specified by code: {language_code.upper()}
- Your answer MUST be in this language ONLY
- Do NOT use any other language"""
            else:
                # Detect language from question
                detected_language_code = await self.detect_text_language_code(question)
                detected_language_name = get_language_name(detected_language_code)
                language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in {detected_language_name or detected_language_code} ({detected_language_code})
- Your answer MUST be in {detected_language_name or detected_language_code} ONLY
- Do NOT use any other language - ONLY {detected_language_name or detected_language_code}
- This is MANDATORY and NON-NEGOTIABLE"""

            # Add system message for context
            system_content = f"""You are a helpful AI assistant that provides clear, accurate, and contextual answers. Use the conversation history and the provided image to maintain context and provide relevant responses.

{language_requirement}

CONTEXT USAGE GUIDELINES:
- You should try your best to answer the user's question using the provided image context and conversation history when it is relevant
- If the user's question is related to the provided image:
  * Prioritize using information from the image to provide a comprehensive, accurate answer
  * Reference specific details from the image when relevant
  * If the question is somewhat relevant but unclear, you may ask 1-2 clarifying questions if needed, but still attempt to provide a helpful answer based on what you understand
- If the user's question is NOT related to the provided image or goes beyond it:
  * You should still answer the question using your general knowledge
  * It is perfectly fine to answer questions that are out of context
  * Do NOT refuse to answer or redirect the user - simply provide a helpful answer based on your knowledge
  * You can mention if the question is outside the provided image context, but still proceed to answer it
- Always prioritize being helpful and providing accurate information, whether from the image or your general knowledge

FORMATTING AND STRUCTURE GUIDELINES:
- Format your answers using Markdown syntax for better readability
- Use **bold** formatting for key terms, important concepts, names, or critical information (use sparingly, only for emphasis)
- Use *italic* formatting for emphasis on specific words or phrases when it adds clarity (use judiciously)
- When your answer naturally contains multiple points, items, steps, or explanations, use bullet points (•) or numbered lists
- Use point-by-point format when listing concepts, features, benefits, steps, causes, effects, or any structured information
- Structure longer answers with clear paragraphs or sections when appropriate
- Use appropriate icons/emojis SPARINGLY and PURPOSEFULLY to enhance understanding:
  * Use icons only when they genuinely add value (e.g., 📊 for data/statistics, ⚠️ for warnings, ✅ for key points, 💡 for insights, 🔍 for analysis, 📝 for notes)
  * Do NOT overuse icons - maximum 2-4 icons per answer, only when they enhance comprehension
  * Avoid using icons in every sentence or paragraph
  * Choose icons that are universally understood and relevant to the content
  * Icons should help users quickly identify important sections or types of information
- Balance is key: prioritize clarity, accuracy, and readability over decorative elements
- Make the answer engaging and easy to understand, but maintain professionalism
- Format complex information in a way that makes it easy to scan and digest"""

            # Add source reference instructions for PAGE context type
            source_reference_instructions = ""
            if context_type == "PAGE":
                source_reference_instructions = f"""

⚠️⚠️⚠️ CRITICAL: SOURCE REFERENCE REQUIREMENTS (context_type = PAGE) - THIS IS MANDATORY ⚠️⚠️⚠️

When you mention important points, facts, claims, or specific information in your answer that the user should verify or view in the original image, you MUST include source references.

SOURCE REFERENCE FORMAT (USE EXACTLY 3 BRACKETS [[[):
- After mentioning an important point that needs verification, immediately include a source reference
- Format: [[[(N)description of relevant part of image]]]
- Use EXACTLY THREE opening brackets [[[ and THREE closing brackets ]]]
- Where N is the reference number (1, 2, 3, etc.) - increment for each new reference
- The description should reference what part of the image contains the source information (e.g., "text in the top left corner", "diagram showing...", "chart displaying...")
- Stream the reference as a SINGLE complete event: [[[(N)description]]] - do not break it up
- The format is: [[[(N)description]]] - note the THREE brackets on each side

EXAMPLES (CORRECT FORMAT WITH 3 BRACKETS):
- "The discovery was made in 1923. [[[(1)text in the image showing 'discovery was made in 1923 during the expedition']]]"
- "The population increased by 25%. [[[(2)chart in the image displaying population increased by 25 percent over the last decade]]]"
- "The theory suggests multiple factors. [[[(3)diagram in the image showing theory suggests that multiple factors contribute to this phenomenon]]]"

IMPORTANT RULES:
- You MUST include source references for important, verifiable points - this is NOT optional when context_type = PAGE
- Include references for key facts, statistics, claims, important dates, names, or specific data visible in the image
- Do NOT include references for every sentence - focus on important, verifiable information
- The description should be meaningful and help users locate the information in the image
- Number references sequentially: (1), (2), (3), etc.
- Stream each reference as a single complete event immediately after the relevant sentence/point
- ALWAYS use THREE brackets: [[[ and ]]] - never use two brackets [[

REMEMBER: When context_type = PAGE, you MUST include source references in the format [[[(N)description]]] for important points. This is MANDATORY."""

            # Add source reference instructions if context_type is PAGE
            if source_reference_instructions:
                system_content += source_reference_instructions

            messages.append({
                "role": "system",
                "content": system_content
            })

            # Add chat history
            for message in chat_history:
                messages.append({
                    "role": message.role if hasattr(message, 'role') else message.get('role', 'user'),
                    "content": message.content if hasattr(message, 'content') else message.get('content', '')
                })

            # Add current question with image
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": question
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{image_format};base64,{base64_image}"
                        }
                    }
                ]
            })

            # Create streaming response
            stream = await self.client.chat.completions.create(
                model=settings.gpt4o_model,
                messages=messages,
                max_tokens=settings.max_tokens,
                temperature=0.7,
                stream=True
            )

            # Yield chunks as they arrive (streaming directly from OpenAI)
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content

            logger.info("Successfully streamed contextual answer with image",
                       question_length=len(question),
                       chat_history_length=len(chat_history),
                       context_type=context_type,
                       language_code=language_code)

        except Exception as e:
            logger.error("Failed to stream contextual answer with image", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to stream contextual answer with image: {str(e)}")

    async def generate_topic_name(self, text: str) -> str:
        """Generate a concise topic name (ideally 3 words) for the given text."""
        try:
            prompt = f"""Analyze the following text and generate a concise topic name that captures its main subject or theme.

            Text:
            "{text}"

            Requirements:
            - Generate a topic name that is ideally 3 words or less
            - Use descriptive, meaningful words that capture the essence of the content
            - Make it concise but informative
            - Use title case (capitalize first letter of each word)
            - Avoid generic terms like "text", "content", "document"
            - Focus on the main subject, theme, or domain of the text
            - Return only the topic name, no additional text or explanation

            Examples of good topic names:
            - "Machine Learning"
            - "Climate Change"
            - "Ancient History"
            - "Financial Markets"
            - "Space Exploration"
            - "Medical Research"
            - "Art History"
            - "Renewable Energy"

            Topic name:"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,  # Short response needed
                temperature=0.3
            )

            topic_name = response.choices[0].message.content.strip()
            
            # Clean up the response - remove any extra text and ensure proper formatting
            topic_name = topic_name.replace('"', '').replace("'", '').strip()
            
            # Ensure it's not too long (max 3 words)
            words = topic_name.split()
            if len(words) > 3:
                topic_name = ' '.join(words[:3])
            
            logger.info("Successfully generated topic name", 
                       text_length=len(text),
                       topic_name=topic_name)
            
            return topic_name

        except Exception as e:
            logger.error("Failed to generate topic name", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to generate topic name: {str(e)}")

    async def detect_text_language_code(self, text: str) -> str:
        """Detect the language of text and return ISO 639-1 language code (e.g., 'EN', 'ES', 'DE')."""
        try:
            # Limit text to first 500 chars for efficiency
            text_sample = text[:500] if len(text) > 500 else text
            
            prompt = f"""Detect the language of the following text and return ONLY the ISO 639-1 language code in uppercase (e.g., "EN" for English, "ES" for Spanish, "DE" for German, "FR" for French, "HI" for Hindi, "JA" for Japanese, "ZH" for Chinese, "AR" for Arabic, "IT" for Italian, "PT" for Portuguese, "RU" for Russian, "KO" for Korean, etc.).

Text: "{text_sample}"

CRITICAL REQUIREMENTS:
- Return ONLY the ISO 639-1 language code in UPPERCASE (e.g., "EN", "ES", "DE", "FR", "HI", "JA", "ZH", "AR", "IT", "PT", "RU", "KO")
- Do NOT return any additional text, explanation, or formatting
- Be accurate in language detection for ALL languages
- If the text contains multiple languages or is unclear, return the primary language code
- Return only the language code, nothing else
- Use standard ISO 639-1 two-letter codes in uppercase

Language code:"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0.1
            )

            language_code = response.choices[0].message.content.strip().upper()
            # Clean up the response - remove quotes and ensure uppercase
            language_code = language_code.replace('"', '').replace("'", '').strip().upper()
            
            # Validate it's a 2-letter code
            if len(language_code) != 2:
                logger.warning("Invalid language code format, defaulting to EN", code=language_code)
                return "EN"
            
            logger.info("Detected text language code", text_preview=text[:50], language_code=language_code)
            return language_code

        except Exception as e:
            logger.warning("Failed to detect text language code, defaulting to EN", error=str(e))
            return "EN"  # Default to English

    async def _detect_word_language(self, word: str) -> str:
        """Detect the language of a word using LLM to ensure proper pronunciation."""
        try:
            prompt = f"""Detect the language of the following word and return ONLY the language name in English (e.g., "English", "Hindi", "Spanish", "French", "German", "Japanese", "Chinese", "Arabic", "Italian", "Portuguese", "Russian", "Korean", etc.).

Word: "{word}"

CRITICAL REQUIREMENTS:
- Return ONLY the language name in English (e.g., "English", "Hindi", "Spanish", "German", "French")
- Do NOT return any additional text, explanation, or formatting
- Be accurate in language detection for ALL languages
- If the word contains multiple languages or is unclear, return the primary language
- Return only the language name, nothing else

Language:"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=20,
                temperature=0.1
            )

            detected_language = response.choices[0].message.content.strip()
            # Clean up the response
            detected_language = detected_language.replace('"', '').replace("'", '').strip()
            
            logger.info("Detected word language", word=word, language=detected_language)
            return detected_language

        except Exception as e:
            logger.warning("Failed to detect word language, proceeding with default", word=word, error=str(e))
            return "Unknown"  # Fallback to let TTS auto-detect

    async def _prepare_word_for_pronunciation(self, word: str, language: str) -> str:
        """Prepare word for pronunciation by ensuring proper formatting for the detected language."""
        try:
            # Clean and normalize the word first
            cleaned_word = word.strip()
            
            # If language is English or Unknown, return word as-is (but normalized)
            if language.lower() in ["english", "unknown"]:
                return cleaned_word
            
            # For non-English languages, verify and ensure proper formatting
            # Use LLM to check if the word is properly formatted for pronunciation in that language
            prompt = f"""Verify and prepare the following word for text-to-speech pronunciation in {language} language.

Word: "{cleaned_word}"
Language: {language}

CRITICAL REQUIREMENTS:
- If the word is already correctly formatted for {language} pronunciation, return it EXACTLY as-is
- If the word is missing essential diacritics, accents, or special characters for {language}, add them
- Preserve ALL special characters, diacritics, and accents that are essential for correct pronunciation in {language}
- For languages with special characters (Spanish: ñ, á, é, í, ó, ú; German: ü, ö, ä, ß; French: é, è, ê, ç, etc.), ensure they are present and correct
- Do NOT translate the word - only ensure proper formatting for pronunciation
- Do NOT change the word if it's already correct
- Do NOT add explanations or additional text
- Return ONLY the word (formatted if needed), nothing else

Word for pronunciation:"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=50,
                temperature=0.1
            )

            formatted_word = response.choices[0].message.content.strip()
            # Clean up the response - remove quotes if present
            formatted_word = formatted_word.replace('"', '').replace("'", '').strip()
            
            # If the formatted word is empty or seems wrong, fall back to original
            if not formatted_word or len(formatted_word) == 0:
                logger.warning("Formatted word is empty, using original", word=word, language=language)
                return cleaned_word
            
            # Validate that the formatted word is reasonable (not too different from original)
            # If it's completely different, it might be a translation error
            if abs(len(formatted_word) - len(cleaned_word)) > len(cleaned_word) * 0.5:
                logger.warning("Formatted word seems too different, using original", 
                             original=cleaned_word, formatted=formatted_word, language=language)
                return cleaned_word
            
            logger.info("Prepared word for pronunciation", 
                       original_word=cleaned_word, 
                       formatted_word=formatted_word, 
                       language=language)
            return formatted_word

        except Exception as e:
            logger.warning("Failed to prepare word for pronunciation, using original", 
                          word=word, language=language, error=str(e))
            return word.strip()  # Fallback to original word

    async def generate_pronunciation_audio(self, word: str, voice: str = "nova", boost_volume_db: float = 8.0) -> bytes:
        """Generate pronunciation audio for a word using OpenAI TTS with volume boost.
        
        Args:
            word: The word to generate pronunciation for (can be in any language)
            voice: The voice to use (alloy, echo, fable, onyx, nova, shimmer)
                  Default is 'nova' for a sweet-toned American female voice
            boost_volume_db: Volume boost in decibels (default: 8.0 dB for better audibility)
        
        Returns:
            Audio data as bytes (MP3 format) with boosted volume
        """
        try:
            logger.info("Generating pronunciation audio", word=word, voice=voice, volume_boost=boost_volume_db)
            
            # Detect the language of the word to ensure proper pronunciation
            detected_language = await self._detect_word_language(word)
            logger.info("Word language detected for pronunciation", word=word, language=detected_language)
            
            # Prepare the word for pronunciation based on detected language
            # This ensures proper formatting for non-English languages
            pronunciation_word = await self._prepare_word_for_pronunciation(word, detected_language)
            
            # Validate that we have a word to pronounce
            if not pronunciation_word or len(pronunciation_word.strip()) == 0:
                logger.error("Empty pronunciation word after preparation", original_word=word)
                raise LLMServiceError("Cannot generate pronunciation for empty word")
            
            # Use OpenAI's text-to-speech API with HD model for better quality
            # For non-English languages, the prepared word format helps TTS understand the correct pronunciation
            response = await self.client.audio.speech.create(
                model="tts-1-hd",  # HD model for better quality
                voice=voice,
                input=pronunciation_word,
                response_format="mp3"
            )
            
            # Get the audio content
            original_audio_bytes = response.content
            
            # Validate that audio was generated
            if not original_audio_bytes or len(original_audio_bytes) == 0:
                logger.error("Empty audio response from TTS", word=word, pronunciation_word=pronunciation_word, language=detected_language)
                raise LLMServiceError("TTS returned empty audio data")
            
            # Boost volume using pydub
            try:
                # Load audio from bytes
                audio = AudioSegment.from_mp3(io.BytesIO(original_audio_bytes))
                
                # Increase volume by specified dB
                boosted_audio = audio + boost_volume_db
                
                # Export back to MP3 bytes
                output_buffer = io.BytesIO()
                boosted_audio.export(output_buffer, format="mp3", bitrate="128k")
                audio_bytes = output_buffer.getvalue()
                
                logger.info("Successfully generated and boosted pronunciation audio", 
                           word=word, 
                           voice=voice,
                           original_size=len(original_audio_bytes),
                           boosted_size=len(audio_bytes),
                           volume_boost_db=boost_volume_db)
                
                return audio_bytes
                
            except Exception as boost_error:
                logger.warning("Failed to boost audio volume, returning original", 
                             error=str(boost_error))
                # If volume boosting fails, return original audio
                return original_audio_bytes
            
        except Exception as e:
            logger.error("Failed to generate pronunciation audio", word=word, error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to generate pronunciation for word '{word}': {str(e)}")

    async def transcribe_audio(self, audio_bytes: bytes, filename: str, translate: bool = False) -> str:
        """Transcribe audio to text using OpenAI Whisper API.
        
        Args:
            audio_bytes: Audio file data as bytes
            filename: Original filename (for format detection)
            translate: If True, translates non-English audio to English. If False, transcribes in original language.
        
        Returns:
            Transcribed text (in original language or English if translate=True)
        """
        try:
            logger.info("Transcribing audio using Whisper", 
                       filename=filename, 
                       audio_size=len(audio_bytes),
                       translate=translate)
            
            # Create a file-like object from bytes
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename  # Set the name for format detection
            
            if translate:
                # Use translations endpoint to translate to English
                response = await self.client.audio.translations.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )
            else:
                # Use transcriptions endpoint to transcribe in original language
                response = await self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )
            
            # Extract the transcribed text
            transcribed_text = response.strip() if isinstance(response, str) else response.text.strip()
            
            logger.info("Successfully transcribed audio", 
                       filename=filename,
                       text_length=len(transcribed_text),
                       translate=translate)
            
            return transcribed_text
            
        except Exception as e:
            logger.error("Failed to transcribe audio", 
                        filename=filename, 
                        error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to transcribe audio: {str(e)}")

    async def translate_single_text(self, text: str, target_language_code: str) -> str:
        """Translate a single text to the target language using OpenAI.
        
        Args:
            text: Text to translate
            target_language_code: ISO 639-1 language code (e.g., 'EN', 'ES', 'FR', 'DE', 'HI', 'JA', 'ZH')
        
        Returns:
            Translated text
        """
        try:
            if not text or not text.strip():
                return ""
            
            # Map language codes to full language names for better translation
            language_map = {
                "EN": "English",
                "ES": "Spanish",
                "FR": "French",
                "DE": "German",
                "HI": "Hindi",
                "JA": "Japanese",
                "ZH": "Chinese",
                "AR": "Arabic",
                "IT": "Italian",
                "PT": "Portuguese",
                "RU": "Russian",
                "KO": "Korean",
                "NL": "Dutch",
                "PL": "Polish",
                "TR": "Turkish",
                "VI": "Vietnamese",
                "TH": "Thai",
                "ID": "Indonesian",
                "CS": "Czech",
                "SV": "Swedish",
                "DA": "Danish",
                "NO": "Norwegian",
                "FI": "Finnish",
                "EL": "Greek",
                "HE": "Hebrew",
                "UK": "Ukrainian",
                "RO": "Romanian",
                "HU": "Hungarian",
            }
            
            target_language = language_map.get(target_language_code.upper(), target_language_code.upper())
            
            prompt = f"""Translate the following text to {target_language}. 

Text to translate:
{text}

CRITICAL REQUIREMENTS:
- Translate the text accurately to {target_language}
- Preserve the meaning and context
- Return ONLY the translated text
- Do NOT include any additional text, explanations, or formatting
- Do NOT wrap the response in quotes or JSON

Translated text:"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.3
            )

            translated_text = response.choices[0].message.content.strip()
            
            logger.info(
                "Successfully translated single text",
                input_length=len(text),
                output_length=len(translated_text),
                target_language=target_language,
                target_language_code=target_language_code
            )
            
            return translated_text
                
        except Exception as e:
            logger.error("Failed to translate text", error=str(e), target_language_code=target_language_code)
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to translate text: {str(e)}")

    async def translate_batch_with_ids(
        self, 
        items: List[Dict[str, str]], 
        target_language_code: str
    ) -> List[Dict[str, str]]:
        """Translate multiple text items with IDs in a single API call.
        
        Args:
            items: List of dicts with 'id' and 'text' keys
            target_language_code: ISO 639-1 language code (e.g., 'EN', 'ES', 'FR', 'DE', 'HI', 'JA', 'ZH')
        
        Returns:
            List of dicts with 'id' and 'translatedText' keys (same order as input)
        """
        try:
            if not items:
                return []
            
            # Map language codes to full language names for better translation
            language_map = {
                "EN": "English",
                "ES": "Spanish",
                "FR": "French",
                "DE": "German",
                "HI": "Hindi",
                "JA": "Japanese",
                "ZH": "Chinese",
                "AR": "Arabic",
                "IT": "Italian",
                "PT": "Portuguese",
                "RU": "Russian",
                "KO": "Korean",
                "NL": "Dutch",
                "PL": "Polish",
                "TR": "Turkish",
                "VI": "Vietnamese",
                "TH": "Thai",
                "ID": "Indonesian",
                "CS": "Czech",
                "SV": "Swedish",
                "DA": "Danish",
                "NO": "Norwegian",
                "FI": "Finnish",
                "EL": "Greek",
                "HE": "Hebrew",
                "UK": "Ukrainian",
                "RO": "Romanian",
                "HU": "Hungarian",
            }
            
            target_language = language_map.get(target_language_code.upper(), target_language_code.upper())
            
            # Create JSON input for the batch
            items_json = json.dumps(items, ensure_ascii=False)
            
            prompt = f"""Translate the following text items to {target_language}. 

Input (JSON array of objects with 'id' and 'text' fields):
{items_json}

CRITICAL REQUIREMENTS:
- Translate the 'text' field of each object accurately to {target_language}
- Preserve the meaning and context of each text
- Return ONLY a JSON array of objects with 'id' and 'translatedText' fields
- Each object in the output array MUST have:
  * "id": THE EXACT SAME ID from the input - DO NOT MODIFY OR CHANGE THE ID IN ANY WAY
  * "translatedText": the translated version of the corresponding input text
- Maintain the same order as the input items
- Do NOT include any additional text, explanations, markdown formatting, or code blocks
- Return the result as a pure JSON array: [{{"id": "...", "translatedText": "..."}}, ...]

IMPORTANT: The IDs must be EXACTLY the same as in the input. Do not change, modify, or regenerate them.

Translated items (JSON array only):"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.3
            )

            result = response.choices[0].message.content.strip()
            
            # Parse the JSON response
            try:
                # Strip Markdown code block if present
                if result.startswith("```"):
                    result = re.sub(r"^```(?:json)?\n|\n```$", "", result.strip())
                
                translated_items = json.loads(result)
                
                if not isinstance(translated_items, list):
                    raise ValueError("Expected JSON array")
                
                # Validate all input IDs are present in output
                input_ids = {item["id"] for item in items}
                output_ids = {item.get("id") for item in translated_items}
                
                if input_ids != output_ids:
                    logger.warning(
                        "ID mismatch in batch translation",
                        input_ids=input_ids,
                        output_ids=output_ids,
                        missing_ids=input_ids - output_ids,
                        extra_ids=output_ids - input_ids
                    )
                
                # Ensure we have the same number of translations as inputs
                if len(translated_items) != len(items):
                    logger.warning(
                        "Translation count mismatch in batch", 
                        input_count=len(items),
                        output_count=len(translated_items)
                    )
                
                # Create a mapping of id to translatedText for reliable ordering
                translation_map = {item.get("id"): item.get("translatedText", "") for item in translated_items}
                
                # Rebuild results in the same order as input
                ordered_results = []
                for input_item in items:
                    item_id = input_item["id"]
                    translated_text = translation_map.get(item_id, "")
                    ordered_results.append({
                        "id": item_id,
                        "translatedText": translated_text
                    })
                
                logger.info(
                    "Successfully translated batch with IDs",
                    batch_size=len(items),
                    target_language=target_language,
                    target_language_code=target_language_code
                )
                
                return ordered_results
                
            except json.JSONDecodeError as e:
                logger.error("Failed to parse batch translation response as JSON", error=str(e), response=result[:500])
                raise LLMServiceError("Failed to parse batch translation response")
                
        except Exception as e:
            logger.error("Failed to translate batch with IDs", error=str(e), target_language_code=target_language_code)
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to translate batch: {str(e)}")

    async def translate_texts(self, texts: List[str], target_language_code: str) -> List[str]:
        """Translate multiple texts to the target language using OpenAI.
        
        Args:
            texts: List of texts to translate
            target_language_code: ISO 639-1 language code (e.g., 'EN', 'ES', 'FR', 'DE', 'HI', 'JA', 'ZH')
        
        Returns:
            List of translated texts in the same order as input
        """
        try:
            if not texts:
                return []
            
            # Map language codes to full language names for better translation
            language_map = {
                "EN": "English",
                "ES": "Spanish",
                "FR": "French",
                "DE": "German",
                "HI": "Hindi",
                "JA": "Japanese",
                "ZH": "Chinese",
                "AR": "Arabic",
                "IT": "Italian",
                "PT": "Portuguese",
                "RU": "Russian",
                "KO": "Korean",
                "NL": "Dutch",
                "PL": "Polish",
                "TR": "Turkish",
                "VI": "Vietnamese",
                "TH": "Thai",
                "ID": "Indonesian",
                "CS": "Czech",
                "SV": "Swedish",
                "DA": "Danish",
                "NO": "Norwegian",
                "FI": "Finnish",
                "EL": "Greek",
                "HE": "Hebrew",
                "UK": "Ukrainian",
                "RO": "Romanian",
                "HU": "Hungarian",
            }
            
            target_language = language_map.get(target_language_code.upper(), target_language_code.upper())
            
            # Create a prompt that translates all texts at once
            texts_list = "\n".join([f"{i+1}. {text}" for i, text in enumerate(texts)])
            
            prompt = f"""Translate the following texts to {target_language}. 

Texts to translate:
{texts_list}

CRITICAL REQUIREMENTS:
- Translate each text accurately to {target_language}
- Preserve the meaning and context of each text
- Maintain the same order as the input texts
- Return ONLY a JSON array of translated texts in the same order
- Each element in the array should be the translated version of the corresponding input text
- Do NOT include any additional text, explanations, or formatting
- Return the result as a JSON array: ["translated text 1", "translated text 2", ...]

Translated texts (JSON array only):"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.3
            )

            result = response.choices[0].message.content.strip()
            
            # Parse the JSON response
            try:
                # Strip Markdown code block if present
                if result.startswith("```"):
                    result = re.sub(r"^```(?:json)?\n|\n```$", "", result.strip())
                
                translated_texts = json.loads(result)
                
                if not isinstance(translated_texts, list):
                    raise ValueError("Expected JSON array")
                
                # Ensure we have the same number of translations as inputs
                if len(translated_texts) != len(texts):
                    logger.warning(
                        "Translation count mismatch", 
                        input_count=len(texts),
                        output_count=len(translated_texts)
                    )
                    # If we got fewer translations, pad with empty strings
                    # If we got more, truncate
                    if len(translated_texts) < len(texts):
                        translated_texts.extend([""] * (len(texts) - len(translated_texts)))
                    else:
                        translated_texts = translated_texts[:len(texts)]
                
                logger.info(
                    "Successfully translated texts",
                    input_count=len(texts),
                    target_language=target_language,
                    target_language_code=target_language_code
                )
                
                return translated_texts
                
            except json.JSONDecodeError as e:
                logger.error("Failed to parse translation response as JSON", error=str(e), response=result)
                raise LLMServiceError("Failed to parse translation response")
                
        except Exception as e:
            logger.error("Failed to translate texts", error=str(e), target_language_code=target_language_code)
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to translate texts: {str(e)}")

    async def summarise_text(self, text: str, language_code: Optional[str] = None) -> str:
        """Generate a short, insightful summary of the given text using OpenAI.
        
        Args:
            text: The text to summarize (can contain newline characters)
            language_code: Optional language code. If provided, summary will be strictly in this language.

        Returns:
            A concise, insightful summary of the input text
        """
        try:
            # Build language requirement section
            if language_code:
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in {language_name} ({language_code})
- The summary MUST be in {language_name} ONLY
- Do NOT use any other language - ONLY {language_name}
- This is MANDATORY and NON-NEGOTIABLE

"""
                else:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST respond STRICTLY in the language specified by code: {language_code.upper()}
- The summary MUST be in this language ONLY
- Do NOT use any other language

"""
            else:
                language_requirement = ""

            prompt = f"""Analyze the following text and generate a short, insightful summary that captures the main ideas and key points.

Text:
{text}
{language_requirement}CRITICAL REQUIREMENTS:
- Generate a concise summary that captures the essence and main ideas of the text
- Keep it brief but insightful - focus on the most important information
- Preserve the core meaning and key concepts
- Make it clear and easy to understand
- If the text contains multiple paragraphs or sections, synthesize them into a coherent summary
- Handle newline characters and multi-paragraph text appropriately
- Return only the summary text, no additional commentary or formatting
- The summary should be significantly shorter than the original text while retaining key information

Summary:"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.3
            )

            summary = response.choices[0].message.content.strip()
            
            logger.info("Successfully generated summary", 
                       original_length=len(text),
                       summary_length=len(summary))
            
            return summary

        except Exception as e:
            logger.error("Failed to generate summary", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to generate summary: {str(e)}")

    async def summarise_text_stream(self, text: str, language_code: Optional[str] = None, context_type: Optional[str] = "TEXT"):
        """Generate a short, insightful summary of the given text with streaming.

        Args:
            text: The text to summarize (can contain newline characters)
            language_code: Optional target language code. If provided, response will be in this language.
                          If None, language will be detected from the input text.
            context_type: Type of context - "PAGE" (for page/document context with source references) or "TEXT" (standard text context). Default is "TEXT".

        Yields:
            Chunks of the summary text as they are generated by OpenAI.
        """
        try:
            # Log the language_code being used for debugging
            logger.info("Summarise text stream called", 
                       text_length=len(text),
                       language_code=language_code,
                       context_type=context_type,
                       has_language_code=language_code is not None)
            
            # Build language requirement section
            if language_code:
                # Case 2: languageCode is provided - use it directly in prompt
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
⚠️ CRITICAL LANGUAGE REQUIREMENT - READ THIS FIRST ⚠️
You MUST respond EXCLUSIVELY in {language_name} ({language_code}).
- Every word, sentence, and phrase in your summary MUST be in {language_name}
- Do NOT use English or any other language
- Do NOT mix languages
- The ENTIRE summary must be written in {language_name} ONLY
- This is ABSOLUTELY MANDATORY - there are NO exceptions
- If the input text is in a different language, you must still respond in {language_name}
- Translate and summarize the content into {language_name}

"""
                else:
                    language_requirement = f"""
⚠️ CRITICAL LANGUAGE REQUIREMENT - READ THIS FIRST ⚠️
You MUST respond EXCLUSIVELY in the language specified by code: {language_code.upper()}
- Every word, sentence, and phrase in your summary MUST be in {language_code.upper()}
- Do NOT use English or any other language
- Do NOT mix languages
- The ENTIRE summary must be written in {language_code.upper()} ONLY
- This is ABSOLUTELY MANDATORY - there are NO exceptions
- If the input text is in a different language, you must still respond in {language_code.upper()}
- Translate and summarize the content into {language_code.upper()}

"""
            else:
                # Case 1: languageCode is None - detect language from input text
                detected_language_code = await self.detect_text_language_code(text)
                detected_language_name = get_language_name(detected_language_code)
                logger.info("Detected language for summarise", 
                           detected_language_code=detected_language_code,
                           detected_language_name=detected_language_name)
                language_requirement = f"""
⚠️ CRITICAL LANGUAGE REQUIREMENT - READ THIS FIRST ⚠️
You MUST respond EXCLUSIVELY in {detected_language_name or detected_language_code} ({detected_language_code}).
- Every word, sentence, and phrase in your summary MUST be in {detected_language_name or detected_language_code}
- Do NOT use English or any other language
- Do NOT mix languages
- The ENTIRE summary must be written in {detected_language_name or detected_language_code} ONLY
- This is ABSOLUTELY MANDATORY - there are NO exceptions

"""

            # Build the main instruction based on context_type
            if context_type == "PAGE":
                main_instruction = f"""{language_requirement}⚠️ CRITICAL: You are summarizing with context_type = PAGE. You MUST include source references for important points. ⚠️

Analyze the following text and generate a short, insightful summary that captures the main ideas and key points. When you mention important facts, claims, or specific information, you MUST include source references in the format [[[(N)substring from text]]].

Text to summarize:
{text}"""
            else:
                main_instruction = f"""{language_requirement}⚠️ CRITICAL: You MUST include source references for important points in your summary. ⚠️

Analyze the following text and generate a short, insightful summary that captures the main ideas and key points. When you mention important facts, claims, or specific information, you MUST include source references in the format [[[(N)substring from text]]].

Text to summarize:
{text}"""

            prompt = f"""{main_instruction}

CRITICAL REQUIREMENTS:
- Generate a concise summary that captures the essence and main ideas of the text
- Keep it brief but insightful - focus on the most important information
- Preserve the core meaning and key concepts
- Make it clear and easy to understand
- If the text contains multiple paragraphs or sections, synthesize them into a coherent summary
- Handle newline characters and multi-paragraph text appropriately
- The summary should be significantly shorter than the original text while retaining key information
- ⚠️ MANDATORY: You MUST include source references [[[(N)substring]]] for important, verifiable points - this is REQUIRED for ALL summaries

FORMATTING AND STRUCTURE REQUIREMENTS:
- Use **bold** formatting for key terms, important concepts, names, or critical points (use sparingly, only for emphasis)
- Use *italic* formatting for emphasis on specific words or phrases when it adds clarity (use judiciously)
- When the content naturally has multiple points, items, or steps, use bullet points (•) or numbered lists for better readability
- Use point-by-point format when listing concepts, features, benefits, or any structured information
- Structure the summary with clear paragraphs or sections when appropriate
- Use appropriate emojis/icons PURPOSEFULLY throughout the summary to enhance the reading experience and make it more engaging:
  * Use emojis wherever they add value and improve comprehension (e.g., 📊 for data/statistics, ⚠️ for warnings, ✅ for key points, 💡 for insights, 🔍 for analysis, 📝 for notes, 🎯 for goals, ⚡ for important highlights, 🌟 for key achievements, 📈 for growth/trends, 🔑 for important concepts, 💼 for business-related content, 🎓 for educational content, 🏆 for achievements, ⏰ for time-related content, 📍 for locations, 👥 for people/teams, 💰 for financial content, 🔬 for scientific content, 🎨 for creative content, etc.)
  * Use emojis to visually break up text and make different sections more scannable
  * Place emojis at the beginning of key points, important statements, or section headers to draw attention
  * Choose emojis that are universally understood and directly relevant to the content
  * Use emojis naturally and organically - they should enhance understanding, not distract
  * Feel free to use multiple emojis throughout the summary where they genuinely improve the reading experience
  * Balance is important: use emojis to make the summary visually appealing and easier to read, but ensure they add value
- Format the response using Markdown syntax (**, *, bullet points, etc.) combined with emojis for the best reading experience"""

            # Add source reference instructions - ALWAYS included for all summaries
            source_reference_section = f"""

⚠️⚠️⚠️ CRITICAL: SOURCE REFERENCE REQUIREMENTS - THIS IS MANDATORY FOR ALL SUMMARIES ⚠️⚠️⚠️

You MUST include source references when mentioning important points, facts, claims, or specific information in your summary. This is REQUIRED for ALL summaries, regardless of context_type.

SOURCE REFERENCE FORMAT (USE EXACTLY 3 BRACKETS [[[):
- After mentioning an important point that needs verification, immediately include a source reference
- Format: [[[(N)exact substring from the text field]]]
- Use EXACTLY THREE opening brackets [[[ and THREE closing brackets ]]]
- Where N is the reference number (1, 2, 3, etc.) - increment for each new reference
- The substring should be approximately 10 words from the text field that contains the source information
- The substring MUST be an exact quote or very close paraphrase from the text field above
- Stream the reference as a SINGLE complete event: [[[(N)substring]]] - do not break it up
- The format is: [[[(N)substring]]] - note the THREE brackets on each side
- CRITICAL: The reference MUST be streamed in the format [[[(N)substring]]] - this exact format is MANDATORY

EXAMPLES (CORRECT FORMAT WITH 3 BRACKETS):
- "The discovery was made in 1923. [[[(1)discovery was made in 1923 during the expedition]]]"
- "The population increased by 25%. [[[(2)population increased by 25 percent over the last decade]]]"
- "The theory suggests multiple factors. [[[(3)theory suggests that multiple factors contribute to this phenomenon]]]"

IMPORTANT RULES:
- You MUST include source references for important, verifiable points - this is NOT optional
- Include references for key facts, statistics, claims, important dates, names, or specific data
- Do NOT include references for every sentence - focus on important, verifiable information
- The substring should be meaningful and help users locate the information in the text field
- Number references sequentially: (1), (2), (3), etc.
- Each reference should be a complete, standalone substring from the text field
- Stream each reference as a single complete event immediately after the relevant sentence/point
- ALWAYS use THREE brackets: [[[ and ]]] - never use two brackets [[
- The format [[[(N)substring]]] MUST appear in your streamed response for important points

REMEMBER: You MUST include source references in the format [[[(N)substring]]] for important points. This is MANDATORY for ALL summaries. The format [[[(N)substring]]] must be present in your streamed output."""

            prompt += source_reference_section + """

Remember: Your ENTIRE response must be in the language specified above. Do NOT use any other language.

Summary:"""

            # Create streaming response
            stream = await self.client.chat.completions.create(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.max_tokens,
                temperature=0.3,
                stream=True
            )

            # Yield chunks as they arrive (streaming directly from OpenAI)
            async for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content

            logger.info("Successfully streamed summary",
                       original_length=len(text),
                       language_code=language_code)

        except Exception as e:
            logger.error("Failed to stream summary", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            raise LLMServiceError(f"Failed to stream summary: {str(e)}")

    async def generate_possible_questions(self, text: str, language_code: Optional[str] = None) -> List[str]:
        """Generate top 5 possible questions based on the given context/text.
        
        Args:
            text: The text/story to generate questions from
            language_code: Optional language code. If provided, questions will be strictly in this language.
        
        Returns:
            List of top 5 questions ordered by relevance/importance in decreasing order
        """
        try:
            # Build language requirement section
            if language_code:
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST generate questions STRICTLY in {language_name} ({language_code})
- All questions MUST be in {language_name} ONLY
- Do NOT use any other language - ONLY {language_name}
- This is MANDATORY and NON-NEGOTIABLE

"""
                else:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST generate questions STRICTLY in the language specified by code: {language_code.upper()}
- All questions MUST be in this language ONLY
- Do NOT use any other language

"""
            else:
                # Detect language from text
                detected_language_code = await self.detect_text_language_code(text)
                detected_language_name = get_language_name(detected_language_code)
                language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST generate questions STRICTLY in {detected_language_name or detected_language_code} ({detected_language_code})
- All questions MUST be in {detected_language_name or detected_language_code} ONLY
- Do NOT use any other language - ONLY {detected_language_name or detected_language_code}
- This is MANDATORY and NON-NEGOTIABLE

"""

            prompt = f"""{language_requirement}Analyze the following text/story and generate the top 5 most relevant and important questions that someone might ask about this content.

Text/Story:
{text}

CRITICAL REQUIREMENTS:
- Generate exactly 5 questions
- Questions should be based on the most important, relevant, and interesting aspects of the text/story
- Order questions by their relevance and importance in decreasing order (most relevant first)
- Questions should be thought-provoking and help readers understand key concepts, themes, or details
- Focus on questions that explore the main ideas, important details, implications, or deeper understanding
- Make questions clear, concise, and well-formed
- Questions should be in the same language as specified above
- Return the result as a JSON array of exactly 5 strings, ordered by relevance (most relevant first)
- Each question should be a complete, grammatically correct sentence ending with a question mark

Return only the JSON array, no additional text or formatting.

Example format:
["What is the main theme of this story?", "Why did the character make that decision?", "What are the key implications of this concept?", "How does this relate to the broader context?", "What details are most important to understand?"]

Questions (JSON array only):"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,  # Enough for 5 questions
                temperature=0.5
            )

            result = response.choices[0].message.content.strip()

            # Parse the JSON response
            try:
                # Strip Markdown code block if present
                if result.startswith("```"):
                    result = re.sub(r"^```(?:json)?\n|\n```$", "", result.strip())

                questions = json.loads(result)

                if not isinstance(questions, list):
                    raise ValueError("Expected JSON array")

                # Convert all to strings and strip whitespace
                questions = [str(q).strip() for q in questions]

                # Ensure we have exactly 5 questions, pad or truncate if needed
                if len(questions) < 5:
                    logger.warning("Received fewer than 5 questions, padding with empty strings", count=len(questions))
                    questions.extend([""] * (5 - len(questions)))
                elif len(questions) > 5:
                    logger.warning("Received more than 5 questions, truncating", count=len(questions))
                    questions = questions[:5]

                logger.info("Successfully generated possible questions",
                           text_length=len(text),
                           questions_count=len(questions),
                           language_code=language_code)

                return questions

            except json.JSONDecodeError as e:
                logger.error("Failed to parse questions response as JSON", error=str(e), response=result)
                # Return empty list as fallback
                return [""] * 5

        except Exception as e:
            logger.error("Failed to generate possible questions", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            # Return empty list as fallback instead of raising error
            logger.warning("Returning empty questions list due to error", error=str(e))
            return [""] * 5

    async def generate_possible_questions_for_text(self, text: str, language_code: Optional[str] = None, max_questions: int = 3) -> List[str]:
        """Generate possible questions based on the given text (at least 1, at most max_questions).
        
        Args:
            text: The text to generate questions from
            language_code: Optional language code. If provided, questions will be strictly in this language.
            max_questions: Maximum number of questions to generate (default: 3, generates 1-3 questions)
        
        Returns:
            List of 1 to max_questions questions ordered by relevance/importance in decreasing order
        """
        try:
            # Build language requirement section
            if language_code:
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST generate questions STRICTLY in {language_name} ({language_code})
- All questions MUST be in {language_name} ONLY
- Do NOT use any other language - ONLY {language_name}
- This is MANDATORY and NON-NEGOTIABLE

"""
                else:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST generate questions STRICTLY in the language specified by code: {language_code.upper()}
- All questions MUST be in this language ONLY
- Do NOT use any other language

"""
            else:
                # Detect language from text
                detected_language_code = await self.detect_text_language_code(text)
                detected_language_name = get_language_name(detected_language_code)
                language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST generate questions STRICTLY in {detected_language_name or detected_language_code} ({detected_language_code})
- All questions MUST be in {detected_language_name or detected_language_code} ONLY
- Do NOT use any other language - ONLY {detected_language_name or detected_language_code}
- This is MANDATORY and NON-NEGOTIABLE

"""

            prompt = f"""{language_requirement}Analyze the following text and generate the most relevant and important questions that someone might ask about this content.

Text:
{text}

CRITICAL REQUIREMENTS:
- Generate AT LEAST 1 question and AT MOST {max_questions} questions
- Only generate questions if they are genuinely relevant and important to understanding the text
- If the text is very simple or short, you may generate only 1 question
- If the text is complex or has multiple important aspects, generate up to {max_questions} questions
- Quality over quantity: only include questions that add real value for understanding the text
- Questions should be based on the most important, relevant, and interesting aspects of the text
- Order questions by their relevance and importance in decreasing order (most relevant first)
- Questions should be thought-provoking and help readers understand key concepts, themes, or details
- Focus on questions that explore the main ideas, important details, implications, or deeper understanding
- Make questions clear, concise, and well-formed
- Questions should be in the same language as specified above
- Return the result as a JSON array of 1 to {max_questions} strings, ordered by relevance (most relevant first)
- Each question should be a complete, grammatically correct sentence ending with a question mark
- Do NOT pad with empty strings or generate filler questions - only include meaningful questions

Return only the JSON array, no additional text or formatting.

Example formats (depending on text complexity):
- Simple text: ["What is the main theme of this text?"]
- Medium complexity: ["What is the main theme of this text?", "Why is this concept important?"]
- Complex text: ["What is the main theme of this text?", "Why is this concept important?", "What are the key implications?"]

Questions (JSON array only):"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,  # Enough for 3 questions
                temperature=0.5
            )

            result = response.choices[0].message.content.strip()

            # Parse the JSON response
            try:
                # Strip Markdown code block if present
                if result.startswith("```"):
                    result = re.sub(r"^```(?:json)?\n|\n```$", "", result.strip())

                questions = json.loads(result)

                if not isinstance(questions, list):
                    raise ValueError("Expected JSON array")

                # Convert all to strings, strip whitespace, and filter out empty questions
                questions = [str(q).strip() for q in questions if q and str(q).strip()]

                # Validate we have at least 1 question
                if len(questions) == 0:
                    logger.warning("No valid questions generated, this should not happen", text_preview=text[:50])
                    # Return a single generic question as fallback
                    questions = ["What is the main idea of this text?"]
                elif len(questions) > max_questions:
                    logger.warning(f"Received more than {max_questions} questions, truncating to top {max_questions}", count=len(questions))
                    questions = questions[:max_questions]

                logger.info("Successfully generated possible questions for text",
                           text_length=len(text),
                           questions_count=len(questions),
                           language_code=language_code)

                return questions

            except json.JSONDecodeError as e:
                logger.error("Failed to parse questions response as JSON", error=str(e), response=result)
                # Return a single generic question as fallback
                return ["What is the main idea of this text?"]

        except Exception as e:
            logger.error("Failed to generate possible questions for text", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            # Return a single generic question as fallback instead of empty list
            logger.warning("Returning fallback question due to error", error=str(e))
            return ["What is the main idea of this text?"]

    async def generate_recommended_questions(self, current_question: str, chat_history: List, initial_context: Optional[str] = None, language_code: Optional[str] = None) -> List[str]:
        """Generate top 3 recommended questions based on current question and chat history.
        
        Args:
            current_question: The current question being asked
            chat_history: Previous chat history for context
            initial_context: Optional initial context or background information
            language_code: Optional language code. If provided, questions will be strictly in this language.
        
        Returns:
            List of top 3 recommended questions ordered by relevance/importance in decreasing order
        """
        try:
            # Build language requirement section
            if language_code:
                language_name = get_language_name(language_code)
                if language_name:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST generate questions STRICTLY in {language_name} ({language_code})
- All questions MUST be in {language_name} ONLY
- Do NOT use any other language - ONLY {language_name}
- This is MANDATORY and NON-NEGOTIABLE

"""
                else:
                    language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST generate questions STRICTLY in the language specified by code: {language_code.upper()}
- All questions MUST be in this language ONLY
- Do NOT use any other language

"""
            else:
                # Detect language from current question and chat history
                text_to_detect = current_question
                if chat_history:
                    recent_messages = chat_history[-3:] if len(chat_history) > 3 else chat_history
                    for msg in recent_messages:
                        if hasattr(msg, 'content'):
                            text_to_detect += " " + msg.content
                        elif isinstance(msg, dict):
                            text_to_detect += " " + msg.get('content', '')
                
                detected_language_code = await self.detect_text_language_code(text_to_detect)
                detected_language_name = get_language_name(detected_language_code)
                language_requirement = f"""
CRITICAL LANGUAGE REQUIREMENT:
- You MUST generate questions STRICTLY in {detected_language_name or detected_language_code} ({detected_language_code})
- All questions MUST be in {detected_language_name or detected_language_code} ONLY
- Do NOT use any other language - ONLY {detected_language_name or detected_language_code}
- This is MANDATORY and NON-NEGOTIABLE

"""

            # Build chat history context
            chat_history_text = ""
            if chat_history:
                chat_history_text = "\n\nPrevious conversation:\n"
                for msg in chat_history:
                    role = msg.role if hasattr(msg, 'role') else msg.get('role', 'user')
                    content = msg.content if hasattr(msg, 'content') else msg.get('content', '')
                    chat_history_text += f"{role.capitalize()}: {content}\n"
            
            # Build initial context section
            initial_context_section = ""
            if initial_context:
                initial_context_section = f"\n\nInitial Context: {initial_context}\n"

            prompt = f"""{language_requirement}Analyze the current question and conversation history to generate the top 3 most relevant and recommended follow-up questions that would help the user explore the topic further.

Current Question: {current_question}
{initial_context_section}{chat_history_text}
CRITICAL REQUIREMENTS:
- Generate exactly 3 recommended questions
- Questions should be based on the current question, the conversation context, and the topics being discussed
- Questions should help the user explore related aspects, dive deeper into the topic, or clarify important points
- Order questions by their relevance and importance in decreasing order (most relevant first)
- Questions should be natural follow-ups that would logically come next in the conversation
- Make questions clear, concise, and well-formed
- Questions should be in the same language as specified above
- Return the result as a JSON array of exactly 3 strings, ordered by relevance (most relevant first)
- Each question should be a complete, grammatically correct sentence ending with a question mark
- Focus on questions that would be most helpful for understanding the topic better

Return only the JSON array, no additional text or formatting.

Example format:
["What are the key implications of this concept?", "How does this relate to the broader context?", "What are some practical applications?"]

Recommended Questions (JSON array only):"""

            response = await self._make_api_call(
                model=settings.gpt4o_mini_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,  # Enough for 3 questions
                temperature=0.5
            )

            result = response.choices[0].message.content.strip()

            # Parse the JSON response
            try:
                # Strip Markdown code block if present
                if result.startswith("```"):
                    result = re.sub(r"^```(?:json)?\n|\n```$", "", result.strip())

                questions = json.loads(result)

                if not isinstance(questions, list):
                    raise ValueError("Expected JSON array")

                # Convert all to strings and strip whitespace
                questions = [str(q).strip() for q in questions]

                # Ensure we have exactly 3 questions, pad or truncate if needed
                if len(questions) < 3:
                    logger.warning("Received fewer than 3 questions, padding with empty strings", count=len(questions))
                    questions.extend([""] * (3 - len(questions)))
                elif len(questions) > 3:
                    logger.warning("Received more than 3 questions, truncating", count=len(questions))
                    questions = questions[:3]

                logger.info("Successfully generated recommended questions",
                           current_question_length=len(current_question),
                           chat_history_length=len(chat_history),
                           questions_count=len(questions),
                           language_code=language_code)

                return questions

            except json.JSONDecodeError as e:
                logger.error("Failed to parse recommended questions response as JSON", error=str(e), response=result)
                # Return empty list as fallback
                return [""] * 3

        except Exception as e:
            logger.error("Failed to generate recommended questions", error=str(e))
            if isinstance(e, LLMServiceError):
                raise
            # Return empty list as fallback instead of raising error
            logger.warning("Returning empty questions list due to error", error=str(e))
            return [""] * 3

    async def close(self):
        """Close the HTTP client."""
        if hasattr(self.client, '_client') and hasattr(self.client._client, 'aclose'):
            await self.client._client.aclose()
            logger.info("OpenAI HTTP client closed")


# Global service instance
openai_service = OpenAIService()