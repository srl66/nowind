"""本地轻量 API（只绑回环，无鉴权，标准库实现）。

GET  /state   -> 当前压缩快照（JSON，含每个控件的 rect + 按需 fovea）
POST /action  -> {"type":"click","id":3} 或 {"type":"click_rect","rect":[x,y,w,h]}
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    state_fn = None
    action_fn = None

    def log_message(self, fmt, *args):  # 静音，避免刷屏
        return

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            with open(os.path.join(os.getcwd(), "logs", "api_paths.log"), "a", encoding="utf-8") as f:
                f.write(self.path + "\n")
        except Exception:
            pass
        path = self.path.split("?")[0]
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        if path != "/state":
            self._send(404, {"error": "not-found"})
            return
        deep = any(part.strip().lower() in ("deep=1", "deep", "depth=1") for part in qs.split("&"))
        try:
            self._send(200, type(self).state_fn(deep))
        except Exception as ex:  # noqa: BLE001
            self._send(500, {"error": f"{type(ex).__name__}: {ex}"})

    def do_POST(self):
        if self.path.split("?")[0] != "/action":
            self._send(404, {"error": "not-found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, type(self).action_fn(payload))
        except Exception as ex:  # noqa: BLE001
            self._send(500, {"error": f"{type(ex).__name__}: {ex}"})


class ApiServer:
    def __init__(self, state_fn, action_fn, host="127.0.0.1", port=8737):
        self.host, self.port = host, port
        self._srv = None
        self._th = None
        self._state_fn = state_fn
        self._action_fn = action_fn

    def start(self) -> bool:
        h = type("H", (_Handler,), {"state_fn": staticmethod(self._state_fn),
                                    "action_fn": staticmethod(self._action_fn)})
        try:
            self._srv = ThreadingHTTPServer((self.host, self.port), h)
        except Exception:
            return False
        self._srv.daemon_threads = True
        self._th = threading.Thread(target=self._srv.serve_forever, name="api", daemon=True)
        self._th.start()
        return True

    def stop(self):
        if self._srv:
            self._srv.shutdown()
