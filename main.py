"""
AI Web Chat Orchestrator — Main Interface
==========================================

A CLI tool that connects to a live Chrome browser via remote debugging
and lets you chat with ChatGPT, Claude, Gemini, DeepSeek, Kimi, HuggingChat, and Meta AI from a single
terminal, preserving conversation context across model switches.

Setup
-----
1. Launch Chrome with remote debugging:
   chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\selenium\\AutomationProfile"

2. Log into ChatGPT, Claude, Gemini, DeepSeek, Kimi, HuggingChat, and Meta AI in the browser tabs.

3. Run this script:
   python main.py
"""

from __future__ import annotations

import os
import sys

# ── Fix Windows terminal encoding ─────────────────────────────────────────────
# Windows consoles default to cp1252 which can't print emoji/unicode.
# Reconfigure stdout/stderr to UTF-8 with error replacement.
if sys.platform == "win32":
    for stream in ("stdout", "stderr"):
        s = getattr(sys, stream)
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

import yaml

try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init()
except ImportError:
    # Graceful fallback if colorama isn't installed
    class _Dummy:
        def __getattr__(self, name):
            return ""
    Fore = Style = _Dummy()

from dalal_ai.browser.browser_manager import BrowserManager
from dalal_ai.core.context_manager import ContextManager
from dalal_ai.core.document_extractor import extract_document_cached
from dalal_ai.core.flagged_context_manager import FlaggedContextManager
from dalal_ai.core.orchestrator import Orchestrator
from utils.exceptions import BrowserActionRequired, ResponseCaptureTimeout
from utils.paths import get_config_path, get_history_path, init_user_data
from utils.logger import logger

# ── Constants ─────────────────────────────────────────────────────────────────

BANNER = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   {Fore.WHITE}🧠  AI Web Chat Orchestrator{Fore.CYAN}                               ║
║   {Fore.WHITE}   Route prompts across ChatGPT, Claude, Gemini,{Fore.CYAN}         ║
║   {Fore.WHITE}   DeepSeek, Kimi, HuggingChat & Meta AI.{Fore.CYAN}                ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}
"""

HELP_TEXT = f"""
{Fore.YELLOW}━━━ Commands ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}
  {Fore.GREEN}/chatgpt{Style.RESET_ALL}    Switch active model to ChatGPT
  {Fore.GREEN}/claude{Style.RESET_ALL}     Switch active model to Claude
  {Fore.GREEN}/gemini{Style.RESET_ALL}     Switch active model to Gemini
  {Fore.GREEN}/deepseek{Style.RESET_ALL}   Switch active model to DeepSeek
  {Fore.GREEN}/kimi{Style.RESET_ALL}       Switch active model to Kimi
  {Fore.GREEN}/huggingchat{Style.RESET_ALL} Switch active model to HuggingChat
  {Fore.GREEN}/metaai{Style.RESET_ALL}     Switch active model to Meta AI
  {Fore.GREEN}/green [n]{Style.RESET_ALL}  Flag message n (default: last) as global context
  {Fore.GREEN}/red [n]{Style.RESET_ALL}    Flag message n (default: last) as on-demand context
  {Fore.GREEN}/unflag [n]{Style.RESET_ALL} Remove the flag from message n (default: last)
  {Fore.GREEN}/flags{Style.RESET_ALL}      List flagged messages
  {Fore.GREEN}/attach <path>{Style.RESET_ALL} Attach a file to the next message
  {Fore.GREEN}/attached{Style.RESET_ALL}   List queued attachments
  {Fore.GREEN}/detach{Style.RESET_ALL}     Clear queued attachments
  {Fore.GREEN}/status{Style.RESET_ALL}     Show session statistics
  {Fore.GREEN}/tabs{Style.RESET_ALL}       List open browser tabs
  {Fore.GREEN}/history{Style.RESET_ALL}    Show recent conversation history
  {Fore.GREEN}/clear{Style.RESET_ALL}      Reset conversation history
  {Fore.GREEN}/help{Style.RESET_ALL}       Show this help message
  {Fore.GREEN}/quit{Style.RESET_ALL}       Exit the orchestrator
{Fore.YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}
  Type any message to send it to the active model.
