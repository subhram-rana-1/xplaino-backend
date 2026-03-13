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


def retrieve_broad_chunks(
    preprocess_id: str,
    max_chunks: Optional[int] = None,
    token_budget: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Retrieve chunks in document order for broad/holistic questions, capped by a token budget."""
    max_chunks = max_chunks or settings.rag_broad_max_chunks
    token_budget = token_budget or settings.rag_broad_token_budget

    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, chunk_sequence, page_number, content, token_count
                FROM pdf_content_embedding
                WHERE pdf_content_preprocess_id = %s
                ORDER BY chunk_sequence ASC
                LIMIT %s
                """,
                (preprocess_id, max_chunks),
            )
            rows = cur.fetchall()
        conn.commit()

        chunks = []
        total_tokens = 0
        for row in rows:
            tok = row[4] or 0
            if total_tokens + tok > token_budget:
                break
            chunks.append({
                "id": str(row[0]),
                "chunk_sequence": row[1],
                "page_number": row[2],
                "content": row[3],
                "token_count": tok,
                "distance": 0.0,
            })
            total_tokens += tok
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

QUERY_CLASSIFIER_PROMPT = """Classify the user's message about a PDF document into exactly one category.

Reply with a SINGLE word from this list: "specific", "broad", "comparative", "definition", "follow_up", or "conversational".

- "specific": Targets a particular fact, section, argument, event, or detail in the document.
  Examples: "What does section 3 say about pricing?", "What happened in Q2?", "What is the author's conclusion?"

- "broad": Asks for a holistic view, summary, overview, general takeaway, or structured analysis of the whole document (or a large portion of it). This includes multi-part analytical prompts that require reading the entire document.
  Examples: "What are the key takeaways?", "Summarize this document", "What is this about?", "List the main themes.", "Provide key findings, methodology, and implications.", "Analyze this paper: strengths, weaknesses, and conclusions.", "Extract the main arguments and supporting evidence."

- "comparative": Asks to compare, contrast, or find differences/similarities between two or more concepts, entities, or sections within the document.
  Examples: "What is the difference between X and Y?", "Compare approach A and B", "How does section 2 contrast with section 4?"

- "definition": Asks for the meaning, definition, or explanation of a specific term, concept, or acronym as used in this document.
  Examples: "What is RAG?", "Define churn rate as used here", "What does the author mean by 'convergence'?"

- "follow_up": A question that references or continues from the immediately preceding answer, or is too vague to answer without prior context.
  Examples: "Can you elaborate?", "Tell me more about the second point", "What did you mean by that?", "Give me an example of this."

- "conversational": A greeting, small talk, expression of thanks, or anything completely unrelated to the document.
  Examples: "hey", "hello", "hey bro", "thanks", "who are you?", "ok cool", "got it."

Question: {question}"""

COMPARATIVE_SYSTEM_PROMPT = """You are a precise, citation-driven PDF assistant. Your task is to compare and contrast concepts, sections, or entities mentioned in the user's question using ONLY the provided context chunks.

## STRICT RULES

1. **Structure your comparison**: Use a clear format — a table, side-by-side bullet points, or clearly labeled sections (e.g. "Concept A:" then "Concept B:"). Never mix them in running prose.
2. **Cite both sides**: Every comparative claim must be cited with [chunk_sequence:page_number]. If page_number is unknown, use [chunk_sequence].
3. **Ground every claim**: Only state facts present in the provided context. Only say "I don't have enough information in the document to answer this" when the context contains absolutely nothing relevant.
4. **Never hallucinate**: Do NOT invent comparisons not supported by the text.
5. **Be comprehensive**: Cover all meaningful differences AND similarities present in the context.
6. **Conversation continuity**: Refer to previous messages when relevant for follow-up questions.

## CONTEXT CHUNKS
{context}

## PREVIOUS CONVERSATION
{chat_history}
"""

DEFINITION_SYSTEM_PROMPT = """You are a precise, citation-driven PDF assistant. Your task is to define and explain a term or concept as it is used in this specific document, using ONLY the provided context chunks.

## STRICT RULES

1. **Lead with the definition**: Start with a clear, concise definition as the document uses or implies it.
2. **Expand with context**: After the definition, explain the role, significance, or usage of the term within this document.
3. **Cite your sources**: Include a citation [chunk_sequence:page_number] for the definition and each supporting statement.
4. **Document-specific**: If the term has a common general meaning but is used differently here, explicitly note the difference.
5. **Ground every claim**: Only state facts present in the provided context.
6. **Never hallucinate**: Do NOT use outside knowledge. Stick strictly to what the context provides.
7. **Conversation continuity**: Refer to previous messages when relevant.

## CONTEXT CHUNKS
{context}

## PREVIOUS CONVERSATION
{chat_history}
"""


