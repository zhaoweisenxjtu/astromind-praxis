"""JSON -> SQLite 数据迁移

将旧版 ~/.meta-learning/ 中的 JSON 文件迁移到 SQLite 数据库。
"""

import json
from pathlib import Path
from datetime import date
from typing import Any

from .database import get_connection, ensure_db_dir
from .dao_user import create_user
from .dao_track import create_track
from .dao_node import add_node, update_node
from .dao_review import create_review
from .dao_assessment import log_assessment


class JsonMigrator:
    """将旧 JSON 格式迁移到 SQLite。"""

    DEFAULT_JSON_DIR = Path.home() / ".meta-learning"

    def __init__(self, json_dir: str | Path | None = None):
        self.json_dir = Path(json_dir) if json_dir else self.DEFAULT_JSON_DIR

    def migrate(self, user_name: str = "default_user",
                track_name: str = "默认学习路线",
                target_type: str = "applied") -> dict:
        """执行完整迁移。

        Args:
            user_name: 迁移后创建的用户名
            track_name: 迁移后创建的路线名
            target_type: 目标类型

        Returns:
            迁移统计 {nodes, reviews, assessments, journals, errors}
        """
        stats = {"nodes": 0, "reviews": 0, "assessments": 0, "journals": 0, "errors": []}

        # 创建默认用户和路线
        try:
            user = create_user(user_name, "迁移用户")
            stats["user_id"] = user["id"]
        except Exception as e:
            # 用户可能已存在
            from .dao_user import get_user_by_name
            user = get_user_by_name(user_name)
            if not user:
                stats["errors"].append(f"创建用户失败: {e}")
                return stats
            stats["user_id"] = user["id"]

        try:
            track = create_track(user["id"], track_name, target_type)
            stats["track_id"] = track["id"]
        except Exception as e:
            stats["errors"].append(f"创建路线失败: {e}")
            return stats

        # 迁移 SM-2 数据
        sm2_file = self.json_dir / "sm2-data.json"
        if sm2_file.exists():
            try:
                result = self._migrate_sm2(sm2_file, track["id"])
                stats["nodes"] += result["nodes"]
                stats["reviews"] += result["reviews"]
            except Exception as e:
                stats["errors"].append(f"SM-2 迁移失败: {e}")

        # 迁移评估日志
        assess_file = self.json_dir / "assessment-log.json"
        if assess_file.exists():
            try:
                count = self._migrate_assessments(assess_file, user["id"], track["id"])
                stats["assessments"] += count
            except Exception as e:
                stats["errors"].append(f"评估记录迁移失败: {e}")

        # 迁移学习日志
        journal_file = self.json_dir / "learning-journal.json"
        if journal_file.exists():
            try:
                count = self._migrate_journals(journal_file, user["id"])
                stats["journals"] += count
            except Exception as e:
                stats["errors"].append(f"学习日志迁移失败: {e}")

        return stats

    def _migrate_sm2(self, path: Path, track_id: int) -> dict:
        """迁移 SM-2 数据到知识节点和复习历史。"""
        data = json.loads(path.read_text(encoding="utf-8"))
        nodes_count = 0
        reviews_count = 0

        for slug, item in data.items():
            node = add_node(
                track_id=track_id,
                name=item.get("topic", slug),
                current_level=3 if item.get("repetitions", 0) >= 3 else 2,
            )
            nodes_count += 1

            # 更新 SM-2 参数
            update_node(
                node["id"],
                ef=item.get("ef", 2.5),
                interval=item.get("interval", 0),
                repetitions=item.get("repetitions", 0),
                next_review=item.get("next_review"),
            )

            # 迁移复习历史
            for h in item.get("history", []):
                create_review(
                    node_id=node["id"],
                    quality=h.get("quality", 3),
                    ef_after=item.get("ef", 2.5),
                    interval_after=item.get("interval", 1),
                )
                reviews_count += 1

        return {"nodes": nodes_count, "reviews": reviews_count}

    def _migrate_assessments(self, path: Path, user_id: int, track_id: int) -> int:
        """迁移评估记录。"""
        data = json.loads(path.read_text(encoding="utf-8"))
        count = 0
        for entry in data.get("entries", []):
            log_assessment(
                user_id=user_id,
                track_id=track_id,
                level_after=entry.get("level_after", 3),
                level_before=entry.get("level_before", 1),
                methods=entry.get("method", "").split("+") if entry.get("method") else None,
                duration_minutes=entry.get("duration_minutes", 0),
                notes=entry.get("notes", ""),
            )
            count += 1
        return count

    def _migrate_journals(self, path: Path, user_id: int) -> int:
        """迁移学习日志。"""
        data = json.loads(path.read_text(encoding="utf-8"))
        count = 0
        for entry in data.get("entries", []):
            from .dao_journal import create_journal

            date_str = entry.get("date", date.today().isoformat())
            create_journal(
                user_id=user_id,
                date_str=date_str,
                focus_minutes=entry.get("focus_duration_minutes", 0),
                diffuse_minutes=entry.get("diffuse_duration_minutes", 0),
                topics=entry.get("topics_studied", []),
                methods=entry.get("methods_used", []),
                highlights=entry.get("highlights", ""),
                struggles=entry.get("struggles", ""),
                tomorrow_plan=entry.get("tomorrow_plan", ""),
            )
            count += 1
        return count

    def report(self, user_name: str = "default_user") -> dict:
        """生成迁移报告（不实际执行迁移）。"""
        stats = {"json_files_found": [], "json_files_missing": [], "estimated_nodes": 0}

        for fname in ["sm2-data.json", "assessment-log.json", "learning-journal.json"]:
            fpath = self.json_dir / fname
            if fpath.exists():
                stats["json_files_found"].append(fname)
            else:
                stats["json_files_missing"].append(fname)

        sm2_file = self.json_dir / "sm2-data.json"
        if sm2_file.exists():
            try:
                data = json.loads(sm2_file.read_text(encoding="utf-8"))
                stats["estimated_nodes"] = len(data)
            except Exception:
                pass

        return stats
