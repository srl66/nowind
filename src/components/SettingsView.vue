<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import Icon from "./Icon.vue";
import { useI18n } from "../useI18n";
import { isValidEndpoint, probeModels, type ProbeResult } from "../services/models";
import type { ModelConfig } from "../stores/app";

const { t, store } = useI18n();

const draft = reactive<ModelConfig>({
  id: "",
  name: "",
  endpoint: "",
  apiKey: "",
  model: "",
  temperature: 0.7,
  maxTokens: 2048,
});

const showKey = ref(false);
const checking = ref(false);
const checked = ref<ProbeResult | null>(null);
const available = ref<string[]>([]);

const valid = computed(() => draft.name.trim().length > 0 && isValidEndpoint(draft.endpoint));

function loadFrom(model?: ModelConfig) {
  if (!model) return;
  Object.assign(draft, {
    id: model.id,
    name: model.name,
    endpoint: model.endpoint,
    apiKey: model.apiKey,
    model: model.model,
    temperature: model.temperature,
    maxTokens: model.maxTokens,
  });
  available.value = model.model ? [model.model] : [];
  checked.value = null;
  showKey.value = false;
}

watch(() => store.activeModelId, () => loadFrom(store.activeModel), { immediate: true });

async function check() {
  if (!isValidEndpoint(draft.endpoint) || checking.value) return;
  checking.value = true;
  checked.value = null;
  const result = await probeModels(draft.endpoint, draft.apiKey);
  checking.value = false;
  checked.value = result;
  available.value = result.models;
  if (!draft.model && result.models.length) draft.model = result.models[0];
}

function save() {
  if (!valid.value) return;
  store.updateModel({ ...draft });
  store.flash(t("settings.saved"));
}

function removeModel() {
  if (!draft.id) return;
  store.removeModel(draft.id);
  store.flash(t("settings.delete"));
}

function addModel() {
  store.addModel();
}
</script>

