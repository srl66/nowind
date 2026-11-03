# No Wind

**A local AI computer operator for Windows. It reads the UI, clicks, types, reads web pages, and finishes multi-step tasks — with every action shown as an expandable, auditable tool card.**

No Wind runs entirely on your Windows machine. It does **not** take screenshots or upload your screen. A language model decides what to do; a local Python middleware performs the actions through UI Automation (UIA), Win32 messages, and keyboard/mouse input. API keys stay in your browser's local storage.

---

## Features

- **Real computer control** — open/switch apps, click controls, type text, send shortcuts, scroll.
- **Web reading** — `read_url` opens a page in Edge reader mode and extracts the body; `read_text` reads the current page through UIA TextPattern without select-all or clipboard access.
- **Multi-step tasks** — search, open results, read pages, summarize. A task only ends when the model calls `finish_task`, so it cannot silently stop halfway.
- **Auditable tool cards** — every call shows the tool name, arguments, success/failure state, and full result.
- **Collapsible reasoning** — deep-think plans and model reasoning are folded by default.
- **Reflection + experience library** — tool failures trigger a reflection; when a different approach succeeds, the lesson is stored and injected into similar future tasks.
- **UIA fallback** — normal reads use UIA; when a target is missing (or `fallback=true`), it additionally tries UIA Raw View, hover `FromPoint`, and MSAA/IAccessible.
- **Polished ending** — the app returns to chat and brings itself to the foreground when the task finishes. A stop button is always available.

## Demo

Verified examples:

> Open Bilibili, search for "王牌竞速" (Ace Racer), and read me the first 3 video titles.

> Use the calculator to compute 12*7+8.

> Read https://support.microsoft.com/zh-cn/edge/use-immersive-reader-in-microsoft-edge and summarize it in 3 points.

WeChat Moments' "..." like button is **not** a reliable demo yet: it is a hover-only/custom-drawn control and the fallback does not always hit it.

## How it works

```text
Vue 3 + Pinia + Vite (localhost:1420)
        │  /__llm local proxy (same-origin, avoids CORS)
        ▼
Python middleware (127.0.0.1:8737)
        │  UI Automation / PowerShell / Win32 messages
        ▼
Windows apps (browser, Notepad, Calculator, WeChat, ...)

Model: any OpenAI-compatible /chat/completions endpoint
```

Tools: `read_screen`, `list_windows`, `focus_window`, `launch_app`, `click_control`, `type_text`, `press_keys`, `scroll`, `open_url`, `read_url`, `read_text`, `finish_task`.

## Quick start

**Requirements**

- Windows 10 / 11
- Node.js 18+
- Python 3.10+ (the middleware uses the standard library only — no pip install needed)
- Microsoft Edge (for reader mode)

**Run**

```bash
npm install
npm start
```

`npm start` invokes `start-all.ps1`, which starts:

- the bundled middleware: `middleware/src/daemon.py` on `127.0.0.1:8737`
- the Vite frontend on `http://localhost:1420`

If port 8737 is already serving, the script reuses that instance. You can also run them separately:

```bash
python middleware/src/daemon.py --duration 86400 --quiet
npm run dev
```

**Configure a model**

Open `http://localhost:1420` → Settings → fill in:

- Endpoint: any OpenAI-compatible base URL, e.g. `https://api.openai.com/v1`
- API key
- Model name (it must support function calling / tool calls)

Click "Check" to verify, save, then enable **Control computer**.

The API key is only stored in the browser's `localStorage`. Requests go from the local Vite proxy directly to your endpoint; no key is included in this repository.

## Project layout

```text
no-wind/
├─ src/                     Vue frontend (components, store, agent, LLM, middleware client)
├─ src-tauri/               Optional Tauri desktop shell
├─ middleware/src/          Python middleware (UIA, action execution, reader mode, fallback probes)
├─ start-all.ps1            One-command launcher (frontend + middleware)
├─ start.cmd                Windows double-click launcher
├─ vite-plugin-llm-proxy.ts Local proxy (localhost only, http/https only)
└─ README.md
```

## Known limitations & help wanted

**The recognition layer is still basic — this is an early-stage project.**

- UIA exposes only what an app chooses to expose. Custom-drawn UIs, Canvas, DirectUI, CEF/Electron pages and games often expose little or nothing.
- Hover-only buttons (like WeChat Moments' "...") are hit-or-miss. Raw View, hover `FromPoint` and MSAA are best-effort fallbacks, not guarantees.
- No vision/OCR fallback yet, so text drawn as pixels cannot be read.
- Windows only. Success also depends on the chosen model supporting function calling.

If you are experienced with **UI Automation / MSAA / IAccessible2, DirectUI or CEF internals, computer vision/OCR, or agent orchestration**, contributions are very welcome. High-impact areas:

1. More reliable accessibility probing: stable control IDs, structure-changed events, popup/tool-window enumeration.
2. A vision/OCR fallback for apps that expose no accessibility tree.
3. Better hover/popup discovery and hit-testing for custom-drawn controls.
4. More reusable skills and cross-app workflows.
5. Packaging: Tauri installer, bundled Python runtime.

Open an issue or a pull request. When reporting a recognition failure, include the app name, the exact step, and the expanded tool card content (no screenshots of your screen are needed).

## Privacy & safety

- No screenshots, no screen upload. Screen data goes only to the model endpoint you configure.
- No hard-coded API keys; keys live in local browser storage.
- App launching uses an allowlist; destructive operations (shutdown, restart, deleting files, formatting) are refused.
- This is not a sandbox. Run it only on your own machine, and review tool cards before using it on sensitive apps.

## Roadmap

- Screenshot + multimodal vision fallback
- Tauri installer
- More reusable skills (search, forms, document workflows)

## License

Not specified yet. Choose a license (e.g. MIT or Apache-2.0) before publishing.
