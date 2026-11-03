"""Phase 3：跨进程 agent 读取接口 + 读取延迟实测。

独立进程打开 SSR 内存映射做只读，测每次 read() 的耗时（µs），并验证版本单调性。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ssr import RegisterReader  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="logs/ssr.bin")
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--out", default="logs/read_stats.json")
    ap.add_argument("--wait-s", type=float, default=5.0)
    a = ap.parse_args()

    deadline = time.time() + a.wait_s
    while not os.path.exists(a.path) and time.time() < deadline:
        time.sleep(0.02)
    if not os.path.exists(a.path):
        print(json.dumps({"error": "register not found", "path": a.path}))
        return 2

    rr = RegisterReader(a.path)
    samples: list[float] = []
    versions: list[int] = []
    bad = 0
    sample_body = ""
    for _ in range(a.n):
        t0 = time.perf_counter_ns()
        r = rr.read()
        samples.append((time.perf_counter_ns() - t0) / 1000.0)
        if r is None:
            bad += 1
            continue
        ver, t_commit, body = r
        versions.append(ver)
        if body and not sample_body:
            sample_body = body.decode("utf-8", "replace")
    rr.close()

    samples.sort()

    def pct(p):
        return round(samples[min(len(samples) - 1, int(len(samples) * p / 100))], 3) if samples else 0.0

    uniq = sorted(set(versions))
    stats = {
        "reads": a.n,
        "torn_or_empty": bad,
        "read_p50_us": pct(50),
        "read_p95_us": pct(95),
        "read_p99_us": pct(99),
        "read_max_us": round(samples[-1], 3) if samples else 0.0,
        "versions_seen": len(uniq),
        "version_min": uniq[0] if uniq else -1,
        "version_max": uniq[-1] if uniq else -1,
        "monotonic_ok": all(b >= aa for aa, b in zip(versions, versions[1:])),
        "payload_bytes": len(sample_body.encode("utf-8")),
        "sample_head": sample_body.split("\n")[0] if sample_body else "",
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
