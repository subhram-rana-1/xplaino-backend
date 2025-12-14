"""Text processing service for word analysis."""

import asyncio
from typing import List, Dict, Any, AsyncGenerator, Optional
import structlog

from app.models import WordWithLocation, WordInfo
from app.services.llm.open_ai import openai_service
from app.exceptions import ValidationError
from app.utils.utils import get_start_index_and_length_for_words_from_text

logger = structlog.get_logger()


class TextService:
    """Service for text processing and word analysis."""
    
    async def extract_important_words(self, text: str) -> List[WordWithLocation]:
        """Extract important words from text."""
        if not text or not text.strip():
            raise ValidationError("Text cannot be empty")
        
        if len(text) > 10000:
            raise ValidationError("Text exceeds maximum length of 10000 characters")
        
        try:
            # Get important words from LLM
            words = await openai_service.get_important_words(text)
            words_with_location = get_start_index_and_length_for_words_from_text(text, words)
            
            # Convert to WordLocation objects
            word_with_locations = [
                WordWithLocation(
                    word=word_with_location['word'],
                    index=word_with_location['index'],
                    length=word_with_location['length']
                )
                for word_with_location in words_with_location
                if word_with_location['index'] > 0
            ]
            
            logger.info("Successfully extracted important words", count=len(word_with_locations))
            return word_with_locations
            
        except Exception as e:
            logger.error("Failed to extract important words", error=str(e))
            raise
    
    async def get_words_explanations_stream(
        self, 
        text: str, 
        word_locations: List[WordWithLocation],
        language_code: Optional[str] = None
    ) -> AsyncGenerator[WordInfo, None]:
        """Stream word explanations as they become available."""
        if not text or not text.strip():
            raise ValidationError("Text cannot be empty")
        
        if not word_locations:
            raise ValidationError("Word locations cannot be empty")
        
        if len(word_locations) > 10:
            raise ValidationError("Cannot process more than 10 words at once")
        
        # Validate word locations
        for location in word_locations:
            if location.index < 0 or location.index >= len(text):
                raise ValidationError(f"Invalid word location: index {location.index} out of range")
            
            if location.index + location.length > len(text):
                raise ValidationError(f"Invalid word location: extends beyond text length")
        
        # Use provided language_code or detect from text
        if not language_code:
            language_code = await openai_service.detect_text_language_code(text)
            logger.info("Detected language code for text", language_code=language_code, text_preview=text[:50])
        else:
            logger.info("Using provided language code", language_code=language_code, text_preview=text[:50])
        
        # Create tasks for concurrent processing
        tasks = []
        for location in word_locations:
            # Use the word field directly from the location object
            word = location.word
            # Get context around the word (±50 characters)
            context_start = max(0, location.index - 50)
            context_end = min(len(text), location.index + location.length + 50)
            context = text[context_start:context_end]
            
            task = self._get_single_word_explanation(word, context, location, language_code)
            tasks.append(task)
        
        # Process words concurrently and yield results as they complete
        for completed_task in asyncio.as_completed(tasks):
            try:
                word_info = await completed_task
                logger.info("Word explanation completed", word=word_info.word)
                yield word_info
            except Exception as e:
                logger.error("Failed to get word explanation", error=str(e))
                # Continue processing other words even if one fails
                continue
    
    async def _get_single_word_explanation(
        self, 
        word: str, 
        context: str, 
        location: WordWithLocation,
        language_code: str
    ) -> WordInfo:
        """Get explanation for a single word."""
        raw_response = await openai_service.get_word_explanation(word, context, language_code)
        
        return WordInfo(
            location=location,
            word=word,
            raw_response=raw_response,
            meaning=None,
            examples=None,
            languageCode=language_code
        )
    
    async def get_more_examples(
        self, 
        word: str, 
        meaning: str, 
        existing_examples: List[str]
    ) -> List[str]:
        """Generate additional examples for a word."""
        if not word or not word.strip():
            raise ValidationError("Word cannot be empty")
        
        if not meaning or not meaning.strip():
            raise ValidationError("Meaning cannot be empty")
        
        if len(existing_examples) != 2:
            raise ValidationError("Must provide exactly 2 existing examples")
        
        try:
            new_examples = await openai_service.get_more_examples(word, meaning, existing_examples)
            
            # Return all examples (original + new)
            all_examples = existing_examples + new_examples
            
            logger.info("Successfully generated more examples", word=word, total_examples=len(all_examples))
            return all_examples
            
        except Exception as e:
            logger.error("Failed to generate more examples", word=word, error=str(e))
            raise


# Global service instance
text_service = TextService()
