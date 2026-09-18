# Dalal AI: Complete LLM Reference Document

This document is an exhaustive, self-contained reference guide for Dalal AI. It is designed to enable a Large Language Model (LLM) to completely understand the tool's architecture, state mutations, context algorithms, and UI behavior without executing the code.

---

## 1. System Overview & Purpose

**Purpose:** Dalal AI bridges a unified user interface (Web/CLI) with live web sessions of popular AI models (ChatGPT, Claude, Gemini, DeepSeek, Kimi, HuggingChat, Meta AI). It allows users to chat with multiple AIs from one screen while intelligently injecting conversation history when switching models, thus bypassing the need for paid API keys by automating the free-tier web DOMs via the Chrome DevTools Protocol (CDP).

**High-Level Data Flow:**
1. **Input:** User submits a message via Streamlit (`app.py`) or CLI (`main.py`).
2. **Routing:** `Orchestrator` determines if the user is addressing a new model (context switch).
3. **Context Generation:** `FlaggedContextManager` gathers past messages based on manual Green/Red flags (falling back to `ContextCompressor` if no flags exist).
4. **Assembly:** The historical context is converted to a Markdown string and prepended to the user's fresh message.
5. **Execution:** `BrowserManager` delegates to the `_PlaywrightWorker` singleton thread, which connects to the browser via CDP, finds the correct tab, and injects the assembled prompt via keystrokes or clipboard pasting.
6. **Extraction:** A mutation observer (via `response_script.js`) monitors the DOM until the response stabilizes, recovering raw Markdown/LaTeX.
7. **Persistence & Display:** The extracted response is returned, appended to `ContextManager`'s in-memory list, saved to `chat_history.json`, and rendered in the UI.

---

## 2. Architecture & Component Inventory

### 2.1 `dalal_ai/browser/browser_manager.py`
**Responsibility:** Direct DOM interaction via Playwright CDP.
- **`class _PlaywrightWorker`:** A singleton `threading.Thread`. 
  - *Why it exists:* Playwright’s synchronous API relies on greenlets bound to the thread that creates them. Streamlit spawns multiple threads for reruns. Directly invoking Playwright from Streamlit causes fatal greenlet crashes. This worker maintains a single persistent background thread.
  - *Methods:* `run(fn, *args, **kwargs)` blocks the caller using `concurrent.futures.Future` until the Playwright thread completes the callable.
- **`class BrowserManager`:** The public automation API.
  - *State variables:* `self._browser_name` (cached from config), `self._browser` (Playwright instance), `self._context` (BrowserContext).
  - *Public Methods:*
    - `connect()`: Tries to connect to `http://localhost:<port>`. If refused and `auto_launch` is true, spawns a `subprocess.Popen` for Edge/Brave, then connects.
    - `list_open_tabs() -> list[dict]`: Returns active pages.
    - `send_organic_prompt(platform, text)`: Delegates to `_send_organic_prompt_impl`.
    - `extract_stable_response(platform, expect_new=True)`: Delegates to `_extract_stable_response_impl`. `expect_new=True` waits for a reply that differs from the snapshot taken just before the prompt was typed. `expect_new=False` re-reads the reply already on screen — used by the UI's retry button, which would otherwise wait out the full `max_response_wait_s` and fail, because a finished reply never looks "new".
    - `send_prompts_batch(prompts) -> dict[tab_id, error]`: returns the sends that failed.
    - `extract_responses_batch(tab_ids) -> list[str]`: returns a list **aligned with the input**, not a dict. A dict collapses two sub-tasks dispatched to the same tab and loses one reply.
    - `disconnect()`: Closes contexts and shuts down the worker. Registered with `atexit`.
  - *Exceptions raised:* `ConnectionError` (if browser fails to launch/connect).

### 2.2 `dalal_ai/browser/response_script.js`
**Responsibility:** A static JavaScript asset containing the `_RESPONSE_TO_MARKDOWN_SCRIPT` string. It recursively walks DOM nodes, parsing KaTeX/MathJax into standard `$math$` and `$$math$$` blocks, and extracting raw text with Markdown semantics (`##`, `**`, `>`). Crucially, it traverses `<table>`, `<tr>`, `<th>`, and `<td>` elements to reconstruct standard Markdown tables with `|` and `---` delimiters so they render properly in Streamlit.

