"""动作执行器（Phase 3：动作执行闭环）。

职责：把「感知到的 affordance」变成真实输入。
- 点击：SendInput 绝对坐标（虚拟桌面坐标系），点前做遮挡预检，绝不盲点。
- 输入：SendInput + KEYEVENTF_UNICODE（绕过键盘布局/输入法，中文也能打；但不触发 IME 候选）。
- 焦点恢复：AttachThreadInput 抢前台（Windows 前台锁的标准绕法），并轮询确认。
- 每步都计时：prepare / input / verify / total，单位 µs。

安全边界：
- 不做全屏盲点；坐标必须由调用方从感知结果里给出。
- 目标被其它窗口遮挡时不点，先抢前台再复查；仍遮挡则返回失败（绝不误点）。
- 目标最小化时先 SW_RESTORE。
"""
from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import POINTER, Structure, Union, byref, c_int, c_long, c_short, c_ulong, c_ushort, c_size_t, sizeof, wintypes
from dataclasses import dataclass, field

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = c_size_t


class MOUSEINPUT(Structure):
    _fields_ = [("dx", c_long), ("dy", c_long), ("mouseData", c_ulong),
                ("dwFlags", c_ulong), ("time", c_ulong), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(Structure):
    _fields_ = [("wVk", c_ushort), ("wScan", c_ushort), ("dwFlags", c_ulong),
                ("time", c_ulong), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(Structure):
    _fields_ = [("uMsg", c_ulong), ("wParamL", c_short), ("wParamH", c_ushort)]


class _INPUTUNION(Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", c_ulong), ("u", _INPUTUNION)]


class GUITHREADINFO(Structure):
    _fields_ = [("cbSize", c_ulong), ("flags", c_ulong),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_WHEEL = 0x0800

# 快捷键用到的虚拟键（不依赖键盘布局；普通文字仍走 type_text 的 Unicode 输入）
_VK_NAMED = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}
_VK_MODS = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12,
            "win": 0x5B, "meta": 0x5B}
GA_ROOT = 2
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
SW_RESTORE = 9
WM_GETTEXT = 0x000D
CF_UNICODETEXT = 13

user32.SendInput.argtypes = [c_ulong, POINTER(INPUT), c_int]
user32.SendInput.restype = c_ulong
user32.GetSystemMetrics.argtypes = [c_int]
user32.GetSystemMetrics.restype = c_int
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.BringWindowToTop.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class POINT(Structure):
    _fields_ = [("x", c_long), ("y", c_long)]


user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, c_ulong]
user32.GetAncestor.restype = wintypes.HWND
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, c_int]
user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, POINTER(GUITHREADINFO)]
user32.GetGUIThreadInfo.restype = wintypes.BOOL
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.CloseClipboard.restype = wintypes.BOOL
kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
kernel32.GlobalUnlock.restype = wintypes.BOOL


@dataclass
class ActionResult:
    action: str
    ok: bool
    t_total_us: int = 0
    t_prepare_us: int = 0
    t_input_us: int = 0
    t_verify_us: int = 0
    restored: bool = False
    occluded: bool = False
    focus_ok: bool = False
    sent: int = 0
    reason: str = ""

    def as_dict(self) -> dict:
        return self.__dict__.copy()


class _FocusReq:
    """一次抢焦点请求。焦点线程执行，调用线程最多等 fuse_ms。"""
    __slots__ = ("hwnd", "deadline_ns", "done", "ok", "abandoned")

    def __init__(self, hwnd: int, deadline_ns: int):
        self.hwnd = int(hwnd)
        self.deadline_ns = deadline_ns
        self.done = threading.Event()
        self.ok = False
        self.abandoned = False


