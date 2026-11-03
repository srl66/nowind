"""命名管道动作服务（跑在 daemon 的独立线程里）。

协议：一行一个 JSON。请求 {op, hwnd, x, y, text}；响应为 perform() 的返回。
用 multiprocessing.connection 的 AF_PIPE，零第三方依赖。
"""
from __future__ import annotations

import os
from multiprocessing.connection import Listener


def serve(loop, pipe_name: str, ready_path: str) -> None:
    try:
        listener = Listener(pipe_name, family="AF_PIPE", backlog=1)
    except Exception:
        return
    try:
        os.makedirs(os.path.dirname(os.path.abspath(ready_path)), exist_ok=True)
        with open(ready_path, "w", encoding="utf-8") as f:
            f.write(pipe_name)
    except Exception:
        pass

    while True:
        try:
            conn = listener.accept()
        except Exception:
            break
        try:
            while True:
                try:
                    req = conn.recv()
                except EOFError:
                    break
                except Exception:
                    break
                try:
                    resp = loop.perform(dict(req))
                except Exception as ex:  # noqa: BLE001
                    resp = {"ok": False, "error": f"{type(ex).__name__}: {ex}"}
                try:
                    conn.send(resp)
                except Exception:
                    break
        finally:
            try:
                conn.close()
            except Exception:
                pass