# ---------------------------------------------------------------------------
# Query intent classification
# ---------------------------------------------------------------------------

async def classify_query_intent(question: str) -> str:
    """Classify a user question as 'specific' or 'broad' using a fast LLM call."""
    client = _get_async_openai()
    try:
        response = await client.chat.completions.create(
            model=settings.rag_llm_model,
            messages=[
                {"role": "system", "content": QUERY_CLASSIFIER_PROMPT.format(question=question)},
            ],
            max_tokens=10,
            temperature=0.0,
        )
        intent = response.choices[0].message.content.strip().lower()
        if intent not in ("specific", "broad", "comparative", "definition", "follow_up", "conversational"):
            logger.warning("Unexpected classifier output, defaulting to specific", raw=intent)
            return "specific"
        return intent
    except Exception as e:
        logger.warning("Query classification failed, defaulting to specific", error=str(e))
        return "specific"


async def rewrite_follow_up_query(
    question: str,
    chat_history: Optional[List[Dict[str, str]]],
) -> str:
    """Rewrite a context-dependent follow-up question into a self-contained query for vector search.

    E.g. "Can you elaborate on that?" -> "Elaborate on the risk management framework discussed"
    Falls back to the original question on failure.
    """
    if not chat_history:
        return question

    history_parts = []
    for msg in chat_history[-6:]:
        role = msg.get("who", msg.get("role", "user"))
        content = msg.get("chat", msg.get("content", ""))
        label = "User" if role.upper() in ("USER", "user") else "Assistant"
        history_parts.append(f"{label}: {content}")
    history_str = "\n".join(history_parts)

    client = _get_async_openai()
    try:
        response = await client.chat.completions.create(
            model=settings.rag_llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a query rewriting assistant. Given a conversation history and a "
                        "follow-up question, rewrite the follow-up question into a single, fully "
                        "self-contained question that can be understood without the conversation history. "
                        "Preserve the user's intent. Return ONLY the rewritten question, nothing else."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Conversation history:\n{history_str}\n\nFollow-up question: {question}",
                },
            ],
            max_tokens=150,
            temperature=0.0,
        )
        rewritten = response.choices[0].message.content.strip()
        logger.info("Rewrote follow-up query", original=question[:80], rewritten=rewritten[:80])
        return rewritten or question
    except Exception as e:
        logger.warning("Follow-up query rewrite failed, using original", error=str(e))
        return question


# ---------------------------------------------------------------------------
# Session name generation
# ---------------------------------------------------------------------------

async def generate_session_name(question: str) -> str:
    """Generate a concise session name (max 5 words) from the user's question."""
    client = _get_async_openai()
    try:
        response = await client.chat.completions.create(
            model=settings.rag_llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate a short, descriptive title (maximum 5 words) for a chat session "
                        "based on the user's question below. Return ONLY the title — no quotes, "
                        "no punctuation, no explanation."
                    ),
                },
                {"role": "user", "content": question},
            ],
            max_tokens=20,
            temperature=0.5,
        )
        name = response.choices[0].message.content.strip().strip('"\'')
        words = name.split()
        if len(words) > 5:
            name = " ".join(words[:5])
        return name or question[:50]
    except Exception as e:
        logger.warning("Session name generation failed, using truncated question", error=str(e))
        return question[:50]


def build_conversational_prompt(
    question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """Build prompt for conversational/greeting messages — no PDF context needed."""
    history_str = ""
    if chat_history:
        for msg in chat_history[-10:]:
            role = msg.get("who", msg.get("role", "user"))
            content = msg.get("chat", msg.get("content", ""))
            label = "User" if role.upper() in ("USER", "user") else "Assistant"
            history_str += f"{label}: {content}\n"
    history_str = history_str.strip() or "(No previous messages)"

    system_msg = (
        "You are a friendly and helpful PDF assistant. The user has greeted you, made small talk, "
        "or sent a message unrelated to the document content. Respond warmly and briefly, "
        "and naturally invite them to ask any questions they have about the PDF document.\n\n"
        f"## PREVIOUS CONVERSATION\n{history_str}"
    )
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": question},
    ]


