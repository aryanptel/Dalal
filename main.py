"""
AI Web Chat Orchestrator — Main Interface
==========================================

A CLI tool that connects to a live Chrome browser via remote debugging
and lets you chat with ChatGPT, Claude, Gemini, and DeepSeek from a single
terminal, preserving conversation context across model switches.

Setup
-----
1. Launch Chrome with remote debugging:
   chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\selenium\\AutomationProfile"

2. Log into ChatGPT, Claude, Gemini, and DeepSeek in the browser tabs.

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
from dalal_ai.core.orchestrator import Orchestrator
from utils.exceptions import BrowserActionRequired, ResponseCaptureTimeout
from utils.paths import get_config_path, get_history_path, init_user_data
from utils.logger import logger

# ── Constants ─────────────────────────────────────────────────────────────────

BANNER = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   {Fore.WHITE}🧠  AI Web Chat Orchestrator{Fore.CYAN}                               ║
║   {Fore.WHITE}   Route prompts across ChatGPT, Claude,{Fore.CYAN}                 ║
║   {Fore.WHITE}   Gemini & DeepSeek from one terminal.{Fore.CYAN}                   ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}
"""

HELP_TEXT = f"""
{Fore.YELLOW}━━━ Commands ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{Style.RESET_ALL}
  {Fore.GREEN}/chatgpt{Style.RESET_ALL}    Switch active model to ChatGPT
  {Fore.GREEN}/claude{Style.RESET_ALL}     Switch active model to Claude
  {Fore.GREEN}/gemini{Style.RESET_ALL}     Switch active model to Gemini
  {Fore.GREEN}/deepseek{Style.RESET_ALL}   Switch active model to DeepSeek
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
}

PLATFORM_ICONS = {
    "chatgpt":  "🟢",
    "claude":   "🟠",
    "gemini":   "🔵",
    "deepseek": "🟣",
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

            elif cmd in ("/chatgpt", "/claude", "/gemini", "/deepseek"):
                new_model = cmd.lstrip("/")
                if new_model in platforms:
                    active_model = new_model
                    print_model_badge(active_model)
                else:
                    print(f"  {Fore.RED}Unknown platform: {new_model}{Style.RESET_ALL}")
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
                response = orchestrator.send_message(active_model, user_input)
                print_response(active_model, response)
            except BrowserActionRequired as exc:
                print(f"\n  {Fore.YELLOW}⚠ {exc}{Style.RESET_ALL}")
                print(
                    f"  {Fore.YELLOW}👉 Complete the step in the browser, "
                    f"then press Enter to continue...{Style.RESET_ALL}"
                )
                input()
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
