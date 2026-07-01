"""SM-2 算法测试"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import date
from engine.core.sm2 import SM2Calculator


def test_first_review_quality_5():
    """首次复习 quality=5: interval=1, reps=1, ef 微增"""
    result = SM2Calculator.compute(quality=5, ef=2.5, interval_days=0, repetitions=0)
    assert result["interval"] == 1
    assert result["repetitions"] == 1
    assert result["ef"] > 2.5  # should increase
    assert result["next_review"] is not None


def test_first_review_quality_0():
    """首次复习 quality=0: reps 重置, interval=1, ef 下降"""
    result = SM2Calculator.compute(quality=0, ef=2.5, interval_days=0, repetitions=0)
    assert result["interval"] == 1
    assert result["repetitions"] == 0  # reset
    assert result["ef"] < 2.5


def test_second_review_good():
    """第二次复习 quality>=3: interval=6"""
    result = SM2Calculator.compute(quality=4, ef=2.5, interval_days=1, repetitions=1)
    assert result["interval"] == 6
    assert result["repetitions"] == 2


def test_third_review_good():
    """第三次复习 quality>=3: interval = round(6 * ef)"""
    result = SM2Calculator.compute(quality=5, ef=2.5, interval_days=6, repetitions=2)
    assert result["interval"] == 15  # 6 * 2.5 = 15
    assert result["repetitions"] == 3


def test_quality_below_3_resets():
    """quality < 3 重置 repetition"""
    result = SM2Calculator.compute(quality=2, ef=2.5, interval_days=15, repetitions=5)
    assert result["repetitions"] == 0
    assert result["interval"] == 1  # reset to 1


def test_ef_floor():
    """EF 最低 1.3"""
    result = SM2Calculator.compute(quality=0, ef=1.3, interval_days=1, repetitions=0)
    assert result["ef"] >= 1.3


def test_quality_clamping():
    """quality 被 clamp 到 0-5"""
    r1 = SM2Calculator.compute(quality=6, ef=2.5, interval_days=0, repetitions=0)
    r2 = SM2Calculator.compute(quality=-1, ef=2.5, interval_days=0, repetitions=0)
    assert r1["quality"] == 5
    assert r2["quality"] == 0


def test_next_review_date():
    """next_review = today + interval"""
    from datetime import timedelta
    today = date(2026, 7, 1)
    result = SM2Calculator.compute(quality=5, ef=2.5, interval_days=0, repetitions=0, today=today)
    expected = today + timedelta(days=1)
    assert result["next_review"] == expected.isoformat()


def test_get_default_node():
    default = SM2Calculator.get_default_node()
    assert default["ef"] == 2.5
    assert default["interval"] == 0
    assert default["repetitions"] == 0
    assert default["next_review"] is None


def test_ef_calculation():
    """验证 EF 计算公式: EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))"""
    q = 4
    expected_ef = 2.5 + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    result = SM2Calculator.compute(quality=q, ef=2.5, interval_days=0, repetitions=0)
    assert abs(result["ef"] - round(expected_ef, 2)) < 0.01


if __name__ == "__main__":
    for name, fn in sorted({k: v for k, v in globals().items() if k.startswith("test_")}.items()):
        fn()
        print(f"  PASS {name}")
    print("All SM-2 tests passed")
