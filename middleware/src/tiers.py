"""三档 token 预算判定（纯函数，便于单测）。

复杂度 = 2×可交互控件数 + 窗口数 + 已扫描元素数/2。
  ≤24   -> basic   (~150 token)
  ≤60   -> battle  (~350 token)
  >60   -> extreme (~1000 token)
"""
from __future__ import annotations

TIERS = {"basic": 150, "battle": 350, "extreme": 1000}


def choose_tier(n_ctrl: int, n_wins: int, seen: int) -> tuple[str, int, int]:
    complexity = 2 * int(n_ctrl) + int(n_wins) + int(seen) // 2
    if complexity <= 24:
        return "basic", TIERS["basic"], complexity
    if complexity <= 60:
        return "battle", TIERS["battle"], complexity
    return "extreme", TIERS["extreme"], complexity
