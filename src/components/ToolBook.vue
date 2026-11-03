<script setup lang="ts">
import { computed, ref } from "vue";
import Icon from "./Icon.vue";
import { useI18n } from "../useI18n";
import { toolDocs, toolFlow, type ToolDoc } from "../services/toolbook";

const { t, store } = useI18n();
const lang = computed(() => store.lang);
const bi = (v: { zh: string; en: string }) => v[lang.value];

/** 每个工具默认收起，点标题展开参数与示例 */
const expanded = ref<Record<string, boolean>>({});
const toggle = (name: string) => {
  expanded.value[name] = !expanded.value[name];
};
const allOpen = computed(() => toolDocs.every((d) => expanded.value[d.name]));
function toggleAll() {
  const next = !allOpen.value;
  for (const d of toolDocs) expanded.value[d.name] = next;
}

const commandOf = (doc: ToolDoc) => `${doc.name}(${JSON.stringify(doc.example)})`;

/** 经验库：搜索与展示 */
const expQuery = ref("");
const filteredExps = computed(() => {
  const q = expQuery.value.trim().toLowerCase();
  if (!q) return store.experiences;
  return store.experiences.filter((e) =>
    `${e.task} ${e.tool} ${e.error} ${e.fix}`.toLowerCase().includes(q)
  );
});

