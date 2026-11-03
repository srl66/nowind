/**
 * 真实模型调用（OpenAI 兼容协议）。
 *
 * 走本机 Vite 的 /__llm 代理，而不是浏览器直连：第三方 API 不返回 CORS 头，
 * 直连必失败。代理只在本机 dev/preview 服务里存在（见 vite-plugin-llm-proxy.ts）。
 */
export interface LlmMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface LlmConfig {
  endpoint: string;
  apiKey: string;
  model: string;
  temperature: number;
  maxTokens: number;
}

/** 把用户填的 Endpoint 归一化成具体的 API 地址（容忍带/不带 /v1、以及误填成完整路径）。 */
export function apiUrl(endpoint: string, path: "/chat/completions" | "/models"): string {
  let base = endpoint.trim().replace(/\/+$/, "");
  base = base.replace(/\/chat\/completions$/i, "").replace(/\/models$/i, "");
  return `${base}${path}`;
}

export function viaProxy(target: string): string {
  return `/__llm?url=${encodeURIComponent(target)}`;
}

async function httpError(res: Response): Promise<string> {
  let detail = "";
  try {
    detail = (await res.text()).replace(/\s+/g, " ").slice(0, 260);
  } catch {
    // 忽略
  }
  return `HTTP ${res.status}${detail ? ` · ${detail}` : ""}`;
}

/**
 * 流式对话。每收到一段文本就回调 onDelta；上游不是 SSE（有些网关直接回 JSON）时自动降级。
 */
export async function streamChat(
  cfg: LlmConfig,
  messages: LlmMessage[],
  onDelta: (s: string) => void,
  signal?: AbortSignal,
  onReasoning?: (s: string) => void
): Promise<void> {
  const res = await fetch(viaProxy(apiUrl(cfg.endpoint, "/chat/completions")), {
    method: "POST",
    headers: { "content-type": "application/json", "x-llm-key": cfg.apiKey },
    body: JSON.stringify({
      model: cfg.model,
      messages,
      temperature: cfg.temperature,
      max_tokens: cfg.maxTokens,
      stream: true,
    }),
    signal,
  });
  if (!res.ok) throw new Error(await httpError(res));

  const ct = (res.headers.get("content-type") ?? "").toLowerCase();
  if (ct.includes("text/event-stream") && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const s = line.trim();
        if (!s.startsWith("data:")) continue;
        const payload = s.slice(5).trim();
        if (payload === "[DONE]") return;
        try {
          const json = JSON.parse(payload);
          const reasoning =
            json?.choices?.[0]?.delta?.reasoning_content ??
            json?.choices?.[0]?.message?.reasoning_content ??
            "";
          if (typeof reasoning === "string" && reasoning && onReasoning) onReasoning(reasoning);
          const delta =
            json?.choices?.[0]?.delta?.content ?? json?.choices?.[0]?.message?.content ?? "";
          if (typeof delta === "string" && delta) onDelta(delta);
        } catch {
          // 非 JSON 的心跳行忽略
        }
      }
    }
    return;
  }

  const json = (await res.json()) as {
    choices?: Array<{
      message?: { content?: string; reasoning_content?: string };
      delta?: { content?: string; reasoning_content?: string };
    }>;
  };
  const reasoning =
    json?.choices?.[0]?.message?.reasoning_content ??
    json?.choices?.[0]?.delta?.reasoning_content ??
    "";
  if (reasoning && onReasoning) onReasoning(reasoning);
  const text = json?.choices?.[0]?.message?.content ?? json?.choices?.[0]?.delta?.content ?? "";
  if (text) onDelta(text);
}
