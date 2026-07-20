"""User DAO: CRUD for users table."""

from .database import get_connection, row_to_dict, rows_to_dicts


def create_user(name: str, display_name: str = "", config: str = "{}") -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO users (name, display_name, config) VALUES (?, ?, ?)",
            (name, display_name, config),
        )
        conn.commit()
        return get_user(cur.lastrowid)
    finally:
        conn.close()


def get_user(user_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def get_user_by_name(name: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_users() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def update_user(user_id: int, **kwargs) -> dict | None:
    allowed = {"display_name", "config"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return get_user(user_id)

    updates["updated_at"] = "date('now')"
    set_clause = ", ".join(f"{k} = ?" if k != "updated_at" else f"{k} = date('now')" for k in updates)
    values = [v for k, v in updates.items() if k != "updated_at"]

    conn = get_connection()
    try:
        conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*values, user_id))
        conn.commit()
        return get_user(user_id)
    finally:
        conn.close()


def delete_user(user_id: int) -> bool:
    conn = get_connection()
    try:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
