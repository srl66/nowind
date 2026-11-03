import { useAppStore } from "./stores/app";
import { translate } from "./i18n";

/** 全局翻译入口：t() 在 render 中读取 store.lang，所以切换语言会真实重渲染。 */
export function useI18n() {
  const store = useAppStore();
  const t = (key: string, vars?: Record<string, string | number>) =>
    translate(store.lang, key, vars);
  return { t, store };
}
