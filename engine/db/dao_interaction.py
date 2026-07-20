"""DAO for teaching_interactions table.

教学互动记录 — 元数据存 SQLite，全文内容存文件系统。
"""

import sqlite3
from datetime import datetime
from typing import Optional

from .database import get_connection, row_to_dict, rows_to_dicts


def create_interaction(
    session_id: str,
    user_id: int,
    track_id: int,
    node_id: int,
    interaction_type: str,
    method_used: str = "",
    level_before: int = 1,
    level_after: int = 1,
    quality_score: int = 0,
    duration_seconds: int = 0,
    file_path: str = "",
) -> dict:
    """Create a new teaching interaction record. Returns the created record."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO teaching_interactions
               (session_id, user_id, track_id, node_id, interaction_type,
                method_used, level_before, level_after, quality_score,
                duration_seconds, file_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, user_id, track_id, node_id, interaction_type,
             method_used, level_before, level_after, quality_score,
             duration_seconds, file_path),
        )
        conn.commit()
        return get_interaction(cur.lastrowid)
    finally:
        conn.close()


def get_interaction(interaction_id: int) -> Optional[dict]:
    """Get a single interaction by ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM teaching_interactions WHERE id = ?",
            (interaction_id,),
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_interactions(
    user_id: int,
    node_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List interactions for a user, optionally filtered by node."""
    conn = get_connection()
    try:
        if node_id:
            rows = conn.execute(
                """SELECT * FROM teaching_interactions
                   WHERE user_id = ? AND node_id = ?
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (user_id, node_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM teaching_interactions
                   WHERE user_id = ?
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (user_id, limit, offset),
            ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def list_by_session(session_id: str) -> list[dict]:
    """List all interactions in a session."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM teaching_interactions WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def update_interaction(
    interaction_id: int,
    **kwargs,
) -> Optional[dict]:
    """Update interaction fields. Returns updated record."""
    allowed = {
        "quality_score", "level_before", "level_after",
        "duration_seconds", "file_path",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_interaction(interaction_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [interaction_id]

    conn = get_connection()
    try:
        conn.execute(
            f"UPDATE teaching_interactions SET {set_clause} WHERE id = ?",
            params,
        )
        conn.commit()
        return get_interaction(interaction_id)
    finally:
        conn.close()


def delete_interaction(interaction_id: int) -> bool:
    """Delete an interaction. Returns True if deleted."""
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM teaching_interactions WHERE id = ?", (interaction_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
