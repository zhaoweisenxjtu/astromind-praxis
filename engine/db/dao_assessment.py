"""Assessment Log DAO: CRUD for assessment_log table."""

import json
from .database import get_connection, row_to_dict, rows_to_dicts


def log_assessment(user_id: int, track_id: int, level_after: int,
                   node_id: int | None = None,
                   level_before: int | None = None,
                   methods: list | None = None,
                   duration_minutes: int = 0,
                   fake_signals: dict | None = None,
                   notes: str = "") -> dict:
    methods_json = json.dumps(methods or [], ensure_ascii=False)
    signals_json = json.dumps(fake_signals or {}, ensure_ascii=False)
    before = level_before if level_before is not None else 1

    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO assessment_log "
            "(user_id, track_id, node_id, level_before, level_after, methods, duration_minutes, fake_signals, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, track_id, node_id, before, level_after,
             methods_json, duration_minutes, signals_json, notes),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM assessment_log WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_assessments(track_id: int | None = None,
                     user_id: int | None = None,
                     limit: int = 20) -> list[dict]:
    conn = get_connection()
    try:
        query = "SELECT * FROM assessment_log"
        params = []
        conditions = []
        if track_id is not None:
            conditions.append("track_id = ?")
            params.append(track_id)
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def get_recent_assessments(track_id: int, limit: int = 5) -> list[dict]:
    return list_assessments(track_id=track_id, limit=limit)


def get_level_distribution(track_id: int) -> dict:
    """Get count of nodes at each level for a track."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT current_level, COUNT(*) AS cnt FROM knowledge_nodes "
            "WHERE track_id = ? AND status = 'active' "
            "GROUP BY current_level ORDER BY current_level",
            (track_id,),
        ).fetchall()
        dist = {str(row["current_level"]): row["cnt"] for row in rows}
        return dist
    finally:
        conn.close()
