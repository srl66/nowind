<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import Icon from "./Icon.vue";
import ThinkingBlock from "./ThinkingBlock.vue";
import ToolCallCard from "./ToolCallCard.vue";
import { useI18n } from "../useI18n";
import type { Message } from "../stores/app";

const { t, store } = useI18n();

const input = ref("");
const area = ref<HTMLTextAreaElement | null>(null);
const scroller = ref<HTMLDivElement | null>(null);

const suggestions = computed(() => [t("chat.s1"), t("chat.s2"), t("chat.s3")]);
const messages = computed(() => store.activeChat?.messages ?? []);
const userBadge = computed(() => (store.lang === "zh" ? "我" : "U"));

/** 屏幕 token：读屏数据预算 */
const screenMenu = ref(false);
const screenBudgetInput = ref(300);
watch(
  () => store.screenBudget,
  (v) => {
    if (typeof v === "number" && v > 0) screenBudgetInput.value = v;
  },
  { immediate: true }
);

function applyScreenBudget() {
  store.setScreenBudget(Number(screenBudgetInput.value));
  screenBudgetInput.value = store.screenBudget;
}

function pickScreenBudget(n: number) {
  screenBudgetInput.value = n;
  applyScreenBudget();
}

/** 输出 token：自动 / 自定义；自定义值写回当前模型的 Max Tokens */
const tokenMenu = ref(false);
const customTokens = ref(2048);
watch(
  () => store.activeModel?.maxTokens,
  (v) => {
    if (typeof v === "number" && v > 0) customTokens.value = v;
  },
  { immediate: true }
);

function applyTokens() {
  const model = store.activeModel;
  if (!model) return;
  const value = Math.min(16384, Math.max(256, Number(customTokens.value) || 2048));
  customTokens.value = value;
  store.updateModel({ id: model.id, maxTokens: value });
}

function pickTokens(n: number) {
  customTokens.value = n;
  applyTokens();
}

/** 最后一段是文本时，光标画在文本里；否则在末尾补一行“工作中”三点 */
function hasTrailingText(m: Message): boolean {
  const list = m.parts ?? [];
  return list.length > 0 && list[list.length - 1].kind === "text";
}

/** 流式输出时文本 / 工具卡片都在变，用这个签名驱动自动滚动 */
const streamSig = computed(() => {
  const m = messages.value[messages.value.length - 1];
  if (!m) return "";
  const list = m.parts ?? [];
  const tail = list[list.length - 1];
  const tailLen = tail ? (tail.kind === "tool" ? (tail.result?.length ?? 0) : tail.text.length) : 0;
  return `${m.text.length}:${list.length}:${tailLen}`;
});

function autoGrow() {
  const el = area.value;
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
}

