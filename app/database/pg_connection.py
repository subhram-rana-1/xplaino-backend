"""PostgreSQL + pgvector connection pool for vector embeddings."""

from typing import Optional
import psycopg2
import psycopg2.pool
import psycopg2.extras
from pgvector.psycopg2 import register_vector
import structlog

from app.config import settings

logger = structlog.get_logger()

_pg_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None


def get_pg_pool() -> psycopg2.pool.ThreadedConnectionPool:
    """Lazy-initialise and return the PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is None or _pg_pool.closed:
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=settings.pg_host,
            port=settings.pg_port,
            dbname=settings.pg_db_name,
            user=settings.pg_user,
            password=settings.pg_password,
        )
        logger.info("PostgreSQL connection pool created")
    return _pg_pool


def get_pg_connection():
    """Get a connection from the pool with pgvector types registered."""
    pool = get_pg_pool()
    conn = pool.getconn()
    register_vector(conn)
    return conn


def release_pg_connection(conn):
    """Return a connection to the pool."""
    pool = get_pg_pool()
    pool.putconn(conn)


def get_pg_db():
    """FastAPI dependency that yields a pgvector-enabled connection and returns it to the pool."""
    conn = get_pg_connection()
    try:
        yield conn
    finally:
        release_pg_connection(conn)


def close_pg_pool():
    """Close all connections in the pool (call on app shutdown)."""
    global _pg_pool
    if _pg_pool is not None and not _pg_pool.closed:
        _pg_pool.closeall()
        logger.info("PostgreSQL connection pool closed")
        _pg_pool = None
