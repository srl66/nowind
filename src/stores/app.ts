import { defineStore } from "pinia";
import { translate } from "../i18n";
import { streamChat, type LlmMessage } from "../services/llm";
import { runAgent } from "../services/agent";
import { focusApp, ping } from "../services/middleware";
import { autoMaxTokens } from "../services/tokens";

/** 中间件在线探测的定时器（放在模块级，避免塞进 Pinia 的可序列化 state） */
let probeTimer = 0;
/** 当前进行中的请求（用于“停止”按钮中断） */
let activeAbort: AbortController | null = null;

export type Theme = "light" | "dark";
export type Lang = "zh" | "en";
export type View = "chat" | "settings" | "toolbook";
/** 输出 token：auto = 按任务自动调整；custom = 固定用模型配置里的 Max Tokens */
export type TokenMode = "auto" | "custom";

export interface ModelConfig {
  id: string;
  name: string;
  endpoint: string;
  apiKey: string;
  model: string;
  temperature: number;
  maxTokens: number;
}

export interface TextPart {
  kind: "text";
  text: string;
}

/** 思考过程：默认折叠，点击标题展开 */
export interface ThinkingPart {
  kind: "thinking";
  text: string;
}

/** 一次工具调用：渲染成一张卡片，点击可看具体命令与返回 */
export interface ToolPart {
  kind: "tool";
  id: string;
  name: string;
  args: Record<string, unknown>;
  label: string;
  status: "running" | "ok" | "fail";
  result?: string;
}

export type MessagePart = TextPart | ThinkingPart | ToolPart;

/** 失败后改进成功的经验，存本地并注入后续同类任务 */
export interface Experience {
  id: string;
  task: string;
  tool: string;
  error: string;
  fix: string;
  createdAt: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  ts: number;
  /** 流式输出中：气泡里显示光标 */
  pending?: boolean;
  /** 助手消息的分段内容；旧消息没有该字段时退回纯 text 渲染 */
  parts?: MessagePart[];
}

export interface Chat {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}

const uid = () => Math.random().toString(36).slice(2, 10);
const STORE_KEY = "ai-pc-assistant:v1";

interface Persisted {
  theme: Theme;
  lang: Lang;
  models: ModelConfig[];
  activeModelId: string;
  chats: Chat[];
  activeChatId: string;
  allowControl?: boolean;
  deepThink?: boolean;
  tokenMode?: TokenMode;
  screenMode?: TokenMode;
  screenBudget?: number;
  experiences?: Experience[];
}

const blankModel = (): ModelConfig => ({
  id: uid(),
  name: "",
  endpoint: "https://api.openai.com/v1",
  apiKey: "",
  model: "",
  temperature: 0.7,
  maxTokens: 2048,
});

/** 字符二元组：中文任务文本做相似度匹配，不需要分词 */
function bigrams(text: string): Set<string> {
  const s = text.toLowerCase().replace(/\s+/g, "");
  const out = new Set<string>();
  for (let i = 0; i < s.length - 1; i += 1) out.add(s.slice(i, i + 2));
  return out;
}

