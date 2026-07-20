"""Review History DAO: CRUD for review_history table."""

from datetime import date
from .database import get_connection, row_to_dict, rows_to_dicts


def create_review(node_id: int, quality: int, ef_after: float,
                  interval_after: int) -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO review_history (node_id, quality, ef_after, interval_after) "
            "VALUES (?, ?, ?, ?)",
            (node_id, quality, ef_after, interval_after),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM review_history WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_reviews(node_id: int | None = None, limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        if node_id:
            rows = conn.execute(
                "SELECT * FROM review_history WHERE node_id = ? "
                "ORDER BY reviewed_at DESC LIMIT ?",
                (node_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM review_history ORDER BY reviewed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def get_review_stats(track_id: int | None = None) -> dict:
    """Get aggregate review statistics."""
    conn = get_connection()
    try:
        if track_id:
            row = conn.execute(
                "SELECT "
                "  COUNT(r.id) AS total_reviews, "
                "  ROUND(AVG(r.quality), 2) AS avg_quality, "
                "  ROUND(AVG(r.ef_after), 2) AS avg_ef, "
                "  COUNT(CASE WHEN r.quality >= 3 THEN 1 END) * 1.0 / COUNT(*) AS pass_rate "
                "FROM review_history r "
                "JOIN knowledge_nodes n ON r.node_id = n.id "
                "WHERE n.track_id = ?",
                (track_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT "
                "  COUNT(r.id) AS total_reviews, "
                "  ROUND(AVG(r.quality), 2) AS avg_quality, "
                "  ROUND(AVG(r.ef_after), 2) AS avg_ef, "
                "  COUNT(CASE WHEN r.quality >= 3 THEN 1 END) * 1.0 / COUNT(*) AS pass_rate "
                "FROM review_history r"
            ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def get_today_due_count(track_id: int | None = None) -> int:
    today = date.today().isoformat()
    conn = get_connection()
    try:
        if track_id:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM knowledge_nodes "
                "WHERE track_id = ? AND next_review IS NOT NULL AND next_review <= ? "
                "AND status = 'active'",
                (track_id, today),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM knowledge_nodes "
                "WHERE next_review IS NOT NULL AND next_review <= ? AND status = 'active'",
                (today,),
            ).fetchone()
        return row["cnt"]
    finally:
        conn.close()
