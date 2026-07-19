"""
Browser Manager — Playwright CDP client wrapper with organic DOM interaction.

Connects to a real browser (Edge or Brave) via remote debugging, manages
per-platform tabs, and provides human-like input simulation and stable
response extraction.  Works on Windows and macOS.

IMPORTANT: All Playwright operations run on a single dedicated thread
to avoid greenlet/thread conflicts when called from Streamlit.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import platform
import queue
import subprocess
import threading
import time
import sys
import atexit
from typing import Any, Callable

# ── Fix Windows terminal encoding ─────────────────────────────────────────────
if sys.platform == "win32":
    for _stream in ("stdout", "stderr"):
        _s = getattr(sys, _stream)
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")

# ── Fix Windows asyncio event loop policy ─────────────────────────────────────
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

StatusCallback = Callable[[str], None] | None

# Detect OS once
IS_MAC = platform.system() == "Darwin"
IS_WIN = platform.system() == "Windows"
META_KEY = "Meta" if IS_MAC else "Control"


# Browser chat apps render Markdown into HTML before Playwright can read it.
# This script recovers the useful semantic structure (including LaTex exposed
# by KaTeX/MathJax) so Streamlit can render the response faithfully.
_RESPONSE_TO_MARKDOWN_SCRIPT = r"""
(node) => {
  const root = node.matches('.markdown, .standard-markdown, .progressive-markdown')
    ? node
    : node.querySelector('.markdown, .standard-markdown, .progressive-markdown') || node;

  const clean = (value) => (value || '').replace(/[\u200b\ufeff]/g, '');
  const texFor = (element) => {
    const annotation = element.querySelector('annotation[encoding="application/x-tex"]');
    if (annotation?.textContent?.trim()) return annotation.textContent.trim();
    return element.getAttribute('data-tex') || element.getAttribute('alttext') || '';
  };
  const isMath = (element) => element.matches(
    '.katex, .katex-display, mjx-container, math, [data-tex], [alttext]'
  );
  const isBlockMath = (element) => element.matches(
    '.katex-display, mjx-container[display="true"], mjx-container[display="block"], math[display="block"]'
  );

  function walk(current, orderedIndex = 0) {
    if (current.nodeType === Node.TEXT_NODE) return clean(current.nodeValue);
    if (current.nodeType !== Node.ELEMENT_NODE) return '';

    const element = current;
    const tag = element.tagName.toLowerCase();
    if (['script', 'style', 'button', 'svg', 'path', 'nav'].includes(tag)) return '';

    if (isMath(element)) {
      const tex = texFor(element);
      if (tex) return isBlockMath(element) ? `\n\n$$\n${tex}\n$$\n\n` : `$${tex}$`;
    }

    const children = [...element.childNodes]
      .map((child) => walk(child, orderedIndex))
      .join('');
    const text = clean(children).trim();

    if (/^h[1-6]$/.test(tag)) return `\n\n${'#'.repeat(Number(tag[1]))} ${text}\n\n`;
    if (tag === 'p') return `\n\n${text}\n\n`;
    if (tag === 'br') return '\n';
    if (tag === 'hr') return '\n\n---\n\n';
    if (tag === 'strong' || tag === 'b') return text ? `**${text}**` : '';
    if (tag === 'em' || tag === 'i') return text ? `*${text}*` : '';
    if (tag === 'blockquote') return text.split('\n').map((line) => `> ${line}`).join('\n') + '\n\n';
    if (tag === 'code' && element.parentElement?.tagName.toLowerCase() !== 'pre') {
      return text ? `\`${text}\`` : '';
    }
    if (tag === 'pre') return `\n\n\`\`\`\n${element.innerText.trim()}\n\`\`\`\n\n`;
    if (tag === 'a') {
      const href = element.getAttribute('href');
      return href && text ? `[${text}](${href})` : text;
    }
    if (tag === 'li') return `- ${text}\n`;
    if (tag === 'ol' || tag === 'ul') return `\n${children.replace(/\n{2,}/g, '\n')}\n`;
    return children;
  }

  const markdown = walk(root)
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  // When an app has already rendered elementary equations as ordinary text,
  // recover inline LaTex for the common voltage/current/resistance forms.
  return markdown.replace(
    /(?<![A-Za-z$])([VIR](?:[ \t]*=[ \t]*(?:[VIR]|[0-9]+(?:\.[0-9]+)?|[ΩAV]|×|\/|\+|-|[ \t])+)+)(?![A-Za-z])/g,
    (_, equation) => {
      const tex = equation.replace(/[ \t=]+$/, '')
        .replace(/Ω/g, '\\Omega')
        .replace(/×/g, '\\times')
        .replace(/([VIR0-9.]+)[ \t]*\/[ \t]*([VIR0-9.]+)/g, '\\frac{$1}{$2}');
      return `$${tex.trim()}$`;
    },
  );
}
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  Playwright Worker Thread
# ═══════════════════════════════════════════════════════════════════════════════
# Playwright's sync API uses greenlets that are bound to the thread that created
# them.  Streamlit reruns scripts on different threads, causing "cannot switch to
# a different thread" errors.  This worker ensures ALL Playwright calls happen
# on one persistent thread.
# ═══════════════════════════════════════════════════════════════════════════════

