"""Causal indicator state for supplied-bar research; never sends broker orders."""


def ema_crossovers(rows, fast: int, slow: int):
    """First-close-seeded EMA, alpha=2/(window+1), with slow+1-close warmup.

    The caller supplies only the historical prefix available for evaluation.
    State continues across folds; the indicator is not reseeded at OOS boundaries.
    """
    sides = [None] * len(rows)
    if not rows:
        return sides
    fast_ema = slow_ema = float(rows[0]["close"])
    fast_alpha, slow_alpha = 2 / (fast + 1), 2 / (slow + 1)
    for index, row in enumerate(rows[1:], 1):
        previous_fast, previous_slow = fast_ema, slow_ema
        close = float(row["close"])
        fast_ema += fast_alpha * (close - fast_ema)
        slow_ema += slow_alpha * (close - slow_ema)
        if index < slow:
            continue
        if previous_fast <= previous_slow and fast_ema > slow_ema:
            sides[index] = "buy"
        elif previous_fast >= previous_slow and fast_ema < slow_ema:
            sides[index] = "sell"
    return sides
