# Dalal AI: Detailed Design Document & Interface Control Document (ICD)

## 1. Introduction

### 1.1 Purpose
The purpose of this document is to provide a comprehensive, deeply technical breakdown of the **Dalal AI** tool. It serves as both a **Detailed Design Document (DDD)** and an **Interface Control Document (ICD)**. This document is intended for future developers and AI assistants to quickly and thoroughly understand the architecture, internal structures, data flows, and configuration interfaces of the codebase without needing to read every line of code.

### 1.2 Scope
This document covers the entire Dalal AI system, including the Playwright browser automation layer, the context management and compression algorithms (both mathematical and manual flag-based), the routing orchestrator, and the Streamlit/CLI frontends. It reflects the updated architecture incorporating strict type hints, dependency modernization, and robust thread-safety mechanisms.

---

## 2. System Architecture Overview

Dalal AI operates as a local bridge between a user interface (Web/CLI) and a real, locally installed web browser running in remote-debugging mode over CDP.

**High-Level Data Flow:**
1. **User Input:** The user types a message in `dalal_ai/ui/app.py` (Streamlit) or `main.py` (CLI).
2. **Orchestrator Routing:** `dalal_ai/core/orchestrator.py` intercepts the message. If the user is switching to a new AI model, it invokes the Context Management layer to compile a historical transcript.
3. **Context Generation:** `dalal_ai/core/flagged_context_manager.py` builds the transcript based on user-defined Green/Red flags. If no flags exist, it falls back to `dalal_ai/core/context_compressor.py`.
4. **Browser Execution:** The payload is handed to `dalal_ai/browser/browser_manager.py`, which executes DOM manipulations to type the message into the active browser tab and extract the response.
5. **State Persistence:** The response is returned to the Orchestrator, logged via `dalal_ai/core/context_manager.py` into `chat_history.json`, and rendered back to the user.

---

## 3. Detailed Module Specifications

### 3.1 Browser Manager (`dalal_ai/browser/browser_manager.py`)
Handles all direct interaction with the DOM of target platforms (ChatGPT, Claude, Gemini, DeepSeek). It heavily leverages Playwright over a CDP connection.

**Key Structural Elements:**
- **`class _PlaywrightWorker` (Singleton Thread)**
  - **Purpose:** Playwright's synchronous API relies on greenlets bound to the thread that creates them. Because Streamlit spawns multiple threads for reruns, directly invoking Playwright from Streamlit causes fatal thread-safety crashes. This worker maintains a single, persistent background thread containing the event loop.
  - **Methods:**
    - `run(fn, *args, **kwargs)`: Submits a callable to the queue and blocks via `concurrent.futures` until the Playwright thread completes it.

- **`class BrowserManager`**
  - **Purpose:** The public API for browser automation. All public methods delegate to `_PlaywrightWorker.run()`.
  - **Key Methods:**
    - `connect()`: Checks if the CDP port is open. If not, reads `config.yaml` to auto-launch the browser binary (`msedge.exe` or `brave.exe`) with `--remote-debugging-port` and a separate `--user-data-dir`.
    - `_discover_platform_pages()`: Iterates through open tabs and matches domains. If a platform tab is missing, it opens a new one.
    - `_send_organic_prompt_impl(platform, text)`: Brings the tab to focus. Uses JS/DOM events to clear the input box. For text > 500 chars or text containing newlines (`\n`), it uses clipboard pasting (`pyperclip`); otherwise, it simulates keystrokes (`typing_delay_ms`). Dispatches raw `input` events to bypass React state guards.
    - `_extract_stable_response_impl(platform)`: Implements a dynamic mutation observer. It samples the DOM using the extracted JS script. If the extracted text remains unchanged for `stability_samples` consecutive checks over `stability_wait_s`, the response is deemed complete.

- **`response_script.js` (JavaScript Resource)**
  - Loaded at runtime by the `BrowserManager`, this script is injected directly into the page to recursively walk the DOM of the response element. It recovers Markdown semantics (`##`, `**`, `>`) and extracts embedded LaTeX (from KaTeX/MathJax `annotation` tags or `alttext`) before Playwright reads the text.

### 3.2 Context Manager (`dalal_ai/core/context_manager.py`)
The local database tracking conversation turns.

- **`class ContextManager`**
  - **State Variables:** 
    - `messages: list[dict[str, Any]]`: The active memory block holding all messages.
    - `last_used_model: Optional[str]`: Tracks the previous turn to detect model switches.
  - **Key Methods:**
    - `add_message(role, content, model, flag=None)`: Appends a message containing the new `"flag"` field and triggers `_auto_save()`. When loading existing `chat_history.json`, older messages missing the flag field are automatically patched with `"flag": None`.
    - `build_context_transcript(max_chars, messages)`: Transforms a list of raw message dictionaries into a continuous Markdown transcript block, injecting chronological markers. (Note: Artificial prompt trimming logic was intentionally removed to ensure mathematical context is fully preserved, bypassing max_chars).
    - `update_flag(index, new_flag)`: Modifies the flag state ("green", "red", or None) of a specific message. Enforces flag exclusivity and calls `_auto_save()`.
    - `get_stats()`: Returns session metrics, including total messages, character counts, models used, user messages, and assistant messages.

