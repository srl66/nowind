/**
 * 本地 Python 中间件（127.0.0.1:8737）客户端。
 *
 * 浏览器直接访问 8737 会被 CORS 拦掉，所以统一走 Vite 的 /__llm 代理（同源）。
 * 中间件是独立进程，需要先启动它（见使用说明），否则这里会超时。
 */
import { viaProxy } from "./llm";

const MW = "http://127.0.0.1:8737";

export interface Ctrl {
  cid: number;
  id: string;
  type: string;
  name: string;
  rect: number[];
  abs_rect: number[];
  enabled: boolean;
  /** fallback 时的来源：raw / point / point-right / msaa */
  source?: string;
}

export interface ScreenState {
  v?: number;
  fg?: number;
  tier?: string;
  error?: string;
  window_title?: string;
  controls?: Ctrl[];
  [key: string]: unknown;
}

async function call<T>(path: string, init?: RequestInit, timeoutMs = 20_000): Promise<T> {
  const res = await fetch(viaProxy(MW + path), {
    ...init,
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`middleware HTTP ${res.status}`);
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`middleware bad-json: ${text.slice(0, 120)}`);
  }
}

export function getState(deep = false): Promise<ScreenState> {
  // 深度读屏要走 UIA，最坏 15s 左右，不能按普通请求的 4s 掐断
  return call<ScreenState>(deep ? "/state?deep=1" : "/state", undefined, deep ? 25_000 : 8_000);
}

export function postAction(
  body: Record<string, unknown>,
  timeoutMs = 20_000
): Promise<Record<string, unknown>> {
  return call<Record<string, unknown>>(
    "/action",
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    },
    timeoutMs
  );
}

/** 任务结束后把应用自己的窗口切回前台（浏览器 / Tauri 都靠窗口标题匹配） */
export function focusApp(hint = "AI"): Promise<Record<string, unknown>> {
  return postAction({ type: "focus_app", hint });
}

export async function ping(): Promise<boolean> {
  try {
    await call<ScreenState>("/state", undefined, 3_000);
    return true;
  } catch {
    return false;
  }
}
