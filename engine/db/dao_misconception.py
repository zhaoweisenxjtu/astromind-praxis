"""DAO for misconceptions table.

迷思概念记录 — 直存 SQLite（文字少，无需文件存储）。
"""

import json
from typing import Optional

from .database import get_connection, row_to_dict, rows_to_dicts


def add_misconception(
    user_id: int,
    node_id: int,
    misconception: str,
    correction: str = "",
    category: str = "",
    interaction_id: Optional[int] = None,
) -> dict:
    """Add a misconception record. Returns the created record."""
    conn = get_connection()
    try:
        # Check duplicate: same user+node+misconception text → increment count
        existing = conn.execute(
            "SELECT id, encounter_count FROM misconceptions "
            "WHERE user_id=? AND node_id=? AND misconception=?",
            (user_id, node_id, misconception),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE misconceptions SET encounter_count = encounter_count + 1, "
                "last_encountered_at = datetime('now','localtime') "
                "WHERE id = ?",
                (existing["id"],),
            )
            conn.commit()
            return get_misconception(existing["id"])

        cur = conn.execute(
            """INSERT INTO misconceptions
               (user_id, node_id, interaction_id, misconception, correction, category)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, node_id, interaction_id, misconception, correction, category or None),
        )
        conn.commit()
        return get_misconception(cur.lastrowid)
    finally:
        conn.close()


def get_misconception(misconception_id: int) -> Optional[dict]:
    """Get a single misconception by ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM misconceptions WHERE id = ?",
            (misconception_id,),
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_misconceptions(
    user_id: int,
    node_id: Optional[int] = None,
    unresolved_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """List misconceptions for a user."""
    conn = get_connection()
    try:
        parts = ["SELECT * FROM misconceptions WHERE user_id = ?"]
        params = [user_id]

        if node_id:
            parts.append("AND node_id = ?")
            params.append(node_id)
        if unresolved_only:
            parts.append("AND is_resolved = 0")

        parts.append("ORDER BY is_resolved ASC, encounter_count DESC, created_at DESC")
        parts.append("LIMIT ?")
        params.append(limit)

        rows = conn.execute(" ".join(parts), params).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def resolve_misconception(misconception_id: int) -> Optional[dict]:
    """Mark a misconception as resolved."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE misconceptions SET is_resolved = 1, resolved_at = datetime('now','localtime') "
            "WHERE id = ?",
            (misconception_id,),
        )
        conn.commit()
        return get_misconception(misconception_id)
    finally:
        conn.close()


def get_misconception_stats(user_id: int) -> dict:
    """Get misconception statistics for a user."""
    conn = get_connection()
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM misconceptions WHERE user_id = ?",
            (user_id,),
        ).fetchone()["c"]

        unresolved = conn.execute(
            "SELECT COUNT(*) AS c FROM misconceptions WHERE user_id = ? AND is_resolved = 0",
            (user_id,),
        ).fetchone()["c"]

        by_category = {}
        rows = conn.execute(
            "SELECT category, COUNT(*) AS c FROM misconceptions "
            "WHERE user_id = ? AND category IS NOT NULL GROUP BY category",
            (user_id,),
        ).fetchall()
        for r in rows:
            by_category[r["category"]] = r["c"]

        top_nodes = []
        rows = conn.execute(
            "SELECT node_id, COUNT(*) AS c FROM misconceptions "
            "WHERE user_id = ? GROUP BY node_id ORDER BY c DESC LIMIT 5",
            (user_id,),
        ).fetchall()
        for r in rows:
            top_nodes.append({"node_id": r["node_id"], "count": r["c"]})

        return {
            "total": total,
            "unresolved": unresolved,
            "resolved": total - unresolved,
            "by_category": by_category,
            "top_nodes": top_nodes,
        }
    finally:
        conn.close()
