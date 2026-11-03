"""Phase 1：最小屏幕变更事件源（WinEvent out-of-context 钩子 + 消息泵）。

约束：
- 回调里只做「入队 + 计时」，绝不调用任何可能阻塞的 API（WinEvent 回调超时会被系统断开）。
- hooks 与消息泵必须在同一线程注册，否则收不到事件。
- 时间戳统一使用 time.perf_counter_ns()（跨进程同一 QPC 时钟，可与其他进程比较）。

用法：
    python src/event_probe.py --duration 15 --out logs/events.jsonl
"""
from __future__ import annotations

import argparse
import ctypes
import json
import queue
import sys
import threading
import time
import os
from collections import Counter, deque
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winapi as W  # noqa: E402


def run(duration_s: float, out_path: str) -> dict:
    events: "queue.SimpleQueue[tuple]" = queue.SimpleQueue()
    cb_ns: deque[int] = deque(maxlen=20000)
    stop_flag = threading.Event()
    stats = {"events": 0, "commits": 0}

    def on_event(hook, event, hwnd, id_obj, id_child, tid, tmsg):
        t0 = time.perf_counter_ns()
        # 过滤：光标/文本插入符的位置变化是最噪的源，且与 UI 语义无关
        if id_obj == W.OBJID_CURSOR or id_obj == W.OBJID_CARET:
            return
        # 过滤：只保留窗口级 LOCATIONCHANGE，丢弃子元素位移
        if event == W.EVENT_OBJECT_LOCATIONCHANGE and id_obj != W.OBJID_WINDOW:
            return
        if event == W.EVENT_OBJECT_LOCATIONCHANGE and id_child != W.CHILDID_SELF:
            return
        events.put((t0 // 1000, event, int(hwnd or 0), id_obj, id_child))
        cb_ns.append(time.perf_counter_ns() - t0)

    proc = W.WinEventProc(on_event)   # 必须持有引用，否则被 GC 后崩溃

    def pump():
        hooks = []
        for ev in W.HOOK_EVENTS:
            h = W.user32.SetWinEventHook(
                ev, ev, None, proc, 0, 0,
                W.WINEVENT_OUTOFCONTEXT | W.WINEVENT_SKIPOWNPROCESS,
            )
            if h:
                hooks.append(h)
        tid = W.kernel32.GetCurrentThreadId()
        threading.Timer(duration_s, lambda: W.user32.PostThreadMessageW(tid, W.WM_QUIT, 0, 0)).start()
        msg = wintypes.MSG()
        while True:
            r = W.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            W.user32.TranslateMessage(ctypes.byref(msg))
            W.user32.DispatchMessageW(ctypes.byref(msg))
        for h in hooks:
            W.user32.UnhookWinEvent(h)
        stop_flag.set()

    th = threading.Thread(target=pump, name="win-event-pump", daemon=True)
    tn = time.perf_counter_ns()
    th.start()

    f = open(out_path, "w", encoding="utf-8", buffering=1)
    counts: Counter[str] = Counter()
    dumped = 0
    try:
        while not stop_flag.is_set() or not events.empty():
            try:
                item = events.get(timeout=0.05)
            except queue.Empty:
                continue
            t_us, event, hwnd, id_obj, id_child = item
            name = W.EVENT_NAME.get(event, f"0x{event:X}")
            f.write(json.dumps({
                "t_us": t_us, "e": name, "hwnd": hwnd,
                "id_obj": id_obj, "id_child": id_child,
                "pid": W.pid_of(hwnd) if hwnd else 0,
                "title": W.title_of(hwnd) if hwnd else "",
            }, ensure_ascii=False) + "\n")
            counts[name] += 1
            dumped += 1
            stats["events"] = dumped
    finally:
        f.close()

    wall_s = (time.perf_counter_ns() - tn) / 1e9
    cb = list(cb_ns)
    cb.sort()

    def pct(v, p):
        if not v:
            return 0.0
        return v[min(len(v) - 1, int(len(v) * p / 100))]

    summary = {
        "duration_s": round(wall_s, 3),
        "events": dumped,
        "events_per_sec": round(dumped / wall_s, 1) if wall_s else 0,
        "by_event": dict(counts),
        "cb_samples": len(cb),
        "cb_p50_us": round(pct(cb, 50) / 1000, 3),
        "cb_p99_us": round(pct(cb, 99) / 1000, 3),
        "cb_max_us": round((cb[-1] / 1000) if cb else 0, 3),
        "out": out_path,
    }
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=15.0)
    ap.add_argument("--out", default="logs/events.jsonl")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    s = run(a.duration, a.out)
    print(json.dumps(s, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
