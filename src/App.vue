<script setup lang="ts">
import { onMounted } from "vue";
import Sidebar from "./components/Sidebar.vue";
import ChatView from "./components/ChatView.vue";
import SettingsView from "./components/SettingsView.vue";
import ToolBook from "./components/ToolBook.vue";
import { useAppStore } from "./stores/app";

const store = useAppStore();

onMounted(() => store.bootstrap());
</script>

<template>
  <div class="h-full flex bg-canvas text-ink overflow-hidden">
    <Sidebar />
    <main class="flex-1 min-w-0 relative">
      <ChatView v-if="store.view === 'chat'" />
      <ToolBook v-else-if="store.view === 'toolbook'" />
      <SettingsView v-else />

      <transition name="toast">
        <div
          v-if="store.toast"
          class="absolute bottom-6 left-1/2 -translate-x-1/2 rounded-xl bg-ink text-canvas px-3.5 py-2 text-[12px] shadow-soft z-20"
        >{{ store.toast }}</div>
      </transition>
    </main>
  </div>
</template>

<style>
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.18s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
}
</style>
