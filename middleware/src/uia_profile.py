"""按应用（exe）维护 UIA 查询耗时画像，动态决定超时档位。

动机（实测）：记事本稳态 ~1.9ms，Electron/Chromium 前台 >40ms。
固定 8/40ms 会让慢应用反复触发硬档熔断（杀宿主 + 2s 重启窗口）。
做法：按 exe 记账，慢应用自动放宽到 60/150ms，只在后台刷新，不进关键路径。
"""
from __future__ import annotations

import json
import os
import threading

# tier -> (soft deadline ms, hard kill ms)
TIERS = {
    "probing": (60.0, 150.0),   # 新应用：先给宽松档，探两次再说
    "fast": (8.0, 40.0),        # 经典 Win32
    "standard": (20.0, 80.0),   # 中等
    "slow": (60.0, 150.0),      # Electron/Chromium 等
}


class UiaProfile:
    def __init__(self, path: str, window: int = 24, fast_ms: float = 8.0, std_ms: float = 40.0):
        self.path = path
        self.window = window
        self.fast_ms = fast_ms
        self.std_ms = std_ms
        self._lock = threading.Lock()
        self.data: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------ 持久化
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception:
            self.data = {}

    def save(self) -> None:
        with self._lock:
            snap = dict(self.data)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)

    def _state(self, exe: str) -> dict:
        st = self.data.get(exe)
        if st is None:
            st = {"exe": exe, "n": 0, "samples": [], "timeouts": 0,
                  "tier": "probing", "fast_run": 0, "p95_ms": None}
            self.data[exe] = st
        return st

    # ------------------------------------------------------------------ 记录
    def record(self, exe: str, ms: float) -> None:
        if not exe:
            return
        with self._lock:
            st = self._state(exe)
            st["n"] += 1
            st["samples"].append(round(float(ms), 3))
            if len(st["samples"]) > self.window:
                st["samples"] = st["samples"][-self.window:]
            st["fast_run"] = st["fast_run"] + 1 if ms <= self.fast_ms else 0
            self._recompute(st)

    def note_timeout(self, exe: str) -> None:
        if not exe:
            return
        with self._lock:
            st = self._state(exe)
            st["n"] += 1
            st["timeouts"] += 1
            st["fast_run"] = 0
            self._recompute(st)

    def _recompute(self, st: dict) -> None:
        s = sorted(st["samples"])
        st["p95_ms"] = round(s[min(len(s) - 1, int(len(s) * 0.95))], 3) if s else None
        p95 = st["p95_ms"]

        if st["timeouts"] >= 2:
            st["tier"] = "slow"
            return
        if st["n"] < 3 or p95 is None:
            st["tier"] = "probing"
            return

        if st["timeouts"] >= 1:
            target = "slow" if (p95 or 0) > self.std_ms else "standard"
        elif p95 <= self.fast_ms:
            target = "fast"
        elif p95 <= self.std_ms:
            target = "standard"
        else:
            target = "slow"

        order = ["fast", "probing", "standard", "slow"]
        cur = st["tier"]
        if target == cur:
            return
        # 降档要连续 20 次够快；升档立即生效
        if order.index(target) < order.index(cur) and st["fast_run"] < 20:
            return
        st["tier"] = target

    # ------------------------------------------------------------------ 查询
    def budget(self, exe: str) -> tuple[float, float, str]:
        with self._lock:
            st = self._state(exe)
            tier = st["tier"]
        return (*TIERS.get(tier, TIERS["probing"]), tier)

    def summary(self) -> dict:
        with self._lock:
            out = {}
            for exe, st in self.data.items():
                out[exe] = {"n": st["n"], "p95_ms": st["p95_ms"], "timeouts": st["timeouts"],
                            "tier": st["tier"]}
            return out
