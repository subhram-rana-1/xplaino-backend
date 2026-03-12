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


def _split_into_sentences(text: str) -> List[str]:
    """Split text into sentences using regex heuristics."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def _semantic_chunk(
    sentences: List[str],
    sentence_embeddings: List[List[float]],
    max_tokens: int,
    similarity_threshold: float = 0.5,
) -> List[str]:
    """Merge adjacent sentences into chunks while they remain semantically similar
    and under the token limit.
    """
    if not sentences:
        return []

    chunks: List[str] = []
    current_chunk_sentences: List[str] = [sentences[0]]
    current_tokens = _count_tokens(sentences[0])

    for i in range(1, len(sentences)):
        sim = _cosine_similarity(sentence_embeddings[i - 1], sentence_embeddings[i])
        sentence_tokens = _count_tokens(sentences[i])

        if sim >= similarity_threshold and (current_tokens + sentence_tokens) <= max_tokens:
            current_chunk_sentences.append(sentences[i])
            current_tokens += sentence_tokens
        else:
            chunks.append(" ".join(current_chunk_sentences))
            current_chunk_sentences = [sentences[i]]
            current_tokens = sentence_tokens

    if current_chunk_sentences:
        chunks.append(" ".join(current_chunk_sentences))

    return chunks


def _detect_page_number(chunk_text: str, page_texts: List[Tuple[int, str]]) -> Optional[int]:
    """Best-effort page detection: return the page whose raw text most overlaps with the chunk."""
    if not page_texts:
        return None
    first_100 = chunk_text[:100]
    for page_num, page_text in page_texts:
        if first_100 in page_text:
            return page_num
    return None


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

        # 3. Extract text (reuse existing service)
        from app.services.pdf_service import PdfService

        pdf_service = PdfService()
        extracted = pdf_service.extract_text_from_pdf(pdf_bytes)

        if isinstance(extracted, dict):
            full_text = extracted.get("text", "") or extracted.get("markdown", "")
            page_texts: List[Tuple[int, str]] = []
            pages = extracted.get("pages", [])
            for idx, page in enumerate(pages):
                if isinstance(page, dict):
                    page_texts.append((idx + 1, page.get("text", "")))
                elif isinstance(page, str):
                    page_texts.append((idx + 1, page))
        else:
            full_text = str(extracted)
            page_texts = []

        if not full_text or not full_text.strip():
            raise ValueError("PDF text extraction produced empty content")

        logger.info("Extracted text", pdf_id=pdf_id, text_length=len(full_text))

        # 4. Sentence splitting
        sentences = _split_into_sentences(full_text)
        if not sentences:
            raise ValueError("No sentences extracted from PDF")

        # 5. Embed sentences for similarity-based merging
        from app.services.embedding_service import embed_texts

        sentence_embeddings = embed_texts(sentences)

        # 6. Semantic chunking
        chunks = _semantic_chunk(
            sentences,
            sentence_embeddings,
            max_tokens=settings.rag_chunk_size,
            similarity_threshold=0.5,
        )
        logger.info("Semantic chunking complete", pdf_id=pdf_id, num_chunks=len(chunks))

        # 7. Embed final chunks
        chunk_embeddings = embed_texts(chunks)

        # 8. Prepare records
        records = []
        for seq, (chunk_text, embedding) in enumerate(zip(chunks, chunk_embeddings)):
            page_num = _detect_page_number(chunk_text, page_texts)
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
