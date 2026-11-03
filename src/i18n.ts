export type Lang = "zh" | "en";

type Dict = Record<string, string>;

export const messages: Record<Lang, Dict> = {
  zh: {
    "app.name": "No Wind",
    "app.tagline": "本地运行的 AI 电脑操作员",
    "app.badge": "UI 骨架",

    "sidebar.newChat": "新建对话",
    "sidebar.history": "历史对话",
    "sidebar.empty": "还没有对话，点上面的「新建对话」开始。",
    "sidebar.language": "语言",
    "sidebar.theme": "主题",
    "sidebar.light": "明亮",
    "sidebar.dark": "暗黑",
    "sidebar.settings": "设置",
    "sidebar.tools": "工具书",

    "chat.newChatTitle": "新对话",
    "chat.inputPlaceholder": "描述你要在这台电脑上做的事…",
    "chat.send": "发送",
    "chat.stop": "停止",
    "chat.hint": "Enter 发送 · Shift+Enter 换行",
    "chat.thinking": "正在输入…",
    "chat.noModelConfigured":
      "还没有可用的模型：去「设置」里填写 Endpoint 和 API Key，点「检查」选一个模型，保存后再发。",
    "chat.requestFailed": "请求失败",
    "chat.timeout": "请求超时，请检查 Endpoint 是否可达、网络是否正常。",
    "chat.emptyReply": "（模型返回了空内容）",
    "chat.aborted": "（已中断）",
    "chat.taskFinished": "任务完成",
    "chat.backend": "本地中间件",
    "chat.online": "已连接",
    "chat.offline": "未连接",
    "chat.control": "控制电脑",
    "chat.think": "深度思考",
    "chat.backendOffline": "本地中间件未连接：先启动 127.0.0.1:8737，再打开「控制电脑」",
    "chat.thinkingLabel": "思考过程",
    "chat.thinkingLive": "思考中…",
    "chat.toolRunning": "调用中…",
    "chat.toolPending": "等待返回…",
    "chat.toolAborted": "（已中断）",
    "chat.toolCommand": "命令",
    "chat.toolResult": "返回",
    "chat.tokens": "输出 Token",
    "chat.tokenAuto": "自动",
    "chat.tokenCustom": "自定义",
    "chat.tokenAutoHint": "按任务长度和类型自动调整（2048–8192）；输出被截断时会自动翻倍重试。",
    "chat.tokenCustomHint": "固定上限，修改会保存到当前模型配置。",
    "chat.screenTokens": "屏幕 Token",
    "chat.screenAutoHint": "按窗口复杂度自动调整：简单窗口约 300，普通 600，网页 1800–3000，最多 4000；模型需要时还能再扩。",
    "chat.screenCustomHint": "固定上限：只发送预算内的控件，超出部分只提示还有多少条。",
    "agent.system":
      "你是「No Wind」，运行在用户的 Windows 电脑上，通过本地中间件读屏幕、点控件、输入文字。\n" +
      "【流程】读屏 → 选控件 → 动作 → 确认 → 回答。\n" +
      "1) 任何操作前先调用 read_screen（网页里的控件用 deep=true），拿到 cid 列表；\n" +
      "1.5) 目标程序不在屏幕上：先 launch_app（calc/notepad/mspaint/explorer/cmd/powershell/taskmgr/edge）再 read_screen；要在网页上操作先用 open_url 打开链接；目标窗口不是前台：先 list_windows 拿 hwnd，再 focus_window(hwnd)，再 read_screen；\n" +
      "1.6) 白名单之外的程序（微信、Office、Chrome 等）：press_keys(win) 打开开始菜单 → type_text(focus=true, 程序名) → press_keys(enter) 启动；\n" +
      "2) 点击用 click_control(cid)，输入用 type_text(text, cid)；cid 必须来自最近一次 read_screen；\n" +
      "2.5) 地址栏、搜索框、聊天输入框读不到 cid 时：用 press_keys（ctrl+l / ctrl+a / ctrl+v / enter / tab）配合 type_text(focus=true) 直接输入到焦点；列表太长用 scroll 滚动后再 read_screen；\n" +
      "2.6) 读屏返回「另有 N 个未列出」时，如果需要的控件不在列表里，再调用 read_screen(limit=N) 取完整列表（自动模式有效；自定义模式受用户上限约束）；\n" +
      "2.7) 读屏里的 Document 名称是「No Wind」说明读到的是应用自己：用 list_windows 找浏览器窗口，focus_window 后再读；open_url 会用新窗口打开目标页；\n" +
      "2.8) 需要读网页/文章正文，而 read_screen 只给出导航和按钮时：用 read_text（UIA 直接读文本，不选全、不复制）拿正文，再总结或摘取；不要靠控件名猜内容；\n" +
      "2.9) 读新闻/文章/博客正文优先用 read_url（Edge 阅读模式 read:<url>，直接返回全文）；视频、搜索列表等交互页面用 open_url + read_text；\n" +
      "2.10) 点击/输入/按键/启动/打开这类动作工具的结果里会附带「最新屏幕」摘要：直接用它里面的 cid 继续，不要每次动作后再单独 read_screen；摘要不够时才 read_screen(limit=N)；\n" +
      "2.11) 同一回复里能确定的连续动作，尽量一次输出多个 tool_calls，减少往返；\n" +
      "2.12) deep 读屏后仍然找不到目标控件（尤其是鼠标悬停才出现的小按钮）时，调用 read_screen(deep=true, fallback=true)：它会额外用 Raw View、悬停 FromPoint、MSAA 兜底，控件行末会标出来源；\n" +
      "3) 每步都要看返回的 verified/reason 判断成功；失败先换一种方法重试（最多 2 次），不要直接放弃；\n" +
      "4) 任务真正完成、并用工具结果确认后，必须调用 finish_task(summary, success=true) 结束；确认无法完成时调用 finish_task(summary, success=false) 并说明卡在哪一步。不要只输出文字就停下。\n" +
      "5) 普通桌面窗口先 deep=false；如果控件明显不够用（例如计算器只有标题栏和内存键），立刻用 deep=true 再读一次；浏览器页面里的控件也要 deep=true；\n" +
      "6) 每次调用工具前先用一句短话汇报正在做什么（例如“我先打开记事本。”），再发工具调用；\n" +
      "【硬性禁止】\n" +
      "- 不许臆测控件、坐标或窗口内容；\n" +
      "- 不许把工具返回值或 JSON 原样复述给用户；\n" +
      "- 不许执行关机、重启、删除文件、格式化、修改系统设置等破坏性操作，遇到就拒绝并说明；\n" +
      "- 同一个 cid 不许重复点击；同一屏不要连续读两次。\n" +
      "【回答格式】简体中文，3 句以内：你做了什么 → 结果如何 → 下一步建议（可省略）。纯聊天或问答不需要调用任何工具。",
    "chat.model": "模型",
    "chat.noModel": "未配置模型",
    "chat.heroTitle": "想让我在这台电脑上做什么？",
    "chat.heroSubtitle":
      "现在只是界面骨架：对话、主题、模型配置已经跑通，下一步再接本地中间件。",
    "chat.s1": "打开浏览器搜索「测试」，并确认结果",
    "chat.s2": "把当前窗口里的按钮念给我听",
    "chat.s3": "把这段文字打进记事本",
    "chat.emptyTitle": "还没有消息",

    "settings.title": "设置",
    "settings.subtitle": "模型端点、采样参数与外观。保存后立即生效，只存在本地。",
    "settings.models": "模型配置",
    "settings.addModel": "添加模型",
    "settings.edit": "编辑配置",
    "settings.name": "名称",
    "settings.namePlaceholder": "例如：本地 Qwen",
    "settings.endpoint": "Endpoint",
    "settings.endpointPlaceholder": "https://api.example.com/v1",
    "settings.apiKey": "API Key",
    "settings.apiKeyPlaceholder": "sk-…",
    "settings.show": "显示",
    "settings.hide": "隐藏",
    "settings.check": "检查",
    "settings.checking": "检查中…",
    "settings.modelsCount": "可用模型",
    "settings.selectModel": "选择模型",
    "settings.checkFirst": "先点「检查」拉取模型列表",
    "settings.temperature": "Temperature",
    "settings.maxTokens": "Max Tokens",
    "settings.save": "保存",
    "settings.saved": "已保存",
    "settings.delete": "删除",
    "settings.appearance": "外观",
    "settings.appearanceHint": "切换立即生效，并记住你的选择。",
    "settings.invalid": "名称不能为空，Endpoint 需以 http(s):// 开头",
    "settings.checkOk": "拉取到 {n} 个模型",
    "settings.checkFail": "端点未连通（请检查 Endpoint / API Key），已展示示例模型",
    "settings.demoBadge": "示例",
    "settings.emptyModels": "还没有配置，点「添加模型」开始。",

    "toolbook.title": "工具书",
    "toolbook.subtitle":
      "模型能用的全部工具、参数与返回格式。所有调用都经由本机中间件执行，失败会给出可执行的原因。",
    "toolbook.count": "{n} 个工具",
    "toolbook.expandAll": "展开全部",
    "toolbook.collapseAll": "收起全部",
    "toolbook.flowTitle": "一次操作的固定顺序",
    "toolbook.flowHint":
      "模型会按这个顺序调用工具，并在每一步之间用自然语言汇报；所有调用在对话里都会显示成卡片。",
    "toolbook.listTitle": "工具清单",
    "toolbook.listHint": "点开查看参数、示例与注意事项",
    "toolbook.params": "参数",
    "toolbook.returns": "返回",
    "toolbook.example": "示例",
    "toolbook.notes": "注意",
    "toolbook.none": "无参数，直接调用即可。",
    "toolbook.required": "必填",
    "toolbook.optional": "可选",
    "toolbook.recordTitle": "调用记录",
    "toolbook.recordDesc":
      "每次工具调用都会在对话里生成一张卡片：绿色点表示成功、红色点表示失败、转圈表示正在执行。点击卡片可以看到实际发出的命令和完整返回。",
    "toolbook.safetyTitle": "安全边界",
    "toolbook.safety1": "破坏性操作（关机、重启、删除文件、格式化）一律拒绝。",
    "toolbook.safety2": "只允许白名单程序：计算器 / 记事本 / 画图 / 资源管理器 / 命令提示符。",
    "toolbook.safety3": "不会绕过读屏直接猜坐标，无 cid 的点击和输入都会被拒绝。",
    "toolbook.endpoint": "中间件地址 127.0.0.1:8737 · 仅在应用运行期间可用",
    "toolbook.expTitle": "经验库",
    "toolbook.expCount": "{n} 条",
    "toolbook.expClear": "清空",
    "toolbook.expHint":
      "每次工具失败会先反思；换方法成功后自动记录在这里，下次同类任务会自动带进提示词。",
    "toolbook.expSearch": "搜索任务、工具或失败原因…",
    "toolbook.expFailure": "失败",
    "toolbook.expFix": "改进",
    "toolbook.expEmpty": "还没有经验。任务中出现失败并成功换方法后会自动记录。",
    "toolbook.expNoMatch": "没有匹配的经验。",

    "common.delete": "删除",
    "common.cancel": "取消",
  },
  en: {
    "app.name": "No Wind",
    "app.tagline": "Local AI computer operator",
    "app.badge": "UI skeleton",

    "sidebar.newChat": "New chat",
    "sidebar.history": "History",
    "sidebar.empty": "No chats yet — start a new one above.",
    "sidebar.language": "Language",
    "sidebar.theme": "Theme",
    "sidebar.light": "Light",
    "sidebar.dark": "Dark",
    "sidebar.settings": "Settings",
    "sidebar.tools": "Tool book",

    "chat.newChatTitle": "New chat",
    "chat.inputPlaceholder": "Describe what to do on this computer…",
    "chat.send": "Send",
    "chat.stop": "Stop",
    "chat.hint": "Enter to send · Shift+Enter for a new line",
    "chat.thinking": "Typing…",
    "chat.noModelConfigured":
      "No usable model yet: open Settings, fill in Endpoint + API Key, click Check, pick a model, save, then send again.",
    "chat.requestFailed": "Request failed",
    "chat.timeout": "Request timed out. Check that the endpoint is reachable.",
    "chat.emptyReply": "(The model returned an empty reply)",
    "chat.aborted": "(stopped)",
    "chat.taskFinished": "Task finished",
    "chat.backend": "Local middleware",
    "chat.online": "Online",
    "chat.offline": "Offline",
    "chat.control": "Control PC",
    "chat.think": "Deep think",
    "chat.backendOffline": "Local middleware is offline: start 127.0.0.1:8737 first, then enable Control PC.",
    "chat.thinkingLabel": "Thinking",
    "chat.thinkingLive": "thinking…",
    "chat.toolRunning": "Running…",
    "chat.toolPending": "Waiting for result…",
    "chat.toolAborted": "(stopped)",
    "chat.toolCommand": "Command",
    "chat.toolResult": "Result",
    "chat.tokens": "Output tokens",
    "chat.tokenAuto": "Auto",
    "chat.tokenCustom": "Custom",
    "chat.tokenAutoHint": "Adapts to task length and type (2048–8192); doubles the budget and retries if the reply is cut off.",
    "chat.tokenCustomHint": "Fixed cap; edits are saved to the active model profile.",
    "chat.screenTokens": "Screen tokens",
    "chat.screenAutoHint": "Scales with window complexity: ~300 for simple windows, 600 for normal, 1800–3000 for web pages, up to 4000; the model can ask for more.",
    "chat.screenCustomHint": "Hard cap: only controls within budget are sent; the rest are only counted.",
    "agent.system":
      "You are No Wind, running on the user's Windows machine. You read the screen, click controls and type text through a local middleware.\n" +
      "[Loop] read screen -> pick a control -> act -> confirm -> answer.\n" +
      "1) Always call read_screen first (use deep=true for controls inside a web page) to get cid list;\n" +
      "1.5) If the target app is not on screen: launch_app first (calc/notepad/mspaint/explorer/cmd/powershell/taskmgr/edge), then read_screen. For web tasks use open_url first. If the target window is not foreground: list_windows for its hwnd, focus_window(hwnd), then read_screen;\n" +
      "1.6) For apps outside the allow list (WeChat, Office, Chrome, etc.): press_keys(win) to open the Start menu, type_text(focus=true, app name), then press_keys(enter) to launch;\n" +
      "2) Click with click_control(cid); type with type_text(text, cid); cid must come from the latest read_screen;\n" +
      "2.5) When an address bar, search box or chat input has no cid: use press_keys (ctrl+l / ctrl+a / ctrl+v / enter / tab) together with type_text(focus=true) to type into the focus. For long lists use scroll, then read_screen again;\n" +
      "2.6) If read_screen says \"N more not listed\" and you need one of them, call read_screen(limit=N) to fetch the full list (works in auto mode; custom mode is capped by the user);\n" +
      "2.7) If the Document in read_screen is the assistant app itself, you are reading your own page: use list_windows + focus_window to switch to the browser window, then read again. open_url opens the target in a new window;\n" +
      "2.8) When you need the body text of a web page or article and read_screen only shows navigation/buttons, use read_text (UIA reads the text directly; no select-all, no clipboard) to fetch the body, then summarize or extract. Never guess content from control names alone;\n" +
      "2.9) For news/articles/blogs, prefer read_url (Edge reader mode read:<url>, returns the full text directly); for videos and interactive/search pages use open_url + read_text;\n" +
      "2.10) Action tools (click/type/press/launch/open) attach a latest-screen digest to their result. Use its cid directly instead of calling read_screen after every action; only read again with read_screen(limit=N) when the digest is not enough;\n" +
      "2.11) When several consecutive actions are certain, emit multiple tool_calls in one reply to cut round trips;\n" +
      "2.12) If a deep read still cannot find the target (especially small hover-only buttons), call read_screen(deep=true, fallback=true): it additionally uses Raw View, hover FromPoint and MSAA; each line is tagged with its source;\n" +
      "3) Judge success from verified/reason in every tool result; on failure try a different approach (up to 2 retries) instead of giving up;\n" +
      "4) When the task is truly done and verified by tool results, you MUST call finish_task(summary, success=true) to end. If it truly cannot be completed, call finish_task(summary, success=false) and state where it got stuck. Never stop with text alone.\n" +
      "5) Start with deep=false for desktop windows; if the control list is clearly incomplete (e.g. Calculator only shows the title bar and memory keys), immediately read again with deep=true. Use deep=true for controls inside browser pages as well;\n" +
      "6) Before every tool call, say one short sentence about what you are doing (e.g. \"I'll open Notepad first.\"), then call the tool;\n" +
      "[Hard rules]\n" +
      "- Never invent controls, coordinates or window contents;\n" +
      "- Never paste raw tool output or JSON back to the user;\n" +
      "- Never shut down, restart, delete files, format disks or change system settings; refuse such requests;\n" +
      "- Do not click the same cid twice; do not read the same screen twice in a row.\n" +
      "[Answer format] English, max 3 sentences: what you did -> the result -> optional next step. Pure chat or Q&A needs no tools.",
    "chat.model": "Model",
    "chat.noModel": "No model configured",
    "chat.heroTitle": "What should I do on this computer?",
    "chat.heroSubtitle":
      "This is the UI skeleton: chat, theme and model profiles work; middleware comes next.",
    "chat.s1": "Open the browser, search “test” and confirm the result",
    "chat.s2": "Read me the buttons in the active window",
    "chat.s3": "Type this text into Notepad",
    "chat.emptyTitle": "No messages yet",

    "settings.title": "Settings",
    "settings.subtitle":
      "Model endpoints, sampling params and appearance. Saved locally and applied instantly.",
    "settings.models": "Model profiles",
    "settings.addModel": "Add model",
    "settings.edit": "Edit profile",
    "settings.name": "Name",
    "settings.namePlaceholder": "e.g. Local Qwen",
    "settings.endpoint": "Endpoint",
    "settings.endpointPlaceholder": "https://api.example.com/v1",
    "settings.apiKey": "API Key",
    "settings.apiKeyPlaceholder": "sk-…",
    "settings.show": "Show",
    "settings.hide": "Hide",
    "settings.check": "Check",
    "settings.checking": "Checking…",
    "settings.modelsCount": "Available models",
    "settings.selectModel": "Select a model",
    "settings.checkFirst": "Click “Check” to load models",
    "settings.temperature": "Temperature",
    "settings.maxTokens": "Max Tokens",
    "settings.save": "Save",
    "settings.saved": "Saved",
    "settings.delete": "Delete",
    "settings.appearance": "Appearance",
    "settings.appearanceHint": "Changes apply instantly and are remembered.",
    "settings.invalid": "Name is required and endpoint must start with http(s)://",
    "settings.checkOk": "Fetched {n} models",
    "settings.checkFail": "Endpoint unreachable (check Endpoint / API key) — demo models shown",
    "settings.demoBadge": "demo",
    "settings.emptyModels": "No profiles yet — add one.",

    "toolbook.title": "Tool book",
    "toolbook.subtitle":
      "Every tool the model can call, with parameters and result formats. All calls run through the local middleware and failures carry an actionable reason.",
    "toolbook.count": "{n} tools",
    "toolbook.expandAll": "Expand all",
    "toolbook.collapseAll": "Collapse all",
    "toolbook.flowTitle": "The fixed order of one action",
    "toolbook.flowHint":
      "The model follows this order, narrating between steps; every call shows up as a card in the chat.",
    "toolbook.listTitle": "Tools",
    "toolbook.listHint": "Expand for parameters, examples and caveats",
    "toolbook.params": "Parameters",
    "toolbook.returns": "Returns",
    "toolbook.example": "Example",
    "toolbook.notes": "Notes",
    "toolbook.none": "No parameters — call it directly.",
    "toolbook.required": "required",
    "toolbook.optional": "optional",
    "toolbook.recordTitle": "Call records",
    "toolbook.recordDesc":
      "Each tool call becomes a card in the chat: green dot = success, red dot = failure, spinner = running. Click a card to see the exact command and full result.",
    "toolbook.safetyTitle": "Safety limits",
    "toolbook.safety1": "Destructive actions (shutdown, restart, deleting files, formatting) are refused.",
    "toolbook.safety2": "Only allow-listed apps: Calculator / Notepad / Paint / Explorer / Command Prompt.",
    "toolbook.safety3": "No guessing coordinates without a screen read; clicks and typing without a cid are rejected.",
    "toolbook.endpoint": "Middleware at 127.0.0.1:8737 · only available while the app is running",
    "toolbook.expTitle": "Experience library",
    "toolbook.expCount": "{n} entries",
    "toolbook.expClear": "Clear",
    "toolbook.expHint":
      "Every tool failure triggers a reflection; when a different approach succeeds, the lesson is recorded here and injected into similar future tasks.",
    "toolbook.expSearch": "Search task, tool or failure…",
    "toolbook.expFailure": "Failure",
    "toolbook.expFix": "Fix",
    "toolbook.expEmpty": "No lessons yet. They are recorded automatically after a failure is fixed by a different approach.",
    "toolbook.expNoMatch": "No matching lessons.",

    "common.delete": "Delete",
    "common.cancel": "Cancel",
  },
};

export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  let text = messages[lang][key] ?? key;
  if (vars) {
    for (const [k, v] of Object.entries(vars)) text = text.replace(`{${k}}`, String(v));
  }
  return text;
}
