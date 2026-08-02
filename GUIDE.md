# 🧠 Dalal AI — User & Setup Guide

A tool that connects to your browser and lets you chat with **ChatGPT**, **Claude**, **Gemini**, **DeepSeek**, **Kimi**, **HuggingChat**, and **Meta AI** from a single interface — preserving full conversation context when you switch between models.

**Two ways to use it:**
- **Web UI (recommended)** — `python -m dalal_ai` — rich Markdown, LaTeX equations, code blocks, deterministic flagging.
- **Terminal CLI** — `python main.py` — lightweight text interface.

**Supported browsers:** Microsoft Edge, Brave  
**Supported OS:** Windows 10/11, macOS, Linux  

---

## How It Works

```
┌───────────────────┐         ┌──────────────────────────────────┐
│  Browser UI       │ ──────▶ │  Edge / Brave (Debug Port 9222)  │
│  (dalal_ai)       │ ◀────── │  ┌─ ChatGPT tab                 │
│  or Terminal CLI  │         │  ├─ Claude tab                   │
│                   │         │  ├─ Gemini tab                  │
│                   │         │  ├─ DeepSeek tab                │
│  Pick model,      │         │  ├─ Kimi, HuggingChat, Meta AI  │
│  type message…    │         │  └─ (auto-opened if missing)    │
└───────────────────┘         └──────────────────────────────────┘
```

The tool connects to a **real browser** via CDP (Chrome DevTools Protocol). It types your messages into the actual web interfaces and reads responses. **No API keys needed**. You use the free-tier web versions of each AI.

When you **switch models**, it intelligently injects history using a **Flagged Context System**. You can flag messages as 🟩 Green (global, always sent to new models) or 🟥 Red (on-demand, selectively attached when switching). This ensures the new model has precise context without blowing up your token limits or redundantly sending the same history twice.

**Auto-Launch** — The tool can automatically start your browser in debug mode using an isolated automation profile so it doesn't mess with your everyday browsing.

---

## Prerequisites

- **Python 3.8+** installed (3.10+ recommended)
- **Microsoft Edge** or **Brave** browser installed
  - ⚠️ Firefox is NOT supported (different debugging protocol).
