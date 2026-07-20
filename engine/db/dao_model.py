"""Mental Model DAO: CRUD for mental_models table (L2)."""

import json
from datetime import datetime
from .database import get_connection, row_to_dict, rows_to_dicts


def insert_model(author_name: str, topic: str, title: str,
                 content_md: str, md_path: str,
                 evidence_count: int = 0, article_count: int = 0,
                 first_seen_at: str = None, triple_check: dict = None) -> int:
    conn = get_connection()
    try:
        tc_json = json.dumps(triple_check or {}, ensure_ascii=False)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            """INSERT INTO mental_models
               (author_name, topic, title, content_md, md_path,
                evidence_count, article_count, first_seen_at,
                last_updated_at, triple_check)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (author_name, topic, title, content_md, md_path,
             evidence_count, article_count, first_seen_at or now,
             now, tc_json),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_model(model_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM mental_models WHERE id = ?", (model_id,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def get_model_by_topic(author_name: str, topic: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM mental_models WHERE author_name = ? AND topic = ?",
            (author_name, topic),
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_models(author_name: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM mental_models WHERE author_name = ? ORDER BY evidence_count DESC",
            (author_name,),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def update_model(model_id: int, **kwargs):
    allowed = {"title", "content_md", "evidence_count", "article_count",
               "last_updated_at", "triple_check"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return

    if "triple_check" in updates and isinstance(updates["triple_check"], dict):
        updates["triple_check"] = json.dumps(updates["triple_check"], ensure_ascii=False)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if "last_updated_at" not in updates:
        updates["last_updated_at"] = now

    conn = get_connection()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [model_id]
        conn.execute(
            f"UPDATE mental_models SET {set_clause} WHERE id = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def count_models(author_name: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM mental_models WHERE author_name = ?",
            (author_name,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def model_exists(author_name: str, topic: str) -> bool:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM mental_models WHERE author_name = ? AND topic = ?",
            (author_name, topic),
        ).fetchone()
        return row is not None
    finally:
        conn.close()
