"""假懂检测引擎

对 10 种假懂信号进行量化评分，参考 references/fake-detection.md。
"""

from typing import Any


class FakeDetector:
    """假懂检测评分逻辑。"""

    SIGNALS = {
        "can_not_restate": "无法复述——合书想不起核心内容",
        "term_barrier": "术语障碍——只能用术语解释术语",
        "analogy_failure": "类比失效——说不出类比的失效边界",
        "variant_stuck": "变式卡壳——会做原题但变条件就做不出",
        "cannot_predict": "无法预测——不能预测参数变化的结果",
        "avoids_why": "回避原因——被问'为什么'时绕圈子",
        "overconfidence": "过度自信——过于确定但实际错误率高",
        "method_confusion": "方法混乱——不知道该用什么方法",
        "boundary_blur": "边界模糊——不知道适用条件和失效场景",
        "knowledge_island": "知识孤岛——能讲单个概念但说不出关联",
    }

    @staticmethod
    def assess(signal_flags: dict[str, bool]) -> dict:
        """评估假懂风险。

        Args:
            signal_flags: {signal_name: True/False}

        Returns:
            {total_signals, risk_level, details}
        """
        active = []
        for name, triggered in signal_flags.items():
            if triggered and name in FakeDetector.SIGNALS:
                active.append({"signal": name, "description": FakeDetector.SIGNALS[name]})

        count = len(active)

        if count == 0:
            risk = "none"
        elif count <= 1:
            risk = "low"
        elif count <= 3:
            risk = "medium"
        else:
            risk = "high"

        return {
            "total_signals": count,
            "risk_level": risk,
            "details": active,
        }

    @staticmethod
    def get_probing_questions(signal: str) -> list[str]:
        """获取用于检测特定假懂信号的提问。"""
        questions = {
            "can_not_restate": [
                "合上材料，用一句话说出核心思想",
                "不要看书，在白纸上写出刚才讲的内容要点",
            ],
            "term_barrier": [
                "用中学生能听懂的话再讲一次",
                "不要用任何术语来解释这个概念",
            ],
            "analogy_failure": [
                "你给的类比在什么情况下不适用？",
                "这个类比的边界在哪里？",
            ],
            "variant_stuck": [
                "如果把条件X改成Y，结果会怎样变化？",
                "这个题型和刚才那道有什么本质区别？",
            ],
            "cannot_predict": [
                "如果把这个参数加倍，结果会怎么变？",
                "你能预测一下输入变化后的输出走向吗？",
            ],
            "avoids_why": [
                "为什么这个公式是这样而不是别的形式？",
                "为什么这里用方法A而不是方法B？",
            ],
            "overconfidence": [
                "你有多确定？如果错了，最可能错在哪一步？",
                "自评信心分（1-5），然后说说可能的风险",
            ],
            "method_confusion": [
                "这道题为什么用A方法，能不能用B方法？",
                "你怎么知道这个方法是正确的？",
            ],
            "boundary_blur": [
                "在什么情况下这个结论不成立？",
                "这个定理/公式的适用条件是什么？",
            ],
            "knowledge_island": [
                "这个概念和你学过的那几个概念有什么联系？",
                "这个概念在更大的知识框架中处于什么位置？",
            ],
        }
        return questions.get(signal, ["请详细解释你的理解"])

    @staticmethod
    def quick_check_summary(assess_result: dict) -> str:
        """生成假懂检测的快速摘要。"""
        level = assess_result["risk_level"]
        count = assess_result["total_signals"]

        if level == "none":
            return "假懂风险：无。知识结构健康。"
        elif level == "low":
            return f"假懂风险：低（{count}个信号）。建议针对性提问确认。"
        elif level == "medium":
            signals_str = "; ".join(d["description"] for d in assess_result["details"])
            return f"假懂风险：中（{count}个信号）。需要立即检验。信号：{signals_str}"
        else:
            signals_str = "; ".join(d["description"] for d in assess_result["details"])
            return (f"假懂风险：高（{count}个信号）。知识结构存在系统性问题，"
                    f"建议退回上一层级重新构建理解。信号：{signals_str}")
