"""SM-2 纯函数算法

从 scripts/sm2-scheduler.py 重构提取，移除 I/O，保留核心算法。

参考: https://www.supermemo.com/en/archives1990-2015/english/ol/sm2
"""

from datetime import date, timedelta

# SM-2 质量评分标准
QUALITY_DESCRIPTIONS = {
    0: "完全忘记，即使看到答案也毫无印象",
    1: "看到答案后能回忆起来，但感觉完全陌生",
    2: "看到答案后能回忆起来，感觉有点印象但错误严重",
    3: "回忆时有些困难，但最终正确，感觉需要更多复习",
    4: "回忆比较顺利，答案基本正确，有所犹豫",
    5: "完美回忆，毫不犹豫，完全正确",
}


class SM2Calculator:
    """SM-2 算法的纯函数实现。"""

    MIN_EF = 1.3
    INITIAL_EF = 2.5

    @staticmethod
    def compute(quality: int, ef: float, interval_days: int,
                repetitions: int, today: date | None = None) -> dict:
        """计算一次复习后的 SM-2 参数。

        Args:
            quality: 0-5 的评分
            ef: 当前难易度因子 (>= 1.3)
            interval_days: 当前间隔（天）
            repetitions: 连续评分 >= 3 的次数
            today: 今天的日期（默认当天）

        Returns:
            dict with keys: ef, interval_days, repetitions, next_review, passed
        """
        if not (0 <= quality <= 5):
            raise ValueError(f"quality must be 0-5, got {quality}")

        today = today or date.today()

        # 计算新的 EF
        new_ef = max(
            SM2Calculator.MIN_EF,
            ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)),
        )

        if quality < 3:
            # 回忆失败：重置重复次数和间隔
            new_repetitions = 0
            new_interval = 1
            passed = False
        else:
            # 回忆成功
            new_repetitions = repetitions + 1
            passed = True

            if new_repetitions == 1:
                new_interval = 1
            elif new_repetitions == 2:
                new_interval = 6
            else:
                new_interval = round(interval_days * new_ef)

        next_review = today + timedelta(days=new_interval)

        return {
            "ef": round(new_ef, 2),
            "interval_days": new_interval,
            "repetitions": new_repetitions,
            "next_review": next_review.isoformat(),
            "passed": passed,
        }

    @staticmethod
    def get_default_node():
        """返回新知识节点的默认 SM-2 参数。"""
        return {
            "ef": SM2Calculator.INITIAL_EF,
            "interval": 0,
            "repetitions": 0,
            "next_review": None,
        }