function fmtTime(ts: number): string {
  const d = new Date(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="h-14 shrink-0 px-6 flex items-center justify-between border-b border-line/70">
      <div class="min-w-0 flex items-baseline gap-2">
        <span class="text-[13.5px] font-medium">{{ t("toolbook.title") }}</span>
        <span class="text-[11px] text-muted">{{ t("toolbook.count", { n: toolDocs.length }) }}</span>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <span class="chip font-mono">127.0.0.1:8737</span>
        <button class="chip hover:text-ink transition" @click="toggleAll">
          {{ allOpen ? t("toolbook.collapseAll") : t("toolbook.expandAll") }}
        </button>
      </div>
    </header>

    <div class="flex-1 min-h-0 overflow-y-auto">
      <div class="mx-auto w-full max-w-3xl px-6 py-8 space-y-8">
        <!-- 概述 + 工作流 -->
        <section class="animate-fade-up">
          <p class="text-[12.5px] leading-6 text-muted">{{ t("toolbook.subtitle") }}</p>
          <div class="mt-4 rounded-2xl border border-line bg-surface p-4 shadow-sm">
            <div class="text-[11px] uppercase tracking-[0.12em] text-muted/80 mb-3">
              {{ t("toolbook.flowTitle") }}
            </div>
            <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div
                v-for="s in toolFlow"
                :key="s.title.zh"
                class="rounded-xl bg-canvas/70 border border-line/60 px-3 py-2.5"
              >
                <div class="flex items-center gap-1.5 text-accent">
                  <Icon :name="s.icon" :size="13" />
                  <span class="text-[11px] font-medium text-ink/85">{{ bi(s.title) }}</span>
                </div>
                <p class="mt-1 text-[11px] leading-4 text-muted">{{ bi(s.desc) }}</p>
              </div>
            </div>
            <p class="mt-3 text-[11px] leading-5 text-muted/80">{{ t("toolbook.flowHint") }}</p>
          </div>
        </section>

        <!-- 工具清单 -->
        <section class="space-y-3">
          <div class="flex items-baseline justify-between">
            <h3 class="text-[12.5px] font-medium">{{ t("toolbook.listTitle") }}</h3>
            <span class="text-[11px] text-muted">{{ t("toolbook.listHint") }}</span>
          </div>

          <div
            v-for="doc in toolDocs"
            :key="doc.name"
            class="rounded-2xl border border-line bg-surface shadow-sm overflow-hidden"
          >
            <button
              class="w-full flex items-start gap-3 px-4 py-3.5 text-left transition hover:bg-ink/[0.02]"
              @click="toggle(doc.name)"
            >
              <span class="mt-0.5 h-8 w-8 shrink-0 rounded-lg bg-accent-soft text-accent grid place-items-center">
                <Icon name="terminal" :size="15" />
              </span>
              <div class="min-w-0 flex-1">
                <div class="flex items-baseline gap-2 flex-wrap">
                  <span class="font-mono text-[12.5px] font-medium">{{ doc.name }}</span>
                  <span class="text-[11px] text-muted">{{ bi(doc.label) }}</span>
                </div>
                <p class="mt-1 text-[12px] leading-5 text-muted">{{ bi(doc.summary) }}</p>
              </div>
              <Icon
                name="chevron"
                :size="14"
                class="mt-1 shrink-0 text-muted/60 transition"
                :class="expanded[doc.name] ? 'rotate-180' : ''"
              />
            </button>

            <div
              v-if="expanded[doc.name]"
              class="border-t border-line/70 px-4 py-4 space-y-4 animate-fade-in"
            >
              <!-- 参数 -->
              <div>
                <div class="text-[10px] uppercase tracking-[0.1em] text-muted mb-2">
                  {{ t("toolbook.params") }}
                </div>
                <div v-if="doc.params.length" class="space-y-1.5">
                  <div
                    v-for="p in doc.params"
                    :key="p.name"
                    class="rounded-lg bg-canvas/60 border border-line/60 px-2.5 py-2"
                  >
                    <div class="flex items-baseline gap-2 flex-wrap">
                      <span class="font-mono text-[11.5px] text-ink">{{ p.name }}</span>
                      <span class="font-mono text-[10.5px] text-muted/80">{{ p.type }}</span>
                      <span
                        class="text-[10px] px-1.5 py-0.5 rounded-full"
                        :class="p.required
                          ? 'bg-accent-soft text-accent'
                          : 'border border-line text-muted'"
                      >
                        {{ p.required ? t("toolbook.required") : t("toolbook.optional") }}
                      </span>
                    </div>
                    <p class="mt-1 text-[11.5px] leading-5 text-muted">{{ bi(p.desc) }}</p>
                  </div>
                </div>
                <p v-else class="text-[11.5px] text-muted">{{ t("toolbook.none") }}</p>
              </div>

              <!-- 返回 -->
              <div>
                <div class="text-[10px] uppercase tracking-[0.1em] text-muted mb-1.5">
                  {{ t("toolbook.returns") }}
                </div>
                <p class="text-[11.5px] leading-5 text-muted">{{ bi(doc.returns) }}</p>
              </div>

              <!-- 示例 -->
              <div>
                <div class="text-[10px] uppercase tracking-[0.1em] text-muted mb-1.5">
                  {{ t("toolbook.example") }}
                </div>
                <pre
                  class="rounded-lg bg-canvas/70 border border-line/60 px-2.5 py-2 text-[11.5px] leading-5 font-mono text-ink/85 whitespace-pre-wrap break-all"
                >{{ commandOf(doc) }}</pre>
                <pre
                  class="mt-1.5 rounded-lg bg-canvas/70 border border-line/60 px-2.5 py-2 text-[11.5px] leading-5 font-mono text-ink/65 whitespace-pre-wrap break-words"
                >{{ doc.result }}</pre>
              </div>

              <!-- 注意 -->
              <div>
                <div class="text-[10px] uppercase tracking-[0.1em] text-muted mb-1.5">
                  {{ t("toolbook.notes") }}
                </div>
                <ul class="space-y-1">
                  <li
                    v-for="(n, i) in doc.notes"
                    :key="i"
                    class="flex gap-1.5 text-[11.5px] leading-5 text-muted"
                  >
                    <Icon name="check" :size="11" class="mt-1 text-accent/70" />
                    <span>{{ bi(n) }}</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        <!-- 经验库：失败后改进成功的做法 -->
        <section class="space-y-3">
          <div class="flex items-baseline justify-between gap-3">
            <h3 class="text-[12.5px] font-medium">{{ t("toolbook.expTitle") }}</h3>
            <div class="flex items-center gap-2">
              <span class="text-[11px] text-muted">
                {{ t("toolbook.expCount", { n: store.experiences.length }) }}
              </span>
              <button
                v-if="store.experiences.length"
                class="text-[10.5px] text-muted transition hover:text-danger"
                @click="store.clearExperiences()"
              >{{ t("toolbook.expClear") }}</button>
            </div>
          </div>
          <p class="text-[11.5px] leading-5 text-muted">{{ t("toolbook.expHint") }}</p>
          <input
            v-model="expQuery"
            class="field h-9 text-[12px]"
            :placeholder="t('toolbook.expSearch')"
          />

          <div v-if="filteredExps.length" class="space-y-2">
            <div
              v-for="e in filteredExps"
              :key="e.id"
              class="rounded-2xl border border-line bg-surface p-3 shadow-sm"
            >
              <div class="flex items-center gap-2">
                <span class="font-mono text-[10.5px] px-1.5 py-0.5 rounded-full bg-accent-soft text-accent">
                  {{ e.tool }}
                </span>
                <span class="flex-1 text-[10.5px] text-muted">{{ fmtTime(e.createdAt) }}</span>
                <button
                  class="text-[10.5px] text-muted transition hover:text-danger"
                  @click="store.removeExperience(e.id)"
                >{{ t("common.delete") }}</button>
              </div>
              <p class="mt-1.5 text-[12px] leading-5 text-ink/85">{{ e.task || "—" }}</p>
              <div class="mt-1.5 text-[11px] leading-5">
                <span class="text-danger/80">{{ t("toolbook.expFailure") }}</span>
                <span class="text-muted"> {{ e.error }}</span>
              </div>
              <div class="mt-0.5 text-[11px] leading-5">
                <span class="text-emerald-600">{{ t("toolbook.expFix") }}</span>
                <span class="text-muted"> {{ e.fix }}</span>
              </div>
            </div>
          </div>
          <p v-else class="text-[11.5px] text-muted">
            {{ expQuery ? t("toolbook.expNoMatch") : t("toolbook.expEmpty") }}
          </p>
        </section>

        <!-- 调用记录 + 安全边界 -->
        <section class="grid md:grid-cols-2 gap-3">
          <div class="rounded-2xl border border-line bg-surface p-4 shadow-sm">
            <div class="flex items-center gap-1.5 text-[12.5px] font-medium">
              <Icon name="message" :size="14" class="text-accent" />
              {{ t("toolbook.recordTitle") }}
            </div>
            <p class="mt-1.5 text-[11.5px] leading-5 text-muted">{{ t("toolbook.recordDesc") }}</p>
          </div>
          <div class="rounded-2xl border border-line bg-surface p-4 shadow-sm">
            <div class="flex items-center gap-1.5 text-[12.5px] font-medium">
              <Icon name="alert" :size="14" class="text-danger/80" />
              {{ t("toolbook.safetyTitle") }}
            </div>
            <ul class="mt-1.5 space-y-1">
              <li class="flex gap-1.5 text-[11.5px] leading-5 text-muted">
                <Icon name="x" :size="11" class="mt-1 text-danger/60" />
                <span>{{ t("toolbook.safety1") }}</span>
              </li>
              <li class="flex gap-1.5 text-[11.5px] leading-5 text-muted">
                <Icon name="x" :size="11" class="mt-1 text-danger/60" />
                <span>{{ t("toolbook.safety2") }}</span>
              </li>
              <li class="flex gap-1.5 text-[11.5px] leading-5 text-muted">
                <Icon name="x" :size="11" class="mt-1 text-danger/60" />
                <span>{{ t("toolbook.safety3") }}</span>
              </li>
            </ul>
          </div>
        </section>

        <p class="text-center text-[11px] text-muted/70 pb-2">{{ t("toolbook.endpoint") }}</p>
      </div>
    </div>
  </div>
</template>
