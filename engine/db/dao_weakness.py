"""DAO for weakness_patterns table.

薄弱模式分析 — 跨节点聚合迷思，识别系统性缺陷。
"""

import json
from typing import Optional

from .database import get_connection, row_to_dict, rows_to_dicts


def add_pattern(
    user_id: int,
    pattern_type: str,
    description: str,
    related_node_ids: Optional[list[int]] = None,
    severity: int = 1,
) -> dict:
    """Add or update a weakness pattern (upsert by user+type+description)."""
    related_json = json.dumps(related_node_ids or [], ensure_ascii=False)
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM weakness_patterns WHERE user_id=? AND pattern_type=? AND description=?",
            (user_id, pattern_type, description),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE weakness_patterns SET
                   frequency = frequency + 1,
                   severity = MAX(severity, ?),
                   related_node_ids = ?,
                   last_observed_at = datetime('now','localtime')
                   WHERE id = ?""",
                (severity, related_json, existing["id"]),
            )
            conn.commit()
            return get_pattern(existing["id"])

        cur = conn.execute(
            """INSERT INTO weakness_patterns
               (user_id, pattern_type, description, related_node_ids, severity)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, pattern_type, description, related_json, severity),
        )
        conn.commit()
        return get_pattern(cur.lastrowid)
    finally:
        conn.close()


def get_pattern(pattern_id: int) -> Optional[dict]:
    """Get a single pattern by ID."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM weakness_patterns WHERE id = ?",
            (pattern_id,),
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def list_patterns(user_id: int, min_severity: int = 1, limit: int = 50) -> list[dict]:
    """List weakness patterns for a user."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM weakness_patterns
               WHERE user_id = ? AND severity >= ?
               ORDER BY severity DESC, frequency DESC
               LIMIT ?""",
            (user_id, min_severity, limit),
        ).fetchall()
        return rows_to_dicts(rows)
    finally:
        conn.close()


def analyze_from_misconceptions(user_id: int) -> dict:
    """分析用户的 misconceptions → 聚合为 weakness_patterns。

    扫描所有未解决的迷思，按 category 聚合，对高频类别创建/更新 pattern。
    """
    from . import dao_misconception as dm

    stats = dm.get_misconception_stats(user_id)
    if stats["total"] == 0:
        return {"patterns_created": 0, "patterns": []}

    created = []
    category_map = {
        "overgeneralization": ("overgeneralization", "频繁过度泛化"),
        "term_confusion": ("term_confusion", "术语概念混淆"),
        "surface_analogy": ("boundary_blur", "依赖表面类比而忽略深层原理"),
        "missing_boundary": ("boundary_blur", "概念边界/适用条件不清晰"),
        "order_reversal": ("method_confusion", "方法步骤/顺序混淆"),
    }

    for cat, count in stats.get("by_category", {}).items():
        if count < 2:
            continue  # 单次出现不视为模式
        ptype, desc = category_map.get(cat, ("overgeneralization", f"其他迷思 ({cat})"))
        pattern = add_pattern(
            user_id=user_id,
            pattern_type=ptype,
            description=f"{desc}（出现 {count} 次）",
            severity=min(count, 5),
        )
        created.append(pattern)

    return {
        "patterns_created": len(created),
        "patterns": created,
        "total_misconceptions": stats["total"],
        "unresolved": stats["unresolved"],
    }
