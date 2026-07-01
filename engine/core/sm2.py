"""Pure SM-2 spaced repetition algorithm.

Based on the SuperMemo SM-2 algorithm by Piotr Wozniak.
https://www.supermemo.com/en/archives1990-2015/english/ol/sm2
"""

from datetime import date, timedelta
from typing import Optional


class SM2Calculator:
    """SuperMemo SM-2 algorithm implementation.

    Pure functions, no side effects. All inputs explicit.
    """

    @staticmethod
    def compute(
        quality: int,
        ef: float = 2.5,
        interval_days: int = 0,
        repetitions: int = 0,
        today: Optional[date] = None,
    ) -> dict:
        """Compute SM-2 review parameters.

        Args:
            quality: User's recall quality (0-5).
            ef: Current easiness factor (>= 1.3).
            interval_days: Current interval in days.
            repetitions: Current repetition count.
            today: Reference date (defaults to today).

        Returns:
            dict with keys: ef, interval, repetitions, next_review, quality
        """
        today = today or date.today()

        # Clamp quality
        quality = max(0, min(5, quality))

        # If quality < 3, reset repetitions
        if quality < 3:
            repetitions = 0
            interval = 1
        else:
            if repetitions == 0:
                interval = 1
            elif repetitions == 1:
                interval = 6
            else:
                interval = round(interval_days * ef)

            repetitions += 1

        # Update EF
        ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        if ef < 1.3:
            ef = 1.3

        next_review = today + timedelta(days=interval)

        return {
            "ef": round(ef, 2),
            "interval": interval,
            "repetitions": repetitions,
            "next_review": next_review.isoformat(),
            "quality": quality,
        }

    @staticmethod
    def get_default_node() -> dict:
        """Return default SM-2 params for a new node."""
        return {
            "ef": 2.5,
            "interval": 0,
            "repetitions": 0,
            "next_review": None,
        }