def build_rag_prompt(
    question: str,
    chunks: List[Dict[str, Any]],
    chat_history: Optional[List[Dict[str, str]]] = None,
    selected_text: Optional[str] = None,
    system_prompt: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Build the messages list for the LLM call.

    Pass ``system_prompt`` to override the default SYSTEM_PROMPT (e.g. for
    comparative or definition intents that need a different response structure).
    """
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

    active_prompt = system_prompt if system_prompt is not None else SYSTEM_PROMPT
    system_msg = active_prompt.format(context=context_str, chat_history=history_str)

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

    Flow:  classify intent -> retrieve (adaptive) -> build prompt -> stream LLM -> yield chunks
    After the stream completes, yields a final 'complete' event with citations.
    """
    # 1. Classify query intent to choose retrieval strategy
    intent = await classify_query_intent(question)
    logger.info("Query intent classified", intent=intent, question=question[:80])

    # 2. Retrieve context and build prompt using the appropriate strategy
    if intent == "conversational":
        reranked = []
        messages = build_conversational_prompt(question, chat_history)
        logger.info("Conversational path, skipping retrieval")

    elif intent == "broad":
        reranked = retrieve_broad_chunks(preprocess_id)
        logger.info("Broad retrieval", count=len(reranked), preprocess_id=preprocess_id)
        messages = build_rag_prompt(question, reranked, chat_history, selected_text)

    elif intent == "comparative":
        # Cast a wide net for both concepts: doubled top_k
        query_embedding = await aembed_query(question)
        raw_chunks = retrieve_relevant_chunks(
            preprocess_id, query_embedding, top_k=settings.rag_comparative_retrieval_top_k
        )
        logger.info("Comparative retrieval", count=len(raw_chunks), preprocess_id=preprocess_id)
        reranked = rerank_chunks(question, raw_chunks, top_k=settings.rag_comparative_rerank_top_k)
        logger.info("Comparative reranked", count=len(reranked))
        messages = build_rag_prompt(
            question, reranked, chat_history, selected_text,
            system_prompt=COMPARATIVE_SYSTEM_PROMPT,
        )

    elif intent == "definition":
        query_embedding = await aembed_query(question)
        raw_chunks = retrieve_relevant_chunks(preprocess_id, query_embedding)
        logger.info("Definition retrieval", count=len(raw_chunks), preprocess_id=preprocess_id)
        reranked = rerank_chunks(question, raw_chunks)
        logger.info("Definition reranked", count=len(reranked))

        top_score = reranked[0]["rerank_score"] if reranked else 0.0
        if top_score < settings.rag_rerank_score_threshold:
            logger.info(
                "Definition retrieval below relevance threshold, falling back to broad",
                top_score=top_score,
                threshold=settings.rag_rerank_score_threshold,
            )
            reranked = retrieve_broad_chunks(preprocess_id)

        messages = build_rag_prompt(
            question, reranked, chat_history, selected_text,
            system_prompt=DEFINITION_SYSTEM_PROMPT,
        )

    elif intent == "follow_up":
        # Rewrite the vague follow-up into a self-contained query before embedding
        rewritten_question = await rewrite_follow_up_query(question, chat_history)
        query_embedding = await aembed_query(rewritten_question)
        raw_chunks = retrieve_relevant_chunks(preprocess_id, query_embedding)
        logger.info("Follow-up retrieval", count=len(raw_chunks), preprocess_id=preprocess_id,
                    rewritten=rewritten_question[:80])
        reranked = rerank_chunks(rewritten_question, raw_chunks)
        logger.info("Follow-up reranked", count=len(reranked))
        # Use the original question in the user-facing prompt so the answer reads naturally
        messages = build_rag_prompt(question, reranked, chat_history, selected_text)

    else:  # "specific" (default)
        query_embedding = await aembed_query(question)
        raw_chunks = retrieve_relevant_chunks(preprocess_id, query_embedding)
        logger.info("Retrieved chunks", count=len(raw_chunks), preprocess_id=preprocess_id)
        reranked = rerank_chunks(question, raw_chunks)
        logger.info("Reranked chunks", count=len(reranked))

        top_score = reranked[0]["rerank_score"] if reranked else 0.0
        if top_score < settings.rag_rerank_score_threshold:
            logger.info(
                "Specific retrieval below relevance threshold, falling back to broad",
                top_score=top_score,
                threshold=settings.rag_rerank_score_threshold,
            )
            reranked = retrieve_broad_chunks(preprocess_id)

        messages = build_rag_prompt(question, reranked, chat_history, selected_text)

    # 3. Stream LLM response
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

    # 4. Final event with citations and recommended follow-ups
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
