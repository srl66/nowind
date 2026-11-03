/**
 * 工具书数据：与 services/agent.ts 里的 TOOLS 一一对应。
 * 页面只负责排版，文案全部留在这里，方便以后加工具时同步维护。
 */

export interface Bi {
  zh: string;
  en: string;
}

export interface ToolDocParam {
  name: string;
  type: string;
  required: boolean;
  desc: Bi;
}

export interface ToolDoc {
  name: string;
  label: Bi;
  summary: Bi;
  params: ToolDocParam[];
  returns: Bi;
  example: Record<string, unknown>;
  result: string;
  notes: Bi[];
}

export interface FlowStep {
  icon: string;
  title: Bi;
  desc: Bi;
}

const bi = (zh: string, en: string): Bi => ({ zh, en });

export const toolFlow: FlowStep[] = [
  {
    icon: "panel",
    title: bi("1 · 读屏", "1 · Read"),
    desc: bi("read_screen 拿到 cid 清单", "read_screen returns the cid list"),
  },
  {
    icon: "terminal",
    title: bi("2 · 动作", "2 · Act"),
    desc: bi("点击 / 输入 / 启动 / 切窗", "click, type, launch, focus"),
  },
  {
    icon: "check",
    title: bi("3 · 确认", "3 · Verify"),
    desc: bi("看返回的 verified / reason", "check verified / reason"),
  },
  {
    icon: "message",
    title: bi("4 · 汇报", "4 · Report"),
    desc: bi("用自然语言给出结论", "answer in natural language"),
  },
];

