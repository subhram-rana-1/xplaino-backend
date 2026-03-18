"""Celery task for PDF content preprocessing: extract, chunk, embed, store."""

import re
import numpy as np
import tiktoken
import structlog
from typing import List, Optional, Tuple

from app.services.celery_app import celery_app
from app.config import settings

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_mariadb_session():
    """Create a standalone MariaDB session for use inside Celery workers."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(settings.database_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    return Session()


def _get_pg_connection():
    """Create a standalone PostgreSQL connection for use inside Celery workers."""
    import psycopg2
    from pgvector.psycopg2 import register_vector

    conn = psycopg2.connect(
        host=settings.pg_host,
        port=settings.pg_port,
        dbname=settings.pg_db_name,
        user=settings.pg_user,
        password=settings.pg_password,
    )
    register_vector(conn)
    return conn


def _update_preprocess_status(db, preprocess_id: str, status: str, error_message: Optional[str] = None):
    from sqlalchemy import text

    db.execute(
        text("""
            UPDATE pdf_content_preprocess
            SET status = :status, error_message = :error_message
            WHERE id = :id
        """),
        {"id": preprocess_id, "status": status, "error_message": error_message},
    )
    db.commit()


def _get_s3_key_for_pdf(db, pdf_id: str) -> Optional[str]:
    """Resolve the S3 key for a PDF by looking up its file_upload record."""
    from sqlalchemy import text

    row = db.execute(
        text("""
            SELECT s3_key FROM file_upload
            WHERE entity_type = 'PDF' AND entity_id = :pdf_id
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"pdf_id": pdf_id},
    ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Semantic chunking
# ---------------------------------------------------------------------------

_ENCODING: Optional[tiktoken.Encoding] = None


def _get_encoding() -> tiktoken.Encoding:
    global _ENCODING
    if _ENCODING is None:
        _ENCODING = tiktoken.encoding_for_model("gpt-4o-mini")
    return _ENCODING


def _count_tokens(text: str) -> int:
    return len(_get_encoding().encode(text))


_BULLET_OR_HEADER_RE = re.compile(
    r'\n(?='
    r'[\u2022\u25cf\u25aa\u2023\-\*\u2013\u2014•●▪]'  # bullet markers
    r'|\d+[.\)]'                                         # numbered lists
    r'|[A-Z][A-Z ]{2,}'                                  # ALL-CAPS headings
    r')',
)

_MIN_SEGMENT_LEN = 20
_MIN_MERGED_LEN = 40


