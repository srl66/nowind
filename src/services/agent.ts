/**
 * 工具调用闭环：模型 -> 读屏幕 -> 点控件 / 输入 -> 确认 -> 用自然语言回答。
 *
 * 设计要点（对应截图里的三类毛病）：
 *  1) 工具结果是**给模型看的紧凑文本**，不是原始 JSON；UI 只显示一行短标签。
 *  2) 失败必须给出可行动的原因（例如“必须带 cid，当前可见输入框 2:xxx”），而不是 ok:false。
 *  3) 轮次上限后**强制收尾**：再发一次不带 tools 的请求，让模型把结论说完，避免停在半路。
 *  4) 全链路支持 AbortSignal：用户点“停止”时立刻中断，不再发起下一轮。
 */
import { apiUrl, viaProxy, type LlmConfig, type LlmMessage } from "./llm";
import { getState, postAction, type ScreenState } from "./middleware";
import { TOKEN_CAP } from "./tokens";

interface ToolCall {
  id: string;
  type: string;
  function: { name: string; arguments: string };
}

interface AssistantMsg {
  role: "assistant";
  content: string | null;
  tool_calls?: ToolCall[];
}

interface ToolOutcome {
  ok: boolean;
  /** 回填给模型的紧凑文本 */
  payload: string;
  /** 显示在气泡里的一行短标签 */
  label: string;
}