export const toolDocs: ToolDoc[] = [
  {
    name: "read_screen",
    label: bi("读取屏幕", "Read screen"),
    summary: bi(
      "读取当前前台窗口里所有可交互控件，返回每个控件的 cid、类型、名称和屏幕坐标。它是所有点击和输入的前置步骤。",
      "Reads every interactable control in the foreground window: cid, type, name and screen rect. Required before any click or typing."
    ),
    params: [
      {
        name: "deep",
        type: "boolean",
        required: false,
        desc: bi(
          "浏览器 / Electron 页面里的控件需要 true；普通桌面窗口 false 即可。",
          "Use true for controls inside browser / Electron pages; false is enough for regular desktop windows."
        ),
      },
      {
        name: "limit",
        type: "number",
        required: false,
        desc: bi(
          "需要更多控件时传总条数；自动模式下可超过默认预算（约 1200 token 上限）。",
          "Pass the total count when you need more controls; auto mode may exceed the default budget (up to ~1200 tokens)."
        ),
      },
      {
        name: "fallback",
        type: "boolean",
        required: false,
        desc: bi(
          "deep 读屏仍找不到目标控件（尤其悬停才出现的小按钮）时设 true：额外用 Raw View + 悬停 FromPoint + MSAA 兜底，会短暂移动鼠标。",
          "Set true when deep reading still misses the target (especially hover-only buttons): adds Raw View + hover FromPoint + MSAA; it briefly moves the mouse."
        ),
      },
    ],
    returns: bi(
      "首行 `ok total=N shown=… tokens≈… tier=…`，之后每行 `cid 类型 名称 @x1,y1,x2,y2`；被禁用的控件会标注「禁用」。超出预算时会提示还有多少条未列出。",
      "First line `ok total=N shown=… tokens≈… tier=…`, then one line per control: `cid type name @x1,y1,x2,y2`; disabled ones are marked. When over budget, the remaining count is reported."
    ),
    example: { deep: false },
    result:
      "ok total=18 shown=12 tokens≈212 tier=uia\n7 Button 确定 @1042,612,1112,646\n9 Edit 搜索框 @320,88,980,116",
    notes: [
      bi("任何点击 / 输入前都必须先读一次。", "Always read once before any click or typing."),
      bi(
        "读屏数据按「屏幕 Token」预算截断：自动按控件量给 300/600/1200，可用 limit 扩到约 1200；自定义模式固定上限。",
        "Screen data is capped by the Screen tokens budget: auto uses 300/600/1200 based on control count and limit can raise it to ~1200; custom mode is a hard cap."
      ),
      bi(
        "同一屏不要连续读两次，相同结果会走缓存并提示「与上次相同」。",
        "Do not read the same screen twice in a row; identical reads hit the cache."
      ),
      bi(
        "切窗口或启动程序后 cid 会失效，必须重新读。",
        "cids become invalid after focusing another window or launching an app."
      ),
    ],
  },
  {
    name: "list_windows",
    label: bi("列出窗口", "List windows"),
    summary: bi(
      "列出桌面上可见的窗口，返回 hwnd、标题和进程名。目标窗口不是当前前台窗口时，先用它拿到 hwnd。",
      "Lists visible desktop windows with hwnd, title and process. Use it to find the hwnd when the target is not in the foreground."
    ),
    params: [],
    returns: bi(
      "首行 `ok total=N`，之后每行 `hwnd 标题 [进程]`，最多列 12 个。",
      "First line `ok total=N`, then `hwnd title [exe]`, up to 12 items."
    ),
    example: {},
    result: "ok total=6\n131266 计算器 [CalculatorApp.exe]\n65832 记事本 [notepad.exe]",
    notes: [
      bi(
        "hwnd 不是固定编号，每次都要重新取。",
        "hwnd values are not stable; always fetch them again."
      ),
      bi("拿到 hwnd 后接 focus_window，再读屏。", "After getting hwnd, call focus_window, then read_screen."),
    ],
  },
  {
    name: "focus_window",
    label: bi("切换前台窗口", "Focus window"),
    summary: bi(
      "把指定窗口切到前台，让后续读屏和操作落在正确的窗口上。",
      "Brings the given window to the foreground so later reads and actions hit the right window."
    ),
    params: [
      {
        name: "hwnd",
        type: "number",
        required: true,
        desc: bi("list_windows 返回的窗口句柄。", "Window handle returned by list_windows."),
      },
    ],
    returns: bi(
      "成功 `ok 已切到 hwnd=…`；失败会给出当前前台 hwnd，便于排查。",
      "`ok` with the new foreground hwnd on success; on failure the current foreground hwnd is returned."
    ),
    example: { hwnd: 131266 },
    result: "ok 已切到 hwnd=131266",
    notes: [
      bi("切换后必须重新 read_screen。", "Always read_screen again after focusing."),
    ],
  },
  {
    name: "launch_app",
    label: bi("启动程序", "Launch app"),
    summary: bi(
      "启动一个白名单内的程序并等待它出现在屏幕上。目标程序不在屏幕上时，用它打开后再读屏；要打开网址用 open_url。",
      "Launches an allow-listed app and waits for it to appear. Use it when the target app is not on screen; use open_url for web pages."
    ),
    params: [
      {
        name: "app",
        type: "string",
        required: true,
        desc: bi(
          "白名单：calc / notepad / mspaint / explorer / cmd / powershell / taskmgr / control / edge(browser) / snippingtool。",
          "Allow list: calc / notepad / mspaint / explorer / cmd / powershell / taskmgr / control / edge(browser) / snippingtool."
        ),
      },
      {
        name: "wait_ms",
        type: "number",
        required: false,
        desc: bi("启动后等待毫秒数，默认 1200。", "Milliseconds to wait after launch; default 1200."),
      },
    ],
    returns: bi(
      "成功 `ok 已启动 xxx（前台 hwnd=…）`；失败返回具体原因。",
      "`ok` with the foreground hwnd on success; a concrete reason on failure."
    ),
    example: { app: "calc" },
    result: "ok 已启动 calc（前台 hwnd=131266）",
    notes: [
      bi(
        "只允许白名单内的程序，其它程序会被拒绝。",
        "Only allow-listed apps are accepted; others are rejected."
      ),
      bi("启动后直接 read_screen，再决定点哪里。", "Call read_screen right after launch."),
    ],
  },
  {
    name: "click_control",
    label: bi("点击控件", "Click control"),
    summary: bi(
      "点击读屏结果里的某个控件。必须使用最近一次 read_screen 返回的 cid，不能自己编。",
      "Clicks a control from the latest read_screen result. The cid must come from that result; never invent one."
    ),
    params: [
      {
        name: "cid",
        type: "number",
        required: true,
        desc: bi("read_screen 返回的控件编号。", "Control id returned by read_screen."),
      },
    ],
    returns: bi(
      "成功 `ok 已点击 cid=…（控件名）`；失败会列出当前可用 cid。",
      "`ok` with the control name on success; on failure the available cids are listed."
    ),
    example: { cid: 7 },
    result: "ok 已点击 cid=7（确定）",
    notes: [
      bi("同一个 cid 不要重复点击。", "Do not click the same cid twice."),
      bi("没有读屏就点击会直接被拒绝。", "Clicking without a prior read is rejected."),
    ],
  },
  {
    name: "type_text",
    label: bi("输入文本", "Type text"),
    summary: bi(
      "输入文本。带 cid 会先点击对应控件再输入；带 focus=true 则直接输入到当前焦点，地址栏、搜索框、聊天框这类读不到 Edit 控件的地方用它。",
      "Types text. With a cid it clicks that control first; with focus=true it types into whatever is focused — use this for address bars, search boxes and chat inputs without an Edit control."
    ),
    params: [
      {
        name: "text",
        type: "string",
        required: true,
        desc: bi("要输入的文字。", "Text to type."),
      },
      {
        name: "cid",
        type: "number",
        required: false,
        desc: bi(
          "目标输入框的 cid，必须是 read_screen 里 type=Edit 的控件。",
          "Target cid; must be a control with type=Edit from read_screen."
        ),
      },
      {
        name: "enter",
        type: "boolean",
        required: false,
        desc: bi("输入后是否按回车提交。", "Press Enter after typing."),
      },
      {
        name: "focus",
        type: "boolean",
        required: false,
        desc: bi(
          "true = 不找 cid，直接输入到当前焦点。",
          "true = skip cid lookup and type into the current focus."
        ),
      },
    ],
    returns: bi(
      "成功 `ok 已输入「…」，verified=true（原因）`；未生效时 verified=false 并给出原因。",
      "`ok` plus verified=true on success; verified=false with a reason when the text did not stick."
    ),
    example: { text: "1+1", cid: 9, enter: true },
    result: "ok 已输入「1+1」，verified=true（控件文本已变化）",
    notes: [
      bi(
        "读不到输入框时用 focus=true，配合 press_keys(ctrl+l / ctrl+a) 定位。",
        "When no input control is visible, use focus=true together with press_keys (ctrl+l / ctrl+a)."
      ),
      bi(
        "verified=false 说明文字可能没落进去，应重新读屏确认，而不是重复输入。",
        "verified=false means the text may not have landed; re-read the screen instead of typing blindly again."
      ),
    ],
  },
  {
    name: "press_keys",
    label: bi("发送快捷键", "Press keys"),
    summary: bi(
      "向当前窗口发送组合键。操作地址栏、搜索框、提交表单、复制粘贴时，比逐个找控件更可靠。",
      "Sends a key combo to the current window. More reliable than hunting for controls when you need address bars, search boxes, submit, copy/paste."
    ),
    params: [
      {
        name: "keys",
        type: "string",
        required: true,
        desc: bi(
          "组合键：ctrl+l / ctrl+a / ctrl+c / ctrl+v / ctrl+z / enter / tab / esc / alt+tab / ctrl+shift+tab。",
          "Combo: ctrl+l / ctrl+a / ctrl+c / ctrl+v / ctrl+z / enter / tab / esc / alt+tab / ctrl+shift+tab."
        ),
      },
      {
        name: "hwnd",
        type: "number",
        required: false,
        desc: bi("可选：先把该窗口切到前台再发键。", "Optional: focus this window before sending."),
      },
    ],
    returns: bi(
      "成功 `ok 已发送按键 xxx`；未知键名会返回 `unknown-key:xxx`。",
      "`ok` on success; an unknown key name returns `unknown-key:xxx`."
    ),
    example: { keys: "ctrl+l" },
    result: "ok 已发送按键 ctrl+l",
    notes: [
      bi("先 focus_window 确保目标窗口在前台。", "Call focus_window first so the target is in front."),
      bi("普通文字仍然用 type_text，不要用按键拼字符串。", "Use type_text for actual text, not key combos."),
      bi(
        "启动白名单外的程序：press_keys(win) → type_text(focus=true, 程序名) → press_keys(enter)。",
        "To launch an app outside the allow list: press_keys(win) -> type_text(focus=true, name) -> press_keys(enter)."
      ),
    ],
  },
  {
    name: "scroll",
    label: bi("滚动滚轮", "Scroll"),
    summary: bi(
      "在窗口中心或指定坐标滚动滚轮，用于浏览长列表、网页和聊天记录。",
      "Scrolls the wheel at the window center or a given point — for long lists, web pages and chat history."
    ),
    params: [
      {
        name: "delta",
        type: "number",
        required: true,
        desc: bi("滚动格数：正数向上，负数向下，通常 ±3。", "Notches: positive = up, negative = down, usually ±3."),
      },
      {
        name: "x",
        type: "number",
        required: false,
        desc: bi("可选：滚动位置的屏幕 x 坐标。", "Optional screen x coordinate."),
      },
      {
        name: "y",
        type: "number",
        required: false,
        desc: bi("可选：滚动位置的屏幕 y 坐标。", "Optional screen y coordinate."),
      },
    ],
    returns: bi(
      "成功 `ok 已滚动 N 格`；失败会给出原因。",
      "`ok` with the notch count on success; a reason on failure."
    ),
    example: { delta: -3 },
    result: "ok 已滚动 -3 格",
    notes: [
      bi("滚动后要重新 read_screen，cid 会变化。", "Read the screen again afterwards; cids change."),
    ],
  },
  {
    name: "open_url",
    label: bi("打开链接", "Open URL"),
    summary: bi(
      "用浏览器的新窗口打开一个 http/https 链接，不会顶掉当前正在看的标签页。网页任务先用它打开页面。",
      "Opens an http/https URL in a new browser window without replacing the current tab. Use it before any web task."
    ),
    params: [
      {
        name: "url",
        type: "string",
        required: true,
        desc: bi("完整链接，必须以 http:// 或 https:// 开头。", "Full URL starting with http:// or https://."),
      },
    ],
    returns: bi(
      "成功 `ok 已用默认浏览器打开 …`；非 http(s) 链接会被拒绝。",
      "`ok` on success; non-http(s) URLs are rejected."
    ),
    example: { url: "https://www.bing.com" },
    result: "ok 已用默认浏览器打开 https://www.bing.com",
    notes: [
      bi(
        "打开后先 read_screen，确认 Document 名称是目标页面；如果读到「No Wind」，说明读到了应用自己。",
        "After opening, read_screen and confirm the Document is the target page; if it says the assistant app name, you are reading your own window."
      ),
    ],
  },
  {
    name: "read_url",
    label: bi("阅读模式", "Reader mode"),
    summary: bi(
      "用 Edge 阅读模式打开网页并直接返回正文（内部在地址栏输入 read:<url> 再复制全文）。适合新闻、文章、博客等正文页面。",
      "Opens a page in Edge reader mode and returns the body text (types read:<url> in the address bar, then copies it). Best for news, articles and blogs."
    ),
    params: [
      {
        name: "url",
        type: "string",
        required: true,
        desc: bi("完整链接，http:// 或 https:// 开头；也可直接传 read:<url>。", "Full http(s) URL, or read:<url>."),
      },
      {
        name: "max_chars",
        type: "number",
        required: false,
        desc: bi("最多返回多少字符，默认 4000。", "Maximum characters to return; default 4000."),
      },
    ],
    returns: bi(
      "成功 `ok 阅读模式已读取 N 字符：<正文>`；页面没有正文时返回 `empty-clipboard`。",
      "`ok` with the article text on success; `empty-clipboard` when no text is available."
    ),
    example: { url: "https://www.example.com/article" },
    result: "ok 阅读模式已读取 2840 字符：\n文章标题…",
    notes: [
      bi(
        "Edge 阅读模式只对正文型页面有效，视频、搜索列表、登录页用 open_url + read_text。",
        "Reader mode only works on article-like pages; use open_url + read_text for video, search and login pages."
      ),
      bi(
        "会新开浏览器窗口；正文用 UIA 读取，不占用剪贴板。",
        "It opens a new browser window; the body is read via UIA, so the clipboard is untouched."
      ),
    ],
  },
  {
    name: "read_text",
    label: bi("读取页面文字", "Read page text"),
    summary: bi(
      "用 UIA 直接读取当前前台窗口或网页的可见正文，不选全、不复制、不动剪贴板。读网页正文、文章、搜索结果时用它。",
      "Reads visible text from the current window/page via UIA. It does not select all, copy, or touch the clipboard."
    ),
    params: [
      {
        name: "max_chars",
        type: "number",
        required: false,
        desc: bi("最多返回多少字符，默认 3000。", "Maximum characters to return; default 3000."),
      },
      {
        name: "hwnd",
        type: "number",
        required: false,
        desc: bi("可选：先把该窗口切到前台。", "Optional: focus this window first."),
      },
    ],
    returns: bi(
      "成功 `ok 已读取 N 字符：<正文>`；页面没有 UIA 文本时返回 `no-text`。",
      "`ok` with the body text on success; `no-text` when the page exposes no UIA text."
    ),
    example: { max_chars: 3000 },
    result: "ok 已读取 1843 字符：\n哔哩哔哩…",
    notes: [
      bi(
        "读取的是 UIA 暴露的可见文本；Canvas、图片里的文字读不到。",
        "It reads text exposed through UIA; text inside canvas/images is not readable."
      ),
      bi(
        "只对前台窗口有效，先用 focus_window 切到目标页。",
        "Only works on the foreground window; focus it first."
      ),
    ],
  },
  {
    name: "finish_task",
    label: bi("结束任务", "Finish task"),
    summary: bi(
      "任务真正完成并经过工具结果确认后调用，它是唯一允许结束任务的方式；没做完不要调用，继续执行下一步。",
      "Call only after the task is truly done and verified by tool results. It is the only way to end a task; if not done, keep going."
    ),
    params: [
      {
        name: "summary",
        type: "string",
        required: true,
        desc: bi("一句话结果：做了什么、结果如何。", "One-line result: what was done and how it went."),
      },
      {
        name: "success",
        type: "boolean",
        required: true,
        desc: bi(
          "是否成功；失败时必须说明卡在哪一步。",
          "Whether it succeeded; on failure, state where it got stuck."
        ),
      },
    ],
    returns: bi(
      "本次任务立即结束，不再继续调用工具。",
      "Ends the task immediately; no further tool calls."
    ),
    example: { summary: "已在记事本输入 hello world 并复制到剪贴板", success: true },
    result: "（任务结束）",
    notes: [
      bi(
        "中途的“已完成”只是汇报，不算结束；没调用 finish_task 会自动被催继续。",
        "A mid-way \"done\" is just narration; without finish_task the agent is nudged to continue."
      ),
      bi(
        "失败时先换方法重试，确实无法完成再调用 success=false。",
        "On failure, retry with a different approach before calling success=false."
      ),
    ],
  },
];
