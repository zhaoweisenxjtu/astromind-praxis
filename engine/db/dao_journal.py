"""Learning Journal DAO: CRUD for learning_journal table."""

import json
from .database import get_connection, row_to_dict, rows_to_dicts


def create_journal(user_id: int, date_str: str,
                   focus_minutes: int = 0,
                   diffuse_minutes: int = 0,
                   topics: list | None = None,
                   methods: list | None = None,
                   track_minutes: dict | None = None,
                   highlights: str = "",
                   struggles: str = "",
                   tomorrow_plan: str = "") -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT OR REPLACE INTO learning_journal "
            "(user_id, date, focus_minutes, diffuse_minutes, topics, methods, track_minutes, highlights, struggles, tomorrow_plan) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, date_str, focus_minutes, diffuse_minutes,
             json.dumps(topics or [], ensure_ascii=False),
             json.dumps(methods or [], ensure_ascii=False),
             json.dumps(track_minutes or {}, ensure_ascii=False),
             highlights, struggles, tomorrow_plan),
        )
        conn.commit()
        return get_journal(cur.lastrowid)
    finally:
        conn.close()


def get_journal(journal_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM learning_journal WHERE id = ?", (journal_id,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def get_journal_by_date(user_id: int, date_str: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM learning_journal WHERE user_id = ? AND date = ?",
            (user_id, date_str),
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_journals(user_id: int, from_date: str | None = None,
                  to_date: str | None = None, limit: int = 30) -> list[dict]:
    conn = get_connection()
    try:
        query = "SELECT * FROM learning_journal WHERE user_id = ?"
        params = [user_id]
        if from_date:
            query += " AND date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND date <= ?"
            params.append(to_date)
        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()
