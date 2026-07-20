"""多轨道调度算法

根据急迫度分数在多个学习路线间分配时间。
"""

from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Any
from ..db.database import get_connection, rows_to_dicts


# 默认参数
AVG_REVIEW_TIME = 3       # 单节点复习用时（分钟）
NEW_NODE_TIME = 15        # 单节点新学用时（分钟）
MAX_SLOT_MINUTES = 60     # 单轨道最大分配
MIN_TRACK_MINUTES = 10    # 轨道最低保障
OVERDUE_MULTIPLIER = 1.5  # 逾期加权倍数


@dataclass
class SlotActivity:
    type: str  # "review" or "new_learning"
    node_ids: list[int] = field(default_factory=list)
    count: int = 0


@dataclass
class TrackSlot:
    track_id: int
    name: str
    priority: int
    current_state: str
    due_nodes: list[dict]
    pending_nodes: list[dict]
    overdue_count: int
    stagnant_days: int
    urgency: float = 0.0
    allocation_minutes: int = 0
    activities: list[SlotActivity] = field(default_factory=list)


@dataclass
class DailySchedule:
    user_id: int
    date: str
    total_minutes: int
    slots: list[dict]  # serializable


class MultiTrackScheduler:
    """多轨道调度器。"""

    def __init__(self, db_conn=None):
        self._conn = db_conn

    def _get_conn(self):
        if self._conn:
            return self._conn
        return get_connection()

    def get_schedule(self, user_id: int, total_minutes: int | None = None) -> dict:
        """生成今日学习安排。

        Args:
            user_id: 用户ID
            total_minutes: 可用总时间（默认从学习日志估算）

        Returns:
            {date, total_minutes, tracks: [...]}
        """
        conn = self._get_conn()
        try:
            today = date.today().isoformat()

            if total_minutes is None:
                total_minutes = self._estimate_available_time(conn, user_id)

            # 获取所有活跃路线
            tracks = conn.execute(
                "SELECT * FROM tracks WHERE user_id = ? AND status = 'active' "
                "ORDER BY priority DESC",
                (user_id,),
            ).fetchall()

            if not tracks:
                return {
                    "date": today,
                    "total_minutes": 0,
                    "tracks": [],
                    "message": "没有活跃的学习路线",
                }

            # 为每条路线计算急迫度
            track_slots = []
            for t in tracks:
                track = dict(t)
                due = rows_to_dicts(conn.execute(
                    "SELECT * FROM knowledge_nodes "
                    "WHERE track_id = ? AND next_review IS NOT NULL AND next_review <= ? "
                    "AND status = 'active' ORDER BY next_review",
                    (track["id"], today),
                ).fetchall())

                pending = rows_to_dicts(conn.execute(
                    "SELECT * FROM knowledge_nodes "
                    "WHERE track_id = ? AND status = 'active' AND current_level < 3 "
                    "ORDER BY importance DESC",
                    (track["id"],),
                ).fetchall())

                overdue = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM knowledge_nodes "
                    "WHERE track_id = ? AND next_review IS NOT NULL "
                    "AND julianday(?) - julianday(next_review) > 1 "
                    "AND status = 'active'",
                    (track["id"], today),
                ).fetchone()["cnt"]

                # 停滞天数（最近无评估记录的天数）
                last_activity = conn.execute(
                    "SELECT MAX(date(created_at)) AS last_date FROM assessment_log "
                    "WHERE track_id = ?",
                    (track["id"],),
                ).fetchone()["last_date"]

                stagnant = 0
                if last_activity:
                    stagnant = (date.today() - date.fromisoformat(last_activity)).days
                else:
                    # 如果完全没有记录，看创建时间
                    stagnant = (date.today() - date.fromisoformat(track["created_at"])).days

                slot = TrackSlot(
                    track_id=track["id"],
                    name=track["name"],
                    priority=track["priority"],
                    current_state=track["current_state"],
                    due_nodes=due,
                    pending_nodes=pending,
                    overdue_count=overdue,
                    stagnant_days=stagnant,
                )
                track_slots.append(slot)

            # 计算急迫度
            self._compute_urgency(track_slots)

            # 分配时间
            self._allocate_time(track_slots, total_minutes)

            return {
                "date": today,
                "total_minutes": total_minutes,
                "tracks": [self._slot_to_dict(s) for s in track_slots],
            }

        finally:
            if not self._conn:
                conn.close()

    def _compute_urgency(self, slots: list[TrackSlot]):
        """为每条路线计算急迫度分数。"""
        max_due = max((len(s.due_nodes) for s in slots), default=1)
        max_overdue = max((s.overdue_count for s in slots), default=1)
        max_stagnant = max((s.stagnant_days for s in slots), default=1)

        for s in slots:
            due_score = len(s.due_nodes) / max(max_due, 1)
            overdue_score = (s.overdue_count * OVERDUE_MULTIPLIER) / max(max_overdue * OVERDUE_MULTIPLIER, 1)
            stagnant_score = s.stagnant_days / max(max_stagnant, 1)
            priority_score = s.priority / 5.0

            s.urgency = (
                0.4 * due_score
                + 0.3 * overdue_score
                + 0.2 * stagnant_score
                + 0.1 * priority_score
            )

    def _allocate_time(self, slots: list[TrackSlot], total_minutes: int):
        """按急迫度分配时间。"""
        if not slots:
            return

        # 按急迫度降序
        slots.sort(key=lambda s: s.urgency, reverse=True)

        remaining = total_minutes
        n = len(slots)

        for i, s in enumerate(slots):
            if i == 0 and n > 1:
                # 最高优先级 50%，上限 60min
                alloc = min(int(total_minutes * 0.5), MAX_SLOT_MINUTES)
            else:
                # 其余轨道：剩余按需分配，至少保证最低时间
                remaining_tracks = n - i
                guaranteed = remaining_tracks * MIN_TRACK_MINUTES
                if remaining <= guaranteed:
                    alloc = MIN_TRACK_MINUTES
                else:
                    available = remaining - guaranteed
                    due_time = len(s.due_nodes) * AVG_REVIEW_TIME
                    alloc = min(due_time + 10, MAX_SLOT_MINUTES)

            s.allocation_minutes = max(alloc, MIN_TRACK_MINUTES)
            remaining -= s.allocation_minutes

            # 分配具体活动
            activities = []
            review_time = len(s.due_nodes) * AVG_REVIEW_TIME

            if s.due_nodes:
                activities.append(SlotActivity(
                    type="review",
                    node_ids=[n["id"] for n in s.due_nodes],
                    count=len(s.due_nodes),
                ))

            remaining_track = s.allocation_minutes - review_time
            if remaining_track > NEW_NODE_TIME and s.pending_nodes and s.current_state not in ("completed",):
                max_new = min(
                    len(s.pending_nodes),
                    remaining_track // NEW_NODE_TIME,
                )
                if max_new > 0:
                    activities.append(SlotActivity(
                        type="new_learning",
                        count=max_new,
                    ))

            s.activities = activities

    def _slot_to_dict(self, slot: TrackSlot) -> dict:
        """序列化为可 JSON 序列化的 dict。"""
        return {
            "track_id": slot.track_id,
            "name": slot.name,
            "priority": slot.priority,
            "current_state": slot.current_state,
            "urgency": round(slot.urgency, 3),
            "allocation_minutes": slot.allocation_minutes,
            "due_reviews": len(slot.due_nodes),
            "pending_nodes": len(slot.pending_nodes),
            "overdue_count": slot.overdue_count,
            "stagnant_days": slot.stagnant_days,
            "activities": [
                {
                    "type": a.type,
                    "node_ids": a.node_ids,
                    "count": a.count,
                }
                for a in slot.activities
            ],
        }

    def _estimate_available_time(self, conn, user_id: int) -> int:
        """从近期学习日志估算可用时间。"""
        # 取最近7天的平均专注时间，默认 120 分钟
        row = conn.execute(
            "SELECT ROUND(AVG(focus_minutes)) AS avg_min FROM learning_journal "
            "WHERE user_id = ? ORDER BY date DESC LIMIT 7",
            (user_id,),
        ).fetchone()
        if row and row["avg_min"]:
            return int(row["avg_min"])
        return 120
