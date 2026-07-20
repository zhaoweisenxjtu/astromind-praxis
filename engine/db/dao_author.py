"""Author Profile DAO: CRUD for author_profiles table."""

from datetime import datetime
from .database import get_connection, row_to_dict, rows_to_dicts


def insert_profile(author_name: str, knowledge_base_path: str) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO author_profiles
               (author_name, knowledge_base_path)
               VALUES (?, ?)""",
            (author_name, knowledge_base_path),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_profile(author_name: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM author_profiles WHERE author_name = ?",
            (author_name,),
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_all_profiles() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM author_profiles ORDER BY author_name"
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def update_counts(author_name: str, article_count: int = None,
                  atom_count: int = None, l2_model_count: int = None,
                  last_article_at: str = None):
    conn = get_connection()
    try:
        sets = []
        params = []
        if article_count is not None:
            sets.append("article_count = ?")
            params.append(article_count)
        if atom_count is not None:
            sets.append("atom_count = ?")
            params.append(atom_count)
        if l2_model_count is not None:
            sets.append("l2_model_count = ?")
            params.append(l2_model_count)
        if last_article_at is not None:
            sets.append("last_article_at = ?")
            params.append(last_article_at)
        if sets:
            params.append(author_name)
            conn.execute(
                f"UPDATE author_profiles SET {', '.join(sets)} WHERE author_name = ?",
                params,
            )
            conn.commit()
    finally:
        conn.close()


def set_distilled(author_name: str, l3: bool = False, l4: bool = False):
    conn = get_connection()
    try:
        sets = ["last_distilled_at = ?"]
        params = [datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
        if l3:
            sets.append("l3_available = 1")
        if l4:
            sets.append("l4_available = 1")
        params.append(author_name)
        conn.execute(
            f"UPDATE author_profiles SET {', '.join(sets)} WHERE author_name = ?",
            params,
        )
        conn.commit()
    finally:
        conn.close()


def update_profile(author_name: str, l3_available: int = None,
                   l4_available: int = None, persona_md: str = None,
                   mirror_md: str = None, last_distilled_at: str = None):
    conn = get_connection()
    try:
        sets = []
        params = []
        if l3_available is not None:
            sets.append("l3_available = ?")
            params.append(l3_available)
        if l4_available is not None:
            sets.append("l4_available = ?")
            params.append(l4_available)
        if persona_md is not None:
            sets.append("persona_md = ?")
            params.append(persona_md)
        if mirror_md is not None:
            sets.append("mirror_md = ?")
            params.append(mirror_md)
        if last_distilled_at is not None:
            sets.append("last_distilled_at = ?")
            params.append(last_distilled_at)
        else:
            sets.append("last_distilled_at = ?")
            params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if sets:
            params.append(author_name)
            conn.execute(
                f"UPDATE author_profiles SET {', '.join(sets)} WHERE author_name = ?",
                params,
            )
            conn.commit()
    finally:
        conn.close()


def get_persona(author_name: str) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT persona_md FROM author_profiles WHERE author_name = ?",
            (author_name,),
        ).fetchone()
        return row["persona_md"] if row and row.get("persona_md") else None
    finally:
        conn.close()


def get_mirror(author_name: str) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT mirror_md FROM author_profiles WHERE author_name = ?",
            (author_name,),
        ).fetchone()
        return row["mirror_md"] if row and row.get("mirror_md") else None
    finally:
        conn.close()
