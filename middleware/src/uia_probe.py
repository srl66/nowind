"""Tier1 稀疏 UIA 探测器（进程隔离 + 硬超时熔断）。

设计要点
1. UIA 宿主是独立进程（PowerShell + .NET UIAutomationClient），所以“卡死的 COM 调用”可以被 kill，
   这是线程级超时做不到的；主事件管线永远不调用 COM。
2. 8ms / 40ms 两档：
   - 8ms 软档：结果照收，但标记 late（表示该条 affordance 可能已过时）；
   - 40ms 硬档：仍未返回 -> 杀掉宿主进程 -> 标记 faulted -> 表示退化为窗口级，随后自动重启。
3. 任何时刻最多一个请求在途；在途时新请求直接丢弃（不做排队堆积，避免延迟雪崩）。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque


class UiaProbe:
    def __init__(self, host_script: str, max_items: int = 10, depth: int = 2,
                 fast_ms: float = 8.0, hard_ms: float = 40.0):
        self.host_script = host_script
        self.max_items = max_items
        self.depth = depth
        self.fast_ms = fast_ms
        self.hard_ms = hard_ms
        self.proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._inflight = None          # (t_send_ns, hwnd, deadline_ms, hard_ms)
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._req: "queue.Queue" = queue.Queue()
        self._done: "queue.SimpleQueue" = queue.SimpleQueue()
        self._wait: dict[int, dict] = {}
        self._wait_ev: dict[int, threading.Event] = {}
        self._rid = 0
        self._rid_lock = threading.Lock()
        self._records: list[dict] = []
        self._faulted = False
        self._last_fault_ns = 0
        self._stderr_tail: deque = deque(maxlen=8)
        self.counters = {"submitted": 0, "dropped_busy": 0, "late": 0, "hard_timeouts": 0,
                         "kills": 0, "restarts": 0, "errors": 0, "results": 0, "host_eof": 0}

    # ------------------------------------------------------------------ 生命周期
    def _host_cmd(self) -> list[str]:
        """宿主启动命令：优先预编译 exe（冷启动实测 ~0.14s），否则退回 PowerShell 脚本（~3.5s）。

        exe 由 scripts/build_uia_host_exe.ps1 从**同一份** C# 编译；它比 .py/.ps1 旧时自动退回，
        避免源码改了而 exe 没重建。ASP_UIA_HOST=ps1|exe 可强制指定（对照测试用）。
        """
        mode = os.environ.get("ASP_UIA_HOST", "auto").lower()
        exe = os.path.splitext(self.host_script)[0] + ".exe"
        try:
            fresh = (os.path.exists(exe)
                     and os.path.getmtime(exe) >= os.path.getmtime(self.host_script))
        except Exception:
            fresh = False
        if mode == "exe" or (mode == "auto" and fresh):
            return [exe]
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", self.host_script]

    def start(self, timeout_s: float = 25.0) -> bool:
        if self._stop.is_set():
            return False
        cmd = self._host_cmd()
        cmds = [cmd]
        if cmd[0] != "powershell":
            # exe 起不来（被杀软拦/缺 .NET）就退回脚本宿主，不让感知能力直接消失
            cmds.append(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", self.host_script])
        self.proc = None
        for c in cmds:
            try:
                self.proc = subprocess.Popen(
                    c,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", bufsize=1,
                )
                break
            except Exception:
                continue
        if self.proc is None:
            self._faulted = True
            self._last_fault_ns = time.perf_counter_ns()
            return False
        try:
            # UIA 宿主降到 BELOW_NORMAL：避免在 2 核上跟提交线程抢 CPU（R9 根因修复）
            import ctypes
            from ctypes import wintypes
            _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            _k32.OpenProcess.restype = wintypes.HANDLE
            _h = _k32.OpenProcess(0x0200, False, self.proc.pid)
            if _h:
                _k32.SetPriorityClass(wintypes.HANDLE(_h), 0x00004000)
                _k32.CloseHandle(wintypes.HANDLE(_h))
        except Exception:
            pass
        threading.Thread(target=self._drain_stderr, name="uia-stderr", daemon=True).start()
        self._ready.clear()
        threading.Thread(target=self._reader, name="uia-reader", daemon=True).start()
        threading.Thread(target=self._writer, name="uia-writer", daemon=True).start()
        threading.Thread(target=self._watchdog, name="uia-watchdog", daemon=True).start()
        ok = self._ready.wait(timeout_s)
        if not ok:
            self._faulted = True
            self._last_fault_ns = time.perf_counter_ns()
            self._kill()
        return bool(ok)

    def _kill(self):
        p = self.proc
        if p is None:
            return
        self.proc = None
        try:
            p.kill()
        except Exception:
            pass
        try:
            p.wait(timeout=2)
        except Exception:
            pass

    def stop(self):
        self._stop.set()
        p = self.proc
        self.proc = None
        if p:
            try:
                if p.stdin:
                    p.stdin.close()
            except Exception:
                pass
            try:
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass

    def _try_restart(self) -> bool:
        with self._lock:
            if not self._faulted:
                return self.proc is not None
            # 冷却 0.5s：exe 宿主重启只要 ~0.12s，旧值 2s 会让熔断后的盲区比启动本身还长
            if (time.perf_counter_ns() - self._last_fault_ns) / 1e9 < 0.5:
                return False
            self.counters["restarts"] += 1
        ok = self.start(timeout_s=25.0)
        if ok:
            with self._lock:
                self._faulted = False
        return ok

    # ------------------------------------------------------------------ 线程
    def _drain_stderr(self):
        p = self.proc
        if p is None or p.stderr is None:
            return
        try:
            for line in p.stderr:
                self._stderr_tail.append(line.strip()[:300])
        except Exception:
            pass

    def _reader(self):
        p = self.proc
        if p is None or p.stdout is None:
            return
        while True:
            try:
                line = p.stdout.readline()
            except Exception as ex:  # noqa: BLE001
                self.counters["reader_error"] = f"{type(ex).__name__}: {ex}"
                break
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            if '"ready":true' in line:
                self._ready.set()
                continue
            try:
                obj = json.loads(line)
            except Exception:
                self.counters["errors"] += 1
                continue
            with self._lock:
                inf = self._inflight
                self._inflight = None
            if inf is None:
                continue
            t_send, hwnd, deadline_ms, _hard, rid = inf
            rtt_us = (time.perf_counter_ns() - t_send) / 1000.0
            rec = {
                "hwnd": hwnd,
                "t_us": obj.get("t_us"),
                "fh_us": obj.get("fh_us"),
                "rtt_us": round(rtt_us, 1),
                "n": obj.get("n", 0),
                "seen": obj.get("seen", 0),
                "ok": bool(obj.get("ok")),
                "err": obj.get("e", ""),
                "late": rtt_us > deadline_ms * 1000.0,
                "cold": deadline_ms >= 100.0,   # 冷档（provider 初始化）不计入稳态分位数
            }
            with self._lock:
                self._records.append(rec)
                self.counters["results"] += 1
                if rec["late"]:
                    self.counters["late"] += 1
            item = {"hwnd": hwnd, "items": obj.get("items", []) if rec["ok"] else [],
                    "rec": rec,
                    "page": obj.get("page"), "doc_id": obj.get("doc_id"),
                    "doc_rect": obj.get("doc_rect"), "page_seen": obj.get("page_seen"),
                    "focus": obj.get("focus")}
            if rid:
                # 带 rid 的是同步调用方（动作闭环），不进感知队列，避免被 worker 抢走
                with self._lock:
                    self._wait[rid] = item
                    ev = self._wait_ev.get(rid)
                if ev is not None:
                    ev.set()
            else:
                self._done.put(item)
        self._ready.clear()
        self.counters["host_eof"] += 1

    def _writer(self):
        while not self._stop.is_set():
            try:
                (hwnd, deadline_ms, hard_ms, want_text, rid, deep,
                 target_id, ax, ay, focus, max_items, depth) = self._req.get(timeout=0.05)
            except queue.Empty:
                continue
            p = self.proc
            if p is None or p.stdin is None:
                continue
            mi = int(max_items) if max_items else self.max_items
            dp = int(depth) if depth else self.depth
            line = (f"{int(hwnd)},{mi},{dp},{1 if want_text else 0},"
                    f"{1 if deep else 0},{target_id or '-'},{int(ax)},{int(ay)},"
                    f"{1 if focus else 0}\n")
            with self._lock:
                self._inflight = (time.perf_counter_ns(), hwnd, deadline_ms, hard_ms, rid)
            try:
                p.stdin.write(line)
                p.stdin.flush()
            except Exception:
                with self._lock:
                    self._inflight = None
                    self._faulted = True
                    self._last_fault_ns = time.perf_counter_ns()
                self.counters["errors"] += 1

    def _watchdog(self):
        while not self._stop.is_set():
            time.sleep(0.005)
            with self._lock:
                inf = self._inflight
                if inf is None:
                    continue
                elapsed_ms = (time.perf_counter_ns() - inf[0]) / 1e6
                if elapsed_ms > inf[3]:
                    self._inflight = None
                    self.counters["hard_timeouts"] += 1
                    self.counters["kills"] += 1
                    self._faulted = True
                    self._last_fault_ns = time.perf_counter_ns()
                    self._records.append({"hwnd": inf[1], "t_us": None, "rtt_us": None,
                                          "n": 0, "ok": False, "err": "hard-timeout",
                                          "late": True, "timeout": True})
                    rid = inf[4]
                    if rid:
                        with self._lock:
                            self._wait[rid] = {"hwnd": inf[1], "items": [], "rec": self._records[-1]}
                            ev = self._wait_ev.get(rid)
                        if ev is not None:
                            ev.set()
                    self._kill()

    # ------------------------------------------------------------------ 对外 API
    def submit(self, hwnd: int, deadline_ms: float | None = None,
               hard_ms: float | None = None, want_text: bool = False,
               rid: int = 0, deep: bool = False, target_id: str = "",
               ax: int = 0, ay: int = 0, focus: bool = False,
               max_items: int = 0, depth: int = 0) -> bool:
        """非阻塞提交。返回 False = 丢弃（在途/未就绪/已熔断）。

        deadline_ms 是“软档”（超过只标 late），hard_ms 是“硬档”（超过就杀宿主）。
        冷启动（每个 hwnd 的第一次）必须传更宽松的 hard_ms，否则必然熔断。
        want_text=True 会额外走一次 TextPattern（跨进程），只给验证用，不给常规感知用。
        ax/ay > 0 = 页面锚点（屏幕坐标），用于跨越浏览器渲染边界拿网页内控件。
        focus=True = 只返回当前焦点控件（验证读回）。
        """
        if self._faulted:
            self._try_restart()
        if self.proc is None or not self._ready.is_set():
            return False
        with self._lock:
            if self._inflight is not None:
                self.counters["dropped_busy"] += 1
                return False
        d = self.fast_ms if deadline_ms is None else deadline_ms
        h = self.hard_ms if hard_ms is None else hard_ms
        self.counters["submitted"] += 1
        self._req.put((int(hwnd), float(d), float(h), bool(want_text), int(rid),
                       bool(deep), str(target_id or ""), int(ax), int(ay), bool(focus),
                       int(max_items), int(depth)))
        return True

    def poll(self, max_n: int = 4) -> list[dict]:
        out = []
        for _ in range(max_n):
            try:
                out.append(self._done.get_nowait())
            except queue.Empty:
                break
        return out

    def _alloc_rid(self) -> int:
        with self._rid_lock:
            self._rid += 1
            return self._rid

    def query_blocking(self, hwnd: int, timeout_ms: float = 300.0,
                       hard_ms: float | None = None, deadline_ms: float | None = None,
                       want_text: bool = False, deep: bool = False,
                       target_id: str = "", ax: int = 0, ay: int = 0,
                       focus: bool = False, max_items: int = 0,
                       depth: int = 0) -> dict | None:
        """同步查询（动作闭环/验证用）。带 rid，不会被感知 worker 抢走结果；
        如果宿主正忙（in-flight），在 timeout 内重试提交。"""
        rid = self._alloc_rid()
        ev = threading.Event()
        with self._lock:
            self._wait_ev[rid] = ev
        deadline = time.time() + timeout_ms / 1000.0
        submitted = False
        while time.time() < deadline:
            if self.submit(hwnd, deadline_ms=deadline_ms, hard_ms=hard_ms,
                           want_text=want_text, rid=rid, deep=deep, target_id=target_id,
                           ax=ax, ay=ay, focus=focus, max_items=max_items, depth=depth):
                submitted = True
                break
            time.sleep(0.002)
        if not submitted:
            with self._lock:
                self._wait_ev.pop(rid, None)
            return None
        ev.wait(max(0.0, deadline - time.time()))
        with self._lock:
            item = self._wait.pop(rid, None)
            self._wait_ev.pop(rid, None)
        return item

    def stats(self) -> dict:
        with self._lock:
            allrecs = list(self._records)
        recs = [r for r in allrecs if r.get("t_us") and not r.get("cold")]
        cold = [r for r in allrecs if r.get("t_us") and r.get("cold")]
        vals = sorted(r["t_us"] / 1000.0 for r in recs)   # ms
        rtts = sorted(r["rtt_us"] / 1000.0 for r in recs if r.get("rtt_us"))

        def pct(arr, p):
            if not arr:
                return None
            return round(arr[min(len(arr) - 1, int(len(arr) * p / 100))], 3)

        out = dict(self.counters)
        out.update({
            "queries": len(vals),
            "uia_p50_ms": pct(vals, 50),
            "uia_p95_ms": pct(vals, 95),
            "uia_p99_ms": pct(vals, 99),
            "uia_max_ms": round(vals[-1], 3) if vals else None,
            "rtt_p50_ms": pct(rtts, 50),
            "rtt_p99_ms": pct(rtts, 99),
            "late_pct": round(100.0 * self.counters["late"] / max(1, self.counters["results"]), 2),
            "cold_queries": len(cold),
            "cold_p50_ms": pct(sorted(r["t_us"] / 1000.0 for r in cold), 50),
            "faulted": self._faulted,
            "items_avg": round(sum(r.get("n", 0) for r in recs) / len(recs), 2) if recs else 0,
            "host_stderr_tail": list(self._stderr_tail),
        })
        return out


if __name__ == "__main__":
    host = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uia_host.ps1")
    p = UiaProbe(host)
    ok = p.start()
    print(json.dumps({"start_ok": ok, "host": host}, ensure_ascii=False))
    if ok:
        hwnd = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        r = p.query_blocking(hwnd)
        print(json.dumps(r, ensure_ascii=False)[:2000])
        print(json.dumps(p.stats(), ensure_ascii=False, indent=2))
        p.stop()
