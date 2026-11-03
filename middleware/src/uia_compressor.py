"""把当前 Scene 压成给大模型用的 JSON 快照（带坐标），并按需挂 Fovea 局部图。

与 DSL 的关系：
- DSL（`scene.render`）走极速闭环，省 token，不含 base64；
- 本模块输出的 JSON 只给外部大脑 / `/state` 用，字段冗余但语义明确（每个控件都带 rect）。
"""
from __future__ import annotations

import time

import fovea


CACHE_TTL_MS = 800.0


def _rel(abs_rect, win_rect):
    return [abs_rect[0] - win_rect[0], abs_rect[1] - win_rect[1], abs_rect[2], abs_rect[3]]


def _fovea_reason(controls):
    if not controls:
        return "empty"
    names = {}
    for c in controls:
        n = (c.get("name") or "").strip()
        if n:
            names[n] = names.get(n, 0) + 1
    if any(v > 1 for v in names.values()):
        return "ambiguous"
    return None


def build_snapshot(sc, *, version=0, mode="", tier="basic", budget=150,
                   tokens_est=0, with_fovea=True, cache=None) -> dict:
    """cache: 由 daemon 持有的 dict，用来避免每次 /state 都重新抓图。"""
    now = time.perf_counter_ns() // 1_000_000
    visible_all = sorted((w for w in sc.wins.values() if not w.minimized),
                         key=lambda w: (0 if w.hwnd == sc.fg else 1, w.z))
    idx = {}
    windows = []
    for i, w in enumerate(visible_all, 1):
        idx[w.hwnd] = i
        windows.append({
            "i": i, "title": w.title, "exe": w.exe, "hwnd": w.hwnd,
            "rect": list(w.rect), "rel_rect": [0, 0, w.rect[2], w.rect[3]],
            "z": w.z, "fg": w.hwnd == sc.fg, "minimized": False,
        })
    for w in sorted((x for x in sc.wins.values() if x.minimized), key=lambda x: x.z):
        windows.append({
            "i": 0, "title": w.title, "exe": w.exe, "hwnd": w.hwnd,
            "rect": list(w.rect), "rel_rect": [0, 0, w.rect[2], w.rect[3]],
            "z": w.z, "fg": False, "minimized": True,
        })

    fh = sc.affordance_hwnd or sc.fg
    fwin = sc.wins.get(fh)
    controls = []
    for cid, a in enumerate([x for x in sc.affordances if x.get("e") and not x.get("o")]):
        ar = list(a.get("r") or [0, 0, 0, 0])
        controls.append({
            "cid": cid,
            "id": a.get("id") or "",
            "name": a.get("n") or "",
            "type": a.get("t") or "",
            "rect": _rel(ar, fwin.rect) if fwin else ar,   # 相对所属窗口
            "abs_rect": ar,
            "window": idx.get(fh, 0),
            "enabled": bool(a.get("e")),
            "ambiguous": False,
        })
    names = {}
    for c in controls:
        n = c["name"].strip()
        if n:
            names[n] = names.get(n, 0) + 1
    for c in controls:
        c["ambiguous"] = bool(c["name"] and names.get(c["name"].strip(), 0) > 1)

    out = {
        "v": version, "mode": mode, "tier": tier, "budget": budget,
        "tokens_est": tokens_est,
        "windows": windows, "controls": controls,
        "obs": dict(sc.last_obs) if sc.last_obs else None,
    }

    if not with_fovea:
        return out

    reason = _fovea_reason(controls)
    if not reason:
        return out
    # 触发条件命中：抓一次并缓存，避免同一个状态反复抓图
    key = (fh, len(controls), tuple(tuple(c["abs_rect"]) for c in controls[:4]))
    hit = (cache or {}).get(key)
    if hit and (now - hit["t_ms"]) <= CACHE_TTL_MS:
        out["fovea"] = hit["val"]
        return out

    target = None
    if reason == "ambiguous":
        dup = next(c for c in controls if c["ambiguous"])
        target = dup["abs_rect"]
    elif fwin:
        target = [fwin.rect[0] + fwin.rect[2] // 2, fwin.rect[1] + fwin.rect[3] // 2, 1, 1]

    if target:
        t0 = time.perf_counter_ns()
        shot = fovea.capture_fovea(target[0], target[1], target[2], target[3])
        if shot:
            shot["reason"] = reason
            shot["ms"] = (time.perf_counter_ns() - t0) // 1_000_000
            out["fovea"] = shot
            if cache is not None:
                cache[key] = {"t_ms": now, "val": shot}
    return out
