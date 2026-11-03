/**
 * 本地 LLM 代理（只在 Vite 的 dev / preview 服务里生效）。
 *
 * 为什么需要它：浏览器直连 https://api.deepseek.com 会被 CORS 拦掉（第三方接口不返回
 * Access-Control-Allow-Origin），「检查模型」和「发送消息」都会失败。这里让 Vite（Node 进程）
 * 代发请求，浏览器只和同源的 /__llm 说话，所以不需要 Tauri、也不需要额外开进程。
 *
 * 用法：POST/GET /__llm?url=<目标绝对地址>
 *   - 请求头 x-llm-key: <API Key>（会被转成 Authorization: Bearer ...）
 *   - 请求体原样转发；响应原样回传（含 text/event-stream 流式）
 *
 * 安全边界：只接受 Host 为 localhost/127.0.0.1 的调用；目标只允许 http/https。
 * 这是本机开发期的桥，打包成 Tauri 后应改成 Rust command。
 */
import type { Connect, Plugin } from "vite";
import http from "node:http";
import https from "node:https";
import { URL } from "node:url";

const PREFIX = "/__llm";

function isLocalHost(host: string | undefined): boolean {
  if (!host) return false;
  const h = host.toLowerCase();
  return h.startsWith("localhost") || h.startsWith("127.0.0.1") || h.startsWith("[::1]");
}

function handler(): Connect.NextHandleFunction {
  return (req, res, next) => {
    const parsed = new URL(req.url ?? "", "http://localhost");
    if (!parsed.pathname.startsWith(PREFIX)) return next();

    if (!isLocalHost(req.headers.host)) {
      res.statusCode = 403;
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ error: "forbidden-host" }));
      return;
    }

    const raw = parsed.searchParams.get("url");
    let target: URL;
    try {
      if (!raw) throw new Error("missing-url");
      target = new URL(raw);
    } catch {
      res.statusCode = 400;
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ error: "bad-url" }));
      return;
    }
    if (target.protocol !== "http:" && target.protocol !== "https:") {
      res.statusCode = 400;
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ error: "bad-protocol" }));
      return;
    }

    const headers: Record<string, string> = {
      "content-type": (req.headers["content-type"] as string) || "application/json",
      accept: (req.headers.accept as string) || "application/json",
    };
    const key = req.headers["x-llm-key"];
    if (typeof key === "string" && key.trim()) headers.authorization = `Bearer ${key.trim()}`;

    const lib = target.protocol === "https:" ? https : http;

    const forward = (body?: Buffer) => {
      // 必须显式带 Content-Length：Python 的 BaseHTTPRequestHandler 不认 chunked，
      // 用 req.pipe() 转发时 body 会被当成空对象（中间件报 unknown-type:None）。
      if (body) headers["content-length"] = String(body.length);
      const upstream = lib.request(
        target,
        { method: req.method, headers },
        (up) => {
          res.statusCode = up.statusCode ?? 502;
          const ct = up.headers["content-type"];
          if (ct) res.setHeader("content-type", ct);
          res.setHeader("cache-control", "no-store");
          res.setHeader("x-accel-buffering", "no"); // 关掉中间层缓冲，保证流式是真流式
          up.pipe(res);
        }
      );

      upstream.on("error", (err) => {
        if (!res.headersSent) {
          res.statusCode = 502;
          res.setHeader("content-type", "application/json");
        }
        res.end(JSON.stringify({ error: `upstream: ${err.message}` }));
      });

      upstream.end(body);
    };

    if (req.method === "GET" || req.method === "HEAD") {
      forward();
      return;
    }

    const chunks: Buffer[] = [];
    req.on("data", (chunk: Buffer) => chunks.push(chunk));
    req.on("end", () => forward(Buffer.concat(chunks)));
    req.on("error", (err) => {
      if (!res.headersSent) {
        res.statusCode = 400;
        res.setHeader("content-type", "application/json");
      }
      res.end(JSON.stringify({ error: `request: ${err.message}` }));
    });
  };
}

export function llmProxy(): Plugin {
  return {
    name: "asp-llm-proxy",
    configureServer(server) {
      server.middlewares.use(handler());
    },
    configurePreviewServer(server) {
      server.middlewares.use(handler());
    },
  };
}