export const useAppStore = defineStore("app", {
  state: () => ({
    theme: "light" as Theme,
    lang: "zh" as Lang,
    view: "chat" as View,
    models: [] as ModelConfig[],
    activeModelId: "",
    chats: [] as Chat[],
    activeChatId: "",
    sending: false,
    backendOnline: false,
    allowControl: true,
    deepThink: false,
    tokenMode: "auto" as TokenMode,
    /** 读屏数据预算：auto = 模型可按需扩；custom = 固定上限 */
    screenMode: "auto" as TokenMode,
    screenBudget: 300,
    experiences: [] as Experience[],
    toast: "",
  }),

  getters: {
    activeModel(state): ModelConfig | undefined {
      return state.models.find((m) => m.id === state.activeModelId) ?? state.models[0];
    },
    activeChat(state): Chat | undefined {
      return state.chats.find((c) => c.id === state.activeChatId) ?? state.chats[0];
    },
  },

  actions: {
    bootstrap() {
      try {
        const raw = localStorage.getItem(STORE_KEY);
        if (raw) {
          const d = JSON.parse(raw) as Persisted;
          this.theme = d.theme ?? "light";
          this.lang = d.lang ?? "zh";
          this.models = (d.models ?? []).map((m) => ({ ...blankModel(), ...m, id: m.id || uid() }));
          this.activeModelId = d.activeModelId || this.models[0]?.id || "";
          this.chats = d.chats ?? [];
          this.activeChatId = d.activeChatId || this.chats[0]?.id || "";
          this.allowControl = d.allowControl ?? true;
          this.deepThink = d.deepThink ?? false;
          this.tokenMode = d.tokenMode === "custom" ? "custom" : "auto";
          this.screenMode = d.screenMode === "custom" ? "custom" : "auto";
          this.screenBudget = Math.min(4000, Math.max(80, Number(d.screenBudget) || 300));
          this.experiences = Array.isArray(d.experiences) ? d.experiences.slice(0, 100) : [];
        }
      } catch {
        // 本地数据损坏就当首次启动，重新种子
      }
      if (!this.models.length) {
        const m = { ...blankModel(), name: translate(this.lang, "settings.name") + " #1" };
        this.models = [m];
        this.activeModelId = m.id;
      }
      if (!this.chats.length) this.newChat();
      this.applyTheme();
      this.startProbe();
      this.persist();
    },

    /** 每 4s 探测一次本地中间件；在线状态决定“控制电脑”是否可用 */
    startProbe() {
      if (probeTimer) return;
      const tick = async () => {
        this.backendOnline = await ping();
      };
      void tick();
      probeTimer = window.setInterval(tick, 4000);
    },
    toggleControl() {
      if (!this.backendOnline) {
        this.flash(translate(this.lang, "chat.backendOffline"));
        return;
      }
      this.allowControl = !this.allowControl;
      this.persist();
    },
    toggleDeepThink() {
      this.deepThink = !this.deepThink;
      this.persist();
    },
    setTokenMode(mode: TokenMode) {
      this.tokenMode = mode;
      this.persist();
    },
    setScreenMode(mode: TokenMode) {
      this.screenMode = mode;
      this.persist();
    },
    setScreenBudget(budget: number) {
      this.screenBudget = Math.min(4000, Math.max(80, Math.round(Number(budget) || 300)));
      this.persist();
    },

    // ---------------------------------------------------------------- 经验库
    addExperience(patch: { task: string; tool: string; error: string; fix: string }) {
      const sig = `${patch.tool}|${patch.error.slice(0, 80)}|${patch.fix.slice(0, 80)}`;
      const dup = this.experiences.some(
        (e) => `${e.tool}|${e.error.slice(0, 80)}|${e.fix.slice(0, 80)}` === sig
      );
      if (dup) return;
      this.experiences.unshift({ id: uid(), createdAt: Date.now(), ...patch });
      this.experiences = this.experiences.slice(0, 100);
      this.persist();
    },
    removeExperience(id: string) {
      this.experiences = this.experiences.filter((e) => e.id !== id);
      this.persist();
    },
    clearExperiences() {
      this.experiences = [];
      this.persist();
    },
    /** 按任务文本的字符二元组重合度找相关经验（中文不需要分词） */
    matchExperiences(task: string, limit = 3): Experience[] {
      const q = bigrams(task);
      if (!q.size) return [];
      return this.experiences
        .map((e) => {
          const grams = bigrams(`${e.task} ${e.tool} ${e.error}`);
          let hit = 0;
          for (const g of q) if (grams.has(g)) hit += 1;
          return { e, hit };
        })
        .filter((x) => x.hit >= 2)
        .sort((a, b) => b.hit - a.hit)
        .slice(0, limit)
        .map((x) => x.e);
    },

    applyTheme() {
      document.documentElement.classList.toggle("dark", this.theme === "dark");
    },
    setTheme(theme: Theme) {
      this.theme = theme;
      this.applyTheme();
      this.persist();
    },
    toggleTheme() {
      this.setTheme(this.theme === "light" ? "dark" : "light");
    },

    setLang(lang: Lang) {
      this.lang = lang;
      this.persist();
    },
    toggleLang() {
      this.setLang(this.lang === "zh" ? "en" : "zh");
    },

    setView(view: View) {
      this.view = view;
    },

    // ---------------------------------------------------------------- 模型配置
    addModel() {
      const m = blankModel();
      this.models.push(m);
      this.activeModelId = m.id;
      this.persist();
      return m;
    },
    updateModel(patch: Partial<ModelConfig> & { id: string }) {
      const target = this.models.find((m) => m.id === patch.id);
      if (!target) return;
      Object.assign(target, patch);
      this.persist();
    },
    removeModel(id: string) {
      this.models = this.models.filter((m) => m.id !== id);
      if (this.activeModelId === id) this.activeModelId = this.models[0]?.id ?? "";
      this.persist();
    },
    setActiveModel(id: string) {
      this.activeModelId = id;
      this.persist();
    },

    // ---------------------------------------------------------------- 对话
    newChat(): Chat {
      const chat: Chat = {
        id: uid(),
        title: translate(this.lang, "chat.newChatTitle"),
        messages: [],
        updatedAt: Date.now(),
      };
      this.chats.unshift(chat);
      this.activeChatId = chat.id;
      this.view = "chat";
      this.persist();
      return chat;
    },
    selectChat(id: string) {
      this.activeChatId = id;
      this.view = "chat";
      this.persist();
    },
    deleteChat(id: string) {
      this.chats = this.chats.filter((c) => c.id !== id);
      if (this.activeChatId === id) this.activeChatId = this.chats[0]?.id ?? "";
      if (!this.chats.length) this.newChat();
      this.persist();
    },

    async send(text: string) {
      const body = text.trim();
      if (!body || this.sending) return;
      const chat = this.activeChat ?? this.newChat();
      chat.messages.push({ id: uid(), role: "user", text: body, ts: Date.now() });
      if (chat.messages.length === 1) {
        chat.title = body.length > 22 ? `${body.slice(0, 22)}…` : body;
      }
      chat.updatedAt = Date.now();
      this.chats = [...this.chats];

      const model = this.activeModel;
      if (!model || !model.endpoint || !model.model) {
        chat.messages.push({
          id: uid(),
          role: "assistant",
          text: translate(this.lang, "chat.noModelConfigured"),
          ts: Date.now(),
        });
        this.chats = [...this.chats];
        this.persist();
        return;
      }

      const assistant: Message = {
        id: uid(),
        role: "assistant",
        text: "",
        ts: Date.now(),
        pending: true,
        parts: [],
      };
      chat.messages.push(assistant);
      // 关键：push 进去的是原始对象，后续必须通过 reactive 代理引用改它，否则界面不刷新
      const live = chat.messages[chat.messages.length - 1];
      this.chats = [...this.chats];
      this.sending = true;
      this.persist();

      // ---- 分段写入：文本气泡 / 思考折叠块 / 工具调用卡片，按发生顺序排列 ----
      const parts = () => live.parts!;
      const addText = (s: string) => {
        const list = parts();
        const last = list[list.length - 1];
        if (last && last.kind === "text") {
          last.text += s;
          live.text += s;
        } else {
          list.push({ kind: "text", text: s });
          live.text += `${live.text ? "\n\n" : ""}${s}`;
        }
        chat.updatedAt = Date.now();
      };
      const addThinking = (s: string) => {
        const list = parts();
        const last = list[list.length - 1];
        if (last && last.kind === "thinking") last.text += s;
        else list.push({ kind: "thinking", text: s });
        chat.updatedAt = Date.now();
      };
      const startTool = (id: string, name: string, args: Record<string, unknown>) => {
        parts().push({
          kind: "tool",
          id,
          name,
          args,
          label: translate(this.lang, "chat.toolRunning"),
          status: "running",
        });
        chat.updatedAt = Date.now();
      };
      const endTool = (id: string, ok: boolean, payload: string, label: string) => {
        const part = parts().find((p) => p.kind === "tool" && p.id === id);
        if (part && part.kind === "tool") {
          part.status = ok ? "ok" : "fail";
          part.result = payload;
          part.label = label;
        }
        chat.updatedAt = Date.now();
      };

      // 只取最近 20 条作为上下文，并把刚插入的空助手气泡排除掉
      const history: LlmMessage[] = chat.messages
        .filter((m) => m.id !== assistant.id)
        .slice(-20)
        .map((m) => ({ role: m.role, content: m.text }));

      const ctrl = new AbortController();
      activeAbort = ctrl;
      let timedOut = false;
      const usingTools = this.allowControl && this.backendOnline;
      // 工具任务不再设整体超时：每一步都有自己的超时，任务必须跑到 finish_task 才结束；
      // 用户仍可随时点停止。纯聊天保持 45s。
      const timer = usingTools
        ? 0
        : window.setTimeout(() => {
            timedOut = true;
            ctrl.abort();
          }, 45_000);

      try {
        // auto：按输入长度/任务类型给预算，截断时 agent 还会翻倍重试；custom：固定用模型配置
        const maxTokens =
          this.tokenMode === "auto"
            ? autoMaxTokens(body, usingTools)
            : Math.max(256, model.maxTokens);
        const cfg = {
          endpoint: model.endpoint,
          apiKey: model.apiKey,
          model: model.model,
          temperature: model.temperature,
          maxTokens,
        };
        if (usingTools) {
          // 任务开始前把相似任务的经验带进系统提示
          const lessons = this.matchExperiences(body, 3);
          const expPrompt = lessons.length
            ? "\n【历史经验】以下是同类任务里失败后改进成功的做法，遇到相似情况优先采用：\n" +
              lessons
                .map(
                  (e, i) => `${i + 1}) 任务：${e.task}；「${e.tool}」失败：${e.error}；改进：${e.fix}`
                )
                .join("\n")
            : "";
          // 工具闭环：读屏幕 -> 点/输 -> 看结果 -> 回答
          const result = await runAgent(cfg, history, {
            systemPrompt: translate(this.lang, "agent.system") + expPrompt,
            planFirst: this.deepThink,
            autoTokens: this.tokenMode === "auto",
            screenTokens: { mode: this.screenMode, budget: this.screenBudget },
            signal: ctrl.signal,
            onText: addText,
            onThinking: addThinking,
            onToolStart: startTool,
            onToolResult: endTool,
            // 某次失败后换方法成功，记一条经验
            onLesson: (l) => this.addExperience(l),
          });
          const finished = result.finished;

          // 任务结束：切回聊天界面并把助手窗口拉回前台，让用户一眼看到结果
          this.view = "chat";
          window.setTimeout(() => {
            void focusApp().catch(() => {});
          }, 300);
          if (finished) this.flash(translate(this.lang, "chat.taskFinished"));
        } else {
          await streamChat(
            cfg,
            history,
            addText,
            ctrl.signal,
            this.deepThink ? addThinking : undefined
          );
        }
        if (!live.text.trim()) addText(translate(this.lang, "chat.emptyReply"));
      } catch (err) {
        const aborted = err instanceof DOMException && err.name === "AbortError";
        const detail = err instanceof Error ? err.message : String(err);
        if (aborted && !timedOut) {
          addText(translate(this.lang, "chat.aborted"));
        } else if (timedOut) {
          addText(translate(this.lang, "chat.timeout"));
        } else {
          addText(`${translate(this.lang, "chat.requestFailed")}: ${detail}`);
        }
      } finally {
        window.clearTimeout(timer);
        activeAbort = null;
        // 被中断时，还在转圈的工具卡片要收尾，不能永远停在“调用中”
        for (const p of live.parts ?? []) {
          if (p.kind === "tool" && p.status === "running") {
            p.status = "fail";
            p.label = translate(this.lang, "chat.toolAborted");
            p.result = translate(this.lang, "chat.toolAborted");
          }
        }
        live.pending = false;
        this.sending = false;
        chat.updatedAt = Date.now();
        this.chats = [...this.chats];
        this.persist();
      }
    },

    /** 中断正在进行的请求（流式或工具闭环都支持） */
    stop() {
      activeAbort?.abort();
    },

    flash(message: string) {
      this.toast = message;
      window.setTimeout(() => {
        if (this.toast === message) this.toast = "";
      }, 2200);
    },

    persist() {
      const data: Persisted = {
        theme: this.theme,
        lang: this.lang,
        models: this.models,
        activeModelId: this.activeModelId,
        chats: this.chats,
        activeChatId: this.activeChatId,
        allowControl: this.allowControl,
        deepThink: this.deepThink,
        tokenMode: this.tokenMode,
        screenMode: this.screenMode,
        screenBudget: this.screenBudget,
        experiences: this.experiences,
      };
      try {
        localStorage.setItem(STORE_KEY, JSON.stringify(data));
      } catch {
        // 配额满/隐私模式：静默
      }
    },
  },
});
