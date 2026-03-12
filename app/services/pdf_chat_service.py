"""RAG pipeline for PDF chat: retrieve, rerank, prompt, stream."""

import json
from typing import List, Dict, Any, Optional, AsyncGenerator

import numpy as np
from flashrank import Ranker, RerankRequest
from openai import AsyncOpenAI
import structlog

from app.config import settings
from app.services.embedding_service import aembed_query
from app.database.pg_connection import get_pg_connection, release_pg_connection

logger = structlog.get_logger()

_reranker: Optional[Ranker] = None
_async_openai: Optional[AsyncOpenAI] = None


def _get_reranker() -> Ranker:
    global _reranker
    if _reranker is None:
        _reranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank")
    return _reranker


def _get_async_openai() -> AsyncOpenAI:
    global _async_openai
    if _async_openai is None:
        _async_openai = AsyncOpenAI(api_key=settings.openai_api_key)
    return _async_openai


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve_relevant_chunks(
    preprocess_id: str,
    query_embedding: List[float],
    top_k: Optional[int] = None,
    ef_search: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Retrieve chunks from pgvector filtered by preprocess_id, ordered by cosine similarity."""
    top_k = top_k or settings.rag_retrieval_top_k
    ef_search = ef_search or settings.rag_ef_search

    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL hnsw.ef_search = %s", (ef_search,))
            cur.execute(
                """
                SELECT id, chunk_sequence, page_number, content, token_count,
                       embedding <=> %s::vector AS distance
                FROM pdf_content_embedding
                WHERE pdf_content_preprocess_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, preprocess_id, query_embedding, top_k),
            )
            rows = cur.fetchall()
        conn.commit()

        chunks = []
        for row in rows:
            chunks.append({
                "id": str(row[0]),
                "chunk_sequence": row[1],
                "page_number": row[2],
                "content": row[3],
                "token_count": row[4],
                "distance": float(row[5]),
            })
        return chunks
    finally:
        release_pg_connection(conn)


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------

