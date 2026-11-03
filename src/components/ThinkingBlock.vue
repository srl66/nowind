<script setup lang="ts">
import { computed, ref } from "vue";
import Icon from "./Icon.vue";
import { useI18n } from "../useI18n";

const props = defineProps<{ text: string; pending?: boolean }>();
const { t } = useI18n();

/** 默认折叠，点标题展开/收起 */
const open = ref(false);

/** 收起时给一行预览，让人知道里面确实有内容 */
const preview = computed(() => props.text.replace(/\s+/g, " ").trim().slice(0, 90));
</script>

<template>
  <div class="rounded-xl border border-line/80 bg-surface/50 overflow-hidden animate-fade-in">
    <button
      class="w-full flex items-center gap-2 px-3 py-2 text-left transition hover:bg-ink/[0.03]"
      @click="open = !open"
    >
      <Icon name="sparkles" :size="13" class="text-accent" />
      <span class="text-[11.5px] text-muted">{{ t("chat.thinkingLabel") }}</span>
      <span v-if="pending" class="text-[10.5px] text-accent animate-pulse">
        {{ t("chat.thinkingLive") }}
      </span>
      <span class="flex-1"></span>
      <span v-if="!open" class="max-w-[55%] truncate text-[11px] text-muted/70">
        {{ preview }}
      </span>
      <Icon
        name="chevron"
        :size="12"
        class="text-muted/60 transition"
        :class="open ? 'rotate-180' : ''"
      />
    </button>
    <div
      v-if="open"
      class="px-3 pb-3 text-[12px] leading-5 text-muted whitespace-pre-wrap break-words"
    >{{ text }}</div>
  </div>
</template>