class _PlaywrightWorker:
    """Singleton background thread that executes all Playwright operations."""

    _instance: _PlaywrightWorker | None = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> _PlaywrightWorker:
        with cls._lock:
            if cls._instance is None or not cls._instance._thread.is_alive():
                cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        # A Sync Playwright instance owns a running event loop. It must be
        # started only once on this persistent thread, even if Streamlit
        # recreates BrowserManager during a rerun.
        self._playwright: Playwright | None = None
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="playwright-worker"
        )
        self._thread.start()

    def _loop(self):
        """Worker loop: pull callables from the queue and run them."""
        # Streamlit may install WindowsSelectorEventLoopPolicy. That policy
        # cannot create subprocess transports, but Playwright needs one to
        # start its Node driver. Set the policy before Sync Playwright creates
        # the worker's event loop.
        if sys.platform == "win32":
            proactor_policy = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
            if proactor_policy is not None:
                asyncio.set_event_loop_policy(proactor_policy())

        while True:
            task = self._queue.get()
            if task is None:
                break
            fn, args, kwargs, future = task
            try:
                result = fn(*args, **kwargs)
                if not future.cancelled():
                    future.set_result(result)
            except BaseException as exc:
                if not future.cancelled():
                    future.set_exception(exc)

    def run(self, fn, *args, timeout=300, **kwargs):
        """
        Submit a callable to the Playwright thread and block until done.
        Returns the callable's return value or raises its exception.
        """
        future = concurrent.futures.Future()
        self._queue.put((fn, args, kwargs, future))
        return future.result(timeout=timeout)

    def get_or_start_playwright(self) -> Playwright:
        """Return the one Sync Playwright instance owned by this worker."""
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        return self._playwright

    def stop_playwright(self) -> None:
        """Stop and forget the worker-owned Playwright instance."""
        if self._playwright is not None:
            try:
                self._playwright.stop()
            finally:
                self._playwright = None


# ═══════════════════════════════════════════════════════════════════════════════
#  Browser Manager
# ═══════════════════════════════════════════════════════════════════════════════

