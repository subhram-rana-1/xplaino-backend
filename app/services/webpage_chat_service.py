"""Service layer for the webpage chat feature.

Handles question classification, structured answer generation with citations,
long-page windowed processing, and citation enrichment.
"""

import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from openai import AsyncOpenAI
import structlog

from app.config import settings
from app.prompts.webpage_chat_prompts import (
    ANSWER_SYSTEM_PROMPT,
    BROAD_ANSWER_FORMAT_GUIDANCE,
    CLASSIFY_SYSTEM_PROMPT,
    CONTEXTUAL_ANSWER_FORMAT_GUIDANCE,
    PARTIAL_ANSWER_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
)
from app.services.llm.open_ai import get_language_name

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

def _enrich_citations(
    cited_chunk_ids: List[str],
    chunks_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a citationMap by looking up each cited chunkId from the request chunks."""
    citation_map: Dict[str, Any] = {}
    for chunk_id in cited_chunk_ids:
        if chunk_id in chunks_by_id:
            chunk = chunks_by_id[chunk_id]
            metadata = chunk.get("metadata", {})
            citation_map[chunk_id] = {
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
        else:
            logger.debug(
                "Cited chunkId not found in request chunks — skipping",
                chunk_id=chunk_id,
            )
    return citation_map


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
# Answer generation — single-window path
# ---------------------------------------------------------------------------

async def _answer_single_window(
    question: str,
    chunks: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, str]]],
    language_code: Optional[str] = None,
    selected_text: Optional[str] = None,
    question_type: str = "contextual",
) -> Tuple[str, List[str]]:
    """Call LLM once for all chunks; return (answer_text, cited_chunk_ids)."""
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
    logger.debug("Answer LLM raw response (single window)")

    parsed = json.loads(raw)
    answer = parsed.get("answer", "")
    cited_chunk_ids = list(dict.fromkeys(parsed.get("citedChunkIds", [])))
    return answer, cited_chunk_ids


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
    - Token events:  data: {"chunk": "...", "accumulated": "..."}
    - Citations event (final): data: {"type": "citations", "citationMap": {...}}
    - Done marker: data: [DONE]

    On error:  data: {"type": "error", "error_code": "...", "error_message": "..."}
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
        if total_tokens > MAX_CONTEXT_TOKENS:
            answer, cited_chunk_ids = await _answer_windowed(
                question, chunks, conversation_history, language_code, selected_text, question_type
            )

            # Stream the final answer character-by-character in chunks to keep the
            # SSE contract identical to the single-window streaming path.
            accumulated = ""
            chunk_size = 20
            for i in range(0, len(answer), chunk_size):
                text_piece = answer[i : i + chunk_size]
                accumulated += text_piece
                yield f"data: {json.dumps({'chunk': text_piece, 'accumulated': accumulated})}\n\n"
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

            accumulated = ""
            async for event in stream:
                if event.choices and event.choices[0].delta.content:
                    text_piece = event.choices[0].delta.content
                    accumulated += text_piece
                    yield f"data: {json.dumps({'chunk': text_piece, 'accumulated': accumulated})}\n\n"

            # Parse the accumulated JSON response to extract citedChunkIds.
            # The LLM streams its full JSON blob; we parse it after completion.
            try:
                parsed = json.loads(accumulated)
                answer = parsed.get("answer", accumulated)
                cited_chunk_ids = list(dict.fromkeys(parsed.get("citedChunkIds", [])))
            except json.JSONDecodeError:
                logger.warning("Answer LLM streamed non-JSON response — proceeding without citations")
                answer = accumulated
                cited_chunk_ids = []

        citation_map = _enrich_citations(cited_chunk_ids, chunks_by_id)
        logger.info(
            "Webpage chat answer complete",
            cited_count=len(cited_chunk_ids),
            enriched_count=len(citation_map),
        )

        yield f"data: {json.dumps({'type': 'citations', 'citationMap': citation_map})}\n\n"
        yield "data: [DONE]\n\n"

    except ValueError as exc:
        logger.warning("Webpage chat answer value error", error=str(exc))
        yield f"data: {json.dumps({'type': 'error', 'error_code': 'ANSWER_FAILED', 'error_message': 'Failed to generate answer'})}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:
        logger.error("Unexpected error in answer_question_stream", error=str(exc))
        yield f"data: {json.dumps({'type': 'error', 'error_code': 'INTERNAL_ERROR', 'error_message': 'An unexpected error occurred'})}\n\n"
        yield "data: [DONE]\n\n"
