"""MariaDB CRUD operations for pdf_content_preprocess, pdf_chat_session, and pdf_chat tables."""

from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
import structlog

logger = structlog.get_logger()


def _ts(val: Any) -> str:
    return val.isoformat() if isinstance(val, datetime) else str(val)


# ---------------------------------------------------------------------------
# pdf_content_preprocess
# ---------------------------------------------------------------------------

def upsert_pdf_content_preprocess(db: Session, pdf_id: str) -> Dict[str, Any]:
    """Return existing record or create a new PENDING one. Returns the row dict."""
    existing = get_pdf_content_preprocess_by_pdf_id(db, pdf_id)
    if existing:
        if existing["status"] == "FAILED":
            db.execute(
                text("""
                    UPDATE pdf_content_preprocess
                    SET status = 'PENDING', error_message = NULL
                    WHERE id = :id
                """),
                {"id": existing["id"]},
            )
            db.commit()
            return get_pdf_content_preprocess_by_pdf_id(db, pdf_id)
        return existing

    db.execute(
        text("""
            INSERT INTO pdf_content_preprocess (pdf_id)
            VALUES (:pdf_id)
        """),
        {"pdf_id": pdf_id},
    )
    db.commit()
    return get_pdf_content_preprocess_by_pdf_id(db, pdf_id)


def get_pdf_content_preprocess_by_id(db: Session, preprocess_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text("""
            SELECT id, pdf_id, status, error_message, created_at, updated_at
            FROM pdf_content_preprocess
            WHERE id = :id
        """),
        {"id": preprocess_id},
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "pdf_id": row[1],
        "status": row[2],
        "error_message": row[3],
        "created_at": _ts(row[4]),
        "updated_at": _ts(row[5]),
    }


def get_pdf_content_preprocess_by_pdf_id(db: Session, pdf_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text("""
            SELECT id, pdf_id, status, error_message, created_at, updated_at
            FROM pdf_content_preprocess
            WHERE pdf_id = :pdf_id
        """),
        {"pdf_id": pdf_id},
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "pdf_id": row[1],
        "status": row[2],
        "error_message": row[3],
        "created_at": _ts(row[4]),
        "updated_at": _ts(row[5]),
    }


def update_preprocess_status(
    db: Session,
    preprocess_id: str,
    status: str,
    error_message: Optional[str] = None,
):
    db.execute(
        text("""
            UPDATE pdf_content_preprocess
            SET status = :status, error_message = :error_message
            WHERE id = :id
        """),
        {"id": preprocess_id, "status": status, "error_message": error_message},
    )
    db.commit()


# ---------------------------------------------------------------------------
# pdf_chat_session
# ---------------------------------------------------------------------------