- Free accounts on the platforms you want to use:
  - [ChatGPT](https://chatgpt.com)
  - [Claude](https://claude.ai)
  - [Gemini](https://gemini.google.com)
  - [DeepSeek](https://chat.deepseek.com)

---

## Quick Start (3 Steps)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

*(Note: Ensure you have `scikit-learn` and `numpy` installed, which are provided in the latest `requirements.txt`).*

### 2. Choose Your Browser

Edit `config.yaml` and set your preferred browser:

```yaml
browser:
  use: "edge"       # ← change to "brave" if you prefer Brave
  auto_launch: true  # ← the tool will launch the browser for you
```

### 3. Run the Web UI (Recommended)

```bash
python -m dalal_ai
```

Or double-click `run.bat` on Windows.

Your browser opens at **http://localhost:8501** with a chat interface that renders:
- **LaTeX math** — inline `$E=mc^2$` and block `$$\int_0^1 x^2\,dx$$`
- **Markdown** — headings, lists, proper tables (with `|` separators), bold/italic
- **Code blocks** — syntax-highlighted fenced code
- **Model badges** — colour-coded labels per platform

The web UI will:
1. ✅ Auto-detect your browser executable.
2. 🚀 Launch it in debug mode (separate profile — your normal browser is unaffected).
3. 📡 Connect via CDP.
4. 📑 Open tabs for each AI platform.

**First time only:** Log into ChatGPT, Claude, Gemini, and DeepSeek in the browser tabs that open. After that, your sessions persist in the automation profile.

### Alternative: Terminal CLI

```bash
python main.py
```

Use slash commands (`/chatgpt`, `/claude`, etc.) to switch models. Responses appear as plain text in the terminal.

---

## Configuring the Browser

Just change one line in `config.yaml`:

```yaml
browser:
  use: "edge"    # Options: "edge" or "brave"
```

The tool auto-detects the executable path on Windows and macOS. If your browser is installed in a non-standard location, or you are running on Linux, update the paths in `config.yaml`:

```yaml
  paths:
    edge:
      windows:
        - "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
        - "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"
      mac:
        - "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
    brave:
      windows:
        - "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"
      mac:
        - "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
```

---

## Web UI Features

| Feature | Description |
|---------|-------------|
| Model picker | Sidebar dropdown to target ChatGPT, Claude, Gemini, or DeepSeek |
| Context Flags | Click 🟩 (Green) or 🟥 (Red) on any message to control cross-model context delivery |
| Switch Flow | A pending switch modal lets you attach specific red-flagged messages before changing models |
| Swarm Mode | A toggle to enable the Parallel JSON Engine, allowing a Moderator AI to delegate tasks to multiple Worker AIs simultaneously |
| Rich rendering | Markdown, LaTeX math, structured tables, and code blocks in chat bubbles |
| Live status | Activity log and real-time streaming updates while waiting for browser or Swarm responses |
| Manual paste | If automation times out, paste the response from the browser tab |
| Stats | Message count, character/token count, models used, and context delivery tracking |
| Clear history | Reset conversation with one click |

### 🐝 Swarm Mode (Parallel JSON Engine)

Dalal AI v2 features a **Swarm Mode** that allows you to orchestrate multiple AIs at once to solve complex problems.

1. Toggle **"🐝 Enable Swarm Mode"** in the sidebar.
2. Select your **Moderator AI** (e.g., ChatGPT).
3. Type a complex prompt. The Moderator AI will automatically create a structured JSON plan, break the task into pieces, and delegate it to other tabs (like Claude and Gemini).
4. The system extracts responses from all delegated workers **in parallel** (saving massive amounts of time), wraps them in XML, and feeds them back to the Moderator to synthesize a final answer.

### LaTeX Examples

The web UI renders math returned by models seamlessly extracted by the underlying `response_script.js`, for example:

- Inline: `$f(x) = x^2 + 2x + 1$`
- Block: `$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$`
- Matrices: `$$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$$`

---

## Commands Reference (CLI only)

| Command       | Action                          |
|---------------|---------------------------------|
| `/chatgpt`    | Switch to ChatGPT               |
| `/claude`     | Switch to Claude                |
| `/gemini`     | Switch to Gemini                |
| `/deepseek`   | Switch to DeepSeek              |
| `/status`     | Show session stats              |
| `/tabs`       | List open browser tabs          |
| `/history`    | Show recent conversation log    |
| `/clear`      | Reset all conversation history  |
| `/help`       | Show help                       |
| `/quit`       | Exit the orchestrator           |

---

## Building a Standalone Executable

You can compile Dalal AI into a standalone application that does not require Python to be installed. The build script automatically detects your operating system and creates the appropriate release package.

```bash
python build.py
```

- **Windows:** Creates a `.exe` Installer using Inno Setup (if `ISCC.exe` is installed) or falls back to a Zip archive in the `release/` folder.
- **macOS:** Creates a standalone Mac binary packaged into a `.zip` archive in the `release/` folder.
- **Linux:** Creates a standalone ELF binary packaged into a `.tar.gz` archive in the `release/` folder.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Could not auto-launch edge" | Close all Edge windows first, then retry. Or set `auto_launch: false` and launch manually. |
| "Could not find edge executable" | Update the path in `config.yaml` → `browser.paths.edge.*`. |
| "Cannot find input box" | The platform's UI changed. Update `input_selector` in `config.yaml`. Or type manually in the browser — the tool will wait. |
| Response times out | Increase `max_response_wait_s` in `config.yaml` (default: 180s). |
| CAPTCHA appears | Solve it manually in the browser. Since it's a real browser, you only solve it once. |
| Tool works on one platform but not another | You may not be logged in on that tab. Check the browser. |

---

## Pro Tips

1. **Auto-launch is on by default** — the tool finds and starts your browser automatically. Set `auto_launch: false` in config.yaml if you prefer to manage it yourself.
2. **Your normal browser is NOT affected** — the tool uses a separate `--user-data-dir` profile. Your bookmarks, passwords, and extensions are untouched.
3. **History persists** — saved to `chat_history.json`. Even if you close and reopen the tool, it remembers the conversation. Use `/clear` to start fresh.
4. **Watch the browser** — you can see the automation happen live. Useful for catching CAPTCHAs or login prompts.
5. **Switching browsers** — just change `use: "edge"` to `use: "brave"` in config.yaml. Close the current browser first.
