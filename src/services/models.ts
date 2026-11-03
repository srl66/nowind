/**
 * 模型列表探测（服务于「设置页 → 检查」）。
 *
 * 和对话一样走本地 /__llm 代理：浏览器直连第三方端点会被 CORS 拦掉。
 * 失败时退回示例列表并标记 source=demo，绝不假装连通成功。
 */
import { apiUrl, viaProxy } from "./llm";

export interface ProbeResult {
  ok: boolean;
  models: string[];
  message: string;
  source: "remote" | "demo";
}

export const DEMO_MODELS = [
  "gpt-4o-mini",
  "claude-3-5-sonnet",
  "qwen2.5-72b-instruct",
  "deepseek-chat",
];

export function isValidEndpoint(endpoint: string): boolean {
  return /^https?:\/\//i.test(endpoint.trim());
}

export async function probeModels(endpoint: string, apiKey: string): Promise<ProbeResult> {
  if (!isValidEndpoint(endpoint)) {
    return { ok: false, models: DEMO_MODELS, source: "demo", message: "invalid-endpoint" };
  }

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 8000);
  try {
    const res = await fetch(viaProxy(apiUrl(endpoint, "/models")), {
      method: "GET",
      headers: apiKey.trim() ? { "x-llm-key": apiKey.trim() } : {},
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = (await res.json()) as {
      data?: Array<{ id?: string; name?: string } | string>;
      models?: Array<{ id?: string; name?: string } | string>;
    };
    const raw = json.data ?? json.models ?? [];
    const ids = raw
      .map((m) => (typeof m === "string" ? m : m.id || m.name || ""))
      .filter((s): s is string => Boolean(s));
    if (!ids.length) throw new Error("empty-model-list");
    return { ok: true, models: ids, source: "remote", message: "ok" };
  } catch {
    return { ok: false, models: DEMO_MODELS, source: "demo", message: "unreachable" };
  } finally {
    window.clearTimeout(timer);
  }
}