def rerank_chunks(
    query: str,
    chunks: List[Dict[str, Any]],
    top_k: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Rerank retrieved chunks using FlashRank cross-encoder."""
    top_k = top_k or settings.rag_rerank_top_k
    if not chunks:
        return []

    ranker = _get_reranker()
    passages = [
        {"id": str(i), "text": c["content"], "meta": c}
        for i, c in enumerate(chunks)
    ]
    rerank_request = RerankRequest(query=query, passages=passages)
    results = ranker.rerank(rerank_request)

    reranked: List[Dict[str, Any]] = []
    for r in results[:top_k]:
        chunk = r["meta"]
        chunk["rerank_score"] = float(r["score"])
        reranked.append(chunk)

    return reranked


# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a precise, citation-driven PDF assistant. Your task is to answer questions about a PDF document using ONLY the provided context chunks.

## STRICT RULES

1. **Ground every claim**: Only state facts present in the provided context. Always answer using whatever relevant information is available, even if the content is brief. Only say "I don't have enough information in the document to answer this" when the provided context contains absolutely nothing relevant to the question.
2. **Cite your sources**: For every factual statement, include a citation in the format [chunk_sequence:page_number]. If page_number is unknown, use [chunk_sequence].
3. **Never hallucinate**: Do NOT invent information, statistics, or claims not present in the context. Stick strictly to what the context provides, but do provide a thorough answer from it.
4. **Ask for clarification**: If the user's question is ambiguous or could be interpreted in multiple ways, ask a brief clarifying question instead of guessing.
5. **Selected text**: When the user provides selected text from the PDF, treat it as the primary focus but also use other context chunks for supporting evidence and broader context.
6. **Conversation continuity**: Refer to previous messages when relevant for follow-up questions.
7. **Be concise and structured**: Use bullet points, numbered lists, or short paragraphs. Avoid unnecessary verbosity.
8. **Maximize usefulness**: When asked to summarize or explain a section, extract and present all relevant details from the context. A short source section still deserves a complete answer covering everything it contains.

## CONTEXT CHUNKS
{context}

## PREVIOUS CONVERSATION
{chat_history}
"""

USER_PROMPT_WITH_SELECTION = """The user has selected the following text from the PDF:
---
{selected_text}
---

Question: {question}"""

USER_PROMPT_WITHOUT_SELECTION = """Question: {question}"""


def build_rag_prompt(
    question: str,
    chunks: List[Dict[str, Any]],
    chat_history: Optional[List[Dict[str, str]]] = None,
    selected_text: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Build the messages list for the LLM call."""
    context_parts = []
    for c in chunks:
        page_label = f"page {c['page_number']}" if c.get("page_number") else "page unknown"
        context_parts.append(
            f"[Chunk {c['chunk_sequence']}, {page_label}]\n{c['content']}"
        )
    context_str = "\n\n---\n\n".join(context_parts) if context_parts else "(No context available)"

    history_str = ""
    if chat_history:
        for msg in chat_history[-10:]:
            role = msg.get("who", msg.get("role", "user"))
            content = msg.get("chat", msg.get("content", ""))
            label = "User" if role.upper() in ("USER", "user") else "Assistant"
            history_str += f"{label}: {content}\n"
    history_str = history_str.strip() or "(No previous messages)"

    system_msg = SYSTEM_PROMPT.format(context=context_str, chat_history=history_str)

    if selected_text and selected_text.strip():
        user_msg = USER_PROMPT_WITH_SELECTION.format(
            selected_text=selected_text.strip(),
            question=question,
        )
    else:
        user_msg = USER_PROMPT_WITHOUT_SELECTION.format(question=question)

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


# ---------------------------------------------------------------------------
# Citation extraction
# ---------------------------------------------------------------------------

def format_citations(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert reranked chunks into citation objects for the API response."""
    return [
        {
            "chunkSequence": c["chunk_sequence"],
            "pageNumber": c.get("page_number"),
            "content": c["content"],
        }
        for c in chunks
    ]


# ---------------------------------------------------------------------------
# Full pipeline (async streaming)
# ---------------------------------------------------------------------------

async def ask_pdf_stream(
    question: str,
    preprocess_id: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    selected_text: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Full RAG pipeline that yields SSE-formatted data events.

    Flow:  embed query -> retrieve -> rerank -> build prompt -> stream LLM -> yield chunks
    After the stream completes, yields a final 'complete' event with citations.
    """
    # 1. Embed the question
    query_embedding = await aembed_query(question)

    # 2. Retrieve
    raw_chunks = retrieve_relevant_chunks(preprocess_id, query_embedding)
    logger.info("Retrieved chunks", count=len(raw_chunks), preprocess_id=preprocess_id)

    # 3. Rerank
    reranked = rerank_chunks(question, raw_chunks)
    logger.info("Reranked chunks", count=len(reranked))

    # 4. Build prompt
    messages = build_rag_prompt(question, reranked, chat_history, selected_text)

    # 5. Stream LLM response
    client = _get_async_openai()
    accumulated = ""

    stream = await client.chat.completions.create(
        model=settings.rag_llm_model,
        messages=messages,
        max_tokens=settings.rag_max_tokens,
        temperature=settings.rag_llm_temperature,
        stream=True,
    )

    async for event in stream:
        if event.choices and event.choices[0].delta.content:
            chunk_text = event.choices[0].delta.content
            accumulated += chunk_text
            chunk_data = {"chunk": chunk_text, "accumulated": accumulated}
            yield f"data: {json.dumps(chunk_data)}\n\n"

    # 6. Final event with citations and recommended follow-ups
    citations = format_citations(reranked)

    possible_questions: List[str] = []
    try:
        followup_resp = await client.chat.completions.create(
            model=settings.rag_llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Based on the conversation so far about a PDF document, suggest exactly 3 "
                        "concise follow-up questions the user might ask next. Return ONLY a JSON array "
                        "of strings, nothing else."
                    ),
                },
                {"role": "user", "content": f"User asked: {question}\nAssistant answered: {accumulated[:500]}"},
            ],
            max_tokens=200,
            temperature=0.5,
        )
        raw = followup_resp.choices[0].message.content.strip()
        possible_questions = json.loads(raw) if raw.startswith("[") else []
    except Exception as e:
        logger.warning("Failed to generate follow-up questions", error=str(e))

    final_data = {
        "type": "complete",
        "answer": accumulated,
        "citations": citations,
        "possibleQuestions": possible_questions,
    }
    yield f"data: {json.dumps(final_data)}\n\n"
    yield "data: [DONE]\n\n"
