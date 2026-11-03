"""Phase 3：Screen Shadow Register（内存映射双端寄存器）。

布局（小端）：
  [0:8]   u64 seq        —— 奇数=写入中，偶数=稳定；读者用它检测撕裂
  [8:12]  u32 length     —— payload 字节数
  [12:16] u32 version    —— 单调版本号
  [16:24] u64 t_commit_us—— 提交时刻（perf_counter_ns()//1000，跨进程同一 QPC）
  [24:..] payload

写者：seq+1(奇) -> 写头部与 payload -> seq+2(偶)
读者：读 seq(偶) -> 读头与 payload -> 再读 seq，一致则接受；否则重试，最多 8 次。
"""
from __future__ import annotations

import mmap
import os
import struct

HEADER = 24
PAYLOAD = 16384
TOTAL = HEADER + PAYLOAD


class RegisterWriter:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.f = open(path, "r+b" if os.path.exists(path) else "w+b")
        if os.path.getsize(path) < TOTAL:
            self.f.seek(0)
            self.f.write(b"\x00" * TOTAL)
            self.f.flush()
        self.mm = mmap.mmap(self.f.fileno(), TOTAL, access=mmap.ACCESS_WRITE)
        self.seq = struct.unpack_from("<Q", self.mm, 0)[0]

    def publish(self, data: bytes, version: int, t_commit_us: int) -> None:
        if len(data) > PAYLOAD:
            data = data[:PAYLOAD]
        seq = self.seq
        struct.pack_into("<Q", self.mm, 0, seq + 1)          # 进入写入态（奇数）
        struct.pack_into("<IIQ", self.mm, 8, len(data), version, t_commit_us)
        self.mm[HEADER:HEADER + len(data)] = data
        struct.pack_into("<Q", self.mm, 0, seq + 2)          # 提交（偶数）
        self.seq = seq + 2

    def close(self) -> None:
        try:
            self.mm.close()
        finally:
            self.f.close()


class RegisterReader:
    def __init__(self, path: str):
        self.f = open(path, "rb")
        self.mm = mmap.mmap(self.f.fileno(), TOTAL, access=mmap.ACCESS_READ)

    def read(self) -> tuple[int, int, bytes] | None:
        mm = self.mm
        for _ in range(8):
            s1 = struct.unpack_from("<Q", mm, 0)[0]
            if s1 & 1:
                continue
            ln, ver, t = struct.unpack_from("<IIQ", mm, 8)
            if ln > PAYLOAD:
                continue
            body = bytes(mm[HEADER:HEADER + ln])
            s2 = struct.unpack_from("<Q", mm, 0)[0]
            if s1 == s2:
                return ver, t, body
        return None

    def close(self) -> None:
        try:
            self.mm.close()
        finally:
            self.f.close()
