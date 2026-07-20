"""量化指标引擎

提供仪表盘数据和学习效果量化评估。
"""

from datetime import date, timedelta
from ..db.database import get_connection


class Dashboard:
    """学习效果指标引擎，从 references/learning-indicators.md 提取。"""

    def __init__(self, db_conn=None):
        self._conn = db_conn

    def _get_conn(self):
        if self._conn:
            return self._conn
        return get_connection()

    def overall(self, user_id: int) -> dict:
        """返回5个核心仪表盘数字。

        Returns:
            {total_nodes, l3_plus_pct, ontime_review_pct, monthly_jumps, avg_ef}
        """
        conn = self._get_conn()
        try:
            # 知识总量（所有路线活跃节点）
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM knowledge_nodes n "
                "JOIN tracks t ON n.track_id = t.id "
                "WHERE t.user_id = ? AND n.status = 'active'",
                (user_id,),
            ).fetchone()
            total_nodes = row["cnt"]

            # L3+ 占比
            row = conn.execute(
                "SELECT "
                "  COUNT(*) AS total, "
                "  COUNT(CASE WHEN n.current_level >= 3 THEN 1 END) AS l3_plus "
                "FROM knowledge_nodes n "
                "JOIN tracks t ON n.track_id = t.id "
                "WHERE t.user_id = ? AND n.status = 'active'",
                (user_id,),
            ).fetchone()
            l3_plus_pct = round(row["l3_plus"] / row["total"] * 100, 1) if row["total"] > 0 else 0

            # 按时复习率（过去30天）
            thirty_days_ago = date.today() - timedelta(days=30)
            row = conn.execute(
                "SELECT "
                "  COUNT(*) AS total_due, "
                "  COUNT(CASE WHEN r.reviewed_at <= n.next_review THEN 1 END) AS ontime "
                "FROM knowledge_nodes n "
                "JOIN tracks t ON n.track_id = t.id "
                "LEFT JOIN review_history r ON r.node_id = n.id "
                "  AND date(r.reviewed_at) >= ? "
                "WHERE t.user_id = ? AND n.status = 'active'",
                (thirty_days_ago.isoformat(), user_id),
            ).fetchone()
            ontime_pct = round(row["ontime"] / row["total_due"] * 100, 1) if row["total_due"] > 0 else 0

            # 月跃迁（过去30天层级提升的节点数）
            month_ago = (date.today() - timedelta(days=30)).isoformat()
            row = conn.execute(
                "SELECT COUNT(DISTINCT node_id) AS jumps FROM assessment_log "
                "WHERE user_id = ? AND created_at >= ? AND level_after > level_before",
                (user_id, month_ago),
            ).fetchone()
            monthly_jumps = row["jumps"]

            # 平均 EF
            row = conn.execute(
                "SELECT ROUND(AVG(n.ef), 2) AS avg_ef FROM knowledge_nodes n "
                "JOIN tracks t ON n.track_id = t.id "
                "WHERE t.user_id = ? AND n.status = 'active'",
                (user_id,),
            ).fetchone()
            avg_ef = row["avg_ef"] or 2.5

            return {
                "total_nodes": total_nodes,
                "l3_plus_pct": l3_plus_pct,
                "ontime_review_pct": ontime_pct,
                "monthly_jumps": monthly_jumps,
                "avg_ef": avg_ef,
            }
        finally:
            if not self._conn:
                conn.close()

    def track_summary(self, track_id: int) -> dict:
        """返回指定路线的详情摘要。"""
        conn = self._get_conn()
        try:
            track = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
            if not track:
                return {"error": "track not found"}

            # 节点统计
            node_stats = conn.execute(
                "SELECT "
                "  COUNT(*) AS total, "
                "  COUNT(CASE WHEN status = 'active' THEN 1 END) AS active_count, "
                "  COUNT(CASE WHEN current_level >= 3 THEN 1 END) AS mastered_count, "
                "  ROUND(AVG(current_level), 2) AS avg_level "
                "FROM knowledge_nodes WHERE track_id = ?",
                (track_id,),
            ).fetchone()

            # 待复习
            today = date.today().isoformat()
            due_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM knowledge_nodes "
                "WHERE track_id = ? AND next_review IS NOT NULL AND next_review <= ? "
                "AND status = 'active'",
                (track_id, today),
            ).fetchone()["cnt"]

            # 层级分布
            level_dist = {}
            for r in conn.execute(
                "SELECT current_level, COUNT(*) AS cnt FROM knowledge_nodes "
                "WHERE track_id = ? AND status = 'active' "
                "GROUP BY current_level ORDER BY current_level",
                (track_id,),
            ).fetchall():
                level_dist[str(r["current_level"])] = r["cnt"]

            return {
                "track_id": track_id,
                "track_name": track["name"],
                "target_type": track["target_type"],
                "current_state": track["current_state"],
                "total_nodes": node_stats["total"],
                "active_nodes": node_stats["active_count"],
                "mastered_nodes": node_stats["mastered_count"],
                "avg_level": node_stats["avg_level"],
                "due_reviews": due_count,
                "level_distribution": level_dist,
            }
        finally:
            if not self._conn:
                conn.close()

    def weekly_progress(self, user_id: int, weeks: int = 4) -> list[dict]:
        """按周返回跃迁数量、投入时间、方法效率排名。"""
        conn = self._get_conn()
        try:
            result = []
            today = date.today()
            for w in range(weeks):
                end_date = today - timedelta(days=w * 7)
                start_date = end_date - timedelta(days=6)

                # 周跃迁
                jumps = conn.execute(
                    "SELECT COUNT(DISTINCT node_id) AS cnt FROM assessment_log "
                    "WHERE user_id = ? AND date(created_at) BETWEEN ? AND ? "
                    "AND level_after > level_before",
                    (user_id, start_date.isoformat(), end_date.isoformat()),
                ).fetchone()["cnt"]

                # 周投入时间
                time_row = conn.execute(
                    "SELECT COALESCE(SUM(focus_minutes), 0) AS total_focus "
                    "FROM learning_journal "
                    "WHERE user_id = ? AND date BETWEEN ? AND ?",
                    (user_id, start_date.isoformat(), end_date.isoformat()),
                ).fetchone()

                result.append({
                    "week": f"{start_date.isoformat()}~{end_date.isoformat()}",
                    "jumps": jumps,
                    "focus_minutes": time_row["total_focus"],
                })

            return result
        finally:
            if not self._conn:
                conn.close()