"""

PLATFORM_COLORS = {
    "chatgpt": Fore.GREEN,
    "claude": Fore.YELLOW,
    "gemini": Fore.BLUE,
    "deepseek": Fore.MAGENTA,
    "kimi": Fore.LIGHTBLACK_EX,
    "huggingchat": Fore.LIGHTYELLOW_EX,
    "metaai": Fore.LIGHTBLUE_EX,
}

PLATFORM_ICONS = {
    "chatgpt":  "🟢",
    "claude":   "🟠",
    "gemini":   "🔵",
    "deepseek": "🟣",
    "kimi":     "🌙",
    "huggingchat": "🤗",
    "metaai":   "♾️",
}


# ── Load Configuration ───────────────────────────────────────────────────────

def load_config() -> dict:
    """Load and return the YAML configuration."""
    init_user_data()
    config_path = get_config_path()
    if not os.path.isfile(config_path):
        print(f"{Fore.RED}❌ Config file not found: {config_path}{Style.RESET_ALL}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Display Helpers ───────────────────────────────────────────────────────────

def print_model_badge(platform: str) -> None:
    """Print a colored badge for the active model."""
    color = PLATFORM_COLORS.get(platform, Fore.WHITE)
    icon = PLATFORM_ICONS.get(platform, "🤖")
    print(f"\n  {color}┌─ {icon} Active Model: {platform.upper()} ─┐{Style.RESET_ALL}")


def print_response(platform: str, text: str) -> None:
    """Print the assistant's response with formatting."""
    color = PLATFORM_COLORS.get(platform, Fore.WHITE)
    icon = PLATFORM_ICONS.get(platform, "🤖")
    border = "─" * 60

    print(f"\n  {color}┌{border}┐{Style.RESET_ALL}")
    print(f"  {color}│ {icon} {platform.upper()}{Style.RESET_ALL}")
    print(f"  {color}├{border}┤{Style.RESET_ALL}")

    # Word-wrap response lines
    for line in text.split("\n"):
        # Truncate very long lines for terminal readability
        while len(line) > 56:
            print(f"  {color}│{Style.RESET_ALL} {line[:56]}")
            line = line[56:]
        print(f"  {color}│{Style.RESET_ALL} {line}")

    print(f"  {color}└{border}┘{Style.RESET_ALL}")


def print_status(context: ContextManager, active_model: str) -> None:
    """Print session statistics."""
    stats = context.get_stats()
    color = PLATFORM_COLORS.get(active_model, Fore.WHITE)
    icon = PLATFORM_ICONS.get(active_model, "🤖")

    print(f"\n  {Fore.CYAN}━━━ Session Status ━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}")
    print(f"  {color}{icon} Active Model:{Style.RESET_ALL}    {active_model}")
    print(f"  📊 Total Messages:  {stats['total_messages']}")
    print(f"     ├─ User:         {stats['user_messages']}")
    print(f"     └─ Assistant:    {stats['assistant_messages']}")
    print(f"  🔤 Total Chars:     {stats['total_characters']:,}")
    print(f"  🔀 Models Used:     {', '.join(stats['models_used']) or 'None yet'}")
    print(f"  {Fore.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}")


def print_history(context: ContextManager, last_n: int = 10) -> None:
    """Print recent conversation history."""
    msgs = context.messages[-last_n:]
    if not msgs:
        print(f"\n  {Fore.YELLOW}No messages yet.{Style.RESET_ALL}")
        return

    print(f"\n  {Fore.CYAN}━━━ Recent History (last {len(msgs)} messages) ━━━{Style.RESET_ALL}")
    for msg in msgs:
        role = msg["role"]
        model = msg["model"]
        content = msg["content"][:80] + ("..." if len(msg["content"]) > 80 else "")
        color = PLATFORM_COLORS.get(model, Fore.WHITE)
        icon = "👤" if role == "user" else PLATFORM_ICONS.get(model, "🤖")

        if role == "user":
            print(f"  {icon} {Fore.WHITE}You → {color}{model}{Style.RESET_ALL}: {content}")
        else:
            print(f"  {icon} {color}{model}{Style.RESET_ALL}: {content}")
    print(f"  {Fore.CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}")


# ── Main Loop ─────────────────────────────────────────────────────────────────

