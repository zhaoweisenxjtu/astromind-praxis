"""Track DAO: CRUD for tracks table."""

import json
from .database import get_connection, row_to_dict, rows_to_dicts


def create_track(user_id: int, name: str, target_type: str,
                 priority: int = 3, config: dict | None = None) -> dict:
    ctx = json.dumps(config or {}, ensure_ascii=False)
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tracks (user_id, name, target_type, priority, workflow_context) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, name, target_type, priority, ctx),
        )
        conn.commit()
        return get_track(cur.lastrowid)
    finally:
        conn.close()


def get_track(track_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_tracks(user_id: int | None = None, status: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        query = "SELECT * FROM tracks"
        params = []
        conditions = []
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY priority DESC, created_at"
        rows = conn.execute(query, params).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def update_track(track_id: int, **kwargs) -> dict | None:
    allowed = {"name", "target_type", "status", "priority", "current_state", "workflow_context"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_track(track_id)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    set_clause += ", updated_at = date('now')"
    values = list(updates.values())

    conn = get_connection()
    try:
        conn.execute(f"UPDATE tracks SET {set_clause} WHERE id = ?", (*values, track_id))
        conn.commit()
        return get_track(track_id)
    finally:
        conn.close()


def delete_track(track_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
