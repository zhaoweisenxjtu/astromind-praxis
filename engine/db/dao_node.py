"""Knowledge Node DAO: CRUD for knowledge_nodes table."""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from .database import get_connection, row_to_dict, rows_to_dicts


def add_node(track_id: int, name: str, description: str = "",
             parent_id: int | None = None, importance: int = 3,
             current_level: int = 1) -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO knowledge_nodes (track_id, parent_id, name, description, importance, current_level) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (track_id, parent_id, name, description, importance, current_level),
        )
        conn.commit()
        return get_node(cur.lastrowid)
    finally:
        conn.close()


def get_node(node_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM knowledge_nodes WHERE id = ?", (node_id,)).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_nodes(track_id: int | None = None, status: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        query = "SELECT * FROM knowledge_nodes"
        params = []
        conditions = []
        if track_id is not None:
            conditions.append("track_id = ?")
            params.append(track_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY importance DESC, created_at"
        rows = conn.execute(query, params).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def update_node(node_id: int, **kwargs) -> dict | None:
    allowed = {"name", "description", "importance", "current_level", "status",
               "ef", "interval", "repetitions", "next_review", "parent_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_node(node_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    set_clause += ", updated_at = date('now')"
    values = list(updates.values())

    conn = get_connection()
    try:
        conn.execute(f"UPDATE knowledge_nodes SET {set_clause} WHERE id = ?", (*values, node_id))
        conn.commit()
        return get_node(node_id)
    finally:
        conn.close()


def delete_node(node_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM knowledge_nodes WHERE id = ?", (node_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_due_nodes(track_id: int | None = None, user_id: int | None = None) -> list[dict]:
    """Get nodes where next_review <= today."""
    today = date.today().isoformat()
    conn = get_connection()
    try:
        if track_id:
            rows = conn.execute(
                "SELECT n.* FROM knowledge_nodes n "
                "WHERE n.track_id = ? AND n.next_review IS NOT NULL AND n.next_review <= ? "
                "AND n.status = 'active' ORDER BY n.next_review",
                (track_id, today),
            ).fetchall()
        elif user_id:
            rows = conn.execute(
                "SELECT n.* FROM knowledge_nodes n "
                "JOIN tracks t ON n.track_id = t.id "
                "WHERE t.user_id = ? AND n.next_review IS NOT NULL AND n.next_review <= ? "
                "AND n.status = 'active' AND t.status = 'active' "
                "ORDER BY n.next_review",
                (user_id, today),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT n.* FROM knowledge_nodes n "
                "WHERE n.next_review IS NOT NULL AND n.next_review <= ? "
                "AND n.status = 'active' ORDER BY n.next_review",
                (today,),
            ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def add_dependency(node_id: int, depends_on_id: int, relation_type: str = "prerequisite") -> bool:
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO node_dependencies (node_id, depends_on_id, relation_type) "
            "VALUES (?, ?, ?)",
            (node_id, depends_on_id, relation_type),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_dependencies(node_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT d.*, n.name as depends_on_name FROM node_dependencies d "
            "JOIN knowledge_nodes n ON d.depends_on_id = n.id "
            "WHERE d.node_id = ?",
            (node_id,),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Content Management
# ──────────────────────────────────────────────


def update_node_content(node_id: int, content: str, source_url: str = "",
                        source_title: str = "", quality_score: int = 0,
                        tags: list | None = None) -> dict | None:
    """Update the content and metadata of a knowledge node."""
    now = datetime.now().isoformat()
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE knowledge_nodes SET content=?, content_format='markdown', "
            "source_url=?, source_title=?, quality_score=?, tags=?, "
            "cached_at=?, updated_at=date('now') WHERE id=?",
            (content, source_url, source_title, quality_score,
             tags_json, now, node_id),
        )
        conn.commit()
        return get_node(node_id)
    finally:
        conn.close()


def import_node_content(node_id: int, file_path: str) -> dict | None:
    """Import content from a Markdown/text file into a knowledge node."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")
    content = path.read_text(encoding="utf-8")
    return update_node_content(node_id, content,
                               source_title=path.name,
                               quality_score=3)


def update_quality_score(node_id: int, score: int) -> dict | None:
    """Update the quality score of a node's content (0-5)."""
    if not (0 <= score <= 5):
        raise ValueError("quality_score must be 0-5")
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE knowledge_nodes SET quality_score=?, updated_at=date('now') WHERE id=?",
            (score, node_id),
        )
        conn.commit()
        return get_node(node_id)
    finally:
        conn.close()


def list_low_quality_nodes(track_id: int | None = None,
                           threshold: int = 2) -> list[dict]:
    """List nodes whose content quality is below threshold (no content or low quality)."""
    conn = get_connection()
    try:
        query = ("SELECT * FROM knowledge_nodes "
                 "WHERE (content IS NULL OR content = '' OR quality_score < ? "
                 "OR quality_score IS NULL)")
        params = [threshold]
        if track_id is not None:
            query += " AND track_id = ?"
            params.append(track_id)
        query += " ORDER BY importance DESC"
        rows = conn.execute(query, params).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Full-Text Search
# ──────────────────────────────────────────────


def search_nodes(keyword: str, track_id: int | None = None,
                 limit: int = 20) -> list[dict]:
    """Full-text search across knowledge node names and content.

    Uses FTS5 if available, falls back to LIKE search.
    """
    conn = get_connection()
    try:
        fts_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_fts'"
        ).fetchone()

        if fts_exists:
            # FTS5 query: use MATCH, escape special chars
            safe = _fts_escape(keyword)
            query = """
                SELECT n.* FROM knowledge_fts f
                JOIN knowledge_nodes n ON f.rowid = n.id
                WHERE knowledge_fts MATCH ?
            """
            params = [safe]
            if track_id is not None:
                query += " AND n.track_id = ?"
                params.append(track_id)
            query += " ORDER BY rank LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
        else:
            # Fallback to LIKE search on name + content
            like = f"%{keyword}%"
            query = ("SELECT * FROM knowledge_nodes "
                     "WHERE name LIKE ? OR content LIKE ? OR description LIKE ?")
            params = [like, like, like]
            if track_id is not None:
                query += " AND track_id = ?"
                params.append(track_id)
            query += " ORDER BY importance DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def _fts_escape(keyword: str) -> str:
    """Escape special FTS5 characters and convert to prefix query."""
    # FTS5 special chars: ^ * " ( ) : + -
    for ch in '^"():+-':
        keyword = keyword.replace(ch, " ")
    # Replace * for safety (wildcard at end)
    keyword = keyword.replace("*", " ")
    # Collapse multiple spaces
    parts = [w for w in keyword.split() if w]
    # Create prefix query: each word followed by *
    return " AND ".join(f"{p}*" for p in parts) if parts else keyword
