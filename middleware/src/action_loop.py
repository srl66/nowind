"""动作→感知→验证 闭环（daemon 内使用）。

一次 perform 的完整链路：
  1) 执行动作（SendInput 点击 / Unicode 输入）
  2) 触发感知：对同一窗口做一次带 TextPattern 的 UIA 读回（带 rid，不会和感知 worker 抢结果）
  3) 把读回结果作为一次观察提交写进 SSR（dirty 为空，不参与“变更->可见”配对）
  4) 返回结构化结果（成功/耗时/读回文本/原因）
"""
from __future__ import annotations

import re
import threading
import time

import winapi as W


_NUM = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def _extract_num(s: str) -> str:
    """从 “显示为 0” / “1” 这类文本里取出数字部分。"""
    m = _NUM.search((s or "").replace(",", "").replace("，", ""))
    return m.group(0) if m else ""


class ActionLoop:
    def __init__(self, executor, probe, publish, profile=None, scene=None):
        self.ex = executor
        self.probe = probe
        self.publish = publish       # publish(mode, dirty, t_ev_us, evn, last_ev)
        self.profile = profile
        self.scene = scene
        self._rect_cache: dict[tuple[int, str], dict] = {}
        self.lock = threading.RLock()
        self.stats = {"performed": 0, "ok": 0, "verify_ok": 0, "publish_ok": 0,
                      "fallback_used": 0, "fallback_ok": 0}

    def _exe(self, hwnd: int) -> str:
        try:
            return W.exe_of_pid(W.pid_of(hwnd))
        except Exception:
            return ""

    def perform(self, req: dict) -> dict:
        """串行化：命名管道与本地 HTTP API 共用同一个执行器，不能并发点。"""
        with self.lock:
            return self._perform(req)

    def _perform(self, req: dict) -> dict:
        t0 = time.perf_counter_ns()
        hwnd = int(req.get("hwnd") or 0)
        op = req.get("op") or "click_type"
        if op == "click_id":
            return self._perform_click_id(req, hwnd, t0)
        text = str(req.get("text") or "")
        out: dict = {"op": op, "hwnd": hwnd, "ok": False, "reason": ""}
        self.stats["performed"] += 1

        if not hwnd:
            out["reason"] = "no-hwnd"
            return out

        if op in ("click", "click_type"):
            x = int(req.get("x", 0))
            y = int(req.get("y", 0))
            c = self.ex.click(hwnd, x, y)
            out["click"] = c.as_dict()
            if not c.ok:
                out["reason"] = c.reason or "click-failed"
                return out

        if op in ("type", "click_type"):
            ty = self.ex.type_text(text, hwnd=hwnd)
            out["type"] = ty.as_dict()
            if not ty.ok:
                out["reason"] = ty.reason or "type-failed"
                return out

        # 触发感知 + 读回（验证）
        t1 = time.perf_counter_ns()
        r = self.probe.query_blocking(hwnd, timeout_ms=800, deadline_ms=300.0,
                                      hard_ms=600.0, want_text=True)
        out["verify_us"] = (time.perf_counter_ns() - t1) // 1000
        readback = ""
        if r:
            for it in r.get("items", []):
                v = it.get("v") or ""
                if v:
                    readback = v
                    break
            if self.profile:
                rec = r.get("rec") or {}
                exe = self._exe(hwnd)
                if rec.get("t_us") and not rec.get("cold"):
                    self.profile.record(exe, rec["t_us"] / 1000.0)
                elif rec.get("err") == "hard-timeout":
                    self.profile.note_timeout(exe)
        out["readback"] = readback[:200]

        if text:
            out["verify_ok"] = text in readback
            out["ok"] = bool(out["verify_ok"])
        else:
            out["ok"] = bool(r)

        # 观察提交：把“动作之后屏幕变成了什么”写回寄存器（agent 读 SSR 即可看到结果）
        try:
            if self.scene is not None:
                self.scene.last_obs = {"op": op, "ok": bool(out["ok"]), "rb": readback[:80]}
            self.publish("obs", set(), 0, 1, "ACTION")
            self.stats["publish_ok"] += 1
        except Exception:
            out["publish_error"] = True

        if out["ok"]:
            self.stats["ok"] += 1
        if out.get("verify_ok"):
            self.stats["verify_ok"] += 1
        out["t_total_us"] = (time.perf_counter_ns() - t0) // 1000
        return out

    # ------------------------------------------------------------------ 按 id 定位
    def _resolve(self, hwnd: int, elem_id: str, timeout_ms: float = 900.0) -> dict | None:
        """用 AutomationId 做深查解析，返回带实时 rect 的元素。"""
        r = self.probe.query_blocking(hwnd, timeout_ms=timeout_ms, deadline_ms=300.0,
                                      hard_ms=600.0, deep=True, target_id=elem_id)
        items = (r or {}).get("items") or []
        return items[0] if items else None

    def _read_target(self, hwnd: int, elem_id: str) -> str:
        it = self._resolve(hwnd, elem_id)
        if not it:
            return ""
        return (it.get("v") or it.get("n") or "")

    def _perform_click_id(self, req: dict, hwnd: int, t0: int) -> dict:
        elem_id = str(req.get("id") or "")
        verify_id = str(req.get("verify_id") or "")
        expect = str(req.get("expect") or "")
        out: dict = {"op": "click_id", "hwnd": hwnd, "id": elem_id, "ok": False, "reason": ""}
        self.stats["performed"] += 1
        if not hwnd or not elem_id:
            out["reason"] = "missing-hwnd-or-id"
            return out

        t1 = time.perf_counter_ns()
        # 先激活再解析：UWP 应用在后台会被挂起，挂起时 UIA 树只剩标题栏按钮，必然 id-not-found
        self.ex.activate(hwnd, timeout_ms=300)
        simulate = str(req.get("simulate") or "")
        item = None
        if simulate != "resolve-fail":
            item = self._resolve(hwnd, elem_id)
            if item is None:
                time.sleep(0.15)
                item = self._resolve(hwnd, elem_id)

        if item is not None:
            self._rect_cache[(hwnd, elem_id)] = {
                "rect": tuple(item["r"]), "win": W.rect_of(hwnd),
                "t": time.perf_counter_ns(),
            }
            rect = tuple(item["r"])
            out["resolved"] = {"id": item["id"], "type": item["t"], "name": item["n"], "rect": item["r"]}
        else:
            fb = self._fallback_rect(hwnd, elem_id)
            if fb is None:
                out["reason"] = "id-not-found"
                out["simulated"] = simulate or None
                out["t_total_us"] = (time.perf_counter_ns() - t0) // 1000
                return out
            rect = tuple(fb["rect"])
            out["fallback"] = fb
            out["simulated"] = simulate or None
            self.stats["fallback_used"] += 1

        out["resolve_us"] = (time.perf_counter_ns() - t1) // 1000
        if rect[2] <= 1 or rect[3] <= 1:
            out["reason"] = "empty-rect"
            return out

        before = self._read_target(hwnd, verify_id) if verify_id else ""
        out["before"] = before

        cx = rect[0] + rect[2] // 2
        cy = rect[1] + rect[3] // 2
        c = self.ex.click(hwnd, cx, cy)
        out["click"] = c.as_dict()
        if not c.ok:
            out["reason"] = c.reason or "click-failed"
            out["t_total_us"] = (time.perf_counter_ns() - t0) // 1000
            return out

        if verify_id:
            time.sleep(0.05)   # 给 UI 一个刷新周期（计算器是异步渲染）
            after = self._read_target(hwnd, verify_id)
            out["after"] = after
            if expect:
                got_num = _extract_num(after)
                want_num = _extract_num(expect)
                if want_num:
                    out["ok"] = got_num == want_num
                else:
                    out["ok"] = expect in after
                if not out["ok"]:
                    out["reason"] = f"expect={expect} got={got_num or after}"
            else:
                out["ok"] = True
        else:
            out["ok"] = bool(c.ok)

        try:
            if self.scene is not None:
                self.scene.last_obs = {"op": "click_id", "ok": bool(out["ok"]),
                                       "rb": f"{elem_id}->{out.get('after', '')}"[:80]}
            self.publish("obs", set(), 0, 1, "ACTION")
            self.stats["publish_ok"] += 1
        except Exception:
            out["publish_error"] = True

        if out["ok"]:
            self.stats["ok"] += 1
            if out.get("fallback"):
                self.stats["fallback_ok"] += 1
        out["t_total_us"] = (time.perf_counter_ns() - t0) // 1000
        return out

    def _fallback_rect(self, hwnd: int, elem_id: str) -> dict | None:
        """id 解析失败时的降级：用上次快照/上次解析到的 rect，并按窗口位移做 rebase。"""
        now_win = W.rect_of(hwnd)
        if now_win[2] <= 1 or now_win[3] <= 1:
            return None

        e = self._rect_cache.get((hwnd, elem_id))
        if e:
            w0 = e["win"]
            if abs(w0[2] - now_win[2]) > 10 or abs(w0[3] - now_win[3]) > 10:
                return None      # 窗口尺寸变了，布局可能重排，不能用旧坐标
            dx = now_win[0] - w0[0]
            dy = now_win[1] - w0[1]
            rr = [e["rect"][0] + dx, e["rect"][1] + dy, e["rect"][2], e["rect"][3]]
            stale_ms = round((time.perf_counter_ns() - e["t"]) / 1e6, 1)
            if not self._inside(rr, now_win):
                return None
            return {"source": "cache", "rect": rr, "dx": dx, "dy": dy, "stale_ms": stale_ms}

        if self.scene is not None:
            for it in self.scene.affordances:
                if not elem_id:
                    continue
                if it.get("id") != elem_id and it.get("n") != elem_id:
                    continue
                rr = [int(v) for v in (it.get("r") or [0, 0, 0, 0])]
                if rr[2] <= 1 or rr[3] <= 1 or not self._inside(rr, now_win):
                    continue
                return {"source": "snapshot", "rect": rr, "dx": 0, "dy": 0, "stale_ms": 0}
        return None

    @staticmethod
    def _inside(r: list[int], win: tuple[int, int, int, int], margin: int = 4) -> bool:
        cx = r[0] + r[2] // 2
        cy = r[1] + r[3] // 2
        return (win[0] - margin <= cx <= win[0] + win[2] + margin
                and win[1] - margin <= cy <= win[1] + win[3] + margin)
