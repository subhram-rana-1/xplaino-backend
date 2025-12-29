"""API routes for v2 endpoints of the FastAPI application."""

import asyncio
import json
import os
from enum import Enum
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Depends, Response, Form
from fastapi.responses import StreamingResponse, Response
import structlog

from app.config import settings
from app.models import (
    WordWithLocation,
    WordInfo
)
from app.services.text_service import text_service
from app.services.llm.open_ai import openai_service
from app.services.rate_limiter import rate_limiter
from app.services.web_search_service import web_search_service
from app.services.auth_middleware import authenticate
from app.services.image_service import image_service
from app.exceptions import FileValidationError, ValidationError
from app.utils.utils import get_client_ip
from pydantic import BaseModel, Field

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v2", tags=["API v2"])


def get_allowed_origin_from_request(request: Request) -> str:
    """Get the allowed origin from the request for CORS headers.
    
    When credentials are included, we cannot use '*' and must return the specific origin.
    Echoes back the request origin to allow requests with credentials from any origin.
    This is safe because we're echoing back what the browser sent, not allowing arbitrary origins.
    """
    origin = request.headers.get("Origin")
    
    if origin:
        # Echo back the origin - this is safe because the browser only sends origins
        # that the page is allowed to make requests from
        return origin
    
    # Fallback: if no origin header, return "*" (shouldn't happen with credentials)
    return "*"


# Enums
class ContextType(str, Enum):
    """Context type enum for ask and summarise APIs."""
    PAGE = "PAGE"
    TEXT = "TEXT"