### 3.3 Flagged Context Manager (`dalal_ai/core/flagged_context_manager.py`)
Provides deterministic, user-controlled context filtering when switching models.

- **`class FlaggedContextManager`**
  - **Constructor:** Accepts a `max_tokens` parameter (default 4000) used exclusively when falling back to the `ContextCompressor` algorithm.
  - **State Variables:**
    - `session_delivered: dict[str, set[int]]`: Maps a model name to a set of message indices that have already been injected into its tab. Prevents redundant context loops.
  - **Key Methods:**
    - `build_context(chat_history, target_model, selected_red_ids)`:
      1. If `chat_history` has zero flags, it falls back to `ContextCompressor.build_context()`.
      2. If `target_model` is interacting for the first time: Gathers all `"green"` flagged messages, marks them delivered, and returns only those historical messages (in chronological order).
      3. If `target_model` is known: Discards any green messages (already delivered). Gathers messages with `"red"` flags whose indices are explicitly listed in `selected_red_ids` AND are not yet in the delivered set. Marks them delivered, and returns only those historical messages.
    - `reset_model(model_name)`: Removes the entry from `session_delivered`, allowing re-injection of green context next time.

### 3.4 Context Compressor (`dalal_ai/core/context_compressor.py`)
The legacy algorithmic fallback for semantic token-budget compression, used if the user sets zero manual flags.

- **`class ContextCompressor`**
  - **Key Methods:**
    - `build_context(messages, query)`: 
      - Always includes the `recent_count` latest messages.
      - Chunks the older history.
      - Calculates **TextRank** using a `TfidfVectorizer` (via `scikit-learn`) and cosine similarity (via `numpy`) to find structurally central conversation pieces.
      - Calculates **BM25** to rank chunks against the user's immediate `query`.
      - Combines scores `(alpha * TextRank) + ((1 - alpha) * BM25)` and greedily selects the top chunks that fit within `max_tokens`.

### 3.5 Routing Orchestrator (`dalal_ai/core/orchestrator.py`)
The bridge between the UI and the backend systems.

- **`class Orchestrator`**
  - **Key Methods:**
    - `send_message(platform, user_message, flagged_mgr, selected_red_ids)`:
      - Determines if `platform == context.last_used_model`.
      - **If False (Switch):** Calls `flagged_mgr.build_context()` to get historical messages, generates a context string using `context.build_context_transcript()`, and prepends this historical transcript to the fresh `user_message`.
      - Passes the payload to `browser_manager.send_organic_prompt()`.
      - Calls `browser_manager.extract_stable_response()`.
      - Catches exceptions (`BrowserActionRequired`, `ResponseCaptureTimeout`) and bubbles them to the UI for manual intervention.

### 3.6 Swarm Orchestrator (`dalal_ai/core/swarm_orchestrator.py`)
Handles the Parallel JSON Plan Engine logic.

- **`class SwarmOrchestrator`**
  - **Key Methods:**
    - `execute_swarm_task(prompt, moderator, workers, flagged_mgr, selected_red_ids)`:
      - Automatically isolates index 0 for the Moderator AI (e.g., `deepseek:0`).
      - Compiles green-flagged context via `flagged_mgr` and prepends it to both the Moderator's system prompt and all sub-task worker prompts.
      - Receives the plan from the Moderator and delegates parallel Playwright requests to `worker:n` indexes.
      - Uses `_extract_json()` which features `codecs.decode(..., 'unicode_escape')` regex fallback parsing to gracefully recover AI responses that contain unescaped newline literals in JSON string blocks.

### 3.7 Web UI (`dalal_ai/ui/app.py`)
The primary Streamlit frontend.

- **Architecture:** 
  - Initializes state in `init_session_state`.
  - Sidebar manages configuration, connection, and flag analytics. It displays Green/Red message and token counts. It also shows a "Context Delivery Status" tracking which message indices have been sent to which model.
  - The **Pending Switch Modal** intercepts dropdown model changes to prompt for Red flag selection before updating `active_model`. It lists undelivered red-flagged messages for the user to check before confirming the switch.
  - Chat interface renders historical messages, embedding inline 🟩/🟥 flag toggle buttons via Streamlit columns.
  - Integrates a **Manual Paste Fallback** for when `BrowserActionRequired` or timeouts occur, allowing users to paste responses directly.
  - Clears `selected_red_ids` after every successful send to prevent accidental re-use.

### 3.7 Python Compatibility & Type Hinting
The codebase is designed for backward compatibility with **Python 3.8+** while adopting modern Python 3.10+ type syntax for robust static typing.
- It leverages `from __future__ import annotations` across core modules to defer evaluation of PEP 585/604 type hints (e.g., `list[dict[str, Any]]`) so they do not crash Python 3.8 at runtime.