class ActionExecutor:
    def __init__(self, restore_timeout_ms: float = 50.0, focus_timeout_ms: float = 60.0):
        self.restore_timeout_ms = restore_timeout_ms
        self.focus_timeout_ms = focus_timeout_ms
        self._v = None
        self.stats = {"clicks": 0, "click_ok": 0, "types": 0, "type_ok": 0,
                      "restores": 0, "restore_ok": 0, "occluded_blocks": 0,
                      "focus_fuse_trips": 0, "focus_fallbacks": 0}
        self._focus_q: "queue.Queue" = queue.Queue()
        self._focus_busy = False
        self._focus_lock = threading.Lock()
        threading.Thread(target=self._focus_worker, name="focus-worker", daemon=True).start()

    # ------------------------------------------------------------------ 基础
    def _vmetrics(self) -> tuple[int, int, int, int]:
        if self._v is None:
            self._v = (user32.GetSystemMetrics(SM_XVIRTUALSCREEN),
                       user32.GetSystemMetrics(SM_YVIRTUALSCREEN),
                       max(1, user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
                       max(1, user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)))
        return self._v

    def _abs(self, x: int, y: int) -> tuple[int, int]:
        vx, vy, vw, vh = self._vmetrics()
        dx = int((x - vx) * 65535 / (vw - 1)) if vw > 1 else 0
        dy = int((y - vy) * 65535 / (vh - 1)) if vh > 1 else 0
        return max(0, min(65535, dx)), max(0, min(65535, dy))

    @staticmethod
    def _mouse(dx: int, dy: int, flags: int, data: int = 0) -> INPUT:
        it = INPUT(type=INPUT_MOUSE)
        it.mi = MOUSEINPUT(dx, dy, data, flags, 0, 0)
        return it

    @staticmethod
    def _key(scan: int, flags: int) -> INPUT:
        """Unicode 输入用：wVk=0，字符码放 wScan。"""
        it = INPUT(type=INPUT_KEYBOARD)
        it.ki = KEYBDINPUT(0, scan, flags, 0, 0)
        return it

    @staticmethod
    def _vk(vk: int, flags: int) -> INPUT:
        """虚拟键用：VK 放 wVk、wScan=0（之前把 VK 塞进 wScan 导致按键无效）。"""
        it = INPUT(type=INPUT_KEYBOARD)
        it.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
        return it

    @staticmethod
    def _send(items: list[INPUT]) -> int:
        n = len(items)
        arr = (INPUT * n)(*items)
        return int(user32.SendInput(n, arr, sizeof(INPUT)))

    # ------------------------------------------------------------------ 焦点
    @staticmethod
    def foreground() -> int:
        return int(user32.GetForegroundWindow() or 0)

    @staticmethod
    def _root(hwnd: int) -> int:
        return int(user32.GetAncestor(hwnd, GA_ROOT) or 0)

    def is_occluded(self, hwnd: int, x: int, y: int) -> bool:
        w = int(user32.WindowFromPoint(POINT(x, y)) or 0)
        if not w:
            return True
        return self._root(w) != hwnd

    def activate(self, hwnd: int, timeout_ms: float | None = None) -> bool:
        """把窗口抢到前台，带 50ms 熔断。

        真正的 COM/输入同步动作全部在独立焦点线程里做，调用线程最多阻塞 fuse_ms；
        超时立刻放弃等待、由调用线程用 SetForegroundWindow 兜底；
        焦点线程在 finally 里无条件 DetachThreadInput，绝不长时间挂着。
        """
        tmo = self.restore_timeout_ms if timeout_ms is None else timeout_ms
        hwnd = int(hwnd)
        if self.foreground() == hwnd:
            return True
        with self._focus_lock:
            busy = self._focus_busy
            if not busy:
                self._focus_busy = True
        if busy:
            # 已有请求在途（可能卡死）：不再排队，直接走兜底（必须在锁外调用，否则自锁死）
            self.stats["focus_fuse_trips"] += 1
            return self._fallback_activate(hwnd)

        req = _FocusReq(hwnd, time.perf_counter_ns() + int(tmo * 1e6))
        self._focus_q.put(req)
        finished = req.done.wait(tmo / 1000.0)
        if finished:
            with self._focus_lock:
                self._focus_busy = False
            return req.ok

        # 超时：放弃这次抢焦点，立刻兜底（调用线程不会再被卡住）
        req.abandoned = True
        self.stats["focus_fuse_trips"] += 1
        return self._fallback_activate(hwnd)

    def _fallback_activate(self, hwnd: int) -> bool:
        """兜底激活：绝不阻塞调用线程。

        实测教训：目标线程被挂起时，SetForegroundWindow 会跟着卡死；
        所以兜底也丢到独立线程（fire-and-forget），本次立即返回 False（= 未确认）。
        动作是否真的生效，由后续的焦点校验（GetGUIThreadInfo）判定，绝不靠“以为成功了”。
        """
        self.stats["focus_fallbacks"] += 1
        with self._focus_lock:
            if getattr(self, "_fallback_running", False):
                return False
            self._fallback_running = True

        def _impl():
            try:
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, SW_RESTORE)
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
            except Exception:
                pass
            finally:
                with self._focus_lock:
                    self._fallback_running = False

        threading.Thread(target=_impl, name="focus-fallback", daemon=True).start()
        return False

    def _focus_worker(self):
        """独立线程执行 attach/激活；任何路径退出前都必须 detach。"""
        while True:
            req = self._focus_q.get()
            t0 = time.perf_counter_ns()
            attached = False
            cur_tid = int(kernel32.GetCurrentThreadId())
            fg_tid = 0
            ok = False
            try:
                if self.foreground() == req.hwnd:
                    ok = True
                    continue_running = False
                else:
                    continue_running = True
                if continue_running and user32.IsIconic(req.hwnd):
                    user32.ShowWindow(req.hwnd, SW_RESTORE)
                fg = self.foreground()
                expired = lambda: time.perf_counter_ns() >= req.deadline_ns or req.abandoned
                if not expired() and fg and fg != req.hwnd:
                    fg_tid = int(user32.GetWindowThreadProcessId(fg, None))
                    if fg_tid and fg_tid != cur_tid:
                        attached = bool(user32.AttachThreadInput(cur_tid, fg_tid, True))
                if not expired():
                    user32.BringWindowToTop(req.hwnd)
                    user32.SetForegroundWindow(req.hwnd)
                ok = self.foreground() == req.hwnd
            except Exception:
                ok = False
            finally:
                if attached:
                    user32.AttachThreadInput(cur_tid, fg_tid, False)
                req.ok = ok
                req.done.set()
                with self._focus_lock:
                    self._focus_busy = False
                self.stats.setdefault("focus_calls", 0)
                self.stats["focus_calls"] += 1

    def focused_in(self, hwnd: int) -> bool:
        tid = int(user32.GetWindowThreadProcessId(hwnd, None))
        gti = GUITHREADINFO()
        gti.cbSize = sizeof(GUITHREADINFO)
        if not user32.GetGUIThreadInfo(tid, byref(gti)):
            return False
        f = int(gti.hwndFocus or 0)
        return bool(f) and self._root(f) == hwnd

    def _wait_focus(self, hwnd: int, timeout_ms: float) -> bool:
        deadline = time.perf_counter_ns() + int(timeout_ms * 1e6)
        while time.perf_counter_ns() < deadline:
            if self.focused_in(hwnd):
                return True
            time.sleep(0.0005)
        return self.focused_in(hwnd)

    # ------------------------------------------------------------------ 点击
    def click(self, hwnd: int, x: int, y: int, button: str = "left",
              restore: bool = True) -> ActionResult:
        res = ActionResult(action=f"{button}-click@{x},{y}", ok=False)
        t0 = time.perf_counter_ns()

        if restore and self.foreground() != hwnd:
            res.restored = self.activate(hwnd)
            if res.restored:
                self.stats["restores"] += 1
                self.stats["restore_ok"] += 1
            else:
                self.stats["restores"] += 1

        res.occluded = self.is_occluded(hwnd, x, y)
        if res.occluded:
            # 被别的窗口盖住：先抢前台再复查；仍被盖住就绝不点
            self.activate(hwnd, timeout_ms=80)
            user32.BringWindowToTop(hwnd)
            res.occluded = self.is_occluded(hwnd, x, y)
            if res.occluded:
                self.stats["occluded_blocks"] += 1
                res.t_prepare_us = (time.perf_counter_ns() - t0) // 1000
                res.t_total_us = res.t_prepare_us
                res.reason = "occluded"
                self.stats["clicks"] += 1
                return res

        res.t_prepare_us = (time.perf_counter_ns() - t0) // 1000

        dx, dy = self._abs(x, y)
        down = MOUSEEVENTF_LEFTDOWN if button == "left" else MOUSEEVENTF_RIGHTDOWN
        up = MOUSEEVENTF_LEFTUP if button == "left" else MOUSEEVENTF_RIGHTUP
        items = [
            self._mouse(dx, dy, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
            self._mouse(dx, dy, down),
            self._mouse(dx, dy, up),
        ]
        t1 = time.perf_counter_ns()
        res.sent = self._send(items)
        res.t_input_us = (time.perf_counter_ns() - t1) // 1000

        t2 = time.perf_counter_ns()
        res.focus_ok = self._wait_focus(hwnd, self.focus_timeout_ms)
        res.t_verify_us = (time.perf_counter_ns() - t2) // 1000
        res.t_total_us = (time.perf_counter_ns() - t0) // 1000

        res.ok = res.sent == len(items) and res.focus_ok
        if res.sent != len(items):
            res.reason = f"sendinput-{res.sent}/{len(items)}"
        elif not res.focus_ok:
            res.reason = "focus-not-in-target"
        self.stats["clicks"] += 1
        if res.ok:
            self.stats["click_ok"] += 1
        return res

    # ------------------------------------------------------------------ 输入
    def type_text(self, text: str, hwnd: int | None = None, interval_us: int = 0) -> ActionResult:
        res = ActionResult(action=f"type[{len(text)}]", ok=False)
        t0 = time.perf_counter_ns()

        if hwnd is not None and not self.focused_in(hwnd):
            if self.foreground() != hwnd:
                res.restored = self.activate(hwnd)
            res.t_prepare_us = (time.perf_counter_ns() - t0) // 1000
            if not self.focused_in(hwnd):
                res.reason = "no-focus-in-target"
                res.t_total_us = (time.perf_counter_ns() - t0) // 1000
                self.stats["types"] += 1
                return res
        else:
            res.t_prepare_us = (time.perf_counter_ns() - t0) // 1000

        items: list[INPUT] = []
        for unit in self._utf16_units(text):
            items.append(self._key(unit, KEYEVENTF_UNICODE))
            items.append(self._key(unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        t1 = time.perf_counter_ns()
        if interval_us > 0:
            sent = 0
            for it in items:
                sent += self._send([it])
                time.sleep(interval_us / 1e6)
        else:
            sent = self._send(items)
        res.sent = sent
        res.t_input_us = (time.perf_counter_ns() - t1) // 1000
        res.t_total_us = (time.perf_counter_ns() - t0) // 1000
        res.ok = sent == len(items)
        if not res.ok:
            res.reason = f"sendinput-{sent}/{len(items)}"
        self.stats["types"] += 1
        if res.ok:
            self.stats["type_ok"] += 1
        return res

    @staticmethod
    def _utf16_units(text: str) -> list[int]:
        b = text.encode("utf-16-le")
        return [int.from_bytes(b[i:i + 2], "little") for i in range(0, len(b), 2)]

    # ------------------------------------------------------------------ 按键
    def press_vk(self, vk: int) -> ActionResult:
        """发送一个虚拟键（如 VK_RETURN=0x0D）。"""
        res = ActionResult(action=f"vk-{vk:#x}", ok=False)
        t0 = time.perf_counter_ns()
        items = [self._vk(vk, 0), self._vk(vk, KEYEVENTF_KEYUP)]
        t1 = time.perf_counter_ns()
        res.sent = self._send(items)
        res.t_input_us = (time.perf_counter_ns() - t1) // 1000
        res.t_total_us = (time.perf_counter_ns() - t0) // 1000
        res.ok = res.sent == len(items)
        return res

    @staticmethod
    def _vk_of(name: str) -> int | None:
        n = name.strip().lower()
        if n in _VK_MODS:
            return _VK_MODS[n]
        if n in _VK_NAMED:
            return _VK_NAMED[n]
        if len(n) == 1 and n.isalnum():
            return ord(n.upper())
        return None

    def press_combo(self, combo: str) -> ActionResult:
        """发送组合键，如 ctrl+l / ctrl+a / alt+tab / ctrl+shift+tab / enter。"""
        parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
        res = ActionResult(action=f"keys[{combo}]", ok=False)
        if not parts:
            res.reason = "empty-keys"
            return res
        vks: list[int] = []
        for i, p in enumerate(parts):
            vk = self._vk_of(p)
            if vk is None:
                res.reason = f"unknown-key:{p}"
                return res
            if i < len(parts) - 1 and p not in _VK_MODS:
                res.reason = f"not-a-modifier:{p}"
                return res
            vks.append(vk)
        mods, key = vks[:-1], vks[-1]
        items = [self._vk(v, 0) for v in mods]
        items += [self._vk(key, 0), self._vk(key, KEYEVENTF_KEYUP)]
        items += [self._vk(v, KEYEVENTF_KEYUP) for v in reversed(mods)]
        t0 = time.perf_counter_ns()
        res.sent = self._send(items)
        res.t_input_us = (time.perf_counter_ns() - t0) // 1000
        res.ok = res.sent == len(items)
        if not res.ok:
            res.reason = f"sendinput-{res.sent}/{len(items)}"
        return res

    def scroll(self, x: int, y: int, delta: int) -> ActionResult:
        """在指定屏幕坐标滚动滚轮；delta<0 向下，>0 向上（单位：格）。"""
        res = ActionResult(action=f"scroll@{x},{y}*{delta}", ok=False)
        dx, dy = self._abs(x, y)
        items = [
            self._mouse(dx, dy, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
            self._mouse(0, 0, MOUSEEVENTF_WHEEL, (int(delta) * 120) & 0xFFFFFFFF),
        ]
        t0 = time.perf_counter_ns()
        res.sent = self._send(items)
        res.t_input_us = (time.perf_counter_ns() - t0) // 1000
        res.ok = res.sent == len(items)
        if not res.ok:
            res.reason = f"sendinput-{res.sent}/{len(items)}"
        return res

    def clipboard_get(self, max_chars: int = 8000) -> str:
        """读当前剪贴板文本（配合 Ctrl+A / Ctrl+C 抓网页正文）。"""
        if not user32.OpenClipboard(None):
            return ""
        try:
            h = user32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return ""
            ptr = kernel32.GlobalLock(h)
            if not ptr:
                return ""
            try:
                s = ctypes.c_wchar_p(ptr).value or ""
            finally:
                kernel32.GlobalUnlock(h)
            return s[:max_chars]
        finally:
            user32.CloseClipboard()

    # ------------------------------------------------------------------ 读回
    @staticmethod
    def read_edit_text(hwnd: int, max_chars: int = 2048) -> str | None:
        """Win32 兜底读回：找子 Edit 控件，WM_GETTEXT。找不到 Edit 返回 None。"""
        edit = int(user32.FindWindowExW(hwnd, None, "Edit", None) or 0)
        if not edit:
            return None
        buf = ctypes.create_unicode_buffer(max_chars)
        user32.SendMessageW(edit, WM_GETTEXT, max_chars, ctypes.addressof(buf))
        return buf.value
