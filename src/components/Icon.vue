<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(defineProps<{ name: string; size?: number; stroke?: number }>(), {
  size: 18,
  stroke: 1.7,
});

/** 单文件图标集：只保留 24x24 的描边路径，多段用 | 分隔，避免引入额外依赖。 */
const paths: Record<string, string> = {
  plus: "M12 5v14|M5 12h14",
  message:
    "M21 11.5a8.5 8.5 0 0 1-12.6 7.4L3 21l2.1-5.4A8.5 8.5 0 1 1 21 11.5Z",
  settings:
    "M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z|M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z",
  sun: "M12 4V2|M12 22v-2|M4 12H2|M22 12h-2|M6.3 6.3 4.9 4.9|M19.1 19.1l-1.4-1.4|M6.3 17.7 4.9 19.1|M19.1 4.9l-1.4 1.4|M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z",
  globe:
    "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z|M3 12h18|M12 3c2.5 2.4 3.8 5.6 3.8 9s-1.3 6.6-3.8 9c-2.5-2.4-3.8-5.6-3.8-9S9.5 5.4 12 3Z",
  check: "M20 6 9 17l-5-5",
  trash: "M3 6h18|M8 6V4h8v2|M19 6l-1 14H6L5 6|M10 11v6|M14 11v6",
  send: "M22 2 11 13|M22 2l-7 20-4-9-9-4 20-7Z",
  stop: "M7 7h10v10H7z",
  chevron: "m6 9 6 6 6-6",
  sparkles:
    "M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6L12 3Z|M18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z",
  cpu: "M9 4V2|M15 4V2|M9 22v-2|M15 22v-2|M4 9H2|M4 15H2|M22 9h-2|M22 15h-2|M5 5h14v14H5z|M9 9h6v6H9z",
  key: "M21 2l-2 2|M15.5 8.5 19 5|M18 2l3 3|M10.5 13.5a5 5 0 1 1-7 7 5 5 0 0 1 7-7Z",
  link: "M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1|M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1",
  x: "M18 6 6 18|M6 6l12 12",
  alert:
    "M12 9v4|M12 17h.01|M10.3 3.3 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.3a2 2 0 0 0-3.4 0Z",
  loader: "M12 2a10 10 0 1 0 10 10",
  book: "M6.5 3H20v18H6.5A2.5 2.5 0 0 1 4 18.5v-13A2.5 2.5 0 0 1 6.5 3Z|M20 16H6.5A2.5 2.5 0 0 0 4 18.5",
  terminal: "M4 5h16v14H4z|M8 10l2.5 2.5L8 15|M13 15h3.5",
  panel: "M4 5h16v14H4z|M9 5v14",
};

const d = computed(() => (paths[props.name] ?? "").split("|").filter(Boolean));
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="stroke"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    class="shrink-0"
  >
    <path v-for="(p, i) in d" :key="i" :d="p" />
  </svg>
</template>
