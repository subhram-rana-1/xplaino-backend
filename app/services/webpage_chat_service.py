"""Service layer for the webpage chat feature.

Handles question classification, structured answer generation with citations,
long-page windowed processing, and citation enrichment.
"""

import base64
import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from openai import AsyncOpenAI
import structlog

from app.config import settings
from app.prompts.webpage_chat_prompts import (
    ANSWER_SYSTEM_PROMPT,
    ANSWER_WITH_IMAGE_SYSTEM_PROMPT,
    BROAD_ANSWER_FORMAT_GUIDANCE,
    CLASSIFY_SYSTEM_PROMPT,
    CONTEXTUAL_ANSWER_FORMAT_GUIDANCE,
    PARTIAL_ANSWER_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
)
from app.services.llm.open_ai import get_language_name, openai_service

logger = structlog.get_logger()

_async_openai: Optional[AsyncOpenAI] = None

MAX_CONTEXT_TOKENS = 80_000
WINDOW_TOKEN_LIMIT = 60_000
VALID_QUESTION_TYPES = {"greeting", "broad", "contextual"}


def _get_async_openai() -> AsyncOpenAI:
    global _async_openai
    if _async_openai is None:
        _async_openai = AsyncOpenAI(api_key=settings.openai_api_key)
    return _async_openai


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

def _estimate_tokens(chunks: List[Dict[str, Any]]) -> int:
    return sum(len(c["text"]) for c in chunks) // 4


# ---------------------------------------------------------------------------
# Window splitting
# ---------------------------------------------------------------------------

