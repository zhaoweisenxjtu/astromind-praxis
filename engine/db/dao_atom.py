"""Knowledge Atom DAO: CRUD for knowledge_atoms table (L1)."""

from datetime import datetime
from .database import get_connection, row_to_dict, rows_to_dicts


def insert_atom(article_id: int, author_name: str, atom_type: str,
                content: str, topic: str, evidence: str = None,
                embedding_ref: str = None, published_at: str = None,
                valid_from: str = None) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO knowledge_atoms
               (article_id, author_name, type, content, topic, evidence,
                embedding_ref, published_at, valid_from)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (article_id, author_name, atom_type, content, topic, evidence,
             embedding_ref, published_at, valid_from),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_atom(atom_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM knowledge_atoms WHERE id = ?", (atom_id,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_atoms_by_author(author_name: str, atom_type: str = None) -> list[dict]:
    conn = get_connection()
    try:
        query = "SELECT * FROM knowledge_atoms WHERE author_name = ?"
        params = [author_name]
        if atom_type:
            query += " AND type = ?"
            params.append(atom_type)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def list_atoms_by_topic(author_name: str, topic: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM knowledge_atoms WHERE author_name = ? AND topic = ?",
            (author_name, topic),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def list_atoms_by_article(article_id: int) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM knowledge_atoms WHERE article_id = ? ORDER BY id",
            (article_id,),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def list_atoms_not_merged(author_name: str) -> list[dict]:
    """Atoms that haven't been merged into L2 yet."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM knowledge_atoms WHERE author_name = ? AND merged_to IS NULL",
            (author_name,),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def get_all_topics(author_name: str) -> list[str]:
    """Get all unique topics for an author."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT topic FROM knowledge_atoms WHERE author_name = ? ORDER BY topic",
            (author_name,),
        ).fetchall()
        return [r["topic"] for r in rows]
    finally:
        conn.close()


def count_atoms_by_topic(author_name: str) -> list[dict]:
    """Count atoms per topic, useful for merge triggering."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT topic, COUNT(*) as cnt,
                      COUNT(DISTINCT article_id) as article_cnt,
                      MIN(published_at) as first_seen,
                      MAX(published_at) as last_seen
               FROM knowledge_atoms
               WHERE author_name = ? AND merged_to IS NULL
               GROUP BY topic
               HAVING cnt >= 1
               ORDER BY cnt DESC""",
            (author_name,),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def set_merged(atom_ids: list[int], model_id: int):
    """Mark atoms as merged into a mental model."""
    conn = get_connection()
    try:
        conn.executemany(
            "UPDATE knowledge_atoms SET merged_to = ? WHERE id = ?",
            [(model_id, aid) for aid in atom_ids],
        )
        conn.commit()
    finally:
        conn.close()


def update_topic(atom_id: int, new_topic: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE knowledge_atoms SET topic = ? WHERE id = ?",
            (new_topic, atom_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_atom_time(atom_id: int, valid_until: str = None,
                     last_confirmed_at: str = None):
    conn = get_connection()
    try:
        sets = []
        params = []
        if valid_until is not None:
            sets.append("valid_until = ?")
            params.append(valid_until)
        if last_confirmed_at is not None:
            sets.append("last_confirmed_at = ?")
            params.append(last_confirmed_at)
        if sets:
            params.append(atom_id)
            conn.execute(
                f"UPDATE knowledge_atoms SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
    finally:
        conn.close()


def search_atoms(query: str, author_name: str = None, limit: int = 20) -> list[dict]:
    """FTS5 full-text search on atoms."""
    conn = get_connection()
    try:
        if author_name:
            rows = conn.execute(
                """SELECT k.* FROM knowledge_atoms k
                   JOIN knowledge_atoms_fts f ON k.id = f.rowid
                   WHERE knowledge_atoms_fts MATCH ? AND k.author_name = ?
                   ORDER BY rank LIMIT ?""",
                (query, author_name, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT k.* FROM knowledge_atoms k
                   JOIN knowledge_atoms_fts f ON k.id = f.rowid
                   WHERE knowledge_atoms_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def count_atoms(author_name: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_atoms WHERE author_name = ?",
            (author_name,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()