<template>
  <div class="h-full overflow-y-auto">
    <!-- 顶栏 -->
    <header class="sticky top-0 z-10 backdrop-blur-md bg-canvas/80 border-b border-line/70">
      <div class="mx-auto max-w-3xl px-6 h-14 flex items-center justify-between gap-4">
        <div class="min-w-0">
          <div class="text-[14px] font-semibold leading-5">{{ t("settings.title") }}</div>
          <div class="text-[11.5px] text-muted truncate">{{ t("settings.subtitle") }}</div>
        </div>
        <button class="btn-primary h-9 px-3.5 shrink-0" :disabled="!valid" @click="save">
          <Icon name="check" :size="15" />
          {{ t("settings.save") }}
        </button>
      </div>
    </header>

    <div class="mx-auto max-w-3xl px-6 py-7 space-y-5 pb-14">
      <!-- 模型列表 -->
      <section class="rounded-2xl bg-surface border border-line shadow-sm overflow-hidden">
        <div class="px-5 py-4 flex items-center justify-between border-b border-line/70">
          <div class="flex items-center gap-2 text-[13px] font-medium">
            <Icon name="cpu" :size="15" class="text-accent" />
            {{ t("settings.models") }}
          </div>
          <button class="btn-ghost h-8 px-2.5 text-[12px]" @click="addModel">
            <Icon name="plus" :size="13" />
            {{ t("settings.addModel") }}
          </button>
        </div>

        <div v-if="store.models.length" class="p-3 grid gap-2 sm:grid-cols-2">
          <button
            v-for="m in store.models"
            :key="m.id"
            class="text-left rounded-xl border p-3 transition"
            :class="m.id === store.activeModelId
              ? 'border-accent/60 bg-accent-soft/40'
              : 'border-line hover:border-accent/30 hover:bg-canvas'"
            @click="store.setActiveModel(m.id)"
          >
            <div class="flex items-center gap-2">
              <span class="text-[12.5px] font-medium truncate">
                {{ m.name || t("settings.namePlaceholder") }}
              </span>
              <span
                v-if="m.id === store.activeModelId"
                class="ml-auto h-4 w-4 rounded-full bg-accent text-white grid place-items-center"
              >
                <Icon name="check" :size="10" />
              </span>
            </div>
            <div class="mt-1 text-[11px] text-muted truncate font-mono">{{ m.endpoint }}</div>
            <div class="mt-1.5 text-[11px] text-muted/80 truncate">
              {{ m.model || t("settings.selectModel") }}
            </div>
          </button>
        </div>
        <p v-else class="px-5 py-6 text-[12px] text-muted">{{ t("settings.emptyModels") }}</p>
      </section>

      <!-- 编辑当前配置 -->
      <section class="rounded-2xl bg-surface border border-line shadow-sm">
        <div class="px-5 py-4 border-b border-line/70 flex items-center gap-2 text-[13px] font-medium">
          <Icon name="settings" :size="15" class="text-accent" />
          {{ t("settings.edit") }}
        </div>

        <div class="p-5 space-y-4">
          <div class="grid gap-4 sm:grid-cols-2">
            <label class="block">
              <span class="mb-1.5 block text-[11.5px] text-muted">{{ t("settings.name") }}</span>
              <input
                v-model="draft.name"
                class="field"
                :placeholder="t('settings.namePlaceholder')"
              />
            </label>
            <label class="block">
              <span class="mb-1.5 block text-[11.5px] text-muted">{{ t("settings.endpoint") }}</span>
              <input
                v-model="draft.endpoint"
                class="field font-mono text-[12px]"
                :placeholder="t('settings.endpointPlaceholder')"
                spellcheck="false"
              />
            </label>
          </div>

          <div>
            <span class="mb-1.5 block text-[11.5px] text-muted">{{ t("settings.apiKey") }}</span>
            <div class="flex gap-2">
              <div class="relative flex-1 min-w-0">
                <Icon name="key" :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-muted/70" />
                <input
                  v-model="draft.apiKey"
                  :type="showKey ? 'text' : 'password'"
                  class="field pl-9 pr-16 font-mono text-[12px]"
                  :placeholder="t('settings.apiKeyPlaceholder')"
                  spellcheck="false"
                  autocomplete="off"
                />
                <button
                  class="absolute right-1.5 top-1/2 -translate-y-1/2 text-[11px] px-2 py-1 rounded-md text-muted transition hover:text-ink hover:bg-canvas"
                  @click="showKey = !showKey"
                >
                  {{ showKey ? t("settings.hide") : t("settings.show") }}
                </button>
              </div>
              <button
                class="btn-ghost h-[42px] px-3.5 shrink-0"
                :disabled="checking || !isValidEndpoint(draft.endpoint)"
                @click="check"
              >
                <Icon :name="checking ? 'loader' : 'link'" :size="14" :class="checking ? 'animate-spin' : ''" />
                {{ checking ? t("settings.checking") : t("settings.check") }}
              </button>
            </div>
            <p
              v-if="checked"
              class="mt-2 text-[11px] flex items-center gap-1.5"
              :class="checked.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted'"
            >
              <Icon :name="checked.ok ? 'check' : 'alert'" :size="12" />
              <span>
                {{ checked.ok ? t("settings.checkOk", { n: checked.models.length }) : t("settings.checkFail") }}
              </span>
              <span
                v-if="!checked.ok"
                class="px-1.5 py-0.5 rounded border border-line text-[10px] text-muted"
              >{{ t("settings.demoBadge") }}</span>
            </p>
          </div>

          <div>
            <div class="mb-1.5 flex items-center justify-between text-[11.5px] text-muted">
              <span>{{ t("settings.selectModel") }}</span>
              <span v-if="checked?.ok" class="text-[11px]">
                {{ t("settings.modelsCount") }} · {{ available.length }}
              </span>
            </div>
            <div class="relative">
              <select
                v-model="draft.model"
                class="field appearance-none pr-9"
                :disabled="!available.length"
              >
                <option value="" disabled>
                  {{ available.length ? t("settings.selectModel") : t("settings.checkFirst") }}
                </option>
                <option v-for="m in available" :key="m" :value="m">{{ m }}</option>
              </select>
              <Icon
                name="chevron"
                :size="15"
                class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted"
              />
            </div>
          </div>

          <div class="grid gap-5 sm:grid-cols-2">
            <div>
              <div class="mb-2 flex items-center justify-between text-[11.5px] text-muted">
                <span>{{ t("settings.temperature") }}</span>
                <span class="font-mono text-ink">{{ draft.temperature.toFixed(1) }}</span>
              </div>
              <input
                v-model.number="draft.temperature"
                type="range"
                class="range"
                min="0"
                max="2"
                step="0.1"
              />
              <div class="mt-1 flex justify-between text-[10px] text-muted/70">
                <span>0.0</span><span>2.0</span>
              </div>
            </div>
            <div>
              <div class="mb-2 flex items-center justify-between text-[11.5px] text-muted">
                <span>{{ t("settings.maxTokens") }}</span>
                <span class="font-mono text-ink">{{ draft.maxTokens }}</span>
              </div>
              <input
                v-model.number="draft.maxTokens"
                type="range"
                class="range"
                min="128"
                max="8192"
                step="64"
              />
              <div class="mt-1 flex justify-between text-[10px] text-muted/70">
                <span>128</span><span>8192</span>
              </div>
            </div>
          </div>

          <div class="flex items-center justify-between gap-3 pt-1">
            <p class="text-[11px]" :class="valid ? 'text-muted' : 'text-danger'">
              {{ valid ? "" : t("settings.invalid") }}
            </p>
            <div class="flex items-center gap-2 shrink-0">
              <button
                class="btn-ghost h-9 px-3 text-danger/90 hover:text-danger hover:border-danger/40"
                @click="removeModel"
              >
                <Icon name="trash" :size="14" />
                {{ t("settings.delete") }}
              </button>
              <button class="btn-primary h-9 px-4" :disabled="!valid" @click="save">
                <Icon name="check" :size="15" />
                {{ t("settings.save") }}
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- 外观 -->
      <section class="rounded-2xl bg-surface border border-line shadow-sm p-5">
        <div class="flex items-center gap-2 text-[13px] font-medium">
          <Icon name="sun" :size="15" class="text-accent" />
          {{ t("settings.appearance") }}
        </div>
        <p class="mt-1 text-[11.5px] text-muted">{{ t("settings.appearanceHint") }}</p>

        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <div class="rounded-xl border border-line p-3">
            <div class="mb-2 text-[11.5px] text-muted">{{ t("sidebar.theme") }}</div>
            <div class="flex gap-2">
              <button
                class="flex-1 h-9 rounded-lg border text-[12px] flex items-center justify-center gap-1.5 transition"
                :class="store.theme === 'light'
                  ? 'border-accent/60 bg-accent-soft text-accent'
                  : 'border-line text-muted hover:text-ink'"
                @click="store.setTheme('light')"
              >
                <Icon name="sun" :size="14" />{{ t("sidebar.light") }}
              </button>
              <button
                class="flex-1 h-9 rounded-lg border text-[12px] flex items-center justify-center gap-1.5 transition"
                :class="store.theme === 'dark'
                  ? 'border-accent/60 bg-accent-soft text-accent'
                  : 'border-line text-muted hover:text-ink'"
                @click="store.setTheme('dark')"
              >
                <Icon name="moon" :size="14" />{{ t("sidebar.dark") }}
              </button>
            </div>
          </div>

          <div class="rounded-xl border border-line p-3">
            <div class="mb-2 text-[11.5px] text-muted">{{ t("sidebar.language") }}</div>
            <div class="flex gap-2">
              <button
                class="flex-1 h-9 rounded-lg border text-[12px] transition"
                :class="store.lang === 'zh'
                  ? 'border-accent/60 bg-accent-soft text-accent'
                  : 'border-line text-muted hover:text-ink'"
                @click="store.setLang('zh')"
              >中文</button>
              <button
                class="flex-1 h-9 rounded-lg border text-[12px] transition"
                :class="store.lang === 'en'
                  ? 'border-accent/60 bg-accent-soft text-accent'
                  : 'border-line text-muted hover:text-ink'"
                @click="store.setLang('en')"
              >English</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