def _split_page_text(text: str) -> List[str]:
    """Split a single page's text into semantic segments.

    Handles both prose (split on sentence endings) and structured
    documents like CVs/forms (split on paragraph breaks, bullet markers,
    and section headers).  Very short fragments are merged with their
    neighbours so they don't become useless micro-chunks.
    """
    paragraphs = re.split(r'\n{2,}', text)

    segments: List[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        lines = _BULLET_OR_HEADER_RE.split(para)

        for line in lines:
            line = line.strip()
            if not line:
                continue
            sub = re.split(r'(?<=[.!?])\s+', line)
            for s in sub:
                s = s.strip()
                if s:
                    segments.append(s)

    if not segments:
        return [text.strip()] if text.strip() else []

    merged: List[str] = []
    buf = ""
    for i, seg in enumerate(segments):
        if buf:
            buf = buf + " " + seg
            if len(buf) >= _MIN_MERGED_LEN:
                merged.append(buf)
                buf = ""
        elif len(seg) < _MIN_SEGMENT_LEN and i < len(segments) - 1:
            buf = seg
        else:
            merged.append(seg)

    if buf:
        if merged:
            merged[-1] = merged[-1] + " " + buf
        else:
            merged.append(buf)

    return merged


def _split_into_sentences(
    page_texts: List[Tuple[int, str]],
) -> List[Tuple[int, str]]:
    """Split per-page text into tagged ``(page_number, segment)`` tuples.

    Each page is split independently so that no segment spans a page
    boundary.
    """
    result: List[Tuple[int, str]] = []
    for page_num, text in page_texts:
        for seg in _split_page_text(text):
            result.append((page_num, seg))
    return result


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def _semantic_chunk(
    tagged_sentences: List[Tuple[int, str]],
    sentence_embeddings: List[List[float]],
    max_tokens: int,
    similarity_threshold: float = 0.5,
) -> List[Tuple[int, str]]:
    """Merge adjacent sentences into chunks while they remain semantically
    similar, under the token limit, **and on the same page**.

    Returns a list of ``(page_number, chunk_text)`` tuples.  Chunks never
    span a page boundary.
    """
    if not tagged_sentences:
        return []

    chunks: List[Tuple[int, str]] = []
    current_page = tagged_sentences[0][0]
    current_chunk_sentences: List[str] = [tagged_sentences[0][1]]
    current_tokens = _count_tokens(tagged_sentences[0][1])

    for i in range(1, len(tagged_sentences)):
        page_num, sentence = tagged_sentences[i]
        sim = _cosine_similarity(sentence_embeddings[i - 1], sentence_embeddings[i])
        sentence_tokens = _count_tokens(sentence)

        same_page = page_num == current_page

        if same_page and sim >= similarity_threshold and (current_tokens + sentence_tokens) <= max_tokens:
            current_chunk_sentences.append(sentence)
            current_tokens += sentence_tokens
        else:
            chunks.append((current_page, " ".join(current_chunk_sentences)))
            current_chunk_sentences = [sentence]
            current_tokens = sentence_tokens
            current_page = page_num

    if current_chunk_sentences:
        chunks.append((current_page, " ".join(current_chunk_sentences)))

    return chunks


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    name="app.services.pdf_preprocess_task.preprocess_pdf",
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def preprocess_pdf(self, preprocess_id: str, pdf_id: str):
    """Download a PDF from S3, extract text, semantically chunk it, embed, and store in pgvector."""
    db = _get_mariadb_session()
    pg_conn = None

    try:
        _update_preprocess_status(db, preprocess_id, "IN_PROGRESS")

        # 0. Clean up stale embeddings from a previous failed run
        pg_conn = _get_pg_connection()
        with pg_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pdf_content_embedding WHERE pdf_content_preprocess_id = %s",
                (preprocess_id,),
            )
        pg_conn.commit()
        pg_conn.close()
        pg_conn = None

        # 1. Resolve S3 key
        s3_key = _get_s3_key_for_pdf(db, pdf_id)
        if not s3_key:
            raise ValueError(f"No S3 key found for pdf_id={pdf_id}")

        # 2. Download PDF from S3
        from app.services.s3_service import s3_service

        pdf_bytes = s3_service.download_object(s3_key)
        logger.info("Downloaded PDF", pdf_id=pdf_id, size_bytes=len(pdf_bytes))

        # 3. Extract plain text per page (proper word spacing for citation matching)
        from app.services.pdf_service import PdfService

        pdf_service = PdfService()
        page_texts = pdf_service.extract_plain_text_from_pdf(pdf_bytes)

        if not page_texts:
            raise ValueError("PDF text extraction produced empty content")

        total_chars = sum(len(t) for _, t in page_texts)
        logger.info("Extracted text", pdf_id=pdf_id, text_length=total_chars, pages=len(page_texts))

        # 4. Page-aware sentence splitting
        tagged_sentences = _split_into_sentences(page_texts)
        if not tagged_sentences:
            raise ValueError("No sentences extracted from PDF")

        # 5. Embed sentences for similarity-based merging
        from app.services.embedding_service import embed_texts

        sentence_embeddings = embed_texts([s for _, s in tagged_sentences])

        # 6. Page-aware semantic chunking (never merges across page boundaries)
        tagged_chunks = _semantic_chunk(
            tagged_sentences,
            sentence_embeddings,
            max_tokens=settings.rag_chunk_size,
            similarity_threshold=0.5,
        )
        logger.info("Semantic chunking complete", pdf_id=pdf_id, num_chunks=len(tagged_chunks))

        # 7. Embed final chunks
        chunk_embeddings = embed_texts([c for _, c in tagged_chunks])

        # 8. Prepare records (page_number is deterministic from the pipeline)
        records = []
        for seq, ((page_num, chunk_text), embedding) in enumerate(
            zip(tagged_chunks, chunk_embeddings)
        ):
            records.append(
                (
                    preprocess_id,
                    seq,
                    page_num,
                    chunk_text,
                    _count_tokens(chunk_text),
                    embedding,
                )
            )

        # 9. Bulk insert into PostgreSQL
        pg_conn = _get_pg_connection()
        with pg_conn.cursor() as cur:
            from psycopg2.extras import execute_values

            execute_values(
                cur,
                """
                INSERT INTO pdf_content_embedding
                    (pdf_content_preprocess_id, chunk_sequence, page_number, content, token_count, embedding)
                VALUES %s
                """,
                records,
                template="(%s, %s, %s, %s, %s, %s::vector)",
                page_size=500,
            )
        pg_conn.commit()
        logger.info("Stored embeddings in pgvector", pdf_id=pdf_id, count=len(records))

        # 10. Mark as completed
        _update_preprocess_status(db, preprocess_id, "COMPLETED")
        logger.info("PDF preprocessing completed", preprocess_id=preprocess_id, pdf_id=pdf_id)

    except Exception as exc:
        logger.error(
            "PDF preprocessing failed",
            preprocess_id=preprocess_id,
            pdf_id=pdf_id,
            error=str(exc),
        )
        try:
            _update_preprocess_status(db, preprocess_id, "FAILED", str(exc)[:2000])
        except Exception:
            pass

        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)
    finally:
        db.close()
        if pg_conn is not None:
            pg_conn.close()
