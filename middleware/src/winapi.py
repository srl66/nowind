"""Windows API 绑定（ctypes）。只声明 MVP 需要的符号，零第三方依赖。

所有函数都显式声明 argtypes/restype，避免 64 位下指针被截断。
"""
from __future__ import annotations

import ctypes
from ctypes import POINTER, WINFUNCTYPE, wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

# ---------------------------------------------------------------- WinEvent 常量
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MOVESIZEEND = 0x000B
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_FOCUS = 0x8005
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_NAMECHANGE = 0x800C
EVENT_OBJECT_VALUECHANGE = 0x800E

WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

OBJID_WINDOW = 0
OBJID_CURSOR = -9
OBJID_CARET = -8
CHILDID_SELF = 0

EVENT_NAME = {
    EVENT_SYSTEM_FOREGROUND: "FOREGROUND",
    EVENT_SYSTEM_MOVESIZEEND: "MOVESIZEEND",
    EVENT_SYSTEM_MINIMIZESTART: "MINIMIZESTART",
    EVENT_SYSTEM_MINIMIZEEND: "MINIMIZEEND",
    EVENT_OBJECT_SHOW: "SHOW",
    EVENT_OBJECT_HIDE: "HIDE",
    EVENT_OBJECT_FOCUS: "FOCUS",
    EVENT_OBJECT_LOCATIONCHANGE: "LOCATION",
    EVENT_OBJECT_NAMECHANGE: "NAME",
    EVENT_OBJECT_VALUECHANGE: "VALUE",
}

# 订阅的事件集：单一事件号 -> (lo, hi)，逐个挂钩便于过滤与统计
HOOK_EVENTS = (
    EVENT_SYSTEM_FOREGROUND,
    EVENT_SYSTEM_MOVESIZEEND,
    EVENT_SYSTEM_MINIMIZESTART,
    EVENT_SYSTEM_MINIMIZEEND,
    EVENT_OBJECT_SHOW,
    EVENT_OBJECT_HIDE,
    EVENT_OBJECT_FOCUS,
    EVENT_OBJECT_LOCATIONCHANGE,
    EVENT_OBJECT_NAMECHANGE,
    EVENT_OBJECT_VALUECHANGE,
)

# 结构性事件：会改变窗口集合或 z 序，必须全量重建
STRUCTURAL_EVENTS = frozenset({
    EVENT_SYSTEM_FOREGROUND,
    EVENT_SYSTEM_MINIMIZESTART,
    EVENT_SYSTEM_MINIMIZEEND,
    EVENT_OBJECT_SHOW,
    EVENT_OBJECT_HIDE,
})

# ---------------------------------------------------------------- 函数签名
WinEventProc = WINFUNCTYPE(
    None,
    wintypes.HANDLE,   # hWinEventHook
    wintypes.DWORD,    # event
    wintypes.HWND,     # hwnd
    wintypes.LONG,     # idObject
    wintypes.LONG,     # idChild
    wintypes.DWORD,    # idEventThread
    wintypes.DWORD,    # dwmsEventTime
)

user32.SetWinEventHook.argtypes = [
    wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE,
    WinEventProc, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
user32.UnhookWinEvent.restype = wintypes.BOOL

user32.GetMessageW.argtypes = [POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [POINTER(wintypes.MSG)]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

WNDENUMPROC = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
GA_ROOT = 2
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.SetWindowTextW.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, POINTER(wintypes.DWORD),
]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    POINTER(wintypes.FILETIME), POINTER(wintypes.FILETIME),
    POINTER(wintypes.FILETIME), POINTER(wintypes.FILETIME),
]
kernel32.GetProcessTimes.restype = wintypes.BOOL
kernel32.GetCurrentProcess.restype = wintypes.HANDLE


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


psapi.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE, POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD,
]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
SW_MINIMIZE = 6
SW_RESTORE = 9
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

