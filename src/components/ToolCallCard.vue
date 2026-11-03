<script setup lang="ts">
import { computed, ref } from "vue";
import Icon from "./Icon.vue";
import { useI18n } from "../useI18n";
import type { ToolPart } from "../stores/app";

const props = defineProps<{ part: ToolPart }>();
const { t } = useI18n();

/** 默认收起，只露一行状态；点开看具体命令与返回 */
const open = ref(false);

/** 命令形态：工具名 + 实际参数，和 agent 发出的调用一致 */
const command = computed(() => `${props.part.name}(${JSON.stringify(props.part.args ?? {})})`);
const result = computed(() => props.part.result ?? t("chat.toolPending"));
const isFail = computed(() => props.part.status === "fail");

const dotClass = computed(() => {
  if (props.part.status === "ok") return "bg-emerald-500";
  if (props.part.status === "fail") return "bg-danger";
  return "bg-accent/70";
});
</script>

<template>
  <div
    class="rounded-xl border overflow-hidden animate-fade-in"
    :class="isFail ? 'border-danger/30 bg-surface' : 'border-line bg-surface'"
  >
    <button
      class="w-full flex items-center gap-2 px-3 py-2 text-left transition hover:bg-ink/[0.03]"
      @click="open = !open"
    >
      <span class="h-1.5 w-1.5 rounded-full shrink-0" :class="dotClass"></span>
      <Icon name="terminal" :size="13" class="text-muted" />
      <span class="font-mono text-[11.5px] text-ink/80 shrink-0">{{ part.name }}</span>
      <span class="flex-1 min-w-0 truncate text-[11.5px] text-muted">{{ part.label }}</span>
      <Icon
        v-if="part.status === 'running'"
        name="loader"
        :size="12"
        class="text-accent animate-spin"
      />
      <Icon
        name="chevron"
        :size="12"
        class="text-muted/60 transition"
        :class="open ? 'rotate-180' : ''"
      />
    </button>

    <div v-if="open" class="border-t border-line/70 px-3 py-2.5 space-y-2.5">
      <div>
        <div class="text-[10px] uppercase tracking-[0.1em] text-muted mb-1">
          {{ t("chat.toolCommand") }}
        </div>
        <pre
          class="rounded-lg bg-canvas/70 border border-line/60 px-2.5 py-2 text-[11.5px] leading-5 font-mono text-ink/85 whitespace-pre-wrap break-all"
        >{{ command }}</pre>
      </div>
      <div>
        <div class="text-[10px] uppercase tracking-[0.1em] text-muted mb-1">
          {{ t("chat.toolResult") }}
        </div>
        <pre
          class="rounded-lg bg-canvas/70 border border-line/60 px-2.5 py-2 text-[11.5px] leading-5 font-mono whitespace-pre-wrap break-words"
          :class="isFail ? 'text-danger/90' : 'text-ink/70'"
        >{{ result }}</pre>
      </div>
    </div>
  </div>
</template>