def create_pdf_chat_session(
    db: Session,
    pdf_content_preprocess_id: str,
    user_id: Optional[str],
    unauthenticated_user_id: Optional[str],
    name: str = "Untitled",
) -> Dict[str, Any]:
    db.execute(
        text("""
            INSERT INTO pdf_chat_session
                (name, pdf_content_preprocess_id, user_id, unauthenticated_user_id)
            VALUES (:name, :preprocess_id, :user_id, :unauth_id)
        """),
        {
            "name": name,
            "preprocess_id": pdf_content_preprocess_id,
            "user_id": user_id,
            "unauth_id": unauthenticated_user_id,
        },
    )
    db.commit()

    row = db.execute(
        text("""
            SELECT id, name, pdf_content_preprocess_id, user_id, unauthenticated_user_id,
                   created_at, updated_at
            FROM pdf_chat_session
            WHERE pdf_content_preprocess_id = :preprocess_id
              AND (user_id = :user_id OR unauthenticated_user_id = :unauth_id)
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {
            "preprocess_id": pdf_content_preprocess_id,
            "user_id": user_id,
            "unauth_id": unauthenticated_user_id,
        },
    ).fetchone()
    return _session_row_to_dict(row)


def get_pdf_chat_session_by_id(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text("""
            SELECT id, name, pdf_content_preprocess_id, user_id, unauthenticated_user_id,
                   created_at, updated_at
            FROM pdf_chat_session
            WHERE id = :id
        """),
        {"id": session_id},
    ).fetchone()
    if not row:
        return None
    return _session_row_to_dict(row)


def rename_pdf_chat_session(db: Session, session_id: str, name: str) -> bool:
    result = db.execute(
        text("UPDATE pdf_chat_session SET name = :name WHERE id = :id"),
        {"id": session_id, "name": name},
    )
    db.commit()
    return result.rowcount > 0


def delete_pdf_chat_session(db: Session, session_id: str) -> bool:
    result = db.execute(
        text("DELETE FROM pdf_chat_session WHERE id = :id"),
        {"id": session_id},
    )
    db.commit()
    return result.rowcount > 0


def clear_pdf_chat_session(db: Session, session_id: str) -> int:
    """Delete all chats in a session. Returns the number of rows deleted."""
    result = db.execute(
        text("DELETE FROM pdf_chat WHERE pdf_chat_session_id = :session_id"),
        {"session_id": session_id},
    )
    db.commit()
    return result.rowcount


def get_all_pdf_chat_sessions(
    db: Session,
    pdf_content_preprocess_id: str,
    user_id: Optional[str] = None,
    unauthenticated_user_id: Optional[str] = None,
    include_all_shared: bool = False,
) -> List[Dict[str, Any]]:
    """Return chat sessions for a preprocessed PDF.

    - If ``include_all_shared`` is True the query returns **all** sessions
      attached to this preprocessed PDF (for owner / shared users who should
      see every contributor's chats).
    - Otherwise it filters to the caller's sessions only.
    """
    if include_all_shared:
        rows = db.execute(
            text("""
                SELECT s.id, s.name, s.pdf_content_preprocess_id,
                       s.user_id, s.unauthenticated_user_id,
                       s.created_at, s.updated_at,
                       COALESCE(g.email, g.given_name, 'Unknown') AS owner_label
                FROM pdf_chat_session s
                LEFT JOIN google_user_auth_info g ON g.user_id = s.user_id
                WHERE s.pdf_content_preprocess_id = :preprocess_id
                ORDER BY s.created_at ASC
            """),
            {"preprocess_id": pdf_content_preprocess_id},
        ).fetchall()
        return [_session_row_to_dict_with_owner(r) for r in rows]

    if user_id:
        rows = db.execute(
            text("""
                SELECT id, name, pdf_content_preprocess_id, user_id,
                       unauthenticated_user_id, created_at, updated_at
                FROM pdf_chat_session
                WHERE pdf_content_preprocess_id = :preprocess_id
                  AND user_id = :user_id
                ORDER BY created_at ASC
            """),
            {"preprocess_id": pdf_content_preprocess_id, "user_id": user_id},
        ).fetchall()
    else:
        rows = db.execute(
            text("""
                SELECT id, name, pdf_content_preprocess_id, user_id,
                       unauthenticated_user_id, created_at, updated_at
                FROM pdf_chat_session
                WHERE pdf_content_preprocess_id = :preprocess_id
                  AND unauthenticated_user_id = :unauth_id
                ORDER BY created_at ASC
            """),
            {"preprocess_id": pdf_content_preprocess_id, "unauth_id": unauthenticated_user_id},
        ).fetchall()

    return [_session_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# pdf_chat
# ---------------------------------------------------------------------------

def create_pdf_chat(
    db: Session,
    pdf_chat_session_id: str,
    who: str,
    chat: str,
    citations: Optional[List[Dict[str, Any]]] = None,
    selected_text: Optional[str] = None,
) -> Dict[str, Any]:
    citations_json = json.dumps(citations) if citations else None
    db.execute(
        text("""
            INSERT INTO pdf_chat (pdf_chat_session_id, who, chat, selected_text, citations)
            VALUES (:session_id, :who, :chat, :selected_text, :citations)
        """),
        {
            "session_id": pdf_chat_session_id,
            "who": who,
            "chat": chat,
            "selected_text": selected_text or None,
            "citations": citations_json,
        },
    )
    db.commit()

    row = db.execute(
        text("""
            SELECT id, pdf_chat_session_id, who, chat, selected_text, citations, created_at
            FROM pdf_chat
            WHERE pdf_chat_session_id = :session_id
            ORDER BY created_at DESC
            LIMIT 1
        """),
        {"session_id": pdf_chat_session_id},
    ).fetchone()
    return _chat_row_to_dict(row)


def get_chats_by_session_id(
    db: Session,
    session_id: str,
    limit: int = 50,
    offset: int = 0,
    order: str = "ASC",
) -> Dict[str, Any]:
    total_row = db.execute(
        text("SELECT COUNT(*) FROM pdf_chat WHERE pdf_chat_session_id = :sid"),
        {"sid": session_id},
    ).fetchone()
    total = total_row[0] if total_row else 0

    direction = "DESC" if order.upper() == "DESC" else "ASC"
    rows = db.execute(
        text(f"""
            SELECT id, pdf_chat_session_id, who, chat, selected_text, citations, created_at
            FROM pdf_chat
            WHERE pdf_chat_session_id = :sid
            ORDER BY created_at {direction}
            LIMIT :limit OFFSET :offset
        """),
        {"sid": session_id, "limit": limit, "offset": offset},
    ).fetchall()

    return {
        "messages": [_chat_row_to_dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# Row mappers
# ---------------------------------------------------------------------------

def _session_row_to_dict(row) -> Dict[str, Any]:
    return {
        "id": row[0],
        "name": row[1],
        "pdf_content_preprocess_id": row[2],
        "user_id": row[3],
        "unauthenticated_user_id": row[4],
        "created_at": _ts(row[5]),
        "updated_at": _ts(row[6]),
    }


def _session_row_to_dict_with_owner(row) -> Dict[str, Any]:
    d = _session_row_to_dict(row)
    d["owner_label"] = row[7] if len(row) > 7 else None
    return d


def _chat_row_to_dict(row) -> Dict[str, Any]:
    citations_raw = row[5]
    if isinstance(citations_raw, str):
        try:
            citations_raw = json.loads(citations_raw)
        except (json.JSONDecodeError, TypeError):
            citations_raw = None

    return {
        "id": row[0],
        "pdf_chat_session_id": row[1],
        "who": row[2],
        "chat": row[3],
        "selected_text": row[4],
        "citations": citations_raw,
        "created_at": _ts(row[6]),
    }
