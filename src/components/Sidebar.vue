<script setup lang="ts">
import Icon from "./Icon.vue";
import { useI18n } from "../useI18n";

const { t, store } = useI18n();
</script>

<template>
  <aside class="w-[272px] shrink-0 h-full flex flex-col bg-sidebar border-r border-line/70">
    <!-- 品牌 -->
    <div class="px-4 pt-5 pb-3 flex items-center gap-3">
      <div class="h-9 w-9 rounded-2xl bg-accent text-white grid place-items-center shadow-sm">
        <Icon name="sparkles" :size="18" />
      </div>
      <div class="min-w-0">
        <div class="text-[13.5px] font-semibold leading-tight truncate">{{ t("app.name") }}</div>
        <div class="text-[11px] text-muted leading-tight truncate mt-0.5">{{ t("app.tagline") }}</div>
      </div>
    </div>

    <!-- 新建对话 -->
    <div class="px-3">
      <button
        class="w-full h-10 rounded-xl bg-surface border border-line shadow-sm flex items-center gap-2 px-3 text-[13px] font-medium transition hover:border-accent/40 hover:text-accent active:scale-[0.99]"
        @click="store.newChat()"
      >
        <Icon name="plus" :size="16" />
        <span>{{ t("sidebar.newChat") }}</span>
      </button>
    </div>

    <!-- 历史列表 -->
    <div class="flex-1 min-h-0 mt-4 flex flex-col">
      <div class="px-4 pb-1.5 text-[10.5px] uppercase tracking-[0.12em] text-muted/80">
        {{ t("sidebar.history") }}
      </div>
      <div class="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
        <ul class="space-y-0.5">
          <li v-for="c in store.chats" :key="c.id" class="group">
            <button
              class="w-full text-left rounded-lg px-2.5 py-2 flex items-center gap-2 transition"
              :class="c.id === store.activeChatId ? 'bg-surface shadow-sm ring-1 ring-line' : 'hover:bg-surface/70'"
              @click="store.selectChat(c.id)"
            >
              <Icon name="message" :size="14" class="text-muted group-hover:text-ink/70" />
              <span
                class="flex-1 truncate text-[12.5px]"
                :class="c.id === store.activeChatId ? 'text-ink' : 'text-ink/80'"
              >{{ c.title }}</span>
              <span
                class="h-5 w-5 grid place-items-center rounded-md text-muted opacity-0 group-hover:opacity-100 hover:bg-line/60 hover:text-danger transition"
                @click.stop="store.deleteChat(c.id)"
              >
                <Icon name="trash" :size="12" />
              </span>
            </button>
          </li>
        </ul>
        <p v-if="!store.chats.length" class="px-3 py-6 text-[12px] leading-5 text-muted">
          {{ t("sidebar.empty") }}
        </p>
      </div>
    </div>

    <!-- 底部：语言 / 主题 / 设置 -->
    <div class="p-2.5 border-t border-line/70 space-y-0.5">
      <div class="flex items-center justify-between px-2 h-9">
        <span class="flex items-center gap-2 text-[12px] text-muted">
          <Icon name="globe" :size="15" />{{ t("sidebar.language") }}
        </span>
        <div class="flex p-0.5 rounded-lg bg-surface border border-line text-[11px]">
          <button
            class="px-2 py-1 rounded-md transition"
            :class="store.lang === 'zh' ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink'"
            @click="store.setLang('zh')"
          >中文</button>
          <button
            class="px-2 py-1 rounded-md transition"
            :class="store.lang === 'en' ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink'"
            @click="store.setLang('en')"
          >EN</button>
        </div>
      </div>

      <div class="flex items-center justify-between px-2 h-9">
        <span class="flex items-center gap-2 text-[12px] text-muted">
          <Icon :name="store.theme === 'dark' ? 'moon' : 'sun'" :size="15" />{{ t("sidebar.theme") }}
        </span>
        <div class="flex p-0.5 rounded-lg bg-surface border border-line text-[11px]">
          <button
            class="px-2 py-1 rounded-md transition flex items-center gap-1"
            :class="store.theme === 'light' ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink'"
            @click="store.setTheme('light')"
          >
            <Icon name="sun" :size="12" />{{ t("sidebar.light") }}
          </button>
          <button
            class="px-2 py-1 rounded-md transition flex items-center gap-1"
            :class="store.theme === 'dark' ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink'"
            @click="store.setTheme('dark')"
          >
            <Icon name="moon" :size="12" />{{ t("sidebar.dark") }}
          </button>
        </div>
      </div>

      <button
        class="w-full flex items-center gap-2 px-2 h-9 rounded-lg text-[12.5px] transition"
        :class="store.view === 'toolbook' ? 'bg-surface ring-1 ring-line text-ink' : 'text-muted hover:bg-surface/70 hover:text-ink'"
        @click="store.setView('toolbook')"
      >
        <Icon name="book" :size="15" />
        <span>{{ t("sidebar.tools") }}</span>
      </button>

      <button
        class="w-full flex items-center gap-2 px-2 h-9 rounded-lg text-[12.5px] transition"
        :class="store.view === 'settings' ? 'bg-surface ring-1 ring-line text-ink' : 'text-muted hover:bg-surface/70 hover:text-ink'"
        @click="store.setView('settings')"
      >
        <Icon name="settings" :size="15" />
        <span>{{ t("sidebar.settings") }}</span>
        <span class="ml-auto text-[10px] px-1.5 py-0.5 rounded-full border border-line text-muted">
          {{ t("app.badge") }}
        </span>
      </button>
    </div>
  </aside>
</template>