function scrollToBottom() {
  const el = scroller.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function send() {
  const text = input.value;
  if (!text.trim() || store.sending) return;
  store.send(text);
  input.value = "";
  nextTick(() => {
    autoGrow();
    scrollToBottom();
  });
}

function useSuggestion(text: string) {
  input.value = text;
  nextTick(() => {
    autoGrow();
    area.value?.focus();
  });
}

watch(
  () => [store.activeChatId, messages.value.length, store.sending],
  async () => {
    await nextTick();
    scrollToBottom();
  }
);

// 流式输出时内容和分段都在变，单独盯最后一条的签名才能跟住滚动
watch(streamSig, async () => {
  await nextTick();
  scrollToBottom();
});

onMounted(() => {
  scrollToBottom();
  area.value?.focus();
});
</script>

<template>
  <div class="h-full flex flex-col">
    <!-- 顶栏 -->
    <header class="h-14 shrink-0 px-6 flex items-center justify-between border-b border-line/70">
      <div class="min-w-0 flex items-baseline gap-2">
        <span class="text-[13.5px] font-medium truncate">{{ store.activeChat?.title }}</span>
        <span class="text-[11px] text-muted shrink-0">{{ messages.length }}</span>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <span class="chip">
          <Icon name="cpu" :size="12" />
          <span class="max-w-[160px] truncate">
            {{ store.activeModel?.model || store.activeModel?.name || t("chat.noModel") }}
          </span>
        </span>
        <span class="chip">
          <span
            class="h-1.5 w-1.5 rounded-full"
            :class="store.backendOnline ? 'bg-emerald-500' : 'bg-danger/70'"
          ></span>
          {{ t("chat.backend") }} · {{ store.backendOnline ? t("chat.online") : t("chat.offline") }}
        </span>
      </div>
    </header>

    <!-- 消息区 -->
    <div ref="scroller" class="flex-1 min-h-0 overflow-y-auto">
      <!-- 空态 -->
      <div v-if="!messages.length" class="h-full grid place-items-center px-6">
        <div class="w-full max-w-xl text-center animate-fade-up">
          <div class="mx-auto h-12 w-12 rounded-2xl bg-accent-soft text-accent grid place-items-center mb-5">
            <Icon name="sparkles" :size="22" />
          </div>
          <h2 class="text-[22px] font-semibold tracking-tight leading-8">{{ t("chat.heroTitle") }}</h2>
          <p class="mt-2 text-[13px] leading-6 text-muted">{{ t("chat.heroSubtitle") }}</p>
          <div class="mt-7 grid gap-2">
            <button
              v-for="s in suggestions"
              :key="s"
              class="group w-full text-left rounded-xl border border-line bg-surface px-4 py-3 text-[12.5px] text-ink/80 transition flex items-center gap-3 hover:border-accent/40 hover:text-ink hover:shadow-sm"
              @click="useSuggestion(s)"
            >
              <Icon name="sparkles" :size="14" class="text-accent/70" />
              <span class="flex-1">{{ s }}</span>
              <Icon name="chevron" :size="14" class="text-muted/50 -rotate-90 transition group-hover:translate-x-0.5" />
            </button>
          </div>
        </div>
      </div>

      <!-- 气泡 -->
      <div v-else class="mx-auto w-full max-w-3xl px-6 py-8 space-y-6">
        <div
          v-for="m in messages"
          :key="m.id"
          class="flex gap-3 animate-fade-up"
          :class="m.role === 'user' ? 'flex-row-reverse' : ''"
        >
          <div
            class="h-8 w-8 shrink-0 rounded-xl grid place-items-center text-[11px] font-semibold"
            :class="m.role === 'user' ? 'bg-ink/5 text-muted' : 'bg-accent-soft text-accent'"
          >
            <Icon v-if="m.role === 'assistant'" name="sparkles" :size="15" />
            <span v-else>{{ userBadge }}</span>
          </div>
          <div class="max-w-[78%] min-w-0">
            <!-- 用户消息 -->
            <div
              v-if="m.role === 'user'"
              class="px-4 py-3 text-[13.5px] leading-6 whitespace-pre-wrap break-words rounded-2xl shadow-bubble bg-accent text-white rounded-tr-md"
            >{{ m.text }}</div>

            <!-- 助手消息：按发生顺序渲染文本气泡 / 思考折叠块 / 工具调用卡片 -->
            <div v-else-if="m.parts && m.parts.length" class="space-y-2">
              <template v-for="(p, i) in m.parts" :key="`${m.id}-${i}`">
                <div
                  v-if="p.kind === 'text'"
                  class="px-4 py-3 text-[13.5px] leading-6 whitespace-pre-wrap break-words rounded-2xl shadow-bubble bg-surface ring-1 ring-line rounded-tl-md"
                >
                  {{ p.text }}<span
                    v-if="m.pending && i === m.parts.length - 1"
                    class="inline-block w-[2px] h-[13px] align-[-2px] ml-0.5 bg-accent/70 animate-pulse"
                  ></span>
                </div>
                <ThinkingBlock
                  v-else-if="p.kind === 'thinking'"
                  :text="p.text"
                  :pending="m.pending && i === m.parts.length - 1"
                />
                <ToolCallCard v-else-if="p.kind === 'tool'" :part="p" />
              </template>
              <div v-if="m.pending && !hasTrailingText(m)" class="flex items-center gap-1.5 px-1 py-1">
                <span class="h-1.5 w-1.5 rounded-full bg-accent animate-blink"></span>
                <span class="h-1.5 w-1.5 rounded-full bg-accent animate-blink" style="animation-delay: .18s"></span>
                <span class="h-1.5 w-1.5 rounded-full bg-accent animate-blink" style="animation-delay: .36s"></span>
              </div>
            </div>

            <!-- 旧消息（只有 text）或纯文本回复 -->
            <div
              v-else
              class="px-4 py-3 text-[13.5px] leading-6 whitespace-pre-wrap break-words rounded-2xl shadow-bubble bg-surface ring-1 ring-line rounded-tl-md"
            >
              <span v-if="m.pending && !m.text" class="flex items-center gap-1.5 py-0.5">
                <span class="h-1.5 w-1.5 rounded-full bg-accent animate-blink"></span>
                <span class="h-1.5 w-1.5 rounded-full bg-accent animate-blink" style="animation-delay: .18s"></span>
                <span class="h-1.5 w-1.5 rounded-full bg-accent animate-blink" style="animation-delay: .36s"></span>
              </span>
              <template v-else>
                {{ m.text }}<span
                  v-if="m.pending"
                  class="inline-block w-[2px] h-[13px] align-[-2px] ml-0.5 bg-accent/70 animate-pulse"
                ></span>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="shrink-0 px-6 pt-2 pb-5 bg-gradient-to-t from-canvas via-canvas to-canvas/0">
      <div class="mx-auto w-full max-w-3xl">
        <!-- 控制开关：中间件离线时点不动，并提示要先启动 8737 -->
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <button
            class="h-7 px-2.5 rounded-full border text-[11px] flex items-center gap-1.5 transition"
            :class="store.allowControl && store.backendOnline
              ? 'border-accent/50 bg-accent-soft text-accent'
              : 'border-line text-muted hover:text-ink'"
            @click="store.toggleControl()"
          >
            <Icon name="cpu" :size="12" />
            {{ t("chat.control") }} · {{ store.allowControl && store.backendOnline ? "ON" : "OFF" }}
          </button>
          <button
            class="h-7 px-2.5 rounded-full border text-[11px] flex items-center gap-1.5 transition"
            :class="store.deepThink
              ? 'border-accent/50 bg-accent-soft text-accent'
              : 'border-line text-muted hover:text-ink'"
            @click="store.toggleDeepThink()"
          >
            <Icon name="sparkles" :size="12" />
            {{ t("chat.think") }} · {{ store.deepThink ? "ON" : "OFF" }}
          </button>

          <!-- 屏幕 token：读屏数据预算 -->
          <div class="relative">
            <button
              class="h-7 px-2.5 rounded-full border text-[11px] flex items-center gap-1.5 transition"
              :class="store.screenMode === 'custom'
                ? 'border-accent/50 bg-accent-soft text-accent'
                : 'border-line text-muted hover:text-ink'"
              @click="screenMenu = !screenMenu"
            >
              <Icon name="panel" :size="12" />
              {{ t("chat.screenTokens") }} ·
              {{ store.screenMode === "auto" ? t("chat.tokenAuto") : store.screenBudget }}
            </button>

            <div v-if="screenMenu" class="fixed inset-0 z-20" @click="screenMenu = false"></div>
            <div
              v-if="screenMenu"
              class="absolute bottom-9 left-0 z-30 w-[264px] rounded-xl border border-line bg-surface p-2.5 shadow-soft"
            >
              <div class="flex p-0.5 rounded-lg bg-canvas border border-line text-[11px]">
                <button
                  class="flex-1 py-1.5 rounded-md transition"
                  :class="store.screenMode === 'auto' ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink'"
                  @click="store.setScreenMode('auto')"
                >{{ t("chat.tokenAuto") }}</button>
                <button
                  class="flex-1 py-1.5 rounded-md transition"
                  :class="store.screenMode === 'custom' ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink'"
                  @click="store.setScreenMode('custom')"
                >{{ t("chat.tokenCustom") }}</button>
              </div>

              <div v-if="store.screenMode === 'custom'" class="mt-2.5">
                <div class="flex items-center gap-1.5">
                  <input
                    v-model.number="screenBudgetInput"
                    type="number"
                    min="80"
                    max="4000"
                    step="50"
                    class="field h-8 px-2 py-1 text-[12px]"
                    @change="applyScreenBudget"
                  />
                  <span class="text-[10.5px] text-muted">tokens</span>
                </div>
                <div class="mt-1.5 flex flex-wrap gap-1">
                  <button
                    v-for="n in [600, 1200, 2400, 4000]"
                    :key="n"
                    class="px-1.5 py-0.5 rounded-md border border-line text-[10.5px] text-muted transition hover:text-ink"
                    @click="pickScreenBudget(n)"
                  >{{ n }}</button>
                </div>
                <p class="mt-1.5 text-[10.5px] leading-4 text-muted">{{ t("chat.screenCustomHint") }}</p>
              </div>
              <p v-else class="mt-2 text-[10.5px] leading-4 text-muted">{{ t("chat.screenAutoHint") }}</p>
            </div>
          </div>

          <!-- 输出 token：自动 / 自定义 -->
          <div class="relative">
            <button
              class="h-7 px-2.5 rounded-full border text-[11px] flex items-center gap-1.5 transition"
              :class="store.tokenMode === 'custom'
                ? 'border-accent/50 bg-accent-soft text-accent'
                : 'border-line text-muted hover:text-ink'"
              @click="tokenMenu = !tokenMenu"
            >
              <Icon name="terminal" :size="12" />
              {{ t("chat.tokens") }} ·
              {{ store.tokenMode === "auto" ? t("chat.tokenAuto") : (store.activeModel?.maxTokens ?? 2048) }}
            </button>

            <div v-if="tokenMenu" class="fixed inset-0 z-20" @click="tokenMenu = false"></div>
            <div
              v-if="tokenMenu"
              class="absolute bottom-9 left-0 z-30 w-[244px] rounded-xl border border-line bg-surface p-2.5 shadow-soft"
            >
              <div class="flex p-0.5 rounded-lg bg-canvas border border-line text-[11px]">
                <button
                  class="flex-1 py-1.5 rounded-md transition"
                  :class="store.tokenMode === 'auto' ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink'"
                  @click="store.setTokenMode('auto')"
                >{{ t("chat.tokenAuto") }}</button>
                <button
                  class="flex-1 py-1.5 rounded-md transition"
                  :class="store.tokenMode === 'custom' ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink'"
                  @click="store.setTokenMode('custom')"
                >{{ t("chat.tokenCustom") }}</button>
              </div>

              <div v-if="store.tokenMode === 'custom'" class="mt-2.5">
                <div class="flex items-center gap-1.5">
                  <input
                    v-model.number="customTokens"
                    type="number"
                    min="256"
                    max="16384"
                    step="256"
                    class="field h-8 px-2 py-1 text-[12px]"
                    @change="applyTokens"
                  />
                  <span class="text-[10.5px] text-muted">tokens</span>
                </div>
                <div class="mt-1.5 flex flex-wrap gap-1">
                  <button
                    v-for="n in [1024, 2048, 4096, 8192]"
                    :key="n"
                    class="px-1.5 py-0.5 rounded-md border border-line text-[10.5px] text-muted transition hover:text-ink"
                    @click="pickTokens(n)"
                  >{{ n }}</button>
                </div>
                <p class="mt-1.5 text-[10.5px] leading-4 text-muted">{{ t("chat.tokenCustomHint") }}</p>
              </div>
              <p v-else class="mt-2 text-[10.5px] leading-4 text-muted">{{ t("chat.tokenAutoHint") }}</p>
            </div>
          </div>
        </div>

        <div
          class="rounded-2xl bg-surface border border-line shadow-soft p-2 pl-3 transition
                 focus-within:border-accent/50 focus-within:ring-4 focus-within:ring-accent/10"
        >
          <div class="flex items-end gap-2">
            <textarea
              ref="area"
              v-model="input"
              rows="1"
              class="flex-1 resize-none bg-transparent border-0 outline-none text-[13.5px] leading-6 py-1.5 max-h-[168px] placeholder:text-muted/70"
              :placeholder="t('chat.inputPlaceholder')"
              @input="autoGrow"
              @keydown.enter.exact.prevent="send"
            ></textarea>
            <button
              v-if="store.sending"
              class="h-9 w-9 shrink-0 rounded-xl bg-ink text-canvas grid place-items-center transition hover:opacity-90 active:scale-95"
              :aria-label="t('chat.stop')"
              :title="t('chat.stop')"
              @click="store.stop()"
            >
              <Icon name="stop" :size="14" />
            </button>
            <button
              v-else
              class="h-9 w-9 shrink-0 rounded-xl bg-accent text-white grid place-items-center transition hover:brightness-105 active:scale-95 disabled:opacity-40 disabled:pointer-events-none"
              :disabled="!input.trim()"
              :aria-label="t('chat.send')"
              :title="t('chat.send')"
              @click="send"
            >
              <Icon name="send" :size="16" />
            </button>
          </div>
        </div>
        <p class="mt-2 text-center text-[11px] text-muted/80">{{ t("chat.hint") }}</p>
      </div>
    </div>
  </div>
</template>
