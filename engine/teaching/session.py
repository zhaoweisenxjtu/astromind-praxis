"""会话状态管理（断点续传）.

使用 SQLite 的 workflow_context 表持久化会话状态。
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SessionManager:
    """管理教学会话的持久化状态."""

    def __init__(self, db):
        self.db = db

    def create_session(
        self, user_id: str, track_id: int, topic: str, diagnosis: dict
    ) -> int:
        """创建新会话，返回 session_id."""
        from datetime import timezone

        now = datetime.now(timezone.utc).isoformat()
        session_id = self.db.execute(
            """INSERT INTO workflow_context
               (user_id, track_id, topic, status, diagnosis, current_node,
                completed_nodes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                user_id,
                track_id,
                topic,
                "diagnosed",
                json.dumps(diagnosis, ensure_ascii=False),
                None,
                json.dumps([], ensure_ascii=False),
                now,
                now,
            ],
        )
        return session_id

    def get_session(self, session_id: int) -> Optional[dict]:
        """获取会话状态."""
        row = self.db.fetch_one(
            "SELECT * FROM workflow_context WHERE id = ?", [session_id]
        )
        if not row:
            return None

        session = dict(row)
        # Parse JSON fields
        for field in ("diagnosis", "completed_nodes", "state_data"):
            if session.get(field) and isinstance(session[field], str):
                try:
                    session[field] = json.loads(session[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return session

    def update_session(self, session_id: int, **kwargs):
        """更新会话字段."""
        from datetime import timezone

        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = [
            json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
            for v in kwargs.values()
        ]
        values.append(session_id)
        self.db.execute(
            f"UPDATE workflow_context SET {sets} WHERE id = ?", values
        )

    def set_current_node(self, session_id: int, node_id: Optional[int]):
        """设置当前教学节点."""
        self.update_session(session_id, current_node=node_id)

    def add_completed_node(self, session_id: int, node_id: int):
        """将节点标记为已完成."""
        session = self.get_session(session_id)
        completed = session.get("completed_nodes", []) if session else []
        if node_id not in completed:
            completed.append(node_id)
        self.update_session(session_id, completed_nodes=completed)

    def set_state_data(self, session_id: int, key: str, value: Any):
        """设置状态数据中的某个键."""
        session = self.get_session(session_id)
        state = session.get("state_data", {}) if session else {}
        state[key] = value
        self.update_session(session_id, state_data=state)

    def get_user_sessions(self, user_id: str, limit: int = 10) -> list[dict]:
        """列出用户的会话历史."""
        rows = self.db.fetch_all(
            "SELECT id, topic, status, level, created_at, updated_at "
            "FROM workflow_context WHERE user_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            [user_id, limit],
        )
        return [dict(r) for r in rows]

    def list_active(self) -> list[dict]:
        """列出所有活跃会话."""
        rows = self.db.fetch_all(
            "SELECT id, user_id, topic, status, current_node, updated_at "
            "FROM workflow_context WHERE status NOT IN ('completed', 'abandoned') "
            "ORDER BY updated_at DESC"
        )
        return [dict(r) for r in rows]