const TOOLS = [
  {
    type: "function",
    function: {
      name: "list_windows",
      description: "列出桌面上可见的窗口（hwnd / 标题 / 进程）。要操作的不是当前前台窗口时，先用它拿 hwnd。",
      parameters: { type: "object", properties: {}, required: [] },
    },
  },
  {
    type: "function",
    function: {
      name: "focus_window",
      description: "把指定窗口切到前台（hwnd 来自 list_windows），之后要重新 read_screen。",
      parameters: {
        type: "object",
        properties: { hwnd: { type: "number", description: "list_windows 返回的 hwnd" } },
        required: ["hwnd"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "launch_app",
      description:
        "打开程序：calc / notepad / mspaint / explorer / cmd / powershell / taskmgr / control / edge(browser) / snippingtool。要打开网页用 open_url。",
      parameters: {
        type: "object",
        properties: {
          app: { type: "string", description: "calc | notepad | mspaint | explorer | cmd | powershell | taskmgr | control | edge | snippingtool" },
          wait_ms: { type: "number", description: "启动后等待毫秒，默认 1200" },
        },
        required: ["app"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "read_screen",
      description:
        "读取当前前台窗口和可交互控件。返回 cid、类型、名称、屏幕坐标以及窗口标题。任何点击/输入前都必须先调用一次。控件列表超出屏幕 token 预算时会被截断，并提示还有多少条未列出。",
      parameters: {
        type: "object",
        properties: {
          deep: { type: "boolean", description: "浏览器页面内的控件需要 true；普通窗口用 false" },
          limit: { type: "number", description: "可选：最多列出多少条控件；自动模式下可用它请求更多（上限约 1200 token）" },
          fallback: {
            type: "boolean",
            description:
              "UIA 深层读屏仍找不到目标控件时设为 true：额外用 Raw View + 悬停 FromPoint + MSAA 兜底（会短暂移动鼠标，稍慢）",
          },
        },
        required: [],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "click_control",
      description: "点击 read_screen 返回的某个控件；必须使用它返回的 cid，不要自己编。",
      parameters: {
        type: "object",
        properties: { cid: { type: "number", description: "read_screen 返回的 cid" } },
        required: ["cid"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "type_text",
      description:
        "输入文本。带 cid 会先点击该控件再输入（适合 Edit 控件）；带 focus=true 则直接输入到当前焦点，适合地址栏、搜索框、聊天输入框等读不到控件的场景。",
      parameters: {
        type: "object",
        properties: {
          text: { type: "string", description: "要输入的文字" },
          cid: { type: "number", description: "目标输入框的 cid（来自 read_screen）" },
          enter: { type: "boolean", description: "输入后是否按回车" },
          focus: { type: "boolean", description: "直接输入到当前焦点，不需要 cid" },
        },
        required: ["text"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "press_keys",
      description:
        "发送键盘快捷键到当前窗口。例：ctrl+l 定位浏览器地址栏、ctrl+a 全选、ctrl+c 复制、ctrl+v 粘贴、ctrl+z 撤销、enter 提交、tab 切换焦点、alt+tab 切窗口、esc 关闭弹窗。普通文字用 type_text。",
      parameters: {
        type: "object",
        properties: {
          keys: { type: "string", description: "组合键，如 ctrl+l / ctrl+a / enter / alt+tab" },
          hwnd: { type: "number", description: "可选：先把该窗口切到前台" },
        },
        required: ["keys"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "scroll",
      description:
        "在窗口中心或指定坐标滚动滚轮，用于浏览长列表、网页或聊天记录。delta 正数向上、负数向下，通常用 3 或 -3。",
      parameters: {
        type: "object",
        properties: {
          delta: { type: "number", description: "滚动格数，正上负下" },
          x: { type: "number", description: "可选：屏幕 x 坐标" },
          y: { type: "number", description: "可选：屏幕 y 坐标" },
        },
        required: ["delta"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "read_url",
      description:
        "用 Edge 阅读模式打开网页并直接返回正文（内部在地址栏输入 read:<url>，再用 UIA 读取正文）。适合新闻、文章、博客等正文页面；视频或交互页面用 open_url + read_text。",
      parameters: {
        type: "object",
        properties: {
          url: { type: "string", description: "完整链接，http:// 或 https:// 开头" },
          max_chars: { type: "number", description: "最多返回多少字符，默认 4000" },
        },
        required: ["url"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "read_text",
      description:
        "用 UIA 直接读取当前前台窗口或网页的可见正文（不选全、不复制、不动剪贴板）。读网页正文、文章、搜索结果时用它，比只看控件名有效。",
      parameters: {
        type: "object",
        properties: {
          max_chars: { type: "number", description: "最多返回多少字符，默认 3000" },
          hwnd: { type: "number", description: "可选：先把该窗口切到前台" },
        },
        required: [],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "finish_task",
      description:
        "任务真正完成、并且已经通过工具结果确认后才调用，调用后本次任务结束。没完成不要调用，继续执行下一步。",
      parameters: {
        type: "object",
        properties: {
          summary: { type: "string", description: "一句话结果：做了什么、结果如何" },
          success: { type: "boolean", description: "任务是否成功完成" },
        },
        required: ["summary", "success"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "open_url",
      description:
        "用浏览器的新窗口打开一个 http/https 链接（不会顶掉当前标签页），之后要 read_screen 确认页面标题再操作。",
      parameters: {
        type: "object",
        properties: {
          url: { type: "string", description: "完整链接，必须以 http:// 或 https:// 开头" },
        },
        required: ["url"],
      },
    },
  },
];

let cache: ScreenState | null = null;
let lastReadSig = "";

function parseArgs(raw: string): Record<string, unknown> {
  try {
    return JSON.parse(raw || "{}") as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** 有些模型会把工具调用标记（如 <｜DSML｜tool_calls>）写进 content，不能原样显示给用户 */
function cleanText(raw: string): string {
  return raw
    .replace(/<[^>]*DSML[^>]*>/g, "")
    .replace(/<\/?[^>]*(?:tool_calls|invoke|parameter)[^>]*>/gi, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
}

export interface ScreenTokenConfig {
  mode: "auto" | "custom";
  budget: number;
}

/** 读屏行大多是中英混合，按 2 字符 ≈ 1 token 估算 */
function lineTokens(line: string): number {
  return Math.max(6, Math.ceil(line.length / 2));
}

const SCREEN_TOKEN_CAP = 4000;

/** 自动预算按窗口复杂度给：网页这种上百个控件的直接给足，避免只读到导航栏 */
function autoBudgetFor(total: number): number {
  if (total <= 15) return 300;
  if (total <= 40) return 600;
  if (total <= 120) return 1800;
  return 3000;
}

function screenBudgetOf(limit: unknown, screen: ScreenTokenConfig | undefined, total: number): number {
  // 自定义：用户定的上限就是硬上限，模型要更多也不给
  if ((screen?.mode ?? "auto") === "custom") {
    return Math.min(SCREEN_TOKEN_CAP, Math.max(80, Math.round(screen?.budget ?? 300)));
  }
  let base = autoBudgetFor(total);
  // 自动：模型还可以用 limit（控件条数）再要更多
  const n = Number(limit);
  if (Number.isFinite(n) && n > 0) base = Math.min(SCREEN_TOKEN_CAP, Math.max(base, n * 15));
  return base;
}

async function execTool(
  name: string,
  args: Record<string, unknown>,
  signal?: AbortSignal,
  screen?: ScreenTokenConfig
): Promise<ToolOutcome> {
  throwIfAborted(signal);

  if (name === "list_windows") {
    const st = await getState(false);
    const wins = (st.windows ?? []) as Array<{ hwnd?: number; title?: string; exe?: string }>;
    if (!wins.length) {
      return { ok: false, payload: "fail 没有读到窗口列表", label: "列窗口 · 0 个" };
    }
    const lines = wins
      .slice(0, 12)
      .map((w) => `${w.hwnd} ${(w.title || "-").slice(0, 24)} [${w.exe || "-"}]`);
    return {
      ok: true,
      payload: `ok total=${wins.length}\n${lines.join("\n")}`,
      label: `列窗口 · ${wins.length} 个`,
    };
  }

  if (name === "focus_window") {
    const hwnd = Number(args.hwnd);
    const out = await postAction({ type: "activate", hwnd });
    lastReadSig = "";
    return {
      ok: Boolean(out.ok),
      payload: out.ok ? `ok 已切到 hwnd=${hwnd}` : `fail 切换失败（当前前台 ${out.fg ?? "?"}）`,
      label: `切换窗口 ${hwnd} · ${out.ok ? "ok" : "失败"}`,
    };
  }

  if (name === "launch_app") {
    const app = String(args.app || "").trim().toLowerCase();
    const out = await postAction({ type: "launch", app, wait_ms: Number(args.wait_ms ?? 1200) });
    lastReadSig = "";
    return {
      ok: Boolean(out.ok),
      payload: out.ok
        ? `ok 已启动 ${app}（前台 hwnd=${out.fg ?? "?"}）`
        : `fail 启动失败：${out.reason ?? "unknown"}`,
      label: `启动 ${app} · ${out.ok ? "ok" : "失败"}`,
    };
  }

  if (name === "read_screen") {
    const deep = Boolean(args.deep);
    // 先记下“读的是哪一屏 + 用哪种预算模式”，同一签名重复读直接走缓存
    const sig = `read:${deep}:${Number(args.limit) || 0}:${screen?.mode ?? "auto"}:${screen?.budget ?? 0}`;
    if (sig === lastReadSig && cache) {
      return { ok: true, payload: "（与上一次读取完全相同，直接使用上面的 cid）", label: "读取屏幕 · 与上次相同" };
    }
    cache = await getState(deep);
    // 计算器 / 浏览器这类应用浅查只有标题栏或少量控件：自动补一次深度读屏，
    // 否则模型看到的是“页面只有导航栏”，还得自己再读一次。
    if (!deep && (cache.controls ?? []).length < 25) {
      cache = await getState(true);
    }
    lastReadSig = sig;
    let all = cache.controls ?? [];
    let fbAdded = 0;
    // UIA 读不到（0 个）或模型明确要求兜底时：Raw View + 悬停 FromPoint + MSAA
    if (deep && (Boolean(args.fallback) || all.length === 0)) {
      try {
        const fb = await postAction({ type: "fallback_scan", max_items: 60 }, 30_000);
        const fitems =
          (fb.items as Array<{ t?: string; n?: string; r?: number[]; src?: string }> | undefined) ?? [];
        for (const it of fitems) {
          const rect = (it.r ?? [0, 0, 0, 0]).map(Number);
          if (!rect[2] || !rect[3]) continue;
          const dup = all.some(
            (c) =>
              (c.name || "") === (it.n || "") &&
              Math.abs((c.abs_rect?.[0] ?? -9999) - rect[0]) < 3 &&
              Math.abs((c.abs_rect?.[1] ?? -9999) - rect[1]) < 3
          );
          if (dup) continue;
          all.push({
            cid: all.length,
            id: "",
            type: it.t || "Unknown",
            name: it.n || "",
            rect,
            abs_rect: rect,
            enabled: true,
            source: it.src || "fallback",
          });
          fbAdded += 1;
        }
        if (fbAdded) cache.controls = all;
      } catch {
        // 兜底失败不影响正常读屏结果
      }
    }
    if (!all.length) {
      return {
        ok: false,
        payload: `fail ${cache.error ?? "没有读到可交互控件"}；先激活目标窗口，再用 read_screen(deep=true, fallback=true) 兜底`,
        label: "读取屏幕 · 0 个控件",
      };
    }
    // 自动模式按控件总量给预算：简单窗口 300，普通 600，网页/复杂窗口 1200
    const budget = screenBudgetOf(args.limit, screen, all.length);

    const lines = all.map(
      (c) => `${c.cid} ${c.type} ${(c.name || "-").slice(0, 24)} @${c.abs_rect.join(",")}${
        c.enabled ? "" : " 禁用"
      }${c.source ? ` 〔${c.source}〕` : ""}`
    );
    let used = 0;
    let shown = 0;
    for (const line of lines) {
      const cost = lineTokens(line);
      if (shown > 0 && used + cost > budget) break;
      used += cost;
      shown += 1;
    }
    const hidden = all.length - shown;
    const more = hidden
      ? screen?.mode === "custom"
        ? `\n…另有 ${hidden} 个未列出（当前为自定义上限，可在输入区调大「屏幕 Token」）`
        : `\n…另有 ${hidden} 个未列出；需要更多可再调用 read_screen(limit=${all.length})`
      : "";
    return {
      ok: true,
      payload: `ok total=${all.length} shown=${shown} tokens≈${used} tier=${cache.tier ?? "-"}${
        fbAdded ? ` fallback=+${fbAdded}` : ""
      }\n${lines.slice(0, shown).join("\n")}${more}`,
      label: `读取屏幕 · ${shown}/${all.length} 个控件${fbAdded ? `（兜底 +${fbAdded}）` : ""}`,
    };
  }

  if (name === "click_control") {
    const cid = Number(args.cid);
    const ctrl = (cache?.controls ?? []).find((c) => c.cid === cid);
    if (!ctrl) {
      const some = (cache?.controls ?? [])
        .slice(0, 8)
        .map((c) => `${c.cid}:${c.name}`)
        .join(", ");
      return {
        ok: false,
        payload: `fail 未知 cid=${cid}。必须先 read_screen，当前可用：${some || "无"}`,
        label: `点击 #${cid} · 无此控件`,
      };
    }
    // 深度读屏的 cid 和基础快照的 cid 不是同一套编号，按读到的屏幕坐标点击最稳
    const out = await postAction({ type: "click_rect", rect: ctrl.abs_rect });
    lastReadSig = ""; // 动作后画面可能变化，下一次读屏必须重新取
    const ok = Boolean(out.ok);
    return {
      ok,
      payload: ok
        ? `ok 已点击 cid=${cid}（${ctrl.name}）`
        : `fail 点击 cid=${cid} 被拒绝：${out.reason ?? "unknown"}`,
      label: `点击 #${cid} ${ctrl.name} · ${ok ? "ok" : "失败"}`,
    };
  }

  if (name === "type_text") {
    const focusMode = Boolean(args.focus) || args.cid === undefined || args.cid === null;
    if (focusMode) {
      const text = String(args.text ?? "");
      if (!text) return { ok: false, payload: "fail 文本为空", label: "输入 · 文本为空" };
      const out = await postAction({
        type: "type_focus",
        text,
        enter: Boolean(args.enter),
        ...(args.hwnd ? { hwnd: Number(args.hwnd) } : {}),
      });
      lastReadSig = "";
      const ok = Boolean(out.ok);
      return {
        ok,
        payload: ok ? `ok 已输入「${text}」到当前焦点` : `fail 输入失败：${out.reason ?? "unknown"}`,
        label: `输入（焦点）「${text.slice(0, 10)}」 · ${ok ? "ok" : "失败"}`,
      };
    }
    const cid = args.cid === undefined || args.cid === null ? -1 : Number(args.cid);
    const ctrl = (cache?.controls ?? []).find((c) => c.cid === cid);
    if (!ctrl) {
      const edits = (cache?.controls ?? [])
        .filter((c) => c.type === "Edit")
        .map((c) => `${c.cid}:${c.name}`)
        .join(", ");
      return {
        ok: false,
        payload: `fail 必须带 read_screen 返回的 cid。当前可见输入框：${edits || "无"}`,
        label: "输入 · 缺少有效 cid",
      };
    }
    const text = String(args.text ?? "");
    const enter = Boolean(args.enter);
    const out = await postAction({
      type: "type_text",
      rect: ctrl.abs_rect,
      text,
      enter,
      verify_wait_ms: 1500,
    });
    lastReadSig = "";
    const verified = out.verified as { ok?: boolean; reason?: string } | null | undefined;
    const ok = Boolean(out.ok);
    return {
      ok,
      payload: ok
        ? `ok 已输入「${text}」，verified=${Boolean(verified?.ok)}（${verified?.reason ?? "-"}）`
        : `fail 输入失败：${out.reason ?? "unknown"}`,
      label: `输入「${text.slice(0, 12)}」 · ${ok ? (verified?.ok ? "已验证" : "未验证") : "失败"}`,
    };
  }

  if (name === "read_url") {
    let url = String(args.url ?? "").trim();
    if (url.toLowerCase().startsWith("read://")) url = url.slice(7);
    else if (url.toLowerCase().startsWith("read:")) url = url.slice(5);
    if (!/^https?:\/\//i.test(url)) {
      return { ok: false, payload: "fail 只允许 http/https 链接", label: "阅读模式 · 链接不合法" };
    }
    const max = Math.min(6000, Math.max(200, Number(args.max_chars ?? 4000)));
    const out = await postAction({ type: "read_url", url, max_chars: max });
    lastReadSig = "";
    const text = String(out.text ?? "");
    const ok = Boolean(out.ok) && text.length > 0;
    return {
      ok,
      payload: ok
        ? `ok 阅读模式已读取 ${out.chars ?? text.length} 字符：\n${text}`
        : `fail 阅读模式没有拿到正文：${out.reason ?? "unknown"}`,
      label: `阅读模式 · ${ok ? `${text.length} 字` : "空"}`,
    };
  }

  if (name === "read_text") {
    const max = Math.min(6000, Math.max(200, Number(args.max_chars ?? 3000)));
    const out = await postAction({
      type: "read_text",
      max_chars: max,
      ...(args.hwnd ? { hwnd: Number(args.hwnd) } : {}),
    });
    lastReadSig = "";
    const text = String(out.text ?? "");
    const ok = Boolean(out.ok) && text.length > 0;
    return {
      ok,
      payload: ok
        ? `ok 已读取 ${out.chars ?? text.length} 字符：\n${text}`
        : `fail 没有读到文字：${out.reason ?? "unknown"}`,
      label: `读取页面文字 · ${ok ? `${text.length} 字` : "空"}`,
    };
  }

  if (name === "press_keys") {
    const keys = String(args.keys ?? "").trim();
    if (!keys) return { ok: false, payload: "fail 缺少 keys", label: "按键 · 缺少参数" };
    const out = await postAction({
      type: "keys",
      keys,
      ...(args.hwnd ? { hwnd: Number(args.hwnd) } : {}),
    });
    lastReadSig = "";
    const ok = Boolean(out.ok);
    return {
      ok,
      payload: ok ? `ok 已发送按键 ${keys}` : `fail 按键被拒绝：${out.reason ?? "unknown"}`,
      label: `按键 ${keys} · ${ok ? "ok" : "失败"}`,
    };
  }

  if (name === "scroll") {
    const delta = Number(args.delta ?? -3);
    const out = await postAction({
      type: "scroll",
      delta,
      ...(args.x !== undefined ? { x: Number(args.x) } : {}),
      ...(args.y !== undefined ? { y: Number(args.y) } : {}),
    });
    lastReadSig = "";
    const ok = Boolean(out.ok);
    return {
      ok,
      payload: ok ? `ok 已滚动 ${delta} 格` : `fail 滚动被拒绝：${out.reason ?? "unknown"}`,
      label: `滚动 ${delta} 格 · ${ok ? "ok" : "失败"}`,
    };
  }

  if (name === "open_url") {
    const url = String(args.url ?? "").trim();
    if (!/^https?:\/\//i.test(url)) {
      return { ok: false, payload: "fail 只允许 http/https 链接", label: "打开链接 · 链接不合法" };
    }
    const out = await postAction({ type: "open_url", url });
    lastReadSig = "";
    const ok = Boolean(out.ok);
    return {
      ok,
      payload: ok ? `ok 已用默认浏览器打开 ${url}` : `fail 打开失败：${out.reason ?? "unknown"}`,
      label: `打开链接 · ${ok ? "ok" : "失败"}`,
    };
  }

  return { ok: false, payload: `fail 未知工具 ${name}`, label: `未知工具 ${name}` };
}

async function completion(
  cfg: LlmConfig,
  messages: unknown[],
  tools: unknown[] | null,
  signal?: AbortSignal,
  timeoutMs = 60_000,
  autoGrow = false
): Promise<{ content: string; tool_calls?: ToolCall[]; reasoning?: string; finish?: string }> {
  let maxTokens = Math.max(512, cfg.maxTokens);

  // 自动模式：一旦被 max_tokens 截断（finish_reason=length），翻倍重试，最多到上限
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => ctrl.abort(), timeoutMs);
    const onAbort = () => ctrl.abort();
    signal?.addEventListener("abort", onAbort, { once: true });
    try {
      const res = await fetch(viaProxy(apiUrl(cfg.endpoint, "/chat/completions")), {
        method: "POST",
        headers: { "content-type": "application/json", "x-llm-key": cfg.apiKey },
        body: JSON.stringify({
          model: cfg.model,
          messages,
          temperature: cfg.temperature,
          max_tokens: maxTokens,
          stream: false,
          ...(tools ? { tools, tool_choice: "auto" } : {}),
        }),
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
      const json = (await res.json()) as {
        choices?: Array<{
          finish_reason?: string | null;
          message?: {
            content?: string | null;
            tool_calls?: ToolCall[];
            // DeepSeek / vLLM 等把思考内容单独放在这两个字段
            reasoning_content?: string | null;
            reasoning?: string | null;
          };
        }>;
      };
      const choice = json.choices?.[0];
      const m = choice?.message;
      const finish = choice?.finish_reason ?? "";
      const out = {
        content: m?.content ?? "",
        tool_calls: m?.tool_calls,
        reasoning: (m?.reasoning_content ?? m?.reasoning) ?? undefined,
        finish,
      };
      if (autoGrow && finish === "length" && maxTokens < TOKEN_CAP) {
        maxTokens = Math.min(maxTokens * 2, TOKEN_CAP);
        continue;
      }
      return out;
    } finally {
      window.clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    }
  }
  return { content: "", finish: "length" };
}

/** 动作类工具附带的屏幕摘要：最多 20 条，省掉一次“动作完再让模型读屏”的往返 */
async function attachScreen(payload: string): Promise<string> {
  try {
    const st = await getState(false);
    const all = st.controls ?? [];
    if (!all.length) return payload;
    const max = 20;
    const lines = all.slice(0, max).map(
      (c) => `${c.cid} ${c.type} ${(c.name || "-").slice(0, 18)}`
    );
    cache = st;
    return `${payload}\n最新屏幕：${all.length} 个控件\n${lines.join("\n")}${
      all.length > max ? `\n…另有 ${all.length - max} 个，需要更多时用 read_screen(limit=N)` : ""
    }`;
  } catch {
    return payload;
  }
}

/** 长任务里旧读屏结果会占满上下文：只保留最近 8 条完整，旧结果折叠成一行 */
function pruneContext(msgs: unknown[]): void {
  const tail = 8;
  const end = msgs.length - tail;
  for (let i = 1; i < end; i += 1) {
    const m = msgs[i] as { role?: string; content?: string };
    if (m?.role === "tool" && typeof m.content === "string" && m.content.length > 180) {
      const first = (m.content.split("\n")[0] || "ok").slice(0, 120);
      m.content = `${first} …（较早结果已折叠）`;
    }
  }
}

export interface AgentOptions {
  /** 模型说话（汇报 / 结论） */
  onText: (s: string) => void;
  /** 思考内容（规划 + 模型返回的 reasoning），UI 折叠展示 */
  onThinking: (s: string) => void;
  /** 工具开始执行：UI 立即插入一张“调用中”的卡片 */
  onToolStart: (id: string, name: string, args: Record<string, unknown>) => void;
  /** 工具执行结束：回填同一张卡片的结果与成功状态 */
  onToolResult: (id: string, ok: boolean, payload: string, label: string) => void;
  planFirst?: boolean;
  maxRounds?: number;
  /** 自动 token 模式：输出被截断时翻倍重试 */
  autoTokens?: boolean;
  /** 读屏数据预算（按 token 估算截断控件列表） */
  screenTokens?: ScreenTokenConfig;
  /** 某个工具失败后换方法成功：交给调用方记入经验库 */
  onLesson?: (lesson: { task: string; tool: string; error: string; fix: string }) => void;
  systemPrompt: string;
  signal?: AbortSignal;
}

/** 跑一轮完整的“读屏 -> 操作 -> 收尾回答”。 */
export async function runAgent(
  cfg: LlmConfig,
  history: LlmMessage[],
  opts: AgentOptions
): Promise<{ finished: boolean }> {
  const signal = opts.signal;
  const msgs: unknown[] = [{ role: "system", content: opts.systemPrompt }, ...history];
  // 轮次只是硬上限；正常结束由 finish_task 决定。放开到 60，避免工具用一半就被截断
  const rounds = opts.maxRounds ?? 60;

  if (opts.planFirst) {
    throwIfAborted(signal);
    const plan = await completion(
      cfg,
      [
        {
          role: "system",
          content:
            "先用不超过三句话说明你的思路：要操作什么、先看哪里、怎么确认成功。不要调用工具，不要输出别的内容。",
        },
        ...history,
      ].slice(-8),
      null,
      signal,
      25_000,
      opts.autoTokens
    );
    const thought = [plan.reasoning, plan.content].filter(Boolean).join("\n").trim();
    if (thought) opts.onThinking(thought);
  }

  // 失败 -> 反思 -> 换方法成功：把这一对记成经验
  const taskText =
    [...history].reverse().find((m) => m.role === "user")?.content?.slice(0, 160) ?? "";
  const pendingFailures: Array<{ tool: string; error: string }> = [];
  const recordedLessons = new Set<string>();

  let nudges = 0;              // 模型想“只说话不干活”时，最多催两次
  let failureRetried = false;  // 模型说失败时，先要求换方法再试一次
  let stepCount = 0;
  let lastLabel = "";
  let roundsSinceAction = 0;
  let progressNudged = false;
  const seenSigs = new Map<string, number>();
  const nudgedSigs = new Set<string>();
  const CARRY_SCREEN = new Set(["click_control", "type_text", "press_keys", "scroll", "launch_app", "open_url"]);

const ACTION_TOOLS = new Set([
    "click_control", "type_text", "press_keys", "scroll", "launch_app", "open_url",
  ]);

  const stepSummary = (reason?: string) =>
    `执行了 ${stepCount} 步，最后一步：${lastLabel || "无"}。${reason ?? "任务未确认完成。"}`;

  const finishRun = (summary: string, success: boolean) => {
    const id = `finish_${Date.now()}`;
    opts.onToolStart(id, "finish_task", { summary, success });
    opts.onToolResult(id, success, summary, `结束任务 · ${success ? "成功" : "未完成"}`);
    opts.onText(summary);
  };

  for (let i = 0; i < rounds; i += 1) {
    throwIfAborted(signal);
    const msg = await completion(cfg, msgs, TOOLS, signal, 60_000, opts.autoTokens);
    if (msg.reasoning?.trim()) opts.onThinking(msg.reasoning.trim());

    if (msg.tool_calls?.length) {
      // 明确的完成信号：只有它能让任务结束
      const finish = msg.tool_calls.find((c) => c.function.name === "finish_task");
      if (finish) {
        const args = parseArgs(finish.function.arguments);
        const summary = String(args.summary ?? "").trim();
        if (args.success !== true && !failureRetried) {
          // 还没成功：不急着接受失败，先让它换一种方法再试一轮
          failureRetried = true;
          msgs.push({ role: "assistant", content: msg.content ?? "" });
          msgs.push({
            role: "system",
            content:
              "还没成功。先换一种完全不同的方法再试一次（换工具、换顺序或换控件）；如果确定确实无法完成，再调用 finish_task(success=false) 并说明卡在哪一步。",
          });
          continue;
        }
        const said = cleanText(msg.content ?? "");
        if (said) opts.onText(said);
        finishRun(summary || stepSummary("模型给出了完成信号但没写结果。"), args.success !== false);
        return { finished: args.success !== false };
      }

      // 模型决定动手前的铺垫话先说出来，形成“边汇报边用工具”的节奏
      const said = cleanText(msg.content ?? "");
      if (said) opts.onText(said);
      msgs.push({ role: "assistant", content: msg.content ?? "", tool_calls: msg.tool_calls });

      let advanced = false;
      let repeated = false;
      for (let ci = 0; ci < msg.tool_calls.length; ci += 1) {
        const call = msg.tool_calls[ci];
        const isLastCall = ci === msg.tool_calls.length - 1;
        throwIfAborted(signal);
        stepCount += 1;
        const sig = `${call.function.name}:${call.function.arguments}`;
        if (ACTION_TOOLS.has(call.function.name)) {
          const prev = seenSigs.get(sig);
          if (prev !== undefined && i - prev <= 5 && !nudgedSigs.has(sig)) {
            nudgedSigs.add(sig);
            repeated = true;
          }
          seenSigs.set(sig, i);
        }

        const args = parseArgs(call.function.arguments);
        opts.onToolStart(call.id, call.function.name, args);
        let result: ToolOutcome;
        try {
          result = await execTool(call.function.name, args, signal, opts.screenTokens);
        } catch (err) {
          if (err instanceof DOMException && err.name === "AbortError") throw err;
          result = {
            ok: false,
            payload: `fail ${err instanceof Error ? err.message : String(err)}`,
            label: `${call.function.name} · 异常`,
          };
        }
        // 动作类工具直接把“动作后的最新屏幕”带回，省掉一次“模型再看一眼”的往返
        if (isLastCall && result.ok && CARRY_SCREEN.has(call.function.name)) {
          result.payload = await attachScreen(result.payload);
        }
        opts.onToolResult(call.id, result.ok, result.payload, result.label);
        lastLabel = result.label;

        if (!result.ok) {
          // 失败先反思一句，下一步必须换做法
          const line = (result.payload.split("\n")[0] || result.label).slice(0, 200);
          pendingFailures.push({ tool: call.function.name, error: line });
          opts.onThinking(
            `「${call.function.name}」失败：${line}。换一种做法，不要重复同样的参数。`
          );
        } else if (pendingFailures.length && opts.onLesson) {
          // 这次成功修复了之前的失败：记录经验
          const failed = pendingFailures.pop()!;
          const fix = `${call.function.name}(${JSON.stringify(args).slice(0, 120)}) → ${result.label}`;
          const key = `${failed.tool}|${failed.error.slice(0, 60)}|${fix.slice(0, 60)}`;
          if (!recordedLessons.has(key)) {
            recordedLessons.add(key);
            opts.onLesson({ task: taskText, tool: failed.tool, error: failed.error, fix });
          }
        }

        if (result.ok && ACTION_TOOLS.has(call.function.name)) advanced = true;
        msgs.push({ role: "tool", tool_call_id: call.id, content: result.payload });
      }

      // 长任务里旧读屏结果会撑爆上下文：只保留最近 8 条完整，旧结果折叠
      pruneContext(msgs);

      if (advanced) {
        roundsSinceAction = 0;
        progressNudged = false;
      } else {
        roundsSinceAction += 1;
      }

      if (repeated) {
        msgs.push({
          role: "system",
          content:
            "你刚刚重复了同一个动作。不要再来一次，换一种完全不同的路径（换控件、换工具或换入口）；如果确实无法继续，调用 finish_task(success=false) 说明卡点。",
        });
      }

      if (roundsSinceAction >= 4 && !progressNudged) {
        progressNudged = true;
        msgs.push({
          role: "system",
          content:
            "已经连续多轮只有读屏、没有实际推进。先明确下一步的可见目标，执行一次真实动作；如果环境不允许，就调用 finish_task(success=false) 说明卡在哪里。",
        });
      }
      continue;
    }

    // 没有工具调用也没有 finish_task：说明还想“中途收尾”，催它继续
    const said = cleanText(msg.content ?? "");
    if (said) opts.onText(said);
    if (nudges < 2) {
      nudges += 1;
      if (said) msgs.push({ role: "assistant", content: msg.content ?? "" });
      msgs.push({
        role: "system",
        content:
          "任务还没有结束。如果还没完成，继续调用工具执行下一步；只有真正完成时才调用 finish_task(summary, success=true)。不要只输出文字就停下。",
      });
      continue;
    }
    finishRun(stepSummary("模型停止输出，任务未确认完成。"), false);
    return { finished: false };
  }

  // 步数用尽：也必须以 finish_task 收尾，不能让界面停在“没有拿到结论”
  throwIfAborted(signal);
  pruneContext(msgs);
  const wrap = await completion(
    cfg,
    [
      ...msgs,
      {
        role: "system",
        content:
          "步数已达上限，不要再执行新的操作。如果任务其实已经完成，调用 finish_task(summary, success=true)；否则调用 finish_task(summary, success=false)，用一句话说明已完成什么、卡在哪一步。",
      },
    ],
    TOOLS.filter((t) => t.function.name === "finish_task"),
    signal,
    40_000,
    opts.autoTokens
  );
  const wrapCall = wrap.tool_calls?.find((c) => c.function.name === "finish_task");
  if (wrapCall) {
    const args = parseArgs(wrapCall.function.arguments);
    const summary = String(args.summary ?? "").trim();
    finishRun(summary || stepSummary("达到执行步数上限。"), args.success === true);
    return { finished: args.success === true };
  }
  const wrapText = cleanText(wrap.content ?? "");
  if (wrapText) opts.onText(wrapText);
  finishRun(stepSummary("达到执行步数上限，任务未确认完成。"), false);
  return { finished: false };
}
