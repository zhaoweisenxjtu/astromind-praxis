"""工作流状态机

管理学习路线的状态转换：init -> diagnosis -> teaching -> assessment -> practice -> completed。
"""

from typing import Any


# 所有允许的状态
STATES = ["init", "diagnosis", "teaching", "assessment", "practice", "completed"]

# 状态转换映射表
_TRANSITIONS = {
    "init": ["diagnosis"],
    "diagnosis": ["teaching"],
    "teaching": ["assessment"],
    "assessment": ["teaching", "practice", "completed"],
    "practice": ["assessment"],
    "completed": [],
}

# 状态中文描述
STATE_LABELS = {
    "init": "初始化",
    "diagnosis": "目标诊断",
    "teaching": "深度教学",
    "assessment": "结构检验",
    "practice": "刻意实践",
    "completed": "已完成",
}


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """检查状态转换是否合法。"""
    if from_state not in _TRANSITIONS:
        return False
    return to_state in _TRANSITIONS[from_state]


def get_allowed_transitions(state: str) -> list[str]:
    """返回从当前状态可以转换到的所有目标状态。"""
    return _TRANSITIONS.get(state, [])


def get_state_label(state: str) -> str:
    """返回状态的中文标签。"""
    return STATE_LABELS.get(state, state)


def get_next_recommended(track: dict) -> dict:
    """根据路线数据推荐下一步状态。

    Args:
        track: tracks 表的一行 (dict, 含 workflow_context 字段)

    Returns:
        {next_state, reason, can_transition}
    """
    current = track.get("current_state", "init")
    ctx = track.get("workflow_context", "{}")

    import json
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except (json.JSONDecodeError, TypeError):
            ctx = {}

    allowed = get_allowed_transitions(current)

    if not allowed:
        return {"next_state": current, "reason": "已是最终状态", "can_transition": False}

    # 守卫条件逻辑
    if current == "init":
        return {"next_state": "diagnosis", "reason": "初始化完成，开始目标诊断", "can_transition": True}

    if current == "diagnosis":
        if ctx.get("prerequisites_passed") is False:
            return {"next_state": "diagnosis", "reason": "前置知识未通过，继续诊断", "can_transition": False}
        return {"next_state": "teaching", "reason": "诊断完成，进入深度教学", "can_transition": True}

    if current == "teaching":
        return {"next_state": "assessment", "reason": "教学完成，进入结构检验", "can_transition": True}

    if current == "assessment":
        # 需要外部数据判断：节点层级是否达到要求
        # 如果没有节点数据，默认推荐 practice
        return {"next_state": "practice", "reason": "检验完成，进入刻意实践", "can_transition": True}

    if current == "practice":
        return {"next_state": "assessment", "reason": "实践完成，重新评估", "can_transition": True}

    return {"next_state": allowed[0], "reason": "继续推进", "can_transition": True}


def get_guarded_next(track: dict, nodes: list[dict]) -> dict:
    """带守卫条件的下一步推荐（需要节点数据）。

    Args:
        track: 路线数据
        nodes: 该路线的所有活跃节点 [{current_level, status, ...}]

    Returns:
        {next_state, reason}
    """
    current = track.get("current_state", "init")
    import json
    ctx = track.get("workflow_context", "{}")
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except (json.JSONDecodeError, TypeError):
            ctx = {}

    if current == "assessment":
        if not nodes:
            return {"next_state": "teaching", "reason": "没有活跃节点，回到教学环节"}

        active = [n for n in nodes if n.get("status") == "active"]
        if not active:
            return {"next_state": "teaching", "reason": "没有活跃节点，回到教学环节"}

        all_above_l3 = all(n.get("current_level", 1) >= 3 for n in active)
        any_below_l3 = any(n.get("current_level", 1) < 3 for n in active)
        all_above_l4 = all(n.get("current_level", 1) >= 4 for n in active)

        if all_above_l4:
            target_type = track.get("target_type", "")
            if target_type in ("exam", "applied"):
                return {"next_state": "completed", "reason": "所有节点达到L4+，路线目标达成"}
            return {"next_state": "practice", "reason": "所有节点L4+，进入综合实践"}

        if all_above_l3 and not any_below_l3:
            return {"next_state": "practice", "reason": "所有活跃节点L3+，进入刻意实践"}

        return {"next_state": "teaching", "reason": f"存在层级<3的节点，回到教学强化"}

    if current == "practice":
        return {"next_state": "assessment", "reason": "实践结束，重新评估"}

    if current == "completed":
        return {"next_state": "completed", "reason": "路线已完成"}

    return get_next_recommended(track)