# 不属于“用户窗口”的类名，排除以降低噪声
SKIP_CLASSES = frozenset({
    "Progman", "Shell_TrayWnd", "WorkerW", "Windows.UI.Core.CoreWindow",
    "ApplicationManager_DesktopShellWindow", "ForegroundStaging",
})


def pid_of(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def is_top_level(hwnd: int) -> bool:
    return int(user32.GetAncestor(hwnd, GA_ROOT) or 0) == int(hwnd)


def class_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    n = user32.GetClassNameW(hwnd, buf, 256)
    return buf.value if n else ""


def title_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    n = user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value if n else ""


def rect_of(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return (0, 0, 0, 0)
    return (int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top))


_EXE_CACHE: dict[int, str] = {}


def exe_of_pid(pid: int) -> str:
    hit = _EXE_CACHE.get(pid)
    if hit is not None:
        return hit
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    name = "?"
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = buf.value.rsplit("\\", 1)[-1].lower()
        finally:
            kernel32.CloseHandle(h)
    _EXE_CACHE[pid] = name
    return name


def enum_windows(exclude_pid: int | None = None, max_n: int = 12):
    """按 z 序（前到后）枚举顶层可见窗口，返回 dict 列表。"""
    out: list[dict] = []
    limit = max_n

    @WNDENUMPROC
    def _cb(hwnd, _lparam):
        if len(out) >= limit:
            return False
        h = int(hwnd or 0)
        if not h or not user32.IsWindowVisible(h):
            return True
        cls = class_of(h)
        if cls in SKIP_CLASSES:
            return True
        title = title_of(h)
        if not title:
            return True
        pid = pid_of(h)
        if exclude_pid is not None and pid == exclude_pid:
            return True
        out.append({
            "hwnd": h,
            "title": title,
            "cls": cls,
            "pid": pid,
            "exe": exe_of_pid(pid),
            "rect": rect_of(h),
            "z": len(out),
            "min": bool(user32.IsIconic(h)),
        })
        return True

    user32.EnumWindows(_cb, 0)
    return out


def foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


def process_cpu_seconds() -> float:
    """本进程累计 CPU 秒数（user+kernel）。"""
    h = kernel32.GetCurrentProcess()
    c, e, k, u = (wintypes.FILETIME(), wintypes.FILETIME(),
                  wintypes.FILETIME(), wintypes.FILETIME())
    if not kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                   ctypes.byref(k), ctypes.byref(u)):
        return 0.0
    def _s(ft):
        return (ft.dwHighDateTime << 32 | ft.dwLowDateTime) / 1e7
    return _s(k) + _s(u)


def rss_mb() -> tuple[float, float]:
    """返回 (当前 RSS MB, 峰值 RSS MB)。"""
    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return (0.0, 0.0)
    return (pmc.WorkingSetSize / 1048576.0, pmc.PeakWorkingSetSize / 1048576.0)


def logical_cores() -> int:
    return int(ctypes.windll.kernel32.GetActiveProcessorCount(0))  # type: ignore[attr-defined]


def effective_cores() -> int:
    """本进程实际可调度的核数（Job Object 设了 affinity 后应返回被限制的数量）。

    注意：超过 64 逻辑核的机器需要处理器组 API，MVP 不覆盖（会在文档中标注）。
    """
    proc_mask = ctypes.c_size_t(0)
    sys_mask = ctypes.c_size_t(0)
    kernel32.GetProcessAffinityMask.argtypes = [
        wintypes.HANDLE, POINTER(ctypes.c_size_t), POINTER(ctypes.c_size_t),
    ]
    kernel32.GetProcessAffinityMask.restype = wintypes.BOOL
    ok = kernel32.GetProcessAffinityMask(
        kernel32.GetCurrentProcess(), ctypes.byref(proc_mask), ctypes.byref(sys_mask)
    )
    m = int(proc_mask.value) if ok else 0
    n = bin(m).count("1") if m else 0
    return n or logical_cores()