def _split_into_windows(
    chunks: List[Dict[str, Any]],
    window_token_limit: int = WINDOW_TOKEN_LIMIT,
) -> List[List[Dict[str, Any]]]:
    """Split chunks list into sequential windows capped by approximate token count."""
    windows: List[List[Dict[str, Any]]] = []
    current_window: List[Dict[str, Any]] = []
    current_tokens = 0

    for chunk in chunks:
        chunk_tokens = len(chunk["text"]) // 4
        if current_window and current_tokens + chunk_tokens > window_token_limit:
            windows.append(current_window)
            current_window = []
            current_tokens = 0
        current_window.append(chunk)
        current_tokens += chunk_tokens

    if current_window:
        windows.append(current_window)

    return windows


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_chunks_context(chunks: List[Dict[str, Any]]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(f"[chunkId: {chunk['chunkId']}]\n{chunk['text']}")
    return "\n\n---\n\n".join(parts) if parts else "(No content available)"


def _build_conversation_history(
    conversation_history: Optional[List[Dict[str, str]]],
) -> str:
    if not conversation_history:
        return "(No previous messages)"
    lines = []
    for msg in conversation_history[-10:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        label = "User" if role.lower() == "user" else "Assistant"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _build_selected_text_context(selected_text: Optional[str]) -> str:
    """Build the selected-text section injected into answer prompts.

    When the user has annotated a portion of the page, it is presented as the
    primary focus of the question. The chunks still provide supporting evidence.
    Returns an empty string when no text is selected so the placeholder is
    silently omitted from the prompt.
    """
    if not selected_text or not selected_text.strip():
        return ""
    return (
        "SELECTED TEXT (user's annotation — treat as primary focus):\n"
        "---\n"
        f"{selected_text.strip()}\n"
        "---\n"
        "The user has highlighted the text above on the page. Focus your answer on "
        "this selection first, then use the chunks below for supporting context and "
        "broader evidence."
    )


def _build_answer_format_guidance(question_type: str) -> str:
    """Return the formatting instruction block for the given question type.

    Broad questions (summarise, key points, overview) get a mandatory rich
    structure with bold headings and bullet points. Contextual questions get
    a lighter, prose-friendly set of guidelines.
    """
    if question_type == "broad":
        return BROAD_ANSWER_FORMAT_GUIDANCE
    return CONTEXTUAL_ANSWER_FORMAT_GUIDANCE


def _build_language_requirement(language_code: Optional[str]) -> str:
    """Build the language instruction block to inject into answer prompts.

    Mirrors the pattern used in open_ai.py generate_contextual_answer.
    When no language_code is given, instructs the LLM to match the page
    content language. The citation-marker carve-out is always included so
    the LLM never translates chunkIds.
    """
    if language_code:
        language_name = get_language_name(language_code)
        if language_name:
            return (
                f"CRITICAL LANGUAGE REQUIREMENT:\n"
                f"- Write your answer prose STRICTLY in {language_name} ({language_code.upper()})\n"
                f"- Your answer MUST be in {language_name} ONLY\n"
                f"- Do NOT use any other language for the answer text - ONLY {language_name}\n"
                f"- This is MANDATORY and NON-NEGOTIABLE\n"
                f"- EXCEPTION: Citation markers [[cite:chunkId]] must be kept exactly as-is; "
                f"do not translate chunkIds or alter the marker format in any way"
            )
        else:
            return (
                f"CRITICAL LANGUAGE REQUIREMENT:\n"
                f"- Write your answer prose STRICTLY in the language specified by code: {language_code.upper()}\n"
                f"- Your answer MUST be in this language ONLY\n"
                f"- Do NOT use any other language\n"
                f"- This is MANDATORY and NON-NEGOTIABLE\n"
                f"- EXCEPTION: Citation markers [[cite:chunkId]] must be kept exactly as-is; "
                f"do not translate chunkIds or alter the marker format in any way"
            )
    else:
        return (
            "LANGUAGE:\n"
            "- Respond in the same language as the webpage content provided in the chunks below\n"
            "- Do NOT default to English unless the content itself is in English\n"
            "- Citation markers [[cite:chunkId]] must be kept exactly as-is; "
            "do not translate chunkIds or alter the marker format in any way"
        )


# ---------------------------------------------------------------------------
# Citation enrichment
# ---------------------------------------------------------------------------

def _enrich_citation_entry(chunk_id: str, chunks_by_id: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return enriched citation dict for a single chunkId, or None if not found."""
    if chunk_id not in chunks_by_id:
        logger.debug("Cited chunkId not found in request chunks — skipping", chunk_id=chunk_id)
        return None
    chunk = chunks_by_id[chunk_id]
    metadata = chunk.get("metadata", {})
    return {
        "chunkId": chunk_id,
        "text": chunk["text"],
        "startXPath": metadata.get("startXPath", ""),
        "endXPath": metadata.get("endXPath", ""),
        "startOffset": metadata.get("startOffset", 0),
        "endOffset": metadata.get("endOffset", 0),
        "cssSelector": metadata.get("cssSelector", ""),
        "textSnippetStart": metadata.get("textSnippetStart", ""),
        "textSnippetEnd": metadata.get("textSnippetEnd", ""),
    }


# ---------------------------------------------------------------------------
# Incremental citation-marker parser
# ---------------------------------------------------------------------------

_CITE_PREFIX = "[[cite:"
_CITE_PREFIX_LEN = len(_CITE_PREFIX)

# All prefixes of _CITE_PREFIX that a buffer tail could match (longest first)
_PARTIAL_PREFIXES: List[str] = [_CITE_PREFIX[:n] for n in range(_CITE_PREFIX_LEN, 0, -1)]


class CitationStreamParser:
    """Stateful incremental parser that detects [[cite:chunkId(s)]] markers in a
    token stream.

    Call ``feed(token)`` for each incoming token and ``flush()`` at end of stream.
    Both return a list of event dicts:

    - ``{"type": "text",     "text": "..."}``
    - ``{"type": "citation", "chunk_ids": ["id1", "id2"]}``

    The caller is responsible for translating these into SSE events.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._in_marker = False   # True once we confirmed [[cite: prefix

    # ------------------------------------------------------------------
    def feed(self, token: str) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        self._buffer += token

        while self._buffer:
            if self._in_marker:
                # Waiting for the closing ]]
                close_idx = self._buffer.find("]]")
                if close_idx != -1:
                    # Extract everything between [[cite: and ]]
                    raw_ids = self._buffer[:close_idx]          # e.g. "chunk1,chunk2"
                    self._buffer = self._buffer[close_idx + 2:]
                    self._in_marker = False
                    chunk_ids = [cid.strip() for cid in raw_ids.split(",") if cid.strip()]
                    if chunk_ids:
                        events.append({"type": "citation", "chunk_ids": chunk_ids})
                    # Continue scanning rest of buffer
                else:
                    # Closing ]] not yet received — wait for more tokens
                    break

            else:
                # Look for [[cite: anywhere in the buffer
                start_idx = self._buffer.find(_CITE_PREFIX)
                if start_idx == 0:
                    # Strip the prefix and enter marker mode
                    self._buffer = self._buffer[_CITE_PREFIX_LEN:]
                    self._in_marker = True
                elif start_idx > 0:
                    # Emit text before the marker, then re-loop
                    events.append({"type": "text", "text": self._buffer[:start_idx]})
                    self._buffer = self._buffer[start_idx:]
                    self._in_marker = True
                    self._buffer = self._buffer[_CITE_PREFIX_LEN:]
                else:
                    # No complete [[cite: found; check if buffer *ends with* a
                    # partial prefix that could grow into one on the next token.
                    safe_end = len(self._buffer)
                    for partial in _PARTIAL_PREFIXES:
                        if self._buffer.endswith(partial):
                            safe_end = len(self._buffer) - len(partial)
                            break
                    if safe_end > 0:
                        events.append({"type": "text", "text": self._buffer[:safe_end]})
                        self._buffer = self._buffer[safe_end:]
                    # If safe_end == 0 the whole buffer is a potential partial prefix;
                    # hold it and wait for the next token.
                    break

        return events

    # ------------------------------------------------------------------
    def flush(self) -> List[Dict[str, Any]]:
        """Drain any remaining buffered text at end of stream."""
        events: List[Dict[str, Any]] = []
        if self._buffer:
            events.append({"type": "text", "text": self._buffer})
            self._buffer = ""
        self._in_marker = False
        return events


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

async def classify_question(
    question: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Tuple[str, str]:
    """Classify a user question into 'greeting', 'broad', or 'contextual'.

    Returns a tuple of (question_type, reply). 'reply' is only non-empty for
    greeting-type messages.

    Raises ValueError if the LLM returns malformed or unexpected JSON.
    """
    client = _get_async_openai()

    messages = [{"role": "system", "content": CLASSIFY_SYSTEM_PROMPT}]

    if conversation_history:
        for msg in conversation_history[-6:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": question})

    logger.info("Classifying webpage chat question", question_preview=question[:80])

    response = await client.chat.completions.create(
        model=settings.gpt4o_mini_model,
        messages=messages,
        max_tokens=200,
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content.strip()
    logger.debug("Classification LLM raw response", raw=raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Classification LLM returned non-JSON", raw=raw, error=str(exc))
        raise ValueError("classification_failed") from exc

    question_type = parsed.get("type", "")
    if question_type not in VALID_QUESTION_TYPES:
        logger.warning(
            "Classification LLM returned unexpected type",
            raw_type=question_type,
            raw=raw,
        )
        raise ValueError("classification_failed")

    reply = parsed.get("reply", "") or ""
    logger.info("Question classified", question_type=question_type)
    return question_type, reply


# ---------------------------------------------------------------------------
# Answer generation — windowed path
# ---------------------------------------------------------------------------

async def _answer_windowed(
    question: str,
    chunks: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, str]]],
    language_code: Optional[str] = None,
    selected_text: Optional[str] = None,
    question_type: str = "contextual",
) -> Tuple[str, List[str]]:
    """Process chunks in sequential windows; synthesise into final answer."""
    client = _get_async_openai()
    windows = _split_into_windows(chunks)
    language_requirement = _build_language_requirement(language_code)
    selected_text_context = _build_selected_text_context(selected_text)
    answer_format_guidance = _build_answer_format_guidance(question_type)
    logger.info(
        "Long page detected — using windowed LLM calls",
        total_chunks=len(chunks),
        window_count=len(windows),
    )

    partial_answers: List[str] = []
    all_cited_ids: List[str] = []

    for idx, window in enumerate(windows):
        chunks_context = _build_chunks_context(window)
        system_content = PARTIAL_ANSWER_SYSTEM_PROMPT.format(
            chunks_context=chunks_context,
            language_requirement=language_requirement,
            selected_text_context=selected_text_context,
            answer_format_guidance=answer_format_guidance,
        )

        logger.info("Processing window", window_index=idx + 1, total=len(windows), chunk_count=len(window))

        response = await client.chat.completions.create(
            model=settings.rag_llm_model,
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": question},
            ],
            max_tokens=settings.rag_max_tokens,
            temperature=settings.rag_llm_temperature,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content.strip()
        try:
            parsed = json.loads(raw)
            partial_answer = parsed.get("answer", "")
            cited_ids = parsed.get("citedChunkIds", [])
        except json.JSONDecodeError:
            logger.warning("Partial answer LLM returned non-JSON, skipping window", window_index=idx + 1)
            partial_answer = ""
            cited_ids = []

        if partial_answer:
            partial_answers.append(partial_answer)
        all_cited_ids.extend(cited_ids)

    if not partial_answers:
        return "I could not find relevant information on this page to answer your question.", []

    if len(partial_answers) == 1:
        deduplicated_ids = list(dict.fromkeys(all_cited_ids))
        return partial_answers[0], deduplicated_ids

    partial_answers_text = "\n\n---\n\n".join(
        f"Partial answer {i + 1}:\n{p}" for i, p in enumerate(partial_answers)
    )
    synthesis_content = SYNTHESIS_SYSTEM_PROMPT.format(
        partial_answers=partial_answers_text,
        question=question,
        language_requirement=language_requirement,
        answer_format_guidance=answer_format_guidance,
    )

    logger.info("Synthesising partial answers", partial_count=len(partial_answers))

    synth_response = await client.chat.completions.create(
        model=settings.rag_llm_model,
        messages=[
            {"role": "system", "content": synthesis_content},
            {"role": "user", "content": question},
        ],
        max_tokens=settings.rag_max_tokens,
        temperature=settings.rag_llm_temperature,
        response_format={"type": "json_object"},
    )

    raw = synth_response.choices[0].message.content.strip()
    try:
        parsed = json.loads(raw)
        final_answer = parsed.get("answer", "")
        final_cited_ids = list(dict.fromkeys(parsed.get("citedChunkIds", all_cited_ids)))
    except json.JSONDecodeError:
        logger.warning("Synthesis LLM returned non-JSON — concatenating partial answers")
        final_answer = "\n\n".join(partial_answers)
        final_cited_ids = list(dict.fromkeys(all_cited_ids))

    return final_answer, final_cited_ids


# ---------------------------------------------------------------------------
# Shared SSE helper — converts CitationStreamParser events to SSE strings
# ---------------------------------------------------------------------------

def _parser_events_to_sse(
    events: List[Dict[str, Any]],
    chunks_by_id: Dict[str, Dict[str, Any]],
    state: Dict[str, Any],
) -> List[str]:
    """Convert a list of CitationStreamParser events into SSE data strings.

    ``state`` is a mutable dict with keys:
    - ``accumulated``:    str  — clean prose accumulated so far (with [N] substitutes)
    - ``citation_count``: int  — number of citation markers emitted so far
    """
    sse_lines: List[str] = []
    for ev in events:
        if ev["type"] == "text":
            state["accumulated"] += ev["text"]
            sse_lines.append(json.dumps({
                "type": "chunk",
                "text": ev["text"],
                "accumulated": state["accumulated"],
            }))
        elif ev["type"] == "citation":
            state["citation_count"] += 1
            n = state["citation_count"]
            state["accumulated"] += f"[{n}]"
            enriched = [
                entry
                for cid in ev["chunk_ids"]
                for entry in [_enrich_citation_entry(cid, chunks_by_id)]
                if entry is not None
            ]
            sse_lines.append(json.dumps({
                "type": "inline_citation",
                "citationNumber": n,
                "chunkIds": ev["chunk_ids"],
                "citations": enriched,
            }))
    return sse_lines


# ---------------------------------------------------------------------------
# Main streaming entry point
# ---------------------------------------------------------------------------

async def answer_question_stream(
    question: str,
    question_type: str,
    page_url: str,
    page_title: Optional[str],
    chunks: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, str]]] = None,
    language_code: Optional[str] = None,
    selected_text: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted events.

    Stream format:
    - chunk events:           data: {"type": "chunk", "text": "...", "accumulated": "..."}
    - inline_citation events: data: {"type": "inline_citation", "citationNumber": N,
                                     "chunkIds": [...], "citations": [{...}]}
    - possible_questions:     data: {"type": "possible_questions", "possibleQuestions": [...]}
    - Done marker:            data: [DONE]

    On error: data: {"type": "error", "error_code": "...", "error_message": "..."}
    """
    chunks_by_id: Dict[str, Dict[str, Any]] = {c["chunkId"]: c for c in chunks}
    total_tokens = _estimate_tokens(chunks)

    logger.info(
        "Webpage chat answer requested",
        question_type=question_type,
        page_url=page_url,
        chunk_count=len(chunks),
        estimated_tokens=total_tokens,
        language_code=language_code,
        has_selected_text=bool(selected_text),
    )

    try:
        parser = CitationStreamParser()
        state: Dict[str, Any] = {"accumulated": "", "citation_count": 0}

        if total_tokens > MAX_CONTEXT_TOKENS:
            answer, _ = await _answer_windowed(
                question, chunks, conversation_history, language_code, selected_text, question_type
            )
            chunk_size = 20
            for i in range(0, len(answer), chunk_size):
                for sse in _parser_events_to_sse(parser.feed(answer[i : i + chunk_size]), chunks_by_id, state):
                    yield f"data: {sse}\n\n"
        else:
            client = _get_async_openai()

            chunks_context = _build_chunks_context(chunks)
            history_str = _build_conversation_history(conversation_history)
            language_requirement = _build_language_requirement(language_code)
            selected_text_context = _build_selected_text_context(selected_text)
            answer_format_guidance = _build_answer_format_guidance(question_type)

            system_content = ANSWER_SYSTEM_PROMPT.format(
                chunks_context=chunks_context,
                conversation_history=history_str,
                language_requirement=language_requirement,
                selected_text_context=selected_text_context,
                answer_format_guidance=answer_format_guidance,
            )

            stream = await client.chat.completions.create(
                model=settings.rag_llm_model,
                messages=[
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": question},
                ],
                max_tokens=settings.rag_max_tokens,
                temperature=settings.rag_llm_temperature,
                stream=True,
            )

            async for event in stream:
                if event.choices and event.choices[0].delta.content:
                    for sse in _parser_events_to_sse(parser.feed(event.choices[0].delta.content), chunks_by_id, state):
                        yield f"data: {sse}\n\n"

        for sse in _parser_events_to_sse(parser.flush(), chunks_by_id, state):
            yield f"data: {sse}\n\n"

        answer_for_history = state["accumulated"]

        possible_questions: List[str] = []
        try:
            updated_history = list(conversation_history or []) + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer_for_history},
            ]
            possible_questions = await openai_service.generate_recommended_questions(
                question, updated_history, None, language_code
            )
        except Exception as exc:
            logger.error(
                "Failed to generate possible questions for /answer, continuing without them",
                error=str(exc),
            )

        logger.info(
            "Webpage chat answer complete",
            citation_count=state["citation_count"],
            questions_count=len(possible_questions),
        )

        yield f"data: {json.dumps({'type': 'possible_questions', 'possibleQuestions': possible_questions})}\n\n"
        yield "data: [DONE]\n\n"

    except ValueError as exc:
        logger.warning("Webpage chat answer value error", error=str(exc))
        yield f"data: {json.dumps({'type': 'error', 'error_code': 'ANSWER_FAILED', 'error_message': 'Failed to generate answer'})}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:
        logger.error("Unexpected error in answer_question_stream", error=str(exc))
        yield f"data: {json.dumps({'type': 'error', 'error_code': 'INTERNAL_ERROR', 'error_message': 'An unexpected error occurred'})}\n\n"
        yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Image-augmented answer streaming
# ---------------------------------------------------------------------------

async def answer_with_image_stream(
    question: str,
    question_type: str,
    page_url: str,
    page_title: Optional[str],
    image_data: bytes,
    image_format: str,
    chunks: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, str]]] = None,
    language_code: Optional[str] = None,
    selected_text: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE events for an image-augmented webpage chat answer.

    The LLM receives both the image (as a vision message) and the text chunks.
    The image is the primary source; chunks provide supporting text evidence with
    [[cite:chunkId]] citation markers.

    SSE event contract is identical to answer_question_stream:
    - chunk events:           data: {"type": "chunk", "text": "...", "accumulated": "..."}
    - inline_citation events: data: {"type": "inline_citation", "citationNumber": N,
                                     "chunkIds": [...], "citations": [{...}]}
    - possible_questions:     data: {"type": "possible_questions", "possibleQuestions": [...]}
    - Done marker:            data: [DONE]
    """
    chunks_by_id: Dict[str, Dict[str, Any]] = {c["chunkId"]: c for c in chunks}

    logger.info(
        "Webpage chat image answer requested",
        question_type=question_type,
        page_url=page_url,
        chunk_count=len(chunks),
        image_format=image_format,
        image_bytes=len(image_data),
        language_code=language_code,
        has_selected_text=bool(selected_text),
    )

    try:
        client = _get_async_openai()

        chunks_context = _build_chunks_context(chunks)
        history_str = _build_conversation_history(conversation_history)
        language_requirement = _build_language_requirement(language_code)
        selected_text_context = _build_selected_text_context(selected_text)
        answer_format_guidance = _build_answer_format_guidance(question_type)

        system_content = ANSWER_WITH_IMAGE_SYSTEM_PROMPT.format(
            chunks_context=chunks_context,
            conversation_history=history_str,
            language_requirement=language_requirement,
            selected_text_context=selected_text_context,
            answer_format_guidance=answer_format_guidance,
        )

        base64_image = base64.b64encode(image_data).decode("utf-8")

        # Build the messages list. The user message contains both the question text
        # and the image as a vision content block.
        messages = [
            {"role": "system", "content": system_content},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{image_format};base64,{base64_image}",
                            "detail": "high",
                        },
                    },
                ],
            },
        ]

        stream = await client.chat.completions.create(
            model=settings.gpt4o_model,
            messages=messages,
            max_tokens=settings.rag_max_tokens,
            temperature=settings.rag_llm_temperature,
            stream=True,
        )

        parser = CitationStreamParser()
        state: Dict[str, Any] = {"accumulated": "", "citation_count": 0}

        async for event in stream:
            if event.choices and event.choices[0].delta.content:
                for sse in _parser_events_to_sse(parser.feed(event.choices[0].delta.content), chunks_by_id, state):
                    yield f"data: {sse}\n\n"

        for sse in _parser_events_to_sse(parser.flush(), chunks_by_id, state):
            yield f"data: {sse}\n\n"

        answer_for_history = state["accumulated"]

        possible_questions: List[str] = []
        try:
            updated_history = list(conversation_history or []) + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer_for_history},
            ]
            possible_questions = await openai_service.generate_recommended_questions(
                question, updated_history, None, language_code
            )
        except Exception as exc:
            logger.error(
                "Failed to generate possible questions for /answer-with-image, continuing without them",
                error=str(exc),
            )

        logger.info(
            "Webpage chat image answer complete",
            citation_count=state["citation_count"],
            questions_count=len(possible_questions),
        )

        yield f"data: {json.dumps({'type': 'possible_questions', 'possibleQuestions': possible_questions})}\n\n"
        yield "data: [DONE]\n\n"

    except Exception as exc:
        logger.error("Unexpected error in answer_with_image_stream", error=str(exc))
        yield f"data: {json.dumps({'type': 'error', 'error_code': 'INTERNAL_ERROR', 'error_message': 'An unexpected error occurred'})}\n\n"
        yield "data: [DONE]\n\n"