def main() -> None:
    print(BANNER)

    # Load config
    config = load_config()
    platforms = list(config["platforms"].keys())

    # Initialize components
    history_path = get_history_path()
    context = ContextManager(persist_path=history_path)

    browser_name = config["browser"].get("use", "edge").capitalize()
    print(f"  {Fore.CYAN}📡 Connecting to {browser_name} via CDP...{Style.RESET_ALL}")
    browser = BrowserManager(config)
    try:
        browser.connect()
    except ConnectionError as exc:
        print(f"\n{Fore.RED}{exc}{Style.RESET_ALL}")
        sys.exit(1)

    print(f"  {Fore.GREEN}✅ Connected to {browser_name}!{Style.RESET_ALL}")

    # Show discovered tabs
    tabs = browser.list_open_tabs()
    if tabs:
        print(f"\n  {Fore.CYAN}📑 Open tabs:{Style.RESET_ALL}")
        for tab in tabs:
            print(f"     • {tab['title'][:50]} — {tab['url'][:60]}")

    orchestrator = Orchestrator(browser, context, config)
    # Without this the CLI passed flagged_mgr=None, so no context was ever
    # injected on a model switch — the transcript came out empty every time.
    flagged_mgr = FlaggedContextManager()
    pending_attachments: list[str] = []
    attachment_cap = (config.get("attachments") or {}).get("max_chars_per_file")
    try:
        attachment_cap = int(attachment_cap)
    except (TypeError, ValueError):
        attachment_cap = None

    # Default to first platform
    active_model = platforms[0]
    print_model_badge(active_model)
    print(HELP_TEXT)

    # ── Interactive Loop ──────────────────────────────────────────────────
    while True:
        try:
            color = PLATFORM_COLORS.get(active_model, Fore.WHITE)
            icon = PLATFORM_ICONS.get(active_model, "🤖")
            prompt = f"  {color}{icon} [{active_model}]{Style.RESET_ALL} ▶ "
            user_input = input(prompt).strip()

            if not user_input:
                continue

            # ── Command Handling ──────────────────────────────────────────
            cmd = user_input.lower()

            if cmd == "/quit" or cmd == "/exit":
                print(f"\n  {Fore.CYAN}👋 Goodbye!{Style.RESET_ALL}\n")
                break

            elif cmd == "/help":
                print(HELP_TEXT)
                continue

            elif cmd.startswith("/") and cmd[1:] in platforms:
                active_model = cmd[1:]
                print_model_badge(active_model)
                continue

            elif cmd.split()[0] in ("/green", "/red", "/unflag"):
                parts = cmd.split()
                flag = {"/green": "green", "/red": "red", "/unflag": None}[parts[0]]
                if not context.messages:
                    print(f"  {Fore.YELLOW}No messages to flag yet.{Style.RESET_ALL}")
                    continue
                try:
                    index = int(parts[1]) if len(parts) > 1 else len(context.messages) - 1
                except ValueError:
                    print(f"  {Fore.RED}Usage: {parts[0]} [message index]{Style.RESET_ALL}")
                    continue
                if not 0 <= index < len(context.messages):
                    print(f"  {Fore.RED}No message at index {index}.{Style.RESET_ALL}")
                    continue
                context.update_flag(index, flag)
                label = flag or "cleared"
                print(f"  {Fore.GREEN}Message [{index}] flag → {label}.{Style.RESET_ALL}")
                continue

            elif cmd.split()[0] == "/attach":
                raw = user_input.split(None, 1)
                if len(raw) < 2:
                    print(f"  {Fore.RED}Usage: /attach <path to file>{Style.RESET_ALL}")
                    continue
                path = os.path.expanduser(raw[1].strip().strip('"').strip("'"))
                if not os.path.isfile(path):
                    print(f"  {Fore.RED}No such file: {path}{Style.RESET_ALL}")
                    continue
                doc = extract_document_cached(path, max_chars=attachment_cap)
                if doc.error:
                    print(f"  {Fore.YELLOW}⚠ {doc.name}: {doc.error}{Style.RESET_ALL}")
                    print(f"  {Fore.YELLOW}   Queued anyway for native upload.{Style.RESET_ALL}")
                else:
                    print(f"  {Fore.GREEN}📎 {doc.summary()}{Style.RESET_ALL}")
                for warning in doc.warnings:
                    print(f"  {Fore.YELLOW}   ⚠ {warning}{Style.RESET_ALL}")
                if doc.truncated:
                    # No dialog in a terminal: apply the cap and say exactly
                    # what was left out rather than trimming silently.
                    print(
                        f"  {Fore.YELLOW}   Over the {attachment_cap:,}-character "
                        f"limit — sending {doc.page_span()}.{Style.RESET_ALL}"
                    )
                pending_attachments.append(path)
                continue

            elif cmd == "/attached":
                if not pending_attachments:
                    print(f"  {Fore.YELLOW}No attachments queued.{Style.RESET_ALL}")
                for path in pending_attachments:
                    print(f"  📎 {os.path.basename(path)}")
                continue

            elif cmd == "/detach":
                pending_attachments.clear()
                print(f"  {Fore.GREEN}Attachments cleared.{Style.RESET_ALL}")
                continue

            elif cmd == "/flags":
                flagged = [
                    (i, m) for i, m in enumerate(context.messages) if m.get("flag")
                ]
                if not flagged:
                    print(f"  {Fore.YELLOW}No flagged messages.{Style.RESET_ALL}")
                for i, m in flagged:
                    mark = "GREEN" if m["flag"] == "green" else "RED"
                    preview = m["content"][:60].replace("\n", " ")
                    print(f"  [{i}] {mark:<5} {m['role']:<9} {preview}")
                continue

            elif cmd == "/status":
                print_status(context, active_model)
                continue

            elif cmd == "/tabs":
                tabs = browser.list_open_tabs()
                print(f"\n  {Fore.CYAN}📑 Open tabs:{Style.RESET_ALL}")
                for tab in tabs:
                    print(f"     • {tab['title'][:50]} — {tab['url'][:60]}")
                continue

            elif cmd == "/history":
                print_history(context)
                continue

            elif cmd == "/clear":
                context.clear()
                print(f"  {Fore.GREEN}🗑️  History cleared.{Style.RESET_ALL}")
                continue

            elif cmd.startswith("/"):
                print(f"  {Fore.RED}Unknown command: {cmd}. Type /help for options.{Style.RESET_ALL}")
                continue

            # ── Send Message ──────────────────────────────────────────────
            print(f"\n  {Fore.CYAN}📤 Sending to {active_model}...{Style.RESET_ALL}")

            try:
                response = orchestrator.send_message(
                    active_model,
                    user_input,
                    flagged_mgr=flagged_mgr,
                    files=list(pending_attachments) or None,
                )
                pending_attachments.clear()
                print_response(active_model, response)
            except BrowserActionRequired as exc:
                print(f"\n  {Fore.YELLOW}⚠ {exc}{Style.RESET_ALL}")
                print(
                    f"  {Fore.YELLOW}👉 Complete the step in the browser, "
                    f"then paste the reply below (or press Enter to skip).{Style.RESET_ALL}"
                )
                pasted = input("  📋 Response: ").strip()
                if pasted:
                    # Nothing was recorded for this turn, so log both halves.
                    orchestrator.record_manual_response(active_model, user_input, pasted)
                    print_response(active_model, pasted)
            except ResponseCaptureTimeout as exc:
                print(f"\n  {Fore.YELLOW}⚠ {exc}{Style.RESET_ALL}")
                response = input(
                    "  📋 Paste the response manually (or press Enter to skip): "
                ).strip()
                if response:
                    orchestrator.complete_manual_response(response)
                    print_response(active_model, response)
            except Exception as exc:
                print(f"\n  {Fore.RED}❌ Error: {exc}{Style.RESET_ALL}")
                print(
                    f"  {Fore.YELLOW}💡 Tip: Check the browser tab. "
                    f"You can try again or switch models.{Style.RESET_ALL}"
                )

        except KeyboardInterrupt:
            print(f"\n\n  {Fore.CYAN}👋 Interrupted. Goodbye!{Style.RESET_ALL}\n")
            break
        except EOFError:
            break

    # Cleanup
    browser.disconnect()


if __name__ == "__main__":
    main()
