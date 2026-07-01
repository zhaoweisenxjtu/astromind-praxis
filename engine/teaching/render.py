"""结构化教学内容 -> 终端 Markdown 渲染."""

from typing import Any


def render_concept_content(content: dict, concept: str) -> str:
    """渲染概念教学材料为 Markdown."""
    lines = [f"# {concept}\n"]

    if content.get("intuition"):
        lines.extend([
            "## 直觉构建",
            content["intuition"],
            "",
        ])

    if content.get("motivation"):
        lines.extend([
            "## 为什么重要",
            content["motivation"],
            "",
        ])

    if content.get("definition"):
        lines.extend([
            "## 形式定义",
            f"> {content['definition']}",
            "",
        ])

    if content.get("boundary"):
        lines.extend([
            "## 边界条件",
            content["boundary"],
            "",
        ])

    if content.get("connections"):
        lines.extend(["## 关联概念", ""])
        for conn in content["connections"]:
            lines.append(f"- **{conn['concept']}**: {conn.get('relation', '')}")
        lines.append("")

    if content.get("examples"):
        lines.extend(["## 例题", ""])
        for i, ex in enumerate(content["examples"], 1):
            lines.extend([
                f"### 例题 {i} (难度: {'★' * ex.get('difficulty', 1)})",
                f"**题目**: {ex['question']}",
                f"**解答**: {ex['solution']}",
                "",
            ])

    return "\n".join(lines)


def render_questions(questions: list[dict]) -> str:
    """渲染检验题为 Markdown."""
    lines = ["## 检验题\n"]

    for i, q in enumerate(questions, 1):
        type_labels = {
            "conceptual": "概念理解",
            "applied": "应用",
            "discrimination": "辨析",
        }
        label = type_labels.get(q.get("type", ""), q.get("type", ""))
        difficulty = "★" * q.get("difficulty", 1)
        lines.append(f"### 第{i}题 [{label}] ({difficulty})")
        lines.append(q["question"])
        lines.append("")

        if q.get("options"):
            for opt in q["options"]:
                lines.append(f"- {opt}")
            lines.append("")

    return "\n".join(lines)


def render_diagnosis(diagnosis: dict) -> str:
    """渲染诊断报告为 Markdown."""
    level_map = {1: "入门", 2: "基础", 3: "进阶", 4: "熟练", 5: "专家"}
    level = diagnosis.get("level", 1)
    level_name = level_map.get(level, str(level))

    lines = [
        "# 诊断报告\n",
        f"**当前水平**: {level_name} ({level}/5)\n",
    ]

    if diagnosis.get("gaps"):
        lines.extend(["## 知识缺口", ""])
        for gap in diagnosis["gaps"]:
            gap_labels = {"missing": "缺失", "weak": "薄弱", "unstable": "不稳定"}
            label = gap_labels.get(gap.get("gap_type", ""), gap.get("gap_type", ""))
            lines.append(f"- **{gap['concept']}** [{label}]: {gap.get('description', '')}")
        lines.append("")

    if diagnosis.get("misconceptions"):
        lines.extend(["## 迷思概念", ""])
        for mc in diagnosis["misconceptions"]:
            lines.extend([
                f"- **{mc['concept']}**",
                f"  - 误解: {mc['misconception']}",
                f"  - 纠正: {mc.get('correction', '')}",
            ])
        lines.append("")

    if diagnosis.get("recommended_path"):
        lines.extend(["## 推荐学习路径", ""])
        for i, concept in enumerate(diagnosis["recommended_path"], 1):
            lines.append(f"{i}. {concept}")
        lines.append("")

    return "\n".join(lines)


def render_progress_bar(current: int, total: int, width: int = 20) -> str:
    """渲染教学进度条."""
    filled = int(current / total * width) if total > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    return f"📊 教学进度 [{bar}] {current}/{total}"


def render_session_status(session: dict) -> str:
    """渲染会话状态总览."""
    topic = session.get("topic", "未知")
    status = session.get("status", "unknown")
    level = session.get("level", "?")
    node = session.get("current_node", "无")

    lines = [
        f"# 会话状态: {topic}",
        f"**状态**: {status}",
        f"**水平**: {level}/5",
        f"**当前节点**: {node}",
    ]
    return "\n".join(lines)
