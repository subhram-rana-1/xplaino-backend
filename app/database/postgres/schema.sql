-- PostgreSQL + pgvector schema for Caten vector embeddings
-- Run against a PostgreSQL 16+ database with the pgvector extension available.

CREATE EXTENSION IF NOT EXISTS vector;

-- PDF content embedding table (stores chunked text with vector embeddings)
CREATE TABLE IF NOT EXISTS pdf_content_embedding (
    id                         UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    pdf_content_preprocess_id  VARCHAR(36)   NOT NULL,
    chunk_sequence             INT           NOT NULL,
    page_number                INT           NULL,
    content                    TEXT          NOT NULL,
    token_count                INT           NOT NULL,
    embedding                  VECTOR(1536)  NOT NULL,
    created_at                 TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- B-tree index for filtered lookups (primary access path: filter by preprocess_id first)
CREATE INDEX IF NOT EXISTS idx_pce_preprocess_id
    ON pdf_content_embedding (pdf_content_preprocess_id);

-- Composite index for ordered chunk retrieval
CREATE INDEX IF NOT EXISTS idx_pce_preprocess_seq
    ON pdf_content_embedding (pdf_content_preprocess_id, chunk_sequence);

-- HNSW index for approximate nearest-neighbor search
-- m=16: balanced graph connectivity (default, good for 1536-dim)
-- ef_construction=200: high build quality for better recall at query time
CREATE INDEX IF NOT EXISTS idx_pce_hnsw
    ON pdf_content_embedding
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
