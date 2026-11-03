/**
 * 自动输出预算：不再固定用模型配置里的 Max Tokens，
 * 而是按输入长度和任务类型给一个“够用”的上限；真被截断时 agent 还会翻倍重试。
 */
const LONG_TASK =
  /(写|生成|详细|完整|报告|方案|代码|表格|总结|翻译|列出|分析|扩写|write|generate|report|code|summary|list|essay)/i;

export function autoMaxTokens(input: string, agent: boolean): number {
  const n = input.trim().length;
  // 推理模型会消耗 token 思考，基线不能太低
  let tokens = agent ? 3072 : 2048;
  if (n > 180) tokens = Math.max(tokens, 3072);
  if (n > 600 || LONG_TASK.test(input)) tokens = Math.max(tokens, 4096);
  if (n > 1500) tokens = Math.max(tokens, 6144);
  return Math.min(tokens, 8192);
}

export const TOKEN_CAP = 8192;
