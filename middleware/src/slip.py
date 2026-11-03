"""SLIP — Structural Layout & Icon Print（结构指纹 + SID 复用）。

原理：
- 把一组 UI 子树规范化成“稳定字段”串：控件类型 / AutomationId / 名称 / 相对窗体的位置（8px 量化）；
- 剥离易变字段：Value（输入文本）、绝对坐标、z 序、hwnd、时间戳；
- 用 blake2b(3 字节) 取 6 位十六进制作为 SID（24 bit）；
- 同一 SID 再次出现时，表示里只写 `#SID`，不再重发整棵子树。

定位：只服务“表示渲染”。不参与感知与动作；命中/未命中都无副作用。
安全边界：SID 只表示“与上一次提交里该子树相同”，冷启动的 reader 必须等一次完整提交。
"""
from __future__ import annotations

import hashlib
import re


def _norm(s: str, cap: int = 24) -> str:
    s = " ".join((s or "").split())
    return s[:cap]


def _q(v: int, step: int = 8) -> int:
    return int(round(v / step)) * step


def items_key(items: list[dict], origin: tuple[int, int] | None = None) -> str:
    """前台控件集合的稳定指纹。origin = 窗口左上角，用于把绝对坐标转成相对坐标。"""
    parts = []
    ox, oy = origin if origin else (0, 0)
    for it in items:
        r = it.get("r") or [0, 0, 0, 0]
        parts.append("|".join([
            str(it.get("t") or ""),
            str(it.get("id") or ""),
            _norm(it.get("n") or ""),
            str(_q(r[0] - ox)), str(_q(r[1] - oy)), str(int(r[2])), str(int(r[3])),
        ]))
    return "\n".join(sorted(parts))


def titles_key(titles: list[str]) -> str:
    return "\n".join(sorted(_norm(t, 16) for t in titles))


class SlipCache:
    def __init__(self, cap: int = 64):
        self.cap = cap
        self._map: dict[str, str] = {}
        self._order: list[str] = []
        self.stats = {"interned": 0, "hits": 0, "evicted": 0, "collisions": 0}

    @staticmethod
    def sid_of(key: str) -> str:
        h = hashlib.blake2b(key.encode("utf-8"), digest_size=3).hexdigest()
        return h

    def intern(self, key: str) -> tuple[str, bool]:
        """返回 (sid, is_new)。is_new 表示这张指纹第一次见。"""
        if not key:
            return "", False
        sid = self.sid_of(key)
        old = self._map.get(sid)
        if old is not None:
            if old != key:
                self.stats["collisions"] += 1   # 24-bit 冲突：同 sid 不同内容，仍按已知处理但记账
            self.stats["hits"] += 1
            return sid, False
        self._map[sid] = key
        self._order.append(sid)
        self.stats["interned"] += 1
        if len(self._order) > self.cap:
            evict = self._order.pop(0)
            self._map.pop(evict, None)
            self.stats["evicted"] += 1
        return sid, True


_SID_RE = re.compile(r"^#?[0-9a-f]{6}$")