# V2-specific models
class WordsExplanationV2Request(BaseModel):
    """Request model for v2 words explanation with textStartIndex."""
    
    textStartIndex: int = Field(..., ge=0, description="Starting index of the text in the original document")
    text: str = Field(..., min_length=1, max_length=10000, description="Input text to analyze")
    important_words_location: List[WordWithLocation] = Field(..., min_items=1, max_items=10, description="List of important word locations")
    languageCode: Optional[str] = Field(default=None, max_length=10, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected.")


class WordsExplanationV2Response(BaseModel):
    """Response model for v2 words explanation."""
    
    word_info: WordInfo = Field(..., description="Word information with textStartIndex")


class SimplifyRequest(BaseModel):
    """Request model for text simplification."""
    
    textStartIndex: int = Field(..., ge=0, description="Starting index of the text in the original document")
    textLength: int = Field(..., gt=0, description="Length of the text")
    text: str = Field(..., min_length=1, max_length=10000, description="Text to simplify")
    previousSimplifiedTexts: List[str] = Field(default=[], description="Previous simplified versions for context")
    context: Optional[str] = Field(default=None, max_length=50000, description="Full context surrounding the text (prefix words + text + suffix text). This helps the AI better understand the meaning and simplify appropriately.")
    languageCode: Optional[str] = Field(default=None, max_length=10, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected.")


class SimplifyResponse(BaseModel):
    """Response model for text simplification."""
    
    textStartIndex: int = Field(..., description="Starting index of the text in the original document")
    textLength: int = Field(..., description="Length of the text")
    text: str = Field(..., description="Original text")
    previousSimplifiedTexts: List[str] = Field(..., description="Previous simplified versions")
    simplifiedText: str = Field(..., description="New simplified text")
    shouldAllowSimplifyMore: bool = Field(..., description="Whether more simplification attempts are allowed")
    possibleQuestions: Optional[List[str]] = Field(default=None, description="List of 1 to 3 possible questions based on the text (only included when previousSimplifiedTexts is empty), ordered by relevance/importance in decreasing order")


class ImportantWordsV2Request(BaseModel):
    """Request model for v2 important words with textStartIndex."""
    
    textStartIndex: int = Field(..., ge=0, description="Starting index of the text in the original document")
    text: str = Field(..., min_length=1, max_length=10000, description="Input text to analyze")
    languageCode: Optional[str] = Field(default=None, max_length=10, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected.")


class ImportantWordsV2Response(BaseModel):
    """Response model for v2 important words."""
    
    textStartIndex: int = Field(..., description="Starting index of the text in the original document")
    text: str = Field(..., description="Original input text")
    important_words_location: List[WordWithLocation] = Field(..., description="List of important word locations")


class ChatMessage(BaseModel):
    """Model for chat message in ask API."""
    
    role: str = Field(..., description="Role of the message sender (user/assistant)")
    content: str = Field(..., description="Content of the message")


class AskRequest(BaseModel):
    """Request model for ask API."""
    
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    chat_history: List[ChatMessage] = Field(default=[], description="Previous chat history for context")
    initial_context: Optional[str] = Field(default=None, max_length=100000, description="Initial context or background information that the AI should be aware of")
    context_type: Optional[ContextType] = Field(default=ContextType.TEXT, description="Type of context: PAGE (for page/document context with source references) or TEXT (standard text context). Default is TEXT.")
    languageCode: Optional[str] = Field(default=None, max_length=10, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected.")


class AskResponse(BaseModel):
    """Response model for ask API."""
    
    chat_history: List[ChatMessage] = Field(..., description="Updated chat history including the new Q&A")
    possibleQuestions: List[str] = Field(..., description="List of top 3 recommended questions based on current question and chat history, ordered by relevance/importance")


class PronunciationRequest(BaseModel):
    """Request model for word pronunciation API."""
    
    word: str = Field(..., min_length=1, max_length=100, description="Word to generate pronunciation for")
    voice: Optional[str] = Field(default="nova", description="Voice to use (alloy, echo, fable, onyx, nova, shimmer). Default is 'nova' for sweet-toned American female voice")


class VoiceToTextResponse(BaseModel):
    """Response model for voice-to-text API."""
    
    text: str = Field(..., description="Transcribed text from the audio")


class TranslateTextItem(BaseModel):
    """Model for individual text item to translate."""
    
    id: str = Field(..., description="Unique identifier for this text item")
    text: str = Field(..., min_length=1, max_length=5000, description="Text to translate")


class TranslateRequest(BaseModel):
    """Request model for translate API."""
    
    targetLangugeCode: str = Field(..., min_length=2, max_length=2, description="ISO 639-1 language code (e.g., 'EN', 'ES', 'FR', 'DE', 'HI')")
    texts: List[TranslateTextItem] = Field(..., min_items=1, max_items=20, description="List of text items to translate (max 20)")


class SummariseRequest(BaseModel):
    """Request model for summarise API."""
    
    text: str = Field(..., min_length=1, max_length=50000, description="Text to summarize (can contain newline characters)")
    context_type: Optional[ContextType] = Field(default=ContextType.TEXT, description="Type of context: PAGE (for page/document context with source references) or TEXT (standard text context). Default is TEXT.")
    languageCode: Optional[str] = Field(default=None, max_length=10, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected.")


class SummariseResponse(BaseModel):
    """Response model for summarise API."""
    
    summary: str = Field(..., description="Short, insightful summary of the input text")
    possibleQuestions: List[str] = Field(..., description="List of top 5 possible questions based on the context, ordered by relevance/importance")


class WebSearchRequest(BaseModel):
    """Request model for web search API."""
    
    query: str = Field(..., min_length=1, max_length=500, description="Search query string")
    max_results: Optional[int] = Field(default=10, ge=1, le=50, description="Maximum number of results to return (1-50, default: 10)")
    region: Optional[str] = Field(default="wt-wt", description="Search region code (default: 'wt-wt' for worldwide)")
    language: Optional[str] = Field(default=None, description="Language code for search results (e.g., 'en', 'es', 'fr', 'de', 'hi'). If None, defaults to English ('en').")


class SearchResultItem(BaseModel):
    """Model for individual search result item."""
    
    title: str = Field(..., description="Title of the search result")
    link: str = Field(..., description="URL of the search result")
    snippet: str = Field(..., description="Brief description or excerpt from the page")
    displayLink: str = Field(..., description="Display-friendly URL")
    image: Optional[Dict[str, Any]] = Field(default=None, description="Optional image information")


class WebSearchResponse(BaseModel):
    """Response model for web search API (Google Search API-like format)."""
    
    kind: str = Field(..., description="Type of response")
    searchInformation: Dict[str, Any] = Field(..., description="Search metadata including search time and total results")
    queries: Dict[str, Any] = Field(..., description="Query information")
    items: List[SearchResultItem] = Field(..., description="Array of search result items")
    error: Optional[Dict[str, str]] = Field(default=None, description="Error information if search failed")


class SynonymsRequest(BaseModel):
    """Request model for synonyms API."""
    
    words: List[str] = Field(..., min_items=1, max_items=20, description="List of words to get synonyms for (max 20)")


class WordSynonyms(BaseModel):
    """Model for word synonyms."""
    
    word: str = Field(..., description="The original word")
    synonyms: List[str] = Field(..., description="List of synonyms (up to 3, at least 1 if available)")


class SynonymsResponse(BaseModel):
    """Response model for synonyms API."""
    
    results: List[WordSynonyms] = Field(..., description="List of word synonyms")


class AntonymsRequest(BaseModel):
    """Request model for antonyms API."""
    
    words: List[str] = Field(..., min_items=1, max_items=20, description="List of words to get antonyms for (max 20)")


class WordAntonyms(BaseModel):
    """Model for word antonyms."""
    
    word: str = Field(..., description="The original word")
    antonyms: List[str] = Field(..., description="List of antonyms (up to 2, at least 1 if available)")


class AntonymsResponse(BaseModel):
    """Response model for antonyms API."""
    
    results: List[WordAntonyms] = Field(..., description="List of word antonyms")


class SimplifyImageRequest(BaseModel):
    """Request model for image simplification (used for parsing form data)."""
    
    previousSimplifiedTexts: List[str] = Field(default=[], description="Previous simplified versions for context (JSON string)")
    languageCode: Optional[str] = Field(default=None, max_length=10, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected.")


class AskImageRequest(BaseModel):
    """Request model for ask-image API (used for parsing form data)."""
    
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    chat_history: List[ChatMessage] = Field(default=[], description="Previous chat history for context (JSON string)")
    languageCode: Optional[str] = Field(default=None, max_length=10, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected.")
    context_type: Optional[ContextType] = Field(default=ContextType.TEXT, description="Type of context: PAGE (for page/document context with source references) or TEXT (standard text context). Default is TEXT.")


async def get_client_id(request: Request) -> str:
    """Get client identifier for rate limiting."""
    # Use IP address as client ID (in production, you might use authenticated user ID)
    return get_client_ip(request)


@router.post(
    "/words-explanation",
    summary="Get word explanations with streaming (v2)",
    description="Provide contextual meaning + 2 simplified example sentences for each important word via Server-Sent Events. Accepts array of text objects with textStartIndex."
)
async def words_explanation_v2(
    request: Request,
    response: Response,
    body: List[WordsExplanationV2Request],
    auth_context: dict = Depends(authenticate)
):
    """Stream word explanations as they become available for multiple text objects.
    
    NOTE: If authenticate() returns a JSONResponse (401/429), this function
    will NOT execute - FastAPI will use that response directly.
    """
    # This log will only appear if the endpoint executes (i.e., auth passed)
    logger.info("words_explanation_v2 endpoint executing - authentication passed")
    
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "words-explanation")
    
    async def generate_explanations():
        """Generate SSE stream of word explanations."""
        try:
            for text_obj in body:
                # Process each text object
                async for word_info in text_service.get_words_explanations_stream(
                    text_obj.text, 
                    text_obj.important_words_location,
                    text_obj.languageCode
                ):
                    # Send raw_response directly without JSON wrapper
                    event_data = f"data: {word_info.raw_response}\n\n"
                    yield event_data
            
            # Send final completion event
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error("Error in words explanation v2 stream", error=str(e))
            error_event = {
                "error_code": "STREAM_001",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"
    
    logger.info("Starting word explanations v2 stream", 
               text_objects_count=len(body),
               total_words=sum(len(obj.important_words_location) for obj in body))
    
    # Get the actual origin instead of using wildcard when credentials are required
    allowed_origin = get_allowed_origin_from_request(request)
    
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx buffering
        "Access-Control-Allow-Origin": allowed_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-CSRFToken, X-Forwarded-For, User-Agent, Origin, Referer, Cache-Control, Pragma, Content-Disposition, Content-Transfer-Encoding, X-File-Name, X-File-Size, X-File-Type, X-Access-Token, X-Unauthenticated-User-Id",
        "Access-Control-Expose-Headers": "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, Access-Control-Allow-Headers, X-Unauthenticated-User-Id"
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return StreamingResponse(
        generate_explanations(),
        media_type="text/event-stream",
        headers=headers
    )


@router.post(
    "/simplify",
    summary="Simplify text with context (v2) - SSE Streaming",
    description="Generate simplified versions of texts using OpenAI API with previous context via Server-Sent Events. Returns streaming word-by-word response as text is simplified."
)
async def simplify_v2(
    request: Request,
    response: Response,
    body: List[SimplifyRequest],
    auth_context: dict = Depends(authenticate)
):
    """Simplify multiple texts with context from previous simplifications using word-by-word streaming."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "simplify")
    
    async def generate_simplifications():
        """Generate SSE stream of simplified texts with word-by-word streaming."""
        try:
            for text_obj in body:
                accumulated_simplified = ""

                # Stream simplified text chunks from OpenAI
                async for chunk in openai_service.simplify_text_stream(
                    text_obj.text, 
                    text_obj.previousSimplifiedTexts,
                    text_obj.languageCode,
                    text_obj.context
                ):
                    accumulated_simplified += chunk

                    # Send each chunk as it arrives
                    chunk_data = {
                        "textStartIndex": text_obj.textStartIndex,
                        "textLength": text_obj.textLength,
                        "text": text_obj.text,
                        "previousSimplifiedTexts": text_obj.previousSimplifiedTexts,
                        "chunk": chunk,
                        "accumulatedSimplifiedText": accumulated_simplified
                    }
                    event_data = f"data: {json.dumps(chunk_data)}\n\n"
                    yield event_data
                
                # After streaming is complete, generate possible questions if previousSimplifiedTexts is empty
                should_allow_simplify_more = len(text_obj.previousSimplifiedTexts) < settings.max_simplification_attempts
                
                possible_questions = None
                # Only generate questions if previousSimplifiedTexts is empty
                if len(text_obj.previousSimplifiedTexts) == 0:
                    try:
                        possible_questions = await openai_service.generate_possible_questions_for_text(
                            text_obj.text,
                            text_obj.languageCode,
                            max_questions=3
                        )
                    except Exception as e:
                        logger.error("Failed to generate possible questions for simplify, continuing without them", error=str(e))
                        # Continue without questions if generation fails
                        possible_questions = None
                
                final_data = {
                    "type": "complete",
                    "textStartIndex": text_obj.textStartIndex,
                    "textLength": text_obj.textLength,
                    "text": text_obj.text,
                    "previousSimplifiedTexts": text_obj.previousSimplifiedTexts,
                    "simplifiedText": accumulated_simplified,
                    "shouldAllowSimplifyMore": should_allow_simplify_more
                }
                
                # Only include possibleQuestions if it was generated (i.e., previousSimplifiedTexts was empty)
                if possible_questions is not None:
                    final_data["possibleQuestions"] = possible_questions
                
                event_data = f"data: {json.dumps(final_data)}\n\n"
                yield event_data
            
            # Send final completion event
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error("Error in simplify v2 stream", error=str(e))
            error_event = {
                "type": "error",
                "error_code": "STREAM_002",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"
    
    logger.info("Starting text simplifications v2 stream", 
               text_objects_count=len(body))
    
    # Get the actual origin instead of using wildcard when credentials are required
    allowed_origin = get_allowed_origin_from_request(request)
    
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx buffering
        "Access-Control-Allow-Origin": allowed_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-CSRFToken, X-Forwarded-For, User-Agent, Origin, Referer, Cache-Control, Pragma, Content-Disposition, Content-Transfer-Encoding, X-File-Name, X-File-Size, X-File-Type, X-Access-Token, X-Unauthenticated-User-Id",
        "Access-Control-Expose-Headers": "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, Access-Control-Allow-Headers, X-Unauthenticated-User-Id"
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return StreamingResponse(
        generate_simplifications(),
        media_type="text/event-stream",
        headers=headers
    )


@router.post(
    "/important-words-from-text",
    response_model=ImportantWordsV2Response,
    summary="Get important words from text (v2)",
    description="Identify top 10 most important/difficult words in a paragraph with textStartIndex"
)
async def important_words_from_text_v2(
    request: Request,
    response: Response,
    body: ImportantWordsV2Request,
    auth_context: dict = Depends(authenticate)
):
    """Extract important words from text with textStartIndex."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "important-words-from-text")
    
    # Extract important words using existing service
    word_with_locations = await text_service.extract_important_words(body.text, body.languageCode)
    
    logger.info("Successfully extracted important words v2", 
               text_length=len(body.text), 
               words_count=len(word_with_locations),
               textStartIndex=body.textStartIndex)
    
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return ImportantWordsV2Response(
        textStartIndex=body.textStartIndex,
        text=body.text,
        important_words_location=word_with_locations
    )


@router.post(
    "/ask",
    summary="Contextual Q&A with streaming (v2)",
    description="Ask questions with full chat history context and optional initial context for ongoing conversations. Returns streaming word-by-word response via Server-Sent Events. Provide initial context to give the AI background information about a topic."
)
async def ask_v2(
    request: Request,
    response: Response,
    body: AskRequest,
    auth_context: dict = Depends(authenticate)
):
    """Handle contextual Q&A with chat history using streaming."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "ask")
    
    async def generate_streaming_answer():
        """Generate SSE stream of answer chunks."""
        accumulated_answer = ""
        try:
            # Stream answer chunks from OpenAI
            context_type_value = body.context_type.value if body.context_type else "TEXT"
            async for chunk in openai_service.generate_contextual_answer_stream(
                body.question,
                body.chat_history,
                body.initial_context,
                body.languageCode,
                context_type_value
            ):
                accumulated_answer += chunk

                # Send each chunk as it arrives
                chunk_data = {
                    "chunk": chunk,
                    "accumulated": accumulated_answer
                }
                event_data = f"data: {json.dumps(chunk_data)}\n\n"
                yield event_data

            # After streaming is complete, generate recommended questions
            # Build updated chat history first
            updated_history = body.chat_history.copy()
            updated_history.append(ChatMessage(role="user", content=body.question))
            updated_history.append(ChatMessage(role="assistant", content=accumulated_answer))
            
            possible_questions = []
            try:
                # Pass updated history (including current Q&A) for better context in question generation
                # The method will use this to generate follow-up questions based on the full conversation
                possible_questions = await openai_service.generate_recommended_questions(
                    body.question,
                    updated_history,  # Use updated history including current Q&A for better context
                    body.initial_context,
                    body.languageCode
                )
            except Exception as e:
                logger.error("Failed to generate recommended questions, continuing without them", error=str(e))
                # Continue with empty questions list if generation fails
                possible_questions = []

            # Send final response with updated chat history and possible questions
            final_data = {
                "type": "complete",
                "chat_history": [msg.model_dump() for msg in updated_history],
                "possibleQuestions": possible_questions
            }
            event_data = f"data: {json.dumps(final_data)}\n\n"
            yield event_data

            # Send final completion event
            yield "data: [DONE]\n\n"

            logger.info("Successfully streamed contextual answer",
                       question_length=len(body.question),
                       answer_length=len(accumulated_answer),
                       chat_history_length=len(updated_history),
                       questions_count=len(possible_questions))

        except Exception as e:
            logger.error("Error in ask v2 stream", error=str(e))
            error_event = {
                "type": "error",
                "error_code": "STREAM_003",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    logger.info("Starting ask v2 stream",
               question_length=len(body.question),
               chat_history_length=len(body.chat_history),
               has_initial_context=bool(body.initial_context))

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"  # Disable nginx buffering
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return StreamingResponse(
        generate_streaming_answer(),
        media_type="text/event-stream",
        headers=headers
    )


@router.post(
    "/pronunciation",
    summary="Generate word pronunciation audio (v2)",
    description="Generate pronunciation audio for a single word using OpenAI TTS with a sweet-toned American female voice"
)
async def get_pronunciation(
    request: Request,
    response: Response,
    body: PronunciationRequest,
    auth_context: dict = Depends(authenticate)
):
    """Generate pronunciation audio for a word."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "pronunciation")
    
    try:
        # Validate voice parameter
        valid_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        if body.voice and body.voice not in valid_voices:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid voice. Must be one of: {', '.join(valid_voices)}"
            )
        
        # Generate pronunciation audio
        audio_bytes = await openai_service.generate_pronunciation_audio(
            body.word,
            body.voice or "nova"
        )
        
        logger.info("Successfully generated pronunciation audio",
                   word=body.word,
                   voice=body.voice,
                   audio_size=len(audio_bytes))
        
        # Return audio file
        headers = {
            "Content-Disposition": f'inline; filename="{body.word}_pronunciation.mp3"',
            "Cache-Control": "public, max-age=86400"  # Cache for 24 hours
        }
        if auth_context.get("is_new_unauthenticated_user"):
            headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
        
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers=headers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate pronunciation", word=body.word, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to generate pronunciation: {str(e)}")


@router.post(
    "/voice-to-text",
    response_model=VoiceToTextResponse,
    summary="Convert voice audio to text (v2)",
    description="Transcribe audio file to text using OpenAI Whisper. Automatically detects language. Supports various audio formats (mp3, mp4, mpeg, mpga, m4a, wav, webm). Use translate=true to translate non-English audio to English."
)
async def voice_to_text(
    request: Request,
    response: Response,
    audio_file: UploadFile = File(..., description="Audio file to transcribe"),
    translate: bool = False,
    auth_context: dict = Depends(authenticate)
):
    """Convert voice audio to text using OpenAI Whisper.
    
    Args:
        audio_file: Audio file to transcribe
        translate: If True, translates non-English audio to English. If False (default), transcribes in original language.
    """
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "voice-to-text")
    
    try:
        # Validate file type
        allowed_extensions = ["mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm"]
        file_extension = audio_file.filename.split(".")[-1].lower() if audio_file.filename else ""
        
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid audio format. Supported formats: {', '.join(allowed_extensions)}"
            )
        
        # Validate file size (max 25MB for Whisper API)
        audio_bytes = await audio_file.read()
        file_size_mb = len(audio_bytes) / (1024 * 1024)
        
        if file_size_mb > 25:
            raise HTTPException(
                status_code=400,
                detail=f"Audio file too large ({file_size_mb:.2f}MB). Maximum size is 25MB."
            )
        
        logger.info("Processing voice-to-text request",
                   filename=audio_file.filename,
                   file_size_mb=file_size_mb,
                   file_extension=file_extension,
                   translate=translate)
        
        # Transcribe audio using OpenAI Whisper
        transcribed_text = await openai_service.transcribe_audio(
            audio_bytes, 
            audio_file.filename,
            translate=translate
        )
        
        logger.info("Successfully transcribed audio",
                   filename=audio_file.filename,
                   text_length=len(transcribed_text),
                   translate=translate)
        
        if auth_context.get("is_new_unauthenticated_user"):
            response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
        
        return VoiceToTextResponse(text=transcribed_text)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to transcribe audio", 
                   filename=audio_file.filename if audio_file else "unknown",
                   error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to transcribe audio: {str(e)}")


@router.post(
    "/translate",
    summary="Translate texts to target language with streaming (v2) - SSE",
    description="Translate multiple texts to a target language using OpenAI with Server-Sent Events streaming. Each translation is returned immediately as it completes. Supports various language codes (EN, ES, FR, DE, HI, JA, ZH, etc.)"
)
async def translate_v2(
    request: Request,
    response: Response,
    body: TranslateRequest,
    auth_context: dict = Depends(authenticate)
):
    """Translate texts to the target language with SSE streaming."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "translate")
    
    async def generate_translations():
        """Generate SSE stream of translated texts."""
        try:
            # Validate target language code format (should be 2 uppercase letters)
            if not body.targetLangugeCode.isalpha() or len(body.targetLangugeCode) != 2:
                error_event = {
                    "type": "error",
                    "error_code": "VALIDATION_ERROR",
                    "error_message": "Invalid target language code. Must be a 2-letter ISO 639-1 code (e.g., 'EN', 'ES', 'FR')"
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                return
            
            # Validate texts are not empty
            if not body.texts:
                error_event = {
                    "type": "error",
                    "error_code": "VALIDATION_ERROR",
                    "error_message": "Texts cannot be empty"
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                return
            
            # Validate each text item
            for text_item in body.texts:
                if not text_item.text or not text_item.text.strip():
                    error_event = {
                        "type": "error",
                        "error_code": "VALIDATION_ERROR",
                        "error_message": f"Text with id '{text_item.id}' cannot be empty"
                    }
                    yield f"data: {json.dumps(error_event)}\n\n"
                    return
            
            logger.info("Starting translation stream",
                       target_language_code=body.targetLangugeCode,
                       texts_count=len(body.texts))
            
            # Create batches based on text length (200 char threshold)
            batches = []
            current_batch = []
            current_length = 0
            
            for text_item in body.texts:
                text_length = len(text_item.text)
                
                # If single item > 200, send it alone
                if text_length > 200:
                    # Finalize current batch if any
                    if current_batch:
                        batches.append(current_batch)
                        current_batch = []
                        current_length = 0
                    # Add single item as its own batch
                    batches.append([text_item])
                else:
                    # Add to current batch
                    current_batch.append(text_item)
                    current_length += text_length
                    
                    # If total exceeds 200, finalize batch
                    if current_length > 200:
                        batches.append(current_batch)
                        current_batch = []
                        current_length = 0
            
            # Don't forget remaining items
            if current_batch:
                batches.append(current_batch)
            
            logger.info("Created translation batches",
                       total_batches=len(batches),
                       batch_sizes=[len(b) for b in batches])
            
            # Process each batch and stream results
            for batch_index, batch in enumerate(batches):
                try:
                    if len(batch) == 1:
                        # Single text - use existing single text method
                        text_item = batch[0]
                        logger.info("Translating single item",
                                   batch_index=batch_index,
                                   id=text_item.id,
                                   text_length=len(text_item.text))
                        
                        translated_text = await openai_service.translate_single_text(
                            text_item.text,
                            body.targetLangugeCode.upper()
                        )
                        
                        # Send translation result immediately
                        result_data = {
                            "id": text_item.id,
                            "translatedText": translated_text
                        }
                        event_data = f"data: {json.dumps(result_data)}\n\n"
                        yield event_data
                        
                        logger.info("Translated single text item",
                                   id=text_item.id,
                                   target_language_code=body.targetLangugeCode)
                    else:
                        # Multiple texts - use batch method
                        logger.info("Translating batch",
                                   batch_index=batch_index,
                                   batch_size=len(batch),
                                   total_chars=sum(len(item.text) for item in batch))
                        
                        # Prepare items for batch translation
                        items = [{"id": item.id, "text": item.text} for item in batch]
                        
                        try:
                            # Translate batch with IDs
                            results = await openai_service.translate_batch_with_ids(
                                items,
                                body.targetLangugeCode.upper()
                            )
                            
                            # Stream each result individually
                            for result in results:
                                result_data = {
                                    "id": result["id"],
                                    "translatedText": result["translatedText"]
                                }
                                event_data = f"data: {json.dumps(result_data)}\n\n"
                                yield event_data
                            
                            logger.info("Translated batch successfully",
                                       batch_index=batch_index,
                                       batch_size=len(batch),
                                       results_count=len(results))
                            
                        except Exception as batch_error:
                            # Fall back to individual translation if batch fails
                            logger.warning("Batch translation failed, falling back to individual translations",
                                         batch_index=batch_index,
                                         error=str(batch_error))
                            
                            for text_item in batch:
                                try:
                                    translated_text = await openai_service.translate_single_text(
                                        text_item.text,
                                        body.targetLangugeCode.upper()
                                    )
                                    
                                    result_data = {
                                        "id": text_item.id,
                                        "translatedText": translated_text
                                    }
                                    event_data = f"data: {json.dumps(result_data)}\n\n"
                                    yield event_data
                                    
                                except Exception as item_error:
                                    logger.error("Failed to translate text item in fallback",
                                               id=text_item.id,
                                               error=str(item_error))
                                    error_event = {
                                        "type": "error",
                                        "error_code": "TRANSLATION_ERROR",
                                        "error_message": f"Failed to translate text with id '{text_item.id}': {str(item_error)}",
                                        "id": text_item.id
                                    }
                                    yield f"data: {json.dumps(error_event)}\n\n"
                    
                except Exception as e:
                    logger.error("Failed to process batch",
                               batch_index=batch_index,
                               error=str(e))
                    # Send error for all items in batch
                    for text_item in batch:
                        error_event = {
                            "type": "error",
                            "error_code": "TRANSLATION_ERROR",
                            "error_message": f"Failed to translate text with id '{text_item.id}': {str(e)}",
                            "id": text_item.id
                        }
                        yield f"data: {json.dumps(error_event)}\n\n"
            
            # Send final completion event
            yield "data: [DONE]\n\n"
            
            logger.info("Successfully completed translation stream",
                       target_language_code=body.targetLangugeCode,
                       texts_count=len(body.texts))
            
        except Exception as e:
            logger.error("Error in translate v2 stream", error=str(e))
            error_event = {
                "type": "error",
                "error_code": "STREAM_006",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"
    
    logger.info("Starting translate v2 stream",
               target_language_code=body.targetLangugeCode,
               texts_count=len(body.texts))
    
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx buffering
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-CSRFToken, X-Forwarded-For, User-Agent, Origin, Referer, Cache-Control, Pragma, Content-Disposition, Content-Transfer-Encoding, X-File-Name, X-File-Size, X-File-Type, X-Access-Token, X-Unauthenticated-User-Id",
        "Access-Control-Expose-Headers": "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, Access-Control-Allow-Headers, X-Unauthenticated-User-Id"
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return StreamingResponse(
        generate_translations(),
        media_type="text/event-stream",
        headers=headers
    )


@router.post(
    "/summarise",
    summary="Summarise text with streaming (v2)",
    description="Generate a short, insightful summary of the input text using OpenAI with word-by-word streaming via Server-Sent Events. The input text can contain newline characters."
)
async def summarise_v2(
    request: Request,
    response: Response,
    body: SummariseRequest,
    auth_context: dict = Depends(authenticate)
):
    """Generate a short, insightful summary of the input text using streaming."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "summerise")
    
    # Validate text is not empty
    if not body.text or not body.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Text cannot be empty"
        )

    async def generate_streaming_summary():
        """Generate SSE stream of summary chunks."""
        accumulated_summary = ""
        try:
            # Stream summary chunks from OpenAI
            context_type_value = body.context_type.value if body.context_type else "TEXT"
            async for chunk in openai_service.summarise_text_stream(body.text, body.languageCode, context_type_value):
                accumulated_summary += chunk

                # Send each chunk as it arrives
                chunk_data = {
                    "chunk": chunk,
                    "accumulated": accumulated_summary
                }
                event_data = f"data: {json.dumps(chunk_data)}\n\n"
                yield event_data

            # After streaming is complete, generate possible questions
            possible_questions = []
            try:
                possible_questions = await openai_service.generate_possible_questions(
                    body.text,
                    body.languageCode
                )
            except Exception as e:
                logger.error("Failed to generate possible questions, continuing without them", error=str(e))
                # Continue with empty questions list if generation fails
                possible_questions = []

            # Send final response with complete summary and possible questions
            final_data = {
                "type": "complete",
                "summary": accumulated_summary,
                "possibleQuestions": possible_questions
            }
            event_data = f"data: {json.dumps(final_data)}\n\n"
            yield event_data

            # Send final completion event
            yield "data: [DONE]\n\n"

            logger.info(
                "Successfully streamed summary",
                text_length=len(body.text),
                summary_length=len(accumulated_summary),
                questions_count=len(possible_questions)
            )

        except Exception as e:
            logger.error("Error in summarise v2 stream", error=str(e))
            error_event = {
                "type": "error",
                "error_code": "STREAM_004",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    logger.info("Starting summarise v2 stream",
               text_length=len(body.text),
               language_code=body.languageCode,
               has_language_code=body.languageCode is not None)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx buffering
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-CSRFToken, X-Forwarded-For, User-Agent, Origin, Referer, Cache-Control, Pragma, Content-Disposition, Content-Transfer-Encoding, X-File-Name, X-File-Size, X-File-Type, X-Access-Token, X-Unauthenticated-User-Id",
        "Access-Control-Expose-Headers": "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, Access-Control-Allow-Headers, X-Unauthenticated-User-Id"
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return StreamingResponse(
        generate_streaming_summary(),
        media_type="text/event-stream",
        headers=headers
    )


@router.post(
    "/web-search",
    response_model=WebSearchResponse,
    summary="Perform web search (v2)",
    description="Search the web using DuckDuckGo and return results in Google Search API-like JSON format. Results include title, link, snippet, displayLink, and optional image for each result. Perfect for displaying search results in a frontend similar to Google Search."
)
async def web_search_v2(
    request: Request,
    response: Response,
    body: WebSearchRequest,
    auth_context: dict = Depends(authenticate)
):
    """Perform a web search and return structured results in Google Search API format.
    
    This endpoint performs web searches using DuckDuckGo (free, no API key required)
    and returns results in a format similar to Google's Custom Search JSON API.
    The response structure is optimized for frontend display, making it easy to
    create a Google Search-like interface.
    
    Args:
        body: WebSearchRequest containing query, max_results, and optional region
    
    Returns:
        WebSearchResponse with search metadata and array of result items
    """
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "web-search")
    
    try:
        # Validate query
        if not body.query or not body.query.strip():
            raise HTTPException(
                status_code=400,
                detail="Query cannot be empty"
            )
        
        logger.info("Processing web search request",
                   query=body.query,
                   max_results=body.max_results,
                   region=body.region,
                   language=body.language)
        
        # Perform web search
        search_results = await web_search_service.search(
            query=body.query,
            max_results=body.max_results or 10,
            region=body.region,
            language=body.language
        )
        
        # Convert items to SearchResultItem models
        items = []
        for item_data in search_results.get("items", []):
            items.append(SearchResultItem(
                title=item_data.get("title", ""),
                link=item_data.get("link", ""),
                snippet=item_data.get("snippet", ""),
                displayLink=item_data.get("displayLink", ""),
                image=item_data.get("image")
            ))
        
        # Build response
        if auth_context.get("is_new_unauthenticated_user"):
            response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
        
        search_response = WebSearchResponse(
            kind=search_results.get("kind", "customsearch#search"),
            searchInformation=search_results.get("searchInformation", {}),
            queries=search_results.get("queries", {}),
            items=items,
            error=search_results.get("error")
        )
        
        logger.info("Successfully completed web search",
                   query=body.query,
                   results_count=len(items),
                   search_time=search_results.get("searchInformation", {}).get("searchTime", 0))
        
        return search_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to perform web search",
                   query=body.query if body else "unknown",
                   error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to perform web search: {str(e)}"
        )


@router.post(
    "/web-search-stream",
    summary="Perform web search with streaming (v2) - SSE",
    description="Search the web using DuckDuckGo and stream results progressively via Server-Sent Events. Results are sent one by one as they become available, providing a better user experience with progressive loading. Each result includes title, link, snippet, displayLink, and optional image."
)
async def web_search_stream_v2(
    request: Request,
    response: Response,
    body: WebSearchRequest,
    auth_context: dict = Depends(authenticate)
):
    """Perform a web search and stream results progressively via Server-Sent Events.
    
    This endpoint performs web searches using DuckDuckGo and streams results
    one by one as they become available. The first event contains search metadata,
    followed by individual result items, and finally a completion event.
    
    Event types:
    - "metadata": Contains searchInformation and queries (sent first)
    - "result": Individual search result item
    - "complete": Indicates all results have been sent
    - "error": Error information if search failed
    
    Args:
        body: WebSearchRequest containing query, max_results, and optional region
    
    Returns:
        StreamingResponse with Server-Sent Events
    """
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "web-search")
    
    async def generate_search_stream():
        """Generate SSE stream of search results."""
        try:
            # Validate query
            if not body.query or not body.query.strip():
                error_event = {
                    "type": "error",
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Query cannot be empty"
                    }
                }
                yield f"data: {json.dumps(error_event)}\n\n"
                return
            
            logger.info("Starting web search stream",
                       query=body.query,
                       max_results=body.max_results,
                       region=body.region,
                       language=body.language)
            
            # Stream search results
            async for event_data in web_search_service.search_stream(
                query=body.query,
                max_results=body.max_results or 10,
                region=body.region,
                language=body.language
            ):
                # Send each event as SSE
                event_json = f"data: {json.dumps(event_data)}\n\n"
                yield event_json
            
            # Send final completion event
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error("Error in web search stream", error=str(e))
            error_event = {
                "type": "error",
                "error_code": "STREAM_005",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"
    
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no"  # Disable nginx buffering
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return StreamingResponse(
        generate_search_stream(),
        media_type="text/event-stream",
        headers=headers
    )


@router.post(
    "/synonyms",
    response_model=SynonymsResponse,
    summary="Get synonyms for words (v2)",
    description="Get synonyms for a list of words (up to 20 words). Returns up to 3 synonyms for each word, at least 1 if available. If a word has no synonyms, returns an empty array for that word."
)
async def get_synonyms_v2(
    request: Request,
    response: Response,
    body: SynonymsRequest,
    auth_context: dict = Depends(authenticate)
):
    """Get synonyms for multiple words concurrently."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "synonyms")
    
    # Validate words are not empty
    if any(not word.strip() for word in body.words):
        raise HTTPException(
            status_code=400,
            detail="Words cannot be empty strings"
        )
    
    # Validate word lengths
    for word in body.words:
        if len(word) > 100:
            raise HTTPException(
                status_code=400,
                detail=f"Word '{word}' exceeds maximum length of 100 characters"
            )
    
    logger.info("Processing synonyms request", words_count=len(body.words))
    
    # Process words concurrently
    async def get_synonyms_for_word(word: str) -> WordSynonyms:
        """Get synonyms for a single word, returning empty array if not found."""
        try:
            synonyms = await text_service.get_synonyms_of_word(word.strip())
            return WordSynonyms(word=word, synonyms=synonyms)
        except Exception as e:
            logger.warning("Failed to get synonyms for word", word=word, error=str(e))
            # Return empty array if synonyms not found
            return WordSynonyms(word=word, synonyms=[])
    
    # Process all words concurrently
    tasks = [get_synonyms_for_word(word) for word in body.words]
    results = await asyncio.gather(*tasks)
    
    logger.info("Successfully processed synonyms request", 
               words_count=len(body.words),
               successful_count=sum(1 for r in results if r.synonyms))
    
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return SynonymsResponse(results=list(results))


@router.post(
    "/antonyms",
    response_model=AntonymsResponse,
    summary="Get antonyms for words (v2)",
    description="Get antonyms (opposites) for a list of words (up to 20 words). Returns up to 2 antonyms for each word, at least 1 if available. If a word has no antonyms, returns an empty array for that word."
)
async def get_antonyms_v2(
    request: Request,
    response: Response,
    body: AntonymsRequest,
    auth_context: dict = Depends(authenticate)
):
    """Get antonyms for multiple words concurrently."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "antonyms")
    
    # Validate words are not empty
    if any(not word.strip() for word in body.words):
        raise HTTPException(
            status_code=400,
            detail="Words cannot be empty strings"
        )
    
    # Validate word lengths
    for word in body.words:
        if len(word) > 100:
            raise HTTPException(
                status_code=400,
                detail=f"Word '{word}' exceeds maximum length of 100 characters"
            )
    
    logger.info("Processing antonyms request", words_count=len(body.words))
    
    # Process words concurrently
    async def get_antonyms_for_word(word: str) -> WordAntonyms:
        """Get antonyms for a single word, returning empty array if not found."""
        try:
            antonyms = await text_service.get_opposite_of_word(word.strip())
            return WordAntonyms(word=word, antonyms=antonyms)
        except Exception as e:
            logger.warning("Failed to get antonyms for word", word=word, error=str(e))
            # Return empty array if antonyms not found
            return WordAntonyms(word=word, antonyms=[])
    
    # Process all words concurrently
    tasks = [get_antonyms_for_word(word) for word in body.words]
    results = await asyncio.gather(*tasks)
    
    logger.info("Successfully processed antonyms request", 
               words_count=len(body.words),
               successful_count=sum(1 for r in results if r.antonyms))
    
    if auth_context.get("is_new_unauthenticated_user"):
        response.headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return AntonymsResponse(results=list(results))


@router.post(
    "/simplify-image",
    summary="Simplify image content with streaming (v2) - SSE Streaming",
    description="Generate simplified explanation of image content using OpenAI Vision API with previous context via Server-Sent Events. Returns streaming word-by-word response as the image is analyzed and simplified. Supports jpeg, jpg, png, heic, webp, gif, bmp formats (max 5MB)."
)
async def simplify_image_v2(
    request: Request,
    response: Response,
    image: UploadFile = File(..., description="Image file to simplify (max 5MB)"),
    previousSimplifiedTexts: str = Form(default="[]", description="Previous simplified versions for context (JSON array string)"),
    languageCode: Optional[str] = Form(default=None, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected."),
    auth_context: dict = Depends(authenticate)
):
    """Simplify image content with context from previous simplifications using word-by-word streaming."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "simplify-image")
    
    async def generate_simplifications():
        """Generate SSE stream of simplified image explanations with word-by-word streaming."""
        try:
            # Validate and process image
            image_bytes = await image.read()
            processed_image_data, image_format = image_service.validate_image_file_for_api(
                image_bytes, 
                image.filename or "image",
                max_size_mb=5
            )
            
            # Parse previousSimplifiedTexts from JSON string
            try:
                previous_texts = json.loads(previousSimplifiedTexts) if previousSimplifiedTexts else []
                if not isinstance(previous_texts, list):
                    previous_texts = []
            except (json.JSONDecodeError, TypeError):
                previous_texts = []
            
            accumulated_simplified = ""

            # Stream simplified explanation chunks from OpenAI
            async for chunk in openai_service.simplify_image_stream(
                processed_image_data,
                image_format,
                previous_texts,
                languageCode
            ):
                accumulated_simplified += chunk

                # Send each chunk as it arrives
                chunk_data = {
                    "chunk": chunk,
                    "accumulatedSimplifiedText": accumulated_simplified
                }
                event_data = f"data: {json.dumps(chunk_data)}\n\n"
                yield event_data
            
            # After streaming is complete, generate possible questions if previousSimplifiedTexts is empty
            should_allow_simplify_more = len(previous_texts) < settings.max_simplification_attempts
            
            possible_questions = None
            # Only generate questions if previousSimplifiedTexts is empty
            if len(previous_texts) == 0:
                try:
                    # Use the simplified text to generate questions
                    possible_questions = await openai_service.generate_possible_questions_for_text(
                        accumulated_simplified,
                        languageCode,
                        max_questions=3
                    )
                except Exception as e:
                    logger.error("Failed to generate possible questions for simplify-image, continuing without them", error=str(e))
                    # Continue without questions if generation fails
                    possible_questions = None
            
            final_data = {
                "type": "complete",
                "simplifiedText": accumulated_simplified,
                "shouldAllowSimplifyMore": should_allow_simplify_more
            }
            
            # Only include possibleQuestions if it was generated (i.e., previousSimplifiedTexts was empty)
            if possible_questions is not None:
                final_data["possibleQuestions"] = possible_questions
            
            event_data = f"data: {json.dumps(final_data)}\n\n"
            yield event_data
        
            # Send final completion event
            yield "data: [DONE]\n\n"
            
        except FileValidationError as e:
            logger.error("Image validation error in simplify-image v2", error=str(e))
            error_event = {
                "type": "error",
                "error_code": "VALIDATION_ERROR",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"
        except Exception as e:
            logger.error("Error in simplify-image v2 stream", error=str(e))
            error_event = {
                "type": "error",
                "error_code": "STREAM_007",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"
    
    logger.info("Starting image simplification v2 stream", 
               filename=image.filename)
    
    # Get the actual origin instead of using wildcard when credentials are required
    allowed_origin = get_allowed_origin_from_request(request)
    
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx buffering
        "Access-Control-Allow-Origin": allowed_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-CSRFToken, X-Forwarded-For, User-Agent, Origin, Referer, Cache-Control, Pragma, Content-Disposition, Content-Transfer-Encoding, X-File-Name, X-File-Size, X-File-Type, X-Access-Token, X-Unauthenticated-User-Id",
        "Access-Control-Expose-Headers": "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, Access-Control-Allow-Headers, X-Unauthenticated-User-Id"
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]
    
    return StreamingResponse(
        generate_simplifications(),
        media_type="text/event-stream",
        headers=headers
    )


@router.post(
    "/ask-image",
    summary="Contextual Q&A with image context and streaming (v2)",
    description="Ask questions about an image with full chat history context for ongoing conversations. Returns streaming word-by-word response via Server-Sent Events. The image serves as the context for answering questions. Supports jpeg, jpg, png, heic, webp, gif, bmp formats (max 5MB)."
)
async def ask_image_v2(
    request: Request,
    response: Response,
    question: str = Form(..., min_length=1, max_length=2000, description="User's question"),
    image: UploadFile = File(..., description="Image file to use as context (max 5MB)"),
    chat_history: str = Form(default="[]", description="Previous chat history for context (JSON array string)"),
    languageCode: Optional[str] = Form(default=None, description="Optional language code (e.g., 'EN', 'FR', 'ES', 'DE', 'HI'). If provided, response will be strictly in this language. If None, language will be auto-detected."),
    context_type: Optional[ContextType] = Form(default=ContextType.TEXT, description="Type of context: PAGE (for page/document context with source references) or TEXT (standard text context). Default is TEXT."),
    auth_context: dict = Depends(authenticate)
):
    """Handle contextual Q&A with image context and chat history using streaming."""
    client_id = await get_client_id(request)
    await rate_limiter.check_rate_limit(client_id, "ask-image")
    
    async def generate_streaming_answer():
        """Generate SSE stream of answer chunks."""
        accumulated_answer = ""
        try:
            # Validate and process image
            image_bytes = await image.read()
            processed_image_data, image_format = image_service.validate_image_file_for_api(
                image_bytes,
                image.filename or "image",
                max_size_mb=5
            )
            
            # Parse chat_history from JSON string
            try:
                history_data = json.loads(chat_history) if chat_history else []
                parsed_history = []
                for msg in history_data:
                    if isinstance(msg, dict):
                        parsed_history.append(ChatMessage(role=msg.get("role", "user"), content=msg.get("content", "")))
                    elif hasattr(msg, "role") and hasattr(msg, "content"):
                        parsed_history.append(msg)
            except (json.JSONDecodeError, TypeError, KeyError):
                parsed_history = []
            
            # Stream answer chunks from OpenAI
            context_type_value = context_type.value if context_type else "TEXT"
            async for chunk in openai_service.generate_contextual_answer_with_image_stream(
                question,
                processed_image_data,
                image_format,
                parsed_history,
                languageCode,
                context_type_value
            ):
                accumulated_answer += chunk

                # Send each chunk as it arrives
                chunk_data = {
                    "chunk": chunk,
                    "accumulated": accumulated_answer
                }
                event_data = f"data: {json.dumps(chunk_data)}\n\n"
                yield event_data

            # After streaming is complete, generate recommended questions
            # Build updated chat history first
            updated_history = parsed_history.copy()
            updated_history.append(ChatMessage(role="user", content=question))
            updated_history.append(ChatMessage(role="assistant", content=accumulated_answer))
            
            possible_questions = []
            try:
                # Pass updated history (including current Q&A) for better context in question generation
                # Since we're using image context, we'll pass None for initial_context
                possible_questions = await openai_service.generate_recommended_questions(
                    question,
                    updated_history,  # Use updated history including current Q&A for better context
                    None,  # No text initial_context since we're using image
                    languageCode
                )
            except Exception as e:
                logger.error("Failed to generate recommended questions for ask-image, continuing without them", error=str(e))
                # Continue with empty questions list if generation fails
                possible_questions = []

            # Send final response with updated chat history and possible questions
            final_data = {
                "type": "complete",
                "chat_history": [msg.model_dump() for msg in updated_history],
                "possibleQuestions": possible_questions
            }
            event_data = f"data: {json.dumps(final_data)}\n\n"
            yield event_data

            # Send final completion event
            yield "data: [DONE]\n\n"

            logger.info("Successfully streamed contextual answer with image",
                       question_length=len(question),
                       answer_length=len(accumulated_answer),
                       chat_history_length=len(updated_history),
                       questions_count=len(possible_questions))

        except FileValidationError as e:
            logger.error("Image validation error in ask-image v2", error=str(e))
            error_event = {
                "type": "error",
                "error_code": "VALIDATION_ERROR",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"
        except Exception as e:
            logger.error("Error in ask-image v2 stream", error=str(e))
            error_event = {
                "type": "error",
                "error_code": "STREAM_008",
                "error_message": str(e)
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    logger.info("Starting ask-image v2 stream",
               question_length=len(question),
               chat_history_length=len(chat_history) if chat_history else 0,
               filename=image.filename)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Disable nginx buffering
        "Access-Control-Allow-Origin": get_allowed_origin_from_request(request),
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Allow-Headers": "Accept, Accept-Language, Content-Language, Content-Type, Authorization, X-Requested-With, X-CSRFToken, X-Forwarded-For, User-Agent, Origin, Referer, Cache-Control, Pragma, Content-Disposition, Content-Transfer-Encoding, X-File-Name, X-File-Size, X-File-Type, X-Access-Token, X-Unauthenticated-User-Id",
        "Access-Control-Expose-Headers": "Content-Length, Content-Type, Cache-Control, X-Accel-Buffering, Content-Disposition, Access-Control-Allow-Origin, Access-Control-Allow-Methods, Access-Control-Allow-Headers, X-Unauthenticated-User-Id"
    }
    if auth_context.get("is_new_unauthenticated_user"):
        headers["X-Unauthenticated-User-Id"] = auth_context["unauthenticated_user_id"]

    return StreamingResponse(
        generate_streaming_answer(),
        media_type="text/event-stream",
        headers=headers
    )
