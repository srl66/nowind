"""Phase 2/3/4 核心：事件 -> 场景 patch -> DSL 表示 -> SSR 提交（提交日志可测）。

Tier1 UIA 接入方式（关键：不阻塞事件管线）
- UIA 宿主是独立进程，由 UiaProbe 异步提交/回收；主线程只做非阻塞 poll。
- 冷启动（某 hwnd 的第一次查询）用宽松档 300/600ms，因为 provider 初始化要 100ms+；
  稳态用 8ms 软档 / 40ms 硬档（超硬档直接杀宿主进程，表示退化为窗口级）。
- UIA 结果到达时追加一次 “enrichment 提交”，其 dirty 为空 —— 不参与“变更->可见”配对。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winapi as W          # noqa: E402
import scene as S          # noqa: E402
from ssr import RegisterWriter  # noqa: E402
from uia_probe import UiaProbe  # noqa: E402
from uia_profile import UiaProfile  # noqa: E402
from slip import SlipCache  # noqa: E402
import uia_compressor as UC  # noqa: E402
from api_server import ApiServer  # noqa: E402
from tiers import choose_tier, TIERS  # noqa: E402
from action_exec import ActionExecutor  # noqa: E402
from action_loop import ActionLoop  # noqa: E402
import action_server  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=40.0)
    ap.add_argument("--out-dir", default="logs")
    ap.add_argument("--max-windows", type=int, default=12)
    ap.add_argument("--no-uia", action="store_true")
    ap.add_argument("--no-action", action="store_true")
    ap.add_argument("--no-api", action="store_true")
    ap.add_argument("--api-port", type=int, default=8737)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    out_dir = os.path.abspath(a.out_dir)
    # 提交线程优先级抬高：与 UIA 宿主（已降到 BELOW_NORMAL）分开档次（R9 修复）
    try:
        k32 = ctypes.WinDLL("kernel32")
        k32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        k32.SetPriorityClass(ctypes.wintypes.HANDLE(k32.GetCurrentProcess()), 0x00008000)
    except Exception:
        pass
    os.makedirs(out_dir, exist_ok=True)
    reg_path = os.path.join(out_dir, "ssr.bin")
    commits_path = os.path.join(out_dir, "commits.jsonl")
    stats_path = os.path.join(out_dir, "daemon_stats.json")

    ev_q: "queue.SimpleQueue[tuple]" = queue.SimpleQueue()
    cb_ns: deque[int] = deque(maxlen=50000)
    stop = threading.Event()
    counters = {"events": 0}

    def on_event(hook, event, hwnd, id_obj, id_child, tid, tmsg):
        t0 = time.perf_counter_ns()
        if id_obj == W.OBJID_CURSOR or id_obj == W.OBJID_CARET:
            return
        if event == W.EVENT_OBJECT_LOCATIONCHANGE:
            if id_obj != W.OBJID_WINDOW or id_child != W.CHILDID_SELF:
                return
        ev_q.put((t0 // 1000, event, int(hwnd or 0)))
        cb_ns.append(time.perf_counter_ns() - t0)

    proc = W.WinEventProc(on_event)

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
        threading.Timer(a.duration, lambda: W.user32.PostThreadMessageW(tid, W.WM_QUIT, 0, 0)).start()
        msg = wintypes.MSG()
        while True:
            r = W.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            W.user32.TranslateMessage(ctypes.byref(msg))
            W.user32.DispatchMessageW(ctypes.byref(msg))
        for h in hooks:
            W.user32.UnhookWinEvent(h)
        stop.set()

    sc = S.Scene(os.getpid(), max_windows=a.max_windows)
    slip_cache = SlipCache(cap=64)
    sc.slip = slip_cache
    sc.rebuild()
    reg = RegisterWriter(reg_path)
    state = {"v": 0, "body": ""}
    t_run0 = time.perf_counter_ns()
    cpu0 = W.process_cpu_seconds()
    cores = W.effective_cores()

    uia = None
    uia_cold_done: set[int] = set()
    prof = UiaProfile(os.path.join(out_dir, "uia_profile.json"))
    if not a.no_uia:
        uia = UiaProbe(os.path.join(os.path.dirname(os.path.abspath(__file__)), "uia_host.ps1"),
                       max_items=10, depth=2, fast_ms=8.0, hard_ms=40.0)
        # 宿主编译约 2s：放到后台线程，绝不阻塞事件泵和 worker（submit 会在未就绪时自动丢弃）
        threading.Thread(target=uia.start, kwargs={"timeout_s": 25.0},
                         name="uia-start", daemon=True).start()

    def exe_of(hwnd: int) -> str:
        try:
            return W.exe_of_pid(W.pid_of(hwnd))
        except Exception:
            return ""

    modes = {"full": 0, "patch": 0, "init": 0, "uia": 0, "obs": 0}
    pub_lock = threading.Lock()
    # est 是保守代理（CJK=1/ASCII 4 字符），实测 cl100k 约为其 1.15–2 倍 -> 取 2 倍安全边际
    est_override = os.environ.get("ASP_TOKEN_EST_CAP")
    slip_off = os.environ.get("ASP_SLIP_OFF") == "1"      # 仅对照实验用
    fixed_tier = os.environ.get("ASP_TIER_FIXED", "").strip()  # 仅对照实验用
    tier_counts = {"basic": 0, "battle": 0, "extreme": 0}

    f = open(commits_path, "w", encoding="utf-8", buffering=1)

    def do_publish(mode: str, dirty: set[int], t_ev_us: int, evn: int, last_ev: str) -> None:
        with pub_lock:
            state["v"] += 1
            modes[mode] = modes.get(mode, 0) + 1
            age_ms = (time.perf_counter_ns() // 1000 - t_ev_us) / 1000.0 if t_ev_us else 0.0
            if slip_off:
                sc.aff_sid = sc.mn_sid = ""
                sc.aff_repeat = sc.mn_repeat = False
            else:
                sc.prepare()
            # 三档动态预算：按“可交互控件数 ×2 + 窗口数”判定复杂度（废弃写死 256）
            n_ctrl = len([x for x in sc.affordances if x.get("e") and not x.get("o")])
            if fixed_tier in TIERS:
                tier, budget, complexity = fixed_tier, TIERS[fixed_tier], 0
            else:
                tier, budget, complexity = choose_tier(n_ctrl, len(sc.wins), sc.aff_seen)
            tier_counts[tier] += 1
            cap = int(est_override) if est_override else max(60, budget // 2)
            state["tier"], state["budget"] = tier, budget
            level = 1
            body = sc.render(state["v"], age_ms, mode, len(dirty), level=1)
            est = S.est_tokens(body)
            if est > cap:
                for lv in (2, 3, 4):
                    body = sc.render(state["v"], age_ms, mode, len(dirty), level=lv)
                    est = S.est_tokens(body)
                    level = lv
                    if est <= cap:
                        break
            payload = body.encode("utf-8")
            t_commit = time.perf_counter_ns() // 1000
            reg.publish(payload, state["v"], t_commit)
            state["body"] = body
            f.write(json.dumps({
                "v": state["v"], "t_commit_us": t_commit, "t_event_us": t_ev_us,
                "mode": mode, "dirty": [hex(h) for h in dirty],
                "evn": evn, "last_ev": last_ev,
                "bytes": len(payload), "tokens_est": est, "trim": level - 1,
                "tier": tier, "budget": budget,
                "aff_sid": sc.aff_sid, "aff_rep": 1 if sc.aff_repeat else 0,
                "mn_sid": sc.mn_sid, "mn_rep": 1 if sc.mn_repeat else 0,
                "age_ms_at_commit": round(age_ms, 3),
            }, ensure_ascii=False) + "\n")
            state["est"] = est

    do_publish("init", set(), 0, 0, "init")
    n_commits = 1

    # 动作闭环：daemon 内执行 + 读回验证 + 观察提交
    executor = ActionExecutor(restore_timeout_ms=50.0)
    act_loop = ActionLoop(executor, uia, do_publish, prof, scene=sc) if uia is not None else None
    if act_loop is not None and not a.no_action:
        pipe_name = r"\\.\pipe\asp_action_%d" % os.getpid()
        threading.Thread(target=action_server.serve,
                         args=(act_loop, pipe_name, os.path.join(out_dir, "action_pipe.txt")),
                         name="action-server", daemon=True).start()

    # ---------------------------------------------------------------- 本地 API
    fovea_cache: dict = {}

    def api_state(deep: bool = False) -> dict:
        with pub_lock:
            v = state["v"]
            tier = state.get("tier", "basic")
            budget = state.get("budget", 150)
            est = state.get("est", 0)
        # 快照构建（含按需 fovea）放在锁外，避免抓图把提交卡住
        snap = UC.build_snapshot(sc, version=v, mode="api", tier=tier,
                                 budget=budget, tokens_est=est, cache=fovea_cache)
        if deep and (uia is None or not sc.fg):
            snap.update({"error": "no-foreground-or-uia", "fg": int(sc.fg or 0),
                         "uia": uia is not None, "controls": []})
            return snap
        if deep and uia is not None and sc.fg:
            # 深查前先确保目标在前台，并校验 GetForegroundWindow()（失败重试 2 次，仍失败返回明确错误码）
            target = int(sc.fg)
            ok_fg = False
            for _ in range(3):
                executor.activate(target, timeout_ms=300)
                if W.foreground_hwnd() == target:
                    ok_fg = True
                    break
                time.sleep(0.1)
            if not ok_fg:
                snap.update({"error": "foreground-mismatch", "wanted": target,
                             "actual": int(W.foreground_hwnd() or 0), "controls": []})
                return snap
            # 深查视图：给浏览器/Electron 这类“浅查为空”的目标用（慢，但只在被请求时）。
            # ax/ay = 窗口客户区中心的屏幕坐标：浏览器需要这个锚点做 hit-test，
            # 才能穿过 Chromium 渲染边界拿到网页内的 Document/控件（纯 Descendants 枚举到不了）。
            wrect = W.rect_of(target) or (0, 0, 0, 0)
            ax = int(wrect[0] + wrect[2] // 2)
            ay = int(wrect[1] + wrect[3] // 2)
            # 深度读屏要给“计算器 / 浏览器”这类应用留足条目：默认 10 条、深度 2
            # 只能拿到标题栏和内存键；B 站首页前 60 条也才到分类栏，视频卡片在更后面。
            r = uia.query_blocking(target, timeout_ms=18000, deadline_ms=600.0,
                                   hard_ms=12000.0, deep=True, ax=ax, ay=ay,
                                   max_items=200, depth=10)
            if r and r.get("items"):
                items = r["items"]
                ctrls = []
                for cid, it in enumerate(items):
                    ar = list(it.get("r") or [0, 0, 0, 0])
                    rel = ([ar[0] - wrect[0], ar[1] - wrect[1], ar[2], ar[3]]
                           if wrect[2] else ar)
                    ctrls.append({"cid": cid, "id": it.get("id") or "", "name": it.get("n") or "",
                                  "text": it.get("v") or "", "type": it.get("t") or "",
                                  "rect": rel, "abs_rect": ar, "window": 1,
                                  "source": it.get("src") or "win",
                                  "enabled": bool(it.get("e")), "ambiguous": False})
                snap["controls"] = ctrls
                t, b, cplx = choose_tier(len(ctrls), len(sc.wins), r["rec"].get("seen") or 0)
                snap.update({"tier": t, "budget": b, "deep": True, "complexity": cplx,
                             "deep_t_us": r["rec"].get("t_us"), "seen": r["rec"].get("seen"),
                             "page": {"ok": bool(r.get("page")), "doc_id": r.get("doc_id"),
                                      "doc_rect": r.get("doc_rect"),
                                      "seen": r.get("page_seen")},
                             "anchor": [ax, ay]})
            elif r is None:
                snap.update({"error": "deep-timeout", "controls": []})
            elif not r.get("items"):
                snap.update({"error": "deep-empty", "seen": (r.get("rec") or {}).get("seen"),
                             "controls": []})
        return snap

    READ_TEXT_PS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "read_text.ps1")
    FALLBACK_PS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fallback_probe.ps1")

    def fallback_scan(hwnd: int, max_items: int = 60) -> list:
        """UIA 读不到时的兜底：Raw View + 悬停 FromPoint + MSAA。"""
        if not hwnd:
            return []
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", FALLBACK_PS, "-Hwnd", str(int(hwnd)),
                 "-MaxItems", str(int(max_items))],
                capture_output=True, text=True, encoding="utf-8", timeout=25,
            )
            lines = (out.stdout or "").strip().splitlines()
            if not lines:
                return []
            d = json.loads(lines[-1])
            return d.get("items") or []
        except Exception:
            return []

    def read_document_text(hwnd: int, max_chars: int = 4000) -> str:
        """UIA TextPattern 直接读正文：不 Ctrl+A、不复制、不动剪贴板。"""
        if not hwnd:
            return ""
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", READ_TEXT_PS, "-Hwnd", str(int(hwnd)), "-MaxChars", str(int(max_chars))],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
            line = (out.stdout or "").strip().splitlines()
            if not line:
                return ""
            d = json.loads(line[-1])
            return str(d.get("text") or "")[:max_chars]
        except Exception:
            return ""

    def api_action(p: dict) -> dict:
        p = p or {}
        if act_loop is None:
            return {"ok": False, "reason": "action-unavailable"}
        typ = p.get("type")
        hwnd = int(p.get("hwnd") or 0)
        with act_loop.lock:
            # 未指定窗口时：字符串 id 先在可见窗口里找一遍（API 路径允许这点探测成本）
            if not hwnd:
                if typ == "click_id" and p.get("id"):
                    eid = str(p["id"])
                    cands = [sc.fg] + [w.hwnd for w in sc.wins.values()
                                       if not w.minimized and w.hwnd != sc.fg][:5]
                    for hw in cands:
                        if hw and act_loop._resolve(hw, eid, timeout_ms=120):
                            hwnd = hw
                            break
                if not hwnd:
                    hwnd = sc.fg
            if typ == "launch":
                # 只允许白名单程序，避免模型执行任意命令
                app = str(p.get("app") or "").strip().lower()
                allowed = {
                    "calc": ["calc.exe"], "notepad": ["notepad.exe"], "mspaint": ["mspaint.exe"],
                    "explorer": ["explorer.exe"], "cmd": ["cmd.exe"],
                    "powershell": ["powershell.exe"], "taskmgr": ["taskmgr.exe"],
                    "control": ["control.exe"], "snippingtool": ["snippingtool.exe"],
                    # Edge 走 shell 别名，避免写死安装路径
                    "edge": ["cmd", "/c", "start", "", "msedge"],
                    "browser": ["cmd", "/c", "start", "", "msedge"],
                }
                cmd = allowed.get(app)
                if not cmd:
                    return {"ok": False, "reason": "app-not-allowed", "app": app,
                            "allowed": sorted(allowed)}
                try:
                    subprocess.Popen(cmd, close_fds=True)
                except Exception as ex:
                    return {"ok": False, "reason": f"launch-failed:{type(ex).__name__}"}
                time.sleep(float(p.get("wait_ms") or 1200) / 1000.0)
                return {"ok": True, "by": "launch", "exe": cmd[-1],
                        "fg": int(W.foreground_hwnd() or 0)}
            if typ == "activate":
                h = int(p.get("hwnd") or 0)
                if not h:
                    return {"ok": False, "reason": "no-hwnd"}
                ok_fg = False
                for _ in range(3):
                    executor.activate(h, timeout_ms=400)
                    if W.foreground_hwnd() == h:
                        ok_fg = True
                        break
                    time.sleep(0.15)
                return {"ok": ok_fg, "by": "activate", "hwnd": h,
                        "fg": int(W.foreground_hwnd() or 0)}
            if typ == "focus_app":
                # 任务结束后把助手窗口切回前台：按窗口标题匹配，不依赖进程名
                hint = str(p.get("hint") or "AI")
                cand = None
                for w in sc.wins.values():
                    if hint and hint in (getattr(w, "title", "") or ""):
                        cand = w
                        break
                if cand is None:
                    return {"ok": False, "reason": "window-not-found", "hint": hint}
                h = int(cand.hwnd)
                executor.activate(h, timeout_ms=400)
                return {"ok": W.foreground_hwnd() == h, "by": "focus_app",
                        "hwnd": h, "title": getattr(cand, "title", "")}
            if typ == "keys":
                combo = str(p.get("keys") or p.get("combo") or "")
                if hwnd and W.foreground_hwnd() != hwnd:
                    executor.activate(hwnd, timeout_ms=300)
                r = executor.press_combo(combo)
                return {"ok": r.ok, "by": "keys", "keys": combo,
                        "reason": r.reason, "action": r.as_dict()}
            if typ == "type_focus":
                want = str(p.get("text") or "")
                if not want:
                    return {"ok": False, "reason": "empty-text"}
                if hwnd and W.foreground_hwnd() != hwnd:
                    executor.activate(hwnd, timeout_ms=300)
                typed = executor.type_text(want, hwnd=hwnd)
                ent = None
                if p.get("enter"):
                    time.sleep(0.05)
                    ent = executor.press_vk(0x0D)
                return {"ok": typed.ok, "by": "type_focus", "type": typed.as_dict(),
                        "enter": ent.as_dict() if ent else None}
            if typ == "fallback_scan":
                h = int(p.get("hwnd") or W.foreground_hwnd() or 0)
                if not h:
                    return {"ok": False, "reason": "no-window", "by": "fallback_scan"}
                if W.foreground_hwnd() != h:
                    executor.activate(h, timeout_ms=300)
                items = fallback_scan(h, int(p.get("max_items") or 60))
                return {"ok": bool(items), "by": "fallback_scan",
                        "count": len(items), "items": items,
                        "reason": "" if items else "empty"}
            if typ == "read_text":
                # UIA TextPattern 直接读正文，不选全、不复制、不动剪贴板
                max_chars = int(p.get("max_chars") or 4000)
                h = int(p.get("hwnd") or W.foreground_hwnd() or 0)
                if not h:
                    return {"ok": False, "reason": "no-window", "by": "read_text"}
                if W.foreground_hwnd() != h:
                    executor.activate(h, timeout_ms=300)
                text = read_document_text(h, max_chars)
                if not text:
                    time.sleep(0.5)
                    text = read_document_text(h, max_chars)
                return {"ok": bool(text), "by": "read_text", "chars": len(text),
                        "text": text, "reason": "" if text else "no-text"}
            if typ == "scroll":
                delta = int(p.get("delta") or -3)
                x, y = p.get("x"), p.get("y")
                if x is None or y is None:
                    wr = W.rect_of(hwnd) or (0, 0, 0, 0)
                    x = wr[0] + wr[2] // 2
                    y = wr[1] + wr[3] // 2
                r = executor.scroll(int(x), int(y), delta)
                return {"ok": r.ok, "by": "scroll", "action": r.as_dict()}
            if typ == "open_url":
                url = str(p.get("url") or "").strip()
                if not url.lower().startswith(("http://", "https://")):
                    return {"ok": False, "reason": "url-not-allowed", "url": url}
                try:
                    # 用新窗口打开：既不会顶掉用户正在看的标签页，也能让目标页成为前台，
                    # 否则读屏会读到应用自己那一页（同一窗口里当前激活的旧标签）。
                    subprocess.Popen(["cmd", "/c", "start", "", "msedge", "--new-window", url],
                                     close_fds=True)
                except Exception:
                    try:
                        os.startfile(url)
                    except Exception as ex:
                        return {"ok": False, "reason": f"open-failed:{type(ex).__name__}"}
                time.sleep(float(p.get("wait_ms") or 1500) / 1000.0)
                return {"ok": True, "by": "open_url", "url": url,
                        "fg": int(W.foreground_hwnd() or 0)}
            if typ == "read_url":
                # Edge 沉浸式阅读器：地址栏输入 read:<url>，页面会被压成纯正文，再用 UIA 读正文
                raw = str(p.get("url") or "").strip()
                if raw.lower().startswith("read://"):
                    raw = raw[7:]
                elif raw.lower().startswith("read:"):
                    raw = raw[5:]
                if not raw.lower().startswith(("http://", "https://")):
                    return {"ok": False, "reason": "url-not-allowed", "url": raw}
                max_chars = int(p.get("max_chars") or 4000)
                try:
                    subprocess.Popen(["cmd", "/c", "start", "", "msedge",
                                      "--new-window", "about:blank"], close_fds=True)
                except Exception as ex:
                    return {"ok": False, "reason": f"open-failed:{type(ex).__name__}"}
                time.sleep(1.5)
                h = int(W.foreground_hwnd() or 0)
                if not h:
                    return {"ok": False, "reason": "no-foreground"}
                executor.activate(h, timeout_ms=300)
                executor.press_combo("ctrl+l")
                time.sleep(0.15)
                executor.type_text("read:" + raw, hwnd=h)
                time.sleep(0.1)
                executor.press_vk(0x0D)
                time.sleep(1.0)
                executor.press_combo("esc")  # 收起地址栏联想，避免焦点留在地址栏
                time.sleep(float(p.get("wait_ms") or 4000) / 1000.0)

                # 用 UIA TextPattern 读正文，不做 Ctrl+A / Ctrl+C
                text = read_document_text(h, max_chars)
                if len(text) < 80:
                    time.sleep(0.8)
                    text = read_document_text(h, max_chars)
                return {"ok": len(text) >= 80, "by": "read_url", "url": raw,
                        "reader": "read:" + raw, "chars": len(text), "text": text,
                        "reason": "" if text else "no-text"}
            if typ == "click_rect":
                rc = p.get("rect") or [0, 0, 0, 0]
                r = executor.click(hwnd, int(rc[0]) + int(rc[2]) // 2, int(rc[1]) + int(rc[3]) // 2)
                return {"ok": r.ok, "reason": r.reason, "by": "rect", "click": r.as_dict()}
            if typ == "click_id":
                req = {"op": "click_id", "hwnd": hwnd, "id": str(p.get("id") or "")}
                if p.get("verify_id"):
                    req["verify_id"] = str(p["verify_id"])
                    req["expect"] = str(p.get("expect") or "")
                out = act_loop.perform(req)
                out["by"] = "automation-id"
                return out
            if typ == "type_text":
                cid = p.get("cid")
                ctrl = None
                ctrls = UC.build_snapshot(sc, with_fovea=False)["controls"]
                if isinstance(cid, int) and 0 <= cid < len(ctrls):
                    ctrl = ctrls[cid]
                rc = p.get("rect") or (ctrl["abs_rect"] if ctrl else None)
                if rc is None:
                    return {"ok": False, "reason": "control-not-found", "cid": cid}
                want = str(p.get("text") or "")
                title_before = W.title_of(hwnd)
                click = executor.click(hwnd, rc[0] + rc[2] // 2, rc[1] + rc[3] // 2)
                typed = executor.type_text(want, hwnd=hwnd)
                # 通道 A：焦点控件读回（输入后、回车前）。焦点控件的值里出现输入文本 = 文字确实落进目标控件。
                # Chromium 的 AX 值不是同步提交的：刚 SendInput 完读到的可能是占位符（U+FFFC），
                # 因此这里最多轮询 3 次（间隔 250ms），读到目标文本即停。
                focus_readback = {}
                if uia is not None:
                    for _ in range(3):
                        time.sleep(0.25)
                        rf = uia.query_blocking(hwnd, timeout_ms=6000, deadline_ms=600.0,
                                                hard_ms=3000.0, focus=True, want_text=True)
                        fitems = (rf or {}).get("items") or []
                        if not fitems:
                            continue
                        f0 = fitems[0]
                        focus_readback = {"type": f0.get("t"), "id": f0.get("id"),
                                          "name": f0.get("n"), "value": f0.get("v"),
                                          "abs_rect": f0.get("r"),
                                          "t_us": ((rf or {}).get("rec") or {}).get("t_us")}
                        if want and want in str(f0.get("v") or ""):
                            break
                ent = None
                if p.get("enter"):
                    time.sleep(0.05)
                    ent = executor.press_vk(0x0D)
                time.sleep(float(p.get("verify_wait_ms") or 900) / 1000.0)
                title_after = W.title_of(hwnd)
                readback = str(focus_readback.get("value") or "")
                if not (want and want in readback) and uia is not None:
                    rv = uia.query_blocking(hwnd, timeout_ms=8000, deadline_ms=600.0,
                                            hard_ms=4000.0, deep=True, want_text=True)
                    for it in ((rv or {}).get("items") or []):
                        if it.get("v") and (not want or want in it["v"]):
                            readback = it["v"]
                            break
                changed = title_after != title_before
                hit_title = bool(want) and want in title_after
                hit_focus = bool(want) and want in readback
                return {"ok": click.ok and typed.ok, "by": "type_text",
                        "click": click.as_dict(), "type": typed.as_dict(),
                        "enter": ent.as_dict() if ent else None,
                        "verified": {"ok": bool(hit_title or hit_focus),
                                     "reason": ("title-hit" if hit_title else
                                                ("focus-readback-hit" if hit_focus else "no-change")),
                                     "title_before": title_before, "title_after": title_after,
                                     "focus_type": focus_readback.get("type"),
                                     "focus_id": focus_readback.get("id"),
                                     "focus_abs_rect": focus_readback.get("abs_rect"),
                                     "focus_readback": readback[:80],
                                     "focus_readback_raw": focus_readback}}
            if typ == "click":
                cid = p.get("id")
                ctrl = None
                if isinstance(cid, int):
                    ctrls = UC.build_snapshot(sc, with_fovea=False)["controls"]
                    if 0 <= cid < len(ctrls):
                        ctrl = ctrls[cid]
                elif isinstance(cid, str):
                    ctrls = UC.build_snapshot(sc, with_fovea=False)["controls"]
                    ctrl = next((x for x in ctrls if x["id"] == cid or x["name"] == cid), None)
                if ctrl is None:
                    return {"ok": False, "reason": "control-not-found", "id": cid}
                if ctrl["id"]:
                    req = {"op": "click_id", "hwnd": hwnd, "id": ctrl["id"]}
                    if p.get("verify_id"):
                        req["verify_id"] = str(p["verify_id"])
                        req["expect"] = str(p.get("expect") or "")
                    out = act_loop.perform(req)
                    out["by"] = "automation-id"
                    return out
                rc = ctrl["abs_rect"]
                r = executor.click(hwnd, rc[0] + rc[2] // 2, rc[1] + rc[3] // 2)
                return {"ok": r.ok, "reason": r.reason, "by": "rect", "click": r.as_dict()}
            return {"ok": False, "reason": f"unknown-type:{typ}"}

    api_srv = None
    api_started = False
    if not a.no_api:
        api_srv = ApiServer(api_state, api_action, port=a.api_port)
        api_started = api_srv.start()

    def uia_tick() -> bool:
        """非阻塞回收 UIA 结果；有可用结果就追加一次 enrichment 提交。返回是否提交。"""
        if uia is None:
            return False
        published = False
        for res in uia.poll(4):
            rec = res.get("rec") or {}
            exe = exe_of(res["hwnd"])
            if rec.get("t_us") and not rec.get("cold"):
                # 冷启动（provider 初始化，~100ms）不参与画像，否则每个应用都会被判成 slow
                prof.record(exe, rec["t_us"] / 1000.0)
            elif rec.get("err") == "hard-timeout":
                prof.note_timeout(exe)
            if not res["items"]:
                continue
            if res["hwnd"] not in (0, sc.fg):
                continue
            sc.affordances = res["items"]
            sc.affordance_hwnd = sc.fg
            sc.aff_seen = int(rec.get("seen") or 0)
            do_publish("uia", set(), 0, 1, "UIA")
            published = True
        return published

    pending = {"hwnd": 0}

    def uia_submit(hwnd: int) -> None:
        if uia is None or not hwnd:
            return
        # 同一窗口 50ms 内不重复提交：减少 UIA 宿主唤醒，降低 2 核上的调度干扰（R9 修复）
        nonlocal_state = pending
        now = time.perf_counter_ns()
        if hwnd == nonlocal_state.get("last_hwnd") and \
                (now - nonlocal_state.get("last_t", 0)) < 50_000_000:
            return
        nonlocal_state["last_hwnd"], nonlocal_state["last_t"] = hwnd, now
        # 冷档不只看 hwnd，还要看宿主代数：宿主被熔断重启后，UIA provider 对同一 hwnd 又是冷的。
        # 否则“重启 -> 40ms 硬档 -> 再熔断 -> 再重启”会变成风暴（exe 宿主重启只要 0.15s，实测 90 次/45s）。
        cold_key = (int(hwnd), int(uia.counters.get("restarts", 0)))
        cold = cold_key not in uia_cold_done
        if cold:
            # 冷档：每个进程的第一个查询要付 CLR/COM/UIA provider 初始化 + 管道唤醒，
            # exe 宿主实测首查 386–664ms（后续 ~2–8ms），PowerShell 宿主 ~160ms。冷查询不计入稳态分位，
            # 因此这里给足 1500ms，避免“重启一次就被 600ms 硬档再杀一次”的循环。
            d, h = 800.0, 1500.0
        else:
            d, h, _tier = prof.budget(exe_of(hwnd))
        ok = uia.submit(hwnd, deadline_ms=d, hard_ms=h)
        if ok and cold:
            uia_cold_done.add(cold_key)
        # 宿主未就绪/在途时提交会被丢弃：记住它，下一轮再试（不阻塞任何东西）
        pending["hwnd"] = 0 if ok else hwnd

    th = threading.Thread(target=pump, name="pump", daemon=True)
    th.start()
    uia_submit(sc.fg)
    last_fg = sc.fg

    warm_mark = None
    while True:
        if warm_mark is None and (time.perf_counter_ns() - t_run0) > 5_000_000_000:
            warm_mark = (time.perf_counter_ns(), W.process_cpu_seconds())

        batch = []
        while len(batch) < 64:
            try:
                batch.append(ev_q.get_nowait())
            except queue.Empty:
                break
        if not batch:
            uia_tick()
            if pending["hwnd"]:
                uia_submit(pending["hwnd"])
            if stop.is_set() and ev_q.empty():
                break
            try:
                batch.append(ev_q.get(timeout=0.05))
                while len(batch) < 64:
                    try:
                        batch.append(ev_q.get_nowait())
                    except queue.Empty:
                        break
            except queue.Empty:
                continue

        counters["events"] += len(batch)
        t_ev = batch[-1][0]
        dirty = {e[2] for e in batch if e[2]}
        structural = any(e[1] in W.STRUCTURAL_EVENTS for e in batch)
        if structural:
            sc.rebuild()
            mode = "full"
        else:
            if not sc.patch(dirty):
                sc.rebuild()
                mode = "full"
            else:
                mode = "patch"

        if sc.fg != sc.affordance_hwnd:
            sc.affordances = []
            sc.affordance_hwnd = 0

        do_publish(mode, dirty, t_ev, len(batch), W.EVENT_NAME.get(batch[-1][1], "?"))
        n_commits += 1

        if sc.fg != last_fg or structural:
            uia_submit(sc.fg)
            last_fg = sc.fg
        uia_tick()
        if pending["hwnd"]:
            uia_submit(pending["hwnd"])

    th.join(timeout=2.0)
    f.close()
    reg.close()
    uia_stats = None
    if uia is not None:
        uia_stats = uia.stats()
        uia.stop()
        with open(os.path.join(out_dir, "uia_stats_daemon.json"), "w", encoding="utf-8") as fh:
            json.dump(uia_stats, fh, ensure_ascii=False, indent=2)

    snap_path = os.path.join(out_dir, "last_snapshot.txt")
    with open(snap_path, "w", encoding="utf-8") as fh:
        fh.write(state["body"])

    prof.save()

    wall_s = (time.perf_counter_ns() - t_run0) / 1e9
    cpu_s = W.process_cpu_seconds() - cpu0
    if warm_mark is not None:
        steady_wall = (time.perf_counter_ns() - warm_mark[0]) / 1e9
        steady_cpu = W.process_cpu_seconds() - warm_mark[1]
    else:
        steady_wall = steady_cpu = 0.0
    cur_mb, peak_mb = W.rss_mb()
    cbl = sorted(cb_ns)

    def pct(v, p):
        return v[min(len(v) - 1, int(len(v) * p / 100))] / 1000.0 if v else 0.0

    stats = {
        "wall_s": round(wall_s, 3),
        "events": counters["events"],
        "events_per_sec": round(counters["events"] / wall_s, 1) if wall_s else 0,
        "commits": n_commits,
        "commits_per_sec": round(n_commits / wall_s, 1) if wall_s else 0,
        "modes": dict(modes),
        "rebuilds": sc.rebuilds,
        "cb_samples": len(cbl),
        "cb_p50_us": round(pct(cbl, 50), 3),
        "cb_p99_us": round(pct(cbl, 99), 3),
        "cb_max_us": round(cbl[-1] / 1000.0, 3) if cbl else 0.0,
        "cpu_seconds": round(cpu_s, 4),
        "cpu_pct_total": round(100.0 * cpu_s / (wall_s * cores), 3) if wall_s else 0,
        "cpu_pct_single_core": round(100.0 * cpu_s / wall_s, 3) if wall_s else 0,
        "steady_cpu_pct_total": round(100.0 * steady_cpu / (steady_wall * cores), 3) if steady_wall else None,
        "steady_cpu_pct_single_core": round(100.0 * steady_cpu / steady_wall, 3) if steady_wall else None,
        "steady_window_s": round(steady_wall, 1),
        "cores": cores,
        "cores_logical_host": W.logical_cores(),
        "rss_mb": round(cur_mb, 2),
        "rss_peak_mb": round(peak_mb, 2),
        "tokens_est_last": S.est_tokens(state["body"]),
        "payload_bytes_last": len(state["body"].encode("utf-8")),
        "snapshot_path": snap_path,
        "register": reg_path,
        "uia_enabled": uia is not None,
        "uia": uia_stats,
        "uia_profile": prof.summary(),
        "action": (act_loop.stats if act_loop is not None else None),
        "slip": slip_cache.stats,
        "api": {"started": api_started, "port": a.api_port if not a.no_api else 0},
        "tiers": dict(tier_counts),
    }
    with open(stats_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, ensure_ascii=False, indent=2)
    if not a.quiet:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