### 2.3 `dalal_ai/core/context_manager.py`
**Responsibility:** Manages the chronological history array and disk persistence.
- **`class ContextManager`:**
  - *State variables:*
    - `messages: list[dict[str, Any]]`: The active memory block.
    - `last_used_model: Optional[str]`: Tracks the model of the *last appended message*.
  - *Public Methods:*
    - `add_message(role: str, content: str, model: str, flag: Optional[str] = None)`: Appends to `messages`, updates `last_used_model`, and calls `_auto_save()`.
    - `update_flag(index: int, new_flag: Optional[str])`: Mutates `messages[index]["flag"]` and calls `_auto_save()`.
    - `build_context_transcript(max_chars: Optional[int], messages: list[dict]) -> str`: Returns a continuous Markdown string of historical messages. `max_chars=None` (the default, and what `config.yaml`'s `context.max_transcript_chars` yields when unset) returns the full transcript. When a limit **is** set it is honoured by dropping the oldest messages first — previously the parameter was accepted and ignored, so an oversized transcript was pasted whole and truncated by the platform's own input limit, losing the newest and most relevant turns instead of the oldest.
    - `clear()`: Empties `messages` and saves.
    - `_auto_save()`: Writes to `chat_history.json.tmp`, fsyncs, then `os.replace`s it into place. The previous in-place write truncated the file first, so a crash mid-save destroyed the whole conversation.

### 2.4 `dalal_ai/core/flagged_context_manager.py`
**Responsibility:** Deterministic, stateful context filtering for model switches.
- **`class FlaggedContextManager`:**
  - *State variables:*
    - `session_delivered: dict[str, set[int]]`: Maps a `target_model` to a set of message indices that have *already been sent* to that model's browser tab.
  - *Public Methods:*
    - `build_context(chat_history, target_model, selected_red_ids, commit=True) -> list[dict]`: Executes the core routing logic (see Section 5). With `commit=True` it marks the selection delivered immediately; callers that can still fail pass `commit=False` and call `commit_delivery` once the prompt has actually reached the tab. Committing up front loses the context permanently whenever the send then fails.
    - `commit_delivery(chat_history, target_model, messages)`: Records delivery, matching by object identity so duplicate message text cannot mis-match.
    - `mark_contacted(model_name)`: Records a successful turn that carried no context.
    - `reset_model_context(model_name: str)`: Pops the model from `session_delivered` and from `contacted`.
  - *State variables (cont.):* `contacted: set[str]` — models this session has talked to. Kept separate from `session_delivered` because "first contact" and "has received messages" are different questions: a first switch carrying no green flags delivers nothing, and keying first-contact off an empty set would make every later turn re-send the whole green history.

### 2.5 `dalal_ai/core/context_compressor.py`
**Responsibility:** Fallback algorithmic compression when zero manual flags exist.
- **`class ContextCompressor`:**
  - *Methods:* `build_context(messages, query: str, max_tokens: int)`. Uses `scikit-learn` `TfidfVectorizer` and `numpy` dot products. Extracts `recent_count` messages unconditionally, chunks the rest, ranks by TextRank (centrality) and BM25 (relevance to `query`), and returns the top chunks fitting `max_tokens`.

### 2.6 `dalal_ai/core/orchestrator.py`
**Responsibility:** Bridging UI requests with context and single-agent browser injection.
- **`class Orchestrator`:**
  - *Methods:* `send_message(platform, user_message, flagged_mgr, selected_red_ids)`:
    1. Checks if `platform != context.last_used_model`.
    2. If switch: Calls `flagged_mgr.build_context()`, then `context.build_context_transcript()`, and prepends this to `user_message`.
    3. Calls `context.add_message("user", ...)`.
    4. Calls `browser_manager.send_organic_prompt()`.
    5. Calls `browser_manager.extract_stable_response()`.
    6. Calls `context.add_message("assistant", ...)`.
    7. Returns response string.

### 2.7 `dalal_ai/core/swarm_orchestrator.py`
**Responsibility:** Multi-agent parallel coordination.
- **`class SwarmOrchestrator`:**
  - *Methods:* `execute_swarm_task(prompt, moderator, workers, flagged_mgr, selected_red_ids, max_rounds=3)`:
    - A generator implementing a 4-Phase loop. Yields `{"type": "status"}` and `{"type": "complete"}` dicts for Streamlit rendering.
    - Explicitly reserves the `0` index for the moderator tab (e.g., `deepseek:0`) and maps worker arrays to `platform:1`, `platform:2`, etc. to prevent tab collisions.
    - Uses `flagged_mgr` to compile a full transcript of 🟩 green-flagged messages and prepends this to the System Prompts of BOTH the Moderator and the Workers.
    - Implements the **Two-Mode Protocol**:
      - **Parsing (`_parse_moderator_reply`):** returns `("delegate", obj)` **only** when a balanced JSON object has `status == "delegating"` and a non-empty `plan` list; everything else is `("final", markdown)`. Candidate objects come from a brace-balanced scan that skips braces inside string literals, so LaTeX and fenced code samples in a Mode 2 answer are no longer mistaken for a plan. Backslashes that are not legal JSON escapes are doubled before the second parse attempt, which recovers plans containing `\frac` or `C:\Users`.
      - **Mode 1 (Delegating):** sub-task `agent` fields are snapped onto the real worker tab ids by `_assign_worker_tabs`. A bare platform name (`"deepseek"`) resolves to tab index 0 — the *moderator's own tab* — so an unresolved name used to drop a worker prompt into the moderator's conversation; it now resolves to that platform's first worker tab. Sub-tasks sharing a tab are split into sequential waves by `_split_into_waves`, because two prompts in one tab before either reply is read loses the first reply.
      - **Mode 2 (Final Answer):** The Moderator outputs pure, unwrapped Markdown, which is the default classification. A moderator that wraps its answer as `{"status": "complete", "answer": "..."}` anyway is unwrapped.
      - **Exhausted rounds:** the moderator's last reply is persisted and returned rather than discarded.
    - Uses `BrowserManager.send_prompts_batch()` and `BrowserManager.extract_responses_batch()` to execute tasks concurrently on worker tabs.
    - Aggregates results in XML tags (`<worker name="..." role="...">...</worker>`) to inject back into the moderator.

### 2.8 `utils/exceptions.py`
**Responsibility:** Defines domain-specific errors.
- `BrowserActionRequired(Exception)`: Raised when a CSS selector is missing, input is blocked, or CAPTCHA prevents interaction.
- `ResponseCaptureTimeout(Exception)`: Raised when the DOM extraction loop exceeds `max_response_wait_s` without stabilizing.

---

## 3. Complete Configuration Schema (`config.yaml`)

```yaml
browser:
  use: "edge" # Values: "edge" or "brave". Determines which executable to auto-launch.
  remote_debugging_port: 9222 # The CDP websocket port.
  auto_launch: true # If true, subprocess.Popen launches the browser if connection fails.
  paths:
    edge:
      windows: ["C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", ...]
      mac: ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    brave:
      windows: ["C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"]
      mac: ["/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]

timing:
  typing_delay_ms: 10 # Delay between simulated keystrokes for short prompts.
  stability_samples: 3 # Number of consecutive identical DOM reads required to declare generation complete.
  stability_wait_s: 1.5 # Sleep duration between DOM reads. (Total stable time = 3 * 1.5 = 4.5s).
  max_response_wait_s: 180 # Hard timeout limit.

platforms:
  chatgpt: # The platform key (passed internally).
    url: "https://chatgpt.com/"
    input_selector: "#prompt-textarea" # Used by Playwright to find the input box.
    stop_button: "button[aria-label='Stop generating']" # Presence indicates active generation.
    send_button: "button[data-testid='send-button']" # Selector to click to submit.
    response_selector: "div[data-message-author-role='assistant']" # Parent container for extraction.
  # (Followed by claude, gemini, deepseek with identical structure)
```

---

## 4. Persistent State & Data Formats

**`chat_history.json` Schema:**
```json
{
  "last_used_model": "claude",
  "messages": [
    {
      "role": "user",
      "content": "Hello",
      "model": "chatgpt",
      "timestamp": "2024-05-15T14:30:00.000Z",
      "flag": "green"
    },
    {
      "role": "assistant",
      "content": "Hi there",
      "model": "chatgpt",
      "timestamp": "2024-05-15T14:30:05.000Z",
      "flag": null,
      "swarm_role": null
    }
  ]
}
```
*Flag Semantics:* 
- `"green"`: Global context. Sent to a new model upon first interaction.
- `"red"`: On-demand context. Sent to a known model *only* if explicitly checked in the Pending Switch Modal.
- `null`: Ignored by FlaggedContextManager.
*Swarm Role:* Tracks if the message was part of a Swarm workflow (`"moderator"`, `"worker"`, or `null`).
*Note: Upon load, `ContextManager` iterates through messages; if `"flag"` is missing (legacy files), it sets it to `null`.*

**In-Memory State (`ContextManager`):**
- `messages`: List of dictionaries identical to the JSON array.
- `last_used_model`: Extracted from JSON root. Mutated on every `add_message`.

**In-Memory State (`FlaggedContextManager`):**
- `session_delivered`: e.g., `{"claude": {0, 1}, "deepseek": {0}}`.
- When `build_context` returns messages `[msg0, msg1]`, it updates: `session_delivered[target_model].update([0, 1])`.

---

## 5. Context Building Algorithms (All Paths)

The `FlaggedContextManager.build_context(chat_history, target_model, selected_red_ids)` method governs this.

### Scenario A: No flags anywhere in history
**Input State:** `chat_history` has 10 messages, all `flag: null`.
**Execution:** `FlaggedContextManager` detects 0 flags. It immediately returns `ContextCompressor.build_context(...)`.
**Output:** The compressor forcefully includes the last `recent_count` messages, chunks the rest, ranks via TextRank/BM25 against the new prompt, and returns a subset of messages fitting `max_tokens`.

### Scenario B: First time using Target Model (Green Flags exist)
**Input State:** `target_model = "claude"`. `session_delivered = {}`. 
`chat_history`: [0: green, 1: null, 2: green, 3: red].
**Execution:** Since `"claude" not in session_delivered`, it gathers ALL green messages (indices 0, 2). It ignores red.
**Side Effect:** `session_delivered["claude"] = {0, 2}`.
**Output:** `[msg0, msg2]`.

### Scenario C: Subsequent interaction (Known Model, Red Flags exist)
**Input State:** `target_model = "claude"`. `session_delivered = {"claude": {0, 2}}`. 
`chat_history`: [0: green, 1: null, 2: green, 3: red, 4: red]. 
`selected_red_ids = [3]`.
**Execution:** Because `"claude" in session_delivered`, it ignores green flags (they are assumed already in the Claude tab's memory). It gathers red messages whose index is in `selected_red_ids` AND whose index is not in `session_delivered["claude"]`. Index 3 matches. Index 4 is ignored (not selected).
**Side Effect:** `session_delivered["claude"].update([3])` → `{0, 2, 3}`.
**Output:** `[msg3]`.

### Scenario D: Edge Cases
- **No red IDs selected:** Returns `[]`. No context is injected.
- **Red ID already delivered:** If user somehow submits `selected_red_ids=[3]` but `3` is in `session_delivered`, it is filtered out. Returns `[]`.
- **`reset_model_context("claude")` called:** `session_delivered` becomes `{}`. On the next switch to Claude, it behaves like Scenario B (re-injects all green messages).

---

## 6. Prompt Assembly & Browser Injection

**Assembly (`ContextManager.build_context_transcript`):**
Converts the list of messages from Section 5 into a continuous Markdown string, truncating from the front if it exceeds `max_chars=12000`.
Format:
```markdown
[System Note: Context from previous conversation]
[User - 2024-05-15T14:30:00]: Content
[ChatGPT - 2024-05-15T14:30:05]: Content
---
```
This is prepended to the user's fresh message.

**Injection (`BrowserManager._send_organic_prompt_impl`):**
1. Brings page to front, clicks `input_selector`.
2. Evaluates JS `element.value = ''` and dispatches `'input'` event to clear the box.
3. **Short Text (<500 chars & no `\n`):** Uses Playwright's `page.type(selector, text, delay=10)`. Simulates human keystrokes.
4. **Long/Multiline Text:** Uses `pyperclip.copy(text)`. Focuses element, uses `page.keyboard.press("Control+V")` (or `Meta+V` on Mac). Dispatches `'input'` event explicitly to force React to register the pasted value.
5. Clicks the `send_button`.

---

## 7. Response Extraction & Stability Logic

**Logic (`BrowserManager._extract_stable_response_impl`):**
1. Injects `_RESPONSE_TO_MARKDOWN_SCRIPT` as a global window function.
2. Loops every `stability_wait_s` seconds (max limit `max_response_wait_s`).
3. Executes the injected JS on the LAST element matching `response_selector`.
4. Tracks how long the extracted Markdown has been byte-identical (`quietSince_s`).
5. Any change to the string resets that timer.
6. Checks whether the `stop_button` is visible (one non-blocking pass — the old code polled `_find_element` with a 1000 ms timeout every iteration, so each loop paid a full second just to learn the button was absent).
7. Returns once the stop button is gone **and** the text has been quiet for the required window: `stability_wait_s` if the stop button was ever seen (its disappearance already proves generation ended), otherwise `stability_wait_s * stability_samples` — on platforms whose stop-button selector never matches, the text is the only evidence, and a model that pauses mid-answer must not be read as finished.

**Batch Extraction (`BrowserManager._extract_responses_batch_impl`):**
- Returns a list aligned with the requested tab ids. Operates similarly but loops over an array of tabs on a single thread. This permits multiple Playwright pages to receive network data simultaneously, drastically speeding up Swarm generation.

**Error Handling:**
- If loop hits `max_response_wait_s`, raises `ResponseCaptureTimeout`.
- If the selector cannot be found after initial waiting, raises `BrowserActionRequired("Cannot find response element")`.

---

## 8. Streamlit UI Behavior (Complete State Machine)

**Initialization:**
`init_session_state` creates instances of `ContextManager`, `FlaggedContextManager`, and initializes `st.session_state` keys (`active_model`, `selected_red_ids`, `pending_manual`, `connected`).

**Sidebar Interactions:**
- **Connect:** Calls `BrowserManager.connect()`, creates `Orchestrator`, updates `connected=True`.
- **Model Dropdown:** Triggers the **Pending Switch Modal**.
  - *Trigger:* `dropdown_selection != active_model`.
  - *Action:* Renders checkboxes for all `red` flagged messages not in `session_delivered[dropdown_selection]`. Disables main chat input.
  - *Confirm:* Sets `active_model = dropdown_selection`, caches `selected_red_ids`, calls `st.rerun()`.
- **Context Delivery Reset:** Removes a model from `session_delivered`.

**Chat Display & Flag Toggles:**
- Renders `context.messages`. Each message has a 🟩 and 🟥 button.
- Clicking a button triggers a callback to `ContextManager.update_flag`.
- Flags are exclusive: Setting green clears red, setting red clears green. Setting the same color again sets it to `null`.
- Triggers `st.rerun()` instantly, altering the UI rendering.

**Main Chat Input & Sending:**
- `st.chat_input` accepts text.
- Clears `st.session_state.last_send_error`.
- Displays spinner. Calls `orchestrator.send_message`.
- On success: Appends to UI, clears `st.session_state.selected_red_ids`, calls `st.rerun()`.

**Manual Paste Fallback State:**
- If `BrowserActionRequired` or `ResponseCaptureTimeout` is caught:
  - Updates `st.session_state.pending_manual` dict with `platform`, `user_message`, `user_already_sent` boolean.
  - Next rerun: Main chat input is disabled. A `st.text_area` form appears at the bottom.
  - User submits pasted text.
  - If `user_already_sent` is True (Timeout), calls `orchestrator.complete_manual_response(text)`.
  - If False (Browser block), calls `orchestrator.record_manual_response(platform, user_msg, text)`.
  - Sets `pending_manual = None`, calls `st.rerun()`.

---

## 9. CLI (`main.py`) Behavior

The CLI bypasses Streamlit entirely but relies on the identical `ContextManager`, `BrowserManager`, and `Orchestrator` instances.
- **Initialization:** Applies `colorama` for ANSI colors. Forces UTF-8 encoding on Windows `sys.stdout`.
- **Interactive Loop:** Prompts `[active_model] ▶ `.
- **Commands:** Slash commands (`/chatgpt`, `/history`, `/clear`, `/tabs`) are intercepted and handled locally (e.g., swapping `active_model`).
- **Execution:** Sends text directly to `orchestrator.send_message`. No Pending Switch Modal exists in CLI—it simply passes `selected_red_ids=[]` upon switch, meaning only Green flags (Scenario B) or compression fallbacks (Scenario A) apply in CLI.
- **Manual Paste:** Handled sequentially via standard `input()` blocks on exception catch.

---

## 10. Build & Packaging Process

- **Script:** `build.py`. Relies on `PyInstaller` and `DalalAI.spec`.
- **`DalalAI.spec`:** Defines a one-folder layout. Disables console window. Embeds `config.yaml` and Streamlit metadata via `datas`.
- **Windows:** Executes `PyInstaller`. Then looks for `ISCC.exe` (Inno Setup) in `C:\Program Files (x86)\Inno Setup 6`. If found, runs `setup.iss` to produce `DalalAI_Setup.exe`. If missing, falls back to `shutil.make_archive(format="zip")`.
- **macOS:** Produces `.app` structure, archives into `release/DalalAI_macOS.zip`.
- **Linux:** Produces ELF folder, archives into `release/DalalAI_Linux.tar.gz`.
- **Artifacts Included:** The executable folder, `config.yaml`, `README.txt`, `CHANGELOG`, `LICENSE`.

---

## 11. Error Catalog

| Exception Class | Raised By | Trigger Condition | UI Handling |
|---|---|---|---|
| `ConnectionError` | `BrowserManager.connect()` | CDP port refused, and `auto_launch` failed/disabled. | Sidebar shows "Not connected" with error detail string. |
| `BrowserActionRequired` | `BrowserManager` | `input_selector` or `send_button` missing; CAPTCHA intercepts the DOM. | Renders Manual Paste Fallback text area; `user_already_sent=False`. |
| `ResponseCaptureTimeout`| `BrowserManager` | `stable_count` doesn't reach target before `max_response_wait_s` expires. | Renders Manual Paste Fallback text area; `user_already_sent=True`. |
| `Exception` (Generic) | Anywhere | Thread crashes, network drops, bad JSON. | Prints full traceback into a dismissable `st.error` alert box via `last_send_error`. |

---

## 12. Sample Run Transcript

*Simulated Trace of Execution:*

**State 1:** `chat_history` is empty. `active_model = "chatgpt"`.
**Input:** User types "Explain quantum entanglement". User clicks 🟩 (Flag: "green") on this message.
**Action:** `orchestrator.send_message` routes to ChatGPT tab.
**Prompt sent:** `"Explain quantum entanglement"`
**Response:** (ChatGPT returns response). `last_used_model = "chatgpt"`.

**State 2:** User changes dropdown to "claude".
**UI Action:** Pending Switch modal bypasses (no red flags exist). `active_model = "claude"`.
**Input:** User types "Can you summarize that in one sentence?".
**Action:** `orchestrator.send_message("claude", ...)`
**Context Generation:** `FlaggedContextManager` sees `target_model="claude"`. `"claude"` is NOT in `session_delivered`. It gathers all Green messages (the first prompt/response pair). Updates `session_delivered["claude"] = {0, 1}`.
**Assembly:**
```markdown
[System Note: Context from previous conversation]
[User - <Time>]: Explain quantum entanglement
[ChatGPT - <Time>]: Quantum entanglement is a physical phenomenon...
---
Can you summarize that in one sentence?
```
**Injection:** The assembled block above is pasted into Claude's input box.
**Response:** (Claude returns 1 sentence). `last_used_model = "claude"`.

*This reference document provides a complete theoretical model of Dalal AI for LLMs.*