---

## 4. Interface Control Document (ICD)

### 4.1 Configuration Schema (`config.yaml`)
The single source of truth for execution parameters.

| YAML Key Path | Type | Description |
|---|---|---|
| `browser.use` | `string` | The target browser engine: `"edge"` or `"brave"`. |
| `browser.remote_debugging_port` | `integer` | Default `9222`. The CDP port to attach to. |
| `browser.auto_launch` | `boolean` | If true, the system invokes the executable via subprocess on startup. |
| `browser.paths.*` | `list` | Ordered arrays of absolute paths pointing to browser executables for Windows/Mac. |
| `timing.typing_delay_ms` | `integer` | Delay between simulated keystrokes. |
| `timing.stability_wait_s` | `float` | The time gap to pause before re-sampling the response DOM. |
| `timing.max_response_wait_s` | `integer` | Hard timeout (e.g., 180s). If exceeded, raises `ResponseCaptureTimeout`. |
| `platforms.<name>.url` | `string` | The web UI target URL (e.g., `https://chatgpt.com/`). |
| `platforms.<name>.input_selector` | `string` | Comma-separated list of CSS locators for the prompt box. |
| `platforms.<name>.stop_button` | `string` | CSS locator for the "Stop Generating" button. Used to detect generation state. |
| `platforms.<name>.send_button` | `string` | CSS locator to submit the prompt. |
| `platforms.<name>.response_selector` | `string` | CSS locator pointing to the parent node of an assistant message. |

### 4.2 Data Persistence Schema (`chat_history.json`)
Local storage for the conversation. Loaded entirely into memory by `ContextManager`.

```json
{
  "last_used_model": "chatgpt",
  "messages": [
    {
      "role": "user",
      "content": "Can you write a python script?",
      "model": "chatgpt",
      "timestamp": "2024-05-15T14:30:00.000Z",
      "flag": "green"
    }
  ]
}
```

### 4.3 Internal Inter-Process Interfaces
- **UI ↔ Orchestrator Exceptions (defined in `utils.exceptions`):**
  - `BrowserActionRequired`: Raised when a selector fails or an explicit block (like Cloudflare CAPTCHA) occurs. Contains a `detail` string. The UI catches this and renders a manual paste text area.
  - `ResponseCaptureTimeout`: Raised when `max_response_wait_s` is exceeded. Also triggers a manual paste flow in the UI.

---

## 5. Execution Flow Examples

### 5.1 The Model Switch Flow
1. User clicks the Target Model dropdown in Streamlit sidebar, changing from `chatgpt` to `claude`.
2. Streamlit reruns. `dalal_ai/ui/app.py` detects `selected != st.session_state.active_model`.
3. UI locks the main chat input and renders the **Pending Switch Modal** in the sidebar.
4. The modal queries `FlaggedContextManager` to find all `"red"` messages NOT in `session_delivered["claude"]`.
5. User checks checkboxes for specific red messages and clicks "Confirm".
6. `st.session_state.active_model` updates. `selected_red_ids` is cached. Streamlit reruns.
7. User types a prompt.
8. `orchestrator.send_message("claude", prompt, flagged_mgr, selected_red_ids)` is invoked.
9. `flagged_mgr.build_context()` returns the appropriate history. 
10. `browser_manager.send_organic_prompt("claude", transcript + prompt)` executes.
11. `selected_red_ids` cache is cleared.

### 5.2 The Playwright Delegation Flow
1. `browser_manager.extract_stable_response()` is called on the main Streamlit thread.
2. It pushes the `_extract_stable_response_impl` function pointer to the `_PlaywrightWorker` queue via `concurrent.futures`.
3. The Streamlit thread blocks on `.result(timeout)`.
4. The background `_PlaywrightWorker` thread pops the function, executes the Playwright DOM logic on its dedicated asyncio event loop, and sets the future result.
5. The Streamlit thread resumes and returns the Markdown string.

---

## 6. Build and Packaging Process

The tool can be compiled into a standalone, portable application using PyInstaller, orchestrated by `build.py`.

- **Cross-Platform Compilation:** `DalalAI.spec` defines the application bundle. It disables the console window (on Windows/macOS) and explicitly bundles `config.yaml`, the `dalal_ai` source folder, and Streamlit's metadata. 
- **macOS / Linux:** When `build.py` runs on these systems, it invokes PyInstaller to create a native `.app` bundle or ELF binary in `dist/DalalAI`. It then uses `shutil.make_archive` to package this directory into a `.zip` (macOS) or `.tar.gz` (Linux) in the `release/` directory.
- **Windows:** The script first attempts to invoke Inno Setup (`ISCC.exe`) via `installer/setup.iss` to create a professional `DalalAI_Setup.exe` installer. If Inno Setup is missing or fails, it gracefully falls back to generating a `.zip` archive.
- **Artifacts:** A generated `README.txt`, `CHANGELOG`, and `LICENSE` are automatically copied alongside the final archives in the `release/` directory.
