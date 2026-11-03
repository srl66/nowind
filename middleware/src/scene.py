"""Phase 2：极简可行动表示（窗口级 affordance 列表 + 增量 patch + 极短 DSL）。

设计约束（来自冻结基线）：
- 只编码「可行动对象」：窗口 / 前台窗口 / 最小化与焦点状态；不做像素、不做 OCR。
- 表示必须可增量：结构性事件走全量重建，LOCATION/NAME 走单窗口 patch。
- 输出为 tokenizer 友好的线性 DSL（尽量少引号、少冗余字段）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import winapi as W
import slip as SLIP


@dataclass(slots=True)
class Win:
    hwnd: int
    title: str
    cls: str
    exe: str
    rect: tuple[int, int, int, int]
    z: int
    minimized: bool
    pid: int

    def key(self) -> tuple:
        return (self.title, self.exe, self.rect, self.z, self.minimized)


_TYPE_SHORT = {
    "Button": "btn", "Edit": "edt", "CheckBox": "chk", "ComboBox": "cbo",
    "RadioButton": "rad", "MenuItem": "mnu", "Hyperlink": "lnk", "ListItem": "li",
    "TabItem": "tab", "SplitButton": "spl", "Slider": "sld", "Spinner": "spn",
    "DataItem": "dit", "TreeItem": "tri", "Document": "doc",
}


@dataclass
class Scene:
    self_pid: int
    max_windows: int = 12
    wins: dict[int, Win] = field(default_factory=dict)
    fg: int = 0
    rebuilds: int = 0
    patches: int = 0
    affordances: list[dict] = field(default_factory=list)
    affordance_hwnd: int = 0
    aff_seen: int = 0
    last_obs: dict = field(default_factory=dict)
    slip: object = None
    aff_sid: str = ""
    aff_repeat: bool = False
    mn_sid: str = ""
    mn_repeat: bool = False

    # ---------------------------------------------------------------- SLIP
    def prepare(self) -> None:
        """渲染前算好两棵子树的 SID，并标记“该子树是否已经见过”。

        R10 修复（D-039）：折叠判据从“与上一次发布相同”改为“该 SID 在指纹缓存里出现过”
        （即 intern 的 is_new=False）。旧判据在事件驱动发布下几乎不成立：一个静态窗口
        通常只发布一次，第二次折叠永远等不到；新判据对“同一个对话框再次弹出”也成立。
        契约不变：某个 SID 的**第一次**出现一定发完整子树，冷启动 reader 仍只需等一次完整提交。
        """
        if self.slip is None:
            return
        acts = [a for a in self.affordances if a.get("e") and not a.get("o")]
        w = self.wins.get(self.affordance_hwnd) or self.wins.get(self.fg)
        origin = (w.rect[0], w.rect[1]) if w else None
        if acts:
            self.aff_sid, is_new = self.slip.intern(SLIP.items_key(acts, origin))
            self.aff_repeat = bool(self.aff_sid) and not is_new
        else:
            self.aff_sid, self.aff_repeat = "", False

        mins = [w2.title for w2 in self.wins.values() if w2.minimized]
        if mins:
            self.mn_sid, mn_new = self.slip.intern(SLIP.titles_key(mins))
            self.mn_repeat = bool(self.mn_sid) and not mn_new
        else:
            self.mn_sid, self.mn_repeat = "", False

    # ---------------------------------------------------------------- 全量
    def rebuild(self) -> None:
        rows = W.enum_windows(exclude_pid=self.self_pid, max_n=self.max_windows)
        self.wins = {
            r["hwnd"]: Win(r["hwnd"], r["title"], r["cls"], r["exe"], r["rect"], r["z"], r["min"], r["pid"])
            for r in rows
        }
        self.fg = W.foreground_hwnd()
        self.rebuilds += 1

    # ---------------------------------------------------------------- 增量
    def patch(self, hwnds: set[int]) -> bool:
        """只更新受影响窗口。返回 False 表示需要全量重建（出现/消失顶层窗口）。"""
        if not self.wins:
            return False
        for h in hwnds:
            if not h:
                continue
            w = self.wins.get(h)
            if w is None:
                # 未知 hwnd：仅当它是新的顶层可见窗口时才值得全量重建；
                # 子控件（Edit/Button 等）不改变窗口级表示，直接忽略。
                if W.user32.IsWindowVisible(h) and W.is_top_level(h) and W.title_of(h):
                    return False
                continue
            if not W.user32.IsWindowVisible(h):
                return False          # 窗口消失 -> 交给全量
            w.title = W.title_of(h)
            w.rect = W.rect_of(h)
            w.minimized = bool(W.user32.IsIconic(h))
        self.fg = W.foreground_hwnd()
        self.patches += 1
        return True

    # ---------------------------------------------------------------- 渲染
    @staticmethod
    def _clean(t: str, cap: int) -> str:
        t = " ".join(t.split()).replace("|", "/")
        return t if len(t) <= cap else t[:cap - 1] + "…"

    def render(self, version: int, age_ms: float, mode: str, dirty_n: int, level: int = 1) -> str:
        """极简可行动表示。

        token 策略（VITAL v0）：
        - 可见窗口 = 一等公民（标题 32 字上限，前台 48），带坐标与 z 序；
        - 最小化窗口不可见、不参与点击，折叠为一行名字列表（每个 16 字上限）；
        - exe 名只保留给可见窗口，前景用 * 标记。

        level 是 token 预算的裁剪档：1=正常；2/3=发布前超预算时逐级收缩。
        """
        caps = {1: (6, 8, 6), 2: (5, 8, 5), 3: (4, 6, 4), 4: (3, 4, 3)}
        n_win, n_act, n_min = caps.get(level, caps[4])
        visible_all = sorted((w for w in self.wins.values() if not w.minimized),
                             key=lambda w: (0 if w.hwnd == self.fg else 1, w.z))
        visible = visible_all[:n_win]
        minimized = sorted((w for w in self.wins.values() if w.minimized), key=lambda w: w.z)

        fg_key = "?"
        lines = []
        for i, w in enumerate(visible, 1):
            if w.hwnd == self.fg:
                fg_key = f"W{i}"
            cap = 48 if w.hwnd == self.fg else 32
            flag = "*" if w.hwnd == self.fg else ""
            lines.append(
                f"W{i} {self._clean(w.title, cap)}|{w.exe}|"
                f"{w.rect[0]},{w.rect[1]},{w.rect[2]},{w.rect[3]}|z{w.z}{flag}"
            )

        if minimized:
            if self.mn_repeat and self.mn_sid:
                lines.append(f"MN #{self.mn_sid}")
            else:
                names = [self._clean(w.title, 16) for w in minimized[:n_min]]
                more = f"+{len(minimized) - n_min}" if len(minimized) > n_min else ""
                line = "MN " + ",".join(names) + more
                if self.mn_sid:
                    line += f" #{self.mn_sid}"
                lines.append(line)

        acts = [a for a in self.affordances if a.get("e") and not a.get("o")][:n_act]
        if acts:
            if self.aff_repeat and self.aff_sid:
                lines.append(f"A #{self.aff_sid}")
            else:
                seg = []
                for a in acts:
                    r = a.get("r") or [0, 0, 0, 0]
                    nm = self._clean(a.get("n") or "-", 12)
                    tp = _TYPE_SHORT.get(a.get("t", ""), (a.get("t") or "")[:3].lower() or "ctl")
                    seg.append(f"{nm}/{tp}@{r[0]},{r[1]},{r[2]},{r[3]}")
                line = "A " + "; ".join(seg)
                if self.aff_sid:
                    line += f" #{self.aff_sid}"
                lines.append(line)

        if self.last_obs:
            rb = self._clean(str(self.last_obs.get("rb") or ""), 40)
            ok = "ok" if self.last_obs.get("ok") else "fail"
            op = self.last_obs.get("op") or "?"
            lines.append(f"R {ok}|{op}|{rb}")

        head = (f"@v{version} n={len(self.wins)} v={len(visible_all)} m={len(minimized)} "
                f"fg={fg_key} a={age_ms:.1f} u={1 if acts else 0}")
        return "\n".join([head] + lines)


def est_tokens(s: str) -> int:
    """ESTIMATE（非真实 tokenizer）：CJK 每字 1 token，ASCII 按 4 字符 1 token。

    真实 token 数必须在 Phase 4 用目标 tokenizer 复测，此函数只用于运行时预算粗估。
    """
    ascii_n = sum(1 for ch in s if ord(ch) < 128)
    cjk_n = len(s) - ascii_n
    return int(cjk_n + math.ceil(ascii_n / 4.0))