class BrowserManager:
    """
    Manages a Playwright connection to a live browser (Edge/Brave) via CDP.

    All Playwright operations are transparently dispatched to a dedicated
    background thread so the public API is safe to call from any thread
    (including Streamlit reruns).
    """

    def __init__(self, config: dict[str, Any], on_status: StatusCallback = None):
        self._config = config
        self._browser_conf = config["browser"]
        self._cdp_url: str = self._browser_conf["remote_debugging_url"]
        self._platforms: dict[str, dict] = config["platforms"]
        self._timing: dict[str, Any] = config.get("timing", {})
        self._on_status = on_status

        # Playwright objects (only touched on the worker thread)
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._launched_process: subprocess.Popen | None = None
        self._pages: dict[str, Page] = {}
        # Snapshot the page immediately before each send.  Without this, a
        # completed reply already visible in the tab can be mistaken for the
        # reply to the prompt we have just sent.
        self._response_baselines: dict[str, tuple[int, str]] = {}

        # Worker thread for Playwright operations
        self._worker = _PlaywrightWorker.get()

    def _status(self, message: str) -> None:
        if self._on_status:
            self._on_status(message)
        else:
            try:
                print(message, flush=True)
            except UnicodeEncodeError:
                print(message.encode("ascii", errors="replace").decode(), flush=True)

    # ── Public API (thread-safe, delegates to worker) ─────────────────────────

    def connect(self) -> None:
        """Connect to the browser via CDP (thread-safe)."""
        self._worker.run(self._connect_impl)

    def disconnect(self) -> None:
        """Cleanly disconnect (thread-safe)."""
        self._worker.run(self._disconnect_impl)

    def close(self) -> None:
        """Alias for disconnect, useful for graceful shutdown routines."""
        self.disconnect()

    def is_connected(self) -> bool:
        try:
            return self._worker.run(self._is_connected_impl, timeout=10)
        except Exception:
            return False

    def send_organic_prompt(self, platform: str, text: str) -> None:
        """Type a prompt into the platform's input box (thread-safe)."""
        self._worker.run(self._send_organic_prompt_impl, platform, text)

    def extract_stable_response(self, platform: str) -> str:
        """Wait for model response and extract it (thread-safe)."""
        return self._worker.run(self._extract_stable_response_impl, platform)

    def list_open_tabs(self) -> list[dict]:
        """Return info about all open tabs (thread-safe)."""
        try:
            return self._worker.run(self._list_open_tabs_impl, timeout=10)
        except Exception:
            return []

    # ── Browser Auto-Launch (runs on worker thread) ───────────────────────────

    def _find_browser_executable(self) -> str | None:
        browser_choice = self._browser_conf.get("use", "edge")
        paths_conf = self._browser_conf.get("paths", {}).get(browser_choice, {})
        os_key = "mac" if IS_MAC else "windows"
        candidates = paths_conf.get(os_key, [])
        for path in candidates:
            if os.path.isfile(path):
                return path
        return None

    def _is_debug_port_open(self) -> bool:
        import urllib.request
        try:
            urllib.request.urlopen(self._cdp_url + "/json/version", timeout=2)
            return True
        except Exception:
            return False

    def _auto_launch_browser(self) -> bool:
        if self._is_debug_port_open():
            browser_name = self._browser_conf.get("use", "edge")
            self._status(f"✅ {browser_name.capitalize()} already running on debug port.")
            return True

        exe = self._find_browser_executable()
        if not exe:
            browser_name = self._browser_conf.get("use", "edge")
            self._status(f"⚠ Could not find {browser_name} executable.")
            return False

        port = self._browser_conf.get("remote_debugging_port", 9222)
        data_dir = (
            self._browser_conf.get("user_data_dir_mac")
            if IS_MAC
            else self._browser_conf.get("user_data_dir_windows", r"C:\selenium\AutomationProfile")
        )

        cmd = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={data_dir}"]
        browser_name = self._browser_conf.get("use", "edge")
        self._status(f"🚀 Launching {browser_name.capitalize()}...")
        self._status(f"   {exe}")

        try:
            if IS_WIN:
                self._launched_process = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                self._launched_process = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
        except Exception as exc:
            self._status(f"❌ Failed to launch: {exc}")
            return False

        self._status("⏳ Waiting for browser debug port...")
        for _ in range(20):
            time.sleep(0.5)
            if self._is_debug_port_open():
                self._status("✅ Browser debug port ready.")
                return True
        self._status("⚠ Browser debug port timeout.")
        return False

    # ── Connection Implementation (runs on worker thread) ─────────────────────

    def _connect_impl(self) -> None:
        if self._browser is not None and self._browser.is_connected():
            return

        # Auto-launch if configured
        if self._browser_conf.get("auto_launch", False):
            if not self._auto_launch_browser():
                browser_name = self._browser_conf.get("use", "edge")
                raise ConnectionError(
                    f"❌ Could not auto-launch {browser_name}.\n"
                    f"   Please launch it manually or set 'auto_launch: false' in config.yaml."
                )

        self._pw = self._worker.get_or_start_playwright()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
        except Exception as exc:
            self._browser = None
            self._pw = None
            browser_name = self._browser_conf.get("use", "edge")
            raise ConnectionError(
                f"❌ Could not connect to {browser_name} at {self._cdp_url}.\n"
                f"   Make sure the browser is running with remote debugging enabled.\n"
                f"   Error: {exc}"
            ) from exc

        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else self._browser.new_context()
        self._discover_platform_pages()

    def _disconnect_impl(self) -> None:
        self._pages.clear()
        self._response_baselines.clear()
        if self._pw:
            self._worker.stop_playwright()
            self._pw = None
        self._browser = None
        self._context = None

    # ── Page Discovery (runs on worker thread) ────────────────────────────────

    def _discover_platform_pages(self) -> None:
        if not self._context:
            return
        for name, plat_conf in self._platforms.items():
            target_url = plat_conf["url"]
            found = False
            for page in self._context.pages:
                try:
                    if self._urls_match(page.url, target_url):
                        self._pages[name] = page
                        found = True
                        break
                except Exception:
                    continue
            if not found:
                try:
                    new_page = self._context.new_page()
                    new_page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                    self._pages[name] = new_page
                except Exception as exc:
                    self._status(f"⚠ Could not open tab for {name}: {exc}")

    @staticmethod
    def _urls_match(page_url: str, config_url: str) -> bool:
        from urllib.parse import urlparse
        page_domain = urlparse(page_url).netloc.replace("www.", "")
        config_domain = urlparse(config_url).netloc.replace("www.", "")
        return page_domain == config_domain

    def _get_page(self, platform: str) -> Page:
        if platform not in self._pages:
            self._discover_platform_pages()
        if platform not in self._pages:
            raise RuntimeError(
                f"No browser tab found for '{platform}'. "
                f"Please open {self._platforms[platform]['url']} in the browser."
            )
        return self._pages[platform]

    # ── Organic Prompt Sending (runs on worker thread) ────────────────────────

    def _send_organic_prompt_impl(self, platform: str, text: str) -> None:
        page = self._get_page(platform)
        plat = self._platforms[platform]
        typing_delay = self._timing.get("typing_delay_ms", 12)

        # Record the state before interacting with the page, while the prior
        # response is still the last matching element.
        self._response_baselines[platform] = self._get_response_snapshot(
            page, plat["response_selector"]
        )

        # 1. Bring tab to focus
        page.bring_to_front()
        time.sleep(0.3)

        # 2. Find and focus the input element
        input_el = self._find_element(page, plat["input_selector"], timeout=10000)
        fallback_used = False
        fallback_btn = None
        
        if input_el is None:
            self._status("⚠ Input selector failed. Attempting heuristic fallback...")
            fallback_input, fallback_btn = self._find_input_and_button_fallback(page)
            if fallback_input and fallback_btn:
                self._status("⚠ Using heuristic fallback for input and button.")
                input_el = fallback_input
                fallback_used = True
            else:
                from utils.exceptions import BrowserActionRequired
                raise BrowserActionRequired(
                    f"❌ Cannot find input box for {platform}.\n"
                    f"   Selector: {plat['input_selector']}\n"
                    f"   The platform UI may have changed. Please check the page manually."
                )

        input_el.click()
        time.sleep(0.2)

        # 3. Clear any existing content
        self._clear_input(page, input_el)

        # 4. Type the message (clipboard paste for long texts or multiline text)
        if len(text) > 500 or "\n" in text:
            self._paste_text(page, input_el, text)
        else:
            input_el.type(text, delay=typing_delay)

        # 5. Fire input event for React/framework editors
        input_el.dispatch_event("input", {"bubbles": True})
        time.sleep(0.3)

        # 6. Click send
        send_btn = fallback_btn if fallback_used else self._find_element(page, plat["send_button"], timeout=5000)
        if send_btn is None:
            self._status("⚠ Send button selector failed. Attempting heuristic fallback...")
            _, send_btn = self._find_input_and_button_fallback(page)
            
        if send_btn is None:
            self._status(f"⚠ Send button not found for {platform}, trying Enter key...")
            page.keyboard.press("Enter")
        else:
            try:
                send_btn.click(timeout=3000)
            except Exception:
                page.keyboard.press("Enter")

        post_delay = self._timing.get("post_send_delay_s", 1.0)
        time.sleep(post_delay)

    def _clear_input(self, page: Page, element) -> None:
        try:
            element.click()
            page.keyboard.press(f"{META_KEY}+A")
            page.keyboard.press("Backspace")
            time.sleep(0.1)
        except Exception:
            pass

    def _paste_text(self, page: Page, element, text: str) -> None:
        try:
            import pyperclip
            pyperclip.copy(text)
            element.click()
            page.keyboard.press(f"{META_KEY}+V")
        except Exception:
            try:
                element.evaluate(
                    """(el, text) => {
                        el.textContent = text;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                    }""",
                    text,
                )
            except Exception:
                element.type(text, delay=5)

    # ── Response Extraction (runs on worker thread) ───────────────────────────

    def _extract_stable_response_impl(self, platform: str) -> str:
        page = self._get_page(platform)
        plat = self._platforms[platform]
        stability_wait = self._timing.get("stability_wait_s", 2.0)
        stability_samples = self._timing.get("stability_samples", 3)
        max_wait = self._timing.get("max_response_wait_s", 180)

        start_time = time.time()
        baseline = self._response_baselines.get(
            platform, self._get_response_snapshot(page, plat["response_selector"])
        )
        generation_seen = False
        response_seen = False
        network_idle_waited = False
        stable_count = 0
        last_text = ""

        try:
            self._status("⏳ Waiting for a new response...")
            while (time.time() - start_time) < max_wait:
                stop_btn = self._find_element(page, plat["stop_button"], timeout=1000)
                snapshot = self._get_response_snapshot(page, plat["response_selector"])
                is_new_response = self._is_new_response(snapshot, baseline)

                if stop_btn is not None and not generation_seen:
                    generation_seen = True
                    self._status("✅ Response started.")

                if stop_btn is None and response_seen and not network_idle_waited:
                    network_idle_timeout = self._timing.get("network_idle_timeout_s", 2.0)
                    self._status("⏳ Waiting for network idle...")
                    try:
                        page.wait_for_load_state("networkidle", timeout=network_idle_timeout * 1000)
                    except Exception:
                        pass
                    network_idle_waited = True
                    snapshot = self._get_response_snapshot(page, plat["response_selector"])
                    is_new_response = self._is_new_response(snapshot, baseline)

                if is_new_response:
                    if not response_seen:
                        response_seen = True
                        self._status("✅ New response detected.")

                    current_text = snapshot[1]
                    if current_text == last_text:
                        stable_count += 1
                        if stop_btn is None and stable_count >= stability_samples:
                            self._status("✅ Response stable.")
                            return current_text
                    else:
                        stable_count = 0
                    last_text = current_text

                time.sleep(max(stability_wait / max(stability_samples, 1), 0.1))

            if response_seen and last_text:
                self._status("⚠ Stability timeout — returning partial response.")
                return last_text

            raise TimeoutError(
                f"⏱ Timed out waiting for a new {platform} response after {max_wait}s."
            )
        finally:
            self._response_baselines.pop(platform, None)

    def _get_last_response_text(self, page: Page, selector: str) -> str | None:
        return self._get_response_snapshot(page, selector)[1] or None

    def _get_response_snapshot(self, page: Page, selector: str) -> tuple[int, str]:
        """Return the number of response nodes and latest Markdown response."""
        try:
            elements = page.query_selector_all(selector)
            if elements:
                latest = elements[-1]
                try:
                    markdown = latest.evaluate(_RESPONSE_TO_MARKDOWN_SCRIPT)
                    if isinstance(markdown, str) and markdown.strip():
                        return len(elements), markdown.strip()
                except Exception:
                    pass
                return len(elements), latest.inner_text().strip()
        except Exception:
            pass
        return 0, ""

    @staticmethod
    def _is_new_response(
        snapshot: tuple[int, str], baseline: tuple[int, str]
    ) -> bool:
        """Whether a response node appeared or the latest response changed."""
        count, text = snapshot
        baseline_count, baseline_text = baseline
        return bool(text) and (count > baseline_count or text != baseline_text)

    # ── Utility (runs on worker thread) ───────────────────────────────────────

    def _find_element(self, page: Page, selector: str, timeout: int = 5000):
        selectors = [s.strip() for s in selector.split(",")]
        for sel in selectors:
            try:
                locator = page.locator(sel).first
                locator.wait_for(state="visible", timeout=timeout // len(selectors))
                return locator
            except Exception:
                continue
        return None

    def _is_connected_impl(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    def _list_open_tabs_impl(self) -> list[dict]:
        if not self._context:
            return []
        tabs = []
        for page in self._context.pages:
            try:
                tabs.append({"title": page.title(), "url": page.url})
            except Exception:
                pass
        return tabs

    def _find_input_and_button_fallback(self, page: Page):
        """Heuristic fallback to find the largest contenteditable input and send button."""
        input_el = None
        try:
            inputs = page.locator('[contenteditable="true"]').all()
            max_area = -1
            for el in inputs:
                if el.is_visible():
                    box = el.bounding_box()
                    if box:
                        area = box['width'] * box['height']
                        if area > max_area:
                            max_area = area
                            input_el = el
        except Exception:
            pass

        send_btn = None
        try:
            buttons = page.locator('button[aria-label*="Send" i]').all()
            if not buttons:
                buttons = page.locator('button:has-text("Send"), button:has-text("Submit")').all()
            
            max_area = -1
            for el in buttons:
                if el.is_visible():
                    box = el.bounding_box()
                    if box:
                        area = box['width'] * box['height']
                        if area > max_area:
                            max_area = area
                            send_btn = el
        except Exception:
            pass

        return input_el, send_btn

# Register atexit handler to ensure the playwright worker is stopped gracefully
@atexit.register
def _cleanup_playwright_worker():
    worker = _PlaywrightWorker._instance
    if worker is not None:
        worker.stop_playwright()
