"""Article DAO: CRUD for articles table (L0)."""

from datetime import datetime
from .database import get_connection, row_to_dict, rows_to_dicts


def insert_article(author_name: str, title: str, url: str,
                   content_text: str, published_at: str = None,
                   source_type: str = "wechat") -> int:
    conn = get_connection()
    try:
        import hashlib
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        word_count = len(content_text)

        cur = conn.execute(
            """INSERT OR IGNORE INTO articles
               (author_name, title, url, url_hash, content_text,
                word_count, source_type, published_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (author_name, title, url, url_hash, content_text,
             word_count, source_type, published_at),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def article_exists(url: str) -> bool:
    import hashlib
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM articles WHERE url_hash = ?", (url_hash,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_article(article_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM articles WHERE id = ?", (article_id,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def get_article_by_url(url: str) -> dict | None:
    import hashlib
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM articles WHERE url_hash = ?", (url_hash,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_articles(author_name: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM articles WHERE author_name = ? ORDER BY published_at DESC",
            (author_name,),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def list_articles_without_atoms(author_name: str) -> list[dict]:
    """Articles that haven't been extracted yet."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT a.* FROM articles a
               LEFT JOIN knowledge_atoms k ON a.id = k.article_id
               WHERE a.author_name = ? AND k.id IS NULL
               GROUP BY a.id
               ORDER BY a.published_at DESC""",
            (author_name,),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def update_content(article_id: int, content_text: str):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE articles SET content_text = ?, word_count = ? WHERE id = ?",
            (content_text, len(content_text), article_id),
        )
        conn.commit()
    finally:
        conn.close()


def count_articles(author_name: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM articles WHERE author_name = ?",
            (author_name,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def count_articles_with_atoms(author_name: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT COUNT(DISTINCT a.id) as cnt
               FROM articles a
               JOIN knowledge_atoms k ON a.id = k.article_id
               WHERE a.author_name = ?""",
            (author_name,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()
