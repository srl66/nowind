"""Fovea：局部区域抓屏（只在“UIA 空树 / 同名控件无法区分”时使用）。

约束：
- 只抓固定 300x300 的区域（以目标点为中心），绝不抓全屏；
- 不参与常规感知路径，只在 /state 需要消歧时按需调用；
- 用 GDI BitBlt + 自己写的最小 PNG 编码（仅依赖 zlib），不引入第三方库。
"""
from __future__ import annotations

import base64
import struct
import time
import zlib
from ctypes import POINTER, Structure, byref, c_int, c_ulong, c_void_p, sizeof, wintypes

gdi32 = __import__("ctypes").WinDLL("gdi32", use_last_error=True)
user32 = __import__("ctypes").WinDLL("user32", use_last_error=True)

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(Structure):
    _fields_ = [("biSize", c_ulong), ("biWidth", c_int), ("biHeight", c_int),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", c_ulong), ("biSizeImage", c_ulong),
                ("biXPelsPerMeter", c_int), ("biYPelsPerMeter", c_int),
                ("biClrUsed", c_ulong), ("biClrImportant", c_ulong)]


user32.GetDC.argtypes = [c_void_p]
user32.GetDC.restype = c_void_p
user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
gdi32.CreateCompatibleDC.argtypes = [c_void_p]
gdi32.CreateCompatibleDC.restype = c_void_p
gdi32.CreateDIBSection.argtypes = [c_void_p, POINTER(BITMAPINFOHEADER), c_ulong,
                                   POINTER(c_void_p), c_void_p, c_ulong]
gdi32.CreateDIBSection.restype = c_void_p
gdi32.SelectObject.argtypes = [c_void_p, c_void_p]
gdi32.BitBlt.argtypes = [c_void_p, c_int, c_int, c_int, c_int, c_void_p, c_int, c_int, c_ulong]
gdi32.DeleteObject.argtypes = [c_void_p]
gdi32.DeleteDC.argtypes = [c_void_p]


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def encode_png(w: int, h: int, rgba: bytes) -> bytes:
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _chunk(b"IEND", b""))


def grab(cx: int, cy: int, size: int = 300) -> dict | None:
    """以 (cx, cy) 为中心抓 size x size 的区域，返回 PNG + base64。"""
    w = h = int(size)
    left, top = int(cx) - w // 2, int(cy) - h // 2

    hdc = user32.GetDC(None)
    if not hdc:
        return None
    dib = None
    memdc = None
    try:
        bmi = BITMAPINFOHEADER()
        bmi.biSize = sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h            # 负高度 = top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0
        bits = c_void_p()
        dib = gdi32.CreateDIBSection(hdc, byref(bmi), DIB_RGB_COLORS, byref(bits), None, 0)
        if not dib:
            return None
        memdc = gdi32.CreateCompatibleDC(hdc)
        gdi32.SelectObject(memdc, dib)
        t0 = time.perf_counter_ns()
        ok = gdi32.BitBlt(memdc, 0, 0, w, h, hdc, left, top, SRCCOPY)
        grab_us = (time.perf_counter_ns() - t0) // 1000
        if not ok:
            return None
        buf = __import__("ctypes").string_at(bits, w * h * 4)
        # BGRA -> RGBA，并把 alpha 置 255（BitBlt 不写 alpha）
        ba = bytearray(buf)
        ba[0::4], ba[2::4] = ba[2::4], ba[0::4]
        ba[3::4] = b"\xff" * (w * h)
        png = encode_png(w, h, bytes(ba))
        return {"png_b64": base64.b64encode(png).decode("ascii"),
                "rect": [left, top, w, h], "bytes": len(png), "grab_us": grab_us}
    finally:
        if memdc:
            gdi32.DeleteDC(memdc)
        if dib:
            gdi32.DeleteObject(dib)
        user32.ReleaseDC(None, hdc)


def capture_fovea(x: int, y: int, w: int = 300, h: int = 300, **_) -> dict | None:
    """对外接口：以控件中心 (x+ w/2, y + h/2) 为中心抓 300x300。"""
    return grab(int(x) + int(w) // 2, int(y) + int(h) // 2, size=300)


if __name__ == "__main__":
    r = capture_fovea(400, 300, 10, 10)
    print({k: (v if k != "png_b64" else v[:24] + "...") for k, v in (r or {}).items()})
