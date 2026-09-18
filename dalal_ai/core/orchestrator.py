"""
Orchestrator — the core routing logic engine.

Implements the hybrid context strategy:
  - Same model as last turn → send raw message (use platform's native history)
  - Different model → inject formatted transcript + user message (context switch)
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from dalal_ai.browser.browser_manager import BrowserManager
from dalal_ai.core.context_manager import ContextManager
from dalal_ai.core.document_extractor import prepare_attachments
from dalal_ai.core.flagged_context_manager import FlaggedContextManager
from utils.exceptions import BrowserActionRequired, ResponseCaptureTimeout

StatusCallback = Optional[Callable[[str], None]]


class Orchestrator:
    """
    Routes user messages to the correct platform and manages context injection.

    Parameters
    ----------
    browser : BrowserManager
        Connected browser automation instance.
    context : ContextManager
        Local conversation history tracker.
    config : dict
        Full application configuration.
    on_status : callable, optional
        Callback for progress messages (used by the web UI).
    """

    def __init__(
        self,
        browser: BrowserManager,
        context: ContextManager,
        config: dict[str, Any],
        on_status: StatusCallback = None,
    ) -> None:
        self.browser = browser
        self.context = context
        self.config = config
        self._platforms: dict[str, dict] = config["platforms"]
        self._attachments: dict[str, Any] = config.get("attachments", {}) or {}
        self._on_status = on_status

    def _attachment_char_cap(self) -> Optional[int]:
        """Per-file character ceiling from config; None disables capping."""
        cap = self._attachments.get("max_chars_per_file")
        try:
            cap = int(cap)
        except (TypeError, ValueError):
            return None
        return cap if cap > 0 else None

    def _status(self, message: str) -> None:
        """Emit a progress message to the registered callback."""
        if self._on_status:
            self._on_status(message)

    def send_message(
        self,
        platform: str,
        user_message: str,
        flagged_mgr: Optional[FlaggedContextManager] = None,
        selected_red_ids: Optional[list[int]] = None,
        files: Optional[list[str]] = None,
        page_ranges: Optional[dict[str, tuple[int, int]]] = None,
    ) -> str:
        """
        Send a message to the specified platform and return the response.

        Implements the hybrid context strategy:
        - Condition A: same model → send raw text, let native history work
        - Condition B: different model → inject full transcript as context

        Parameters
        ----------
        platform : str
            Target platform name: "chatgpt", "claude", "gemini", "deepseek", "kimi", "huggingchat", or "metaai".
        user_message : str
            The user's raw message text.
        flagged_mgr : FlaggedContextManager, optional
            The manager handling the red/green flag filtering.
        selected_red_ids : list[int], optional
            The indices of red-flagged messages explicitly selected by the user.
        files : list[str], optional
            Attachment paths to send with this message.
        page_ranges : dict[str, tuple[int, int]], optional
            Per-path 1-based inclusive page ranges, set by the UI when a
            document is too large to send whole.

        Returns
        -------
        str  The assistant's response text.
        """
        if platform not in self._platforms:
            raise ValueError(
                f"Unknown platform '{platform}'. "
                f"Available: {', '.join(self._platforms.keys())}"
            )

        is_switch = self.context.is_model_switch(platform)

        needs_context = is_switch
        if flagged_mgr and flagged_mgr.has_pending_context(
            self.context.messages, platform, selected_red_ids
        ):
            needs_context = True

        if needs_context and self.context.messages:
            if is_switch:
                self._status(
                    f"🔄 Context switch detected → injecting history into {platform}"
                )
            else:
                self._status(
                    f"🟢 Injecting pending flagged context into {platform}"
                )

            all_files = list(files) if files else []
            if flagged_mgr:
                # Select without committing: if the browser send fails, this
                # context must stay pending instead of being marked delivered
                # to a model that never saw it.
                selected = flagged_mgr.build_context(
                    self.context.messages, platform, selected_red_ids, commit=False
                )
                for msg in selected:
                    if msg.get("files"):
                        all_files.extend(msg["files"])
            else:
                selected = []

            transcript_limit = self.config.get("context", {}).get("max_transcript_chars")

            transcript = self.context.build_context_transcript(
                messages=selected, max_chars=transcript_limit
            )
            full_prompt = f"{transcript}\n\n**User:** {user_message}" if transcript else user_message
        else:
            selected = []
            full_prompt = user_message
            all_files = list(files) if files else []

        # Read every attachment once, here, and decide how each one travels.
        # Extraction used to happen inside the browser layer, on the Playwright
        # thread, with a raw errors="replace" read that turned PDFs and .docx
        # files into mojibake.
        plan = prepare_attachments(
            all_files,
            max_chars=self._attachment_char_cap(),
            page_ranges=page_ranges,
        )
        for note in plan.notes:
            self._status(f"📎 {note}")
        if plan.inline_suffix:
            full_prompt = full_prompt + plan.inline_suffix

        try:
            self.browser.send_organic_prompt(
                platform,
                full_prompt,
                files=plan.native_paths,
                file_texts=plan.fallback_text,
            )
        except RuntimeError as exc:
            raise BrowserActionRequired(platform, str(exc)) from exc

        # The prompt is in the tab: only now is the context genuinely delivered.
        if flagged_mgr:
            if selected:
                flagged_mgr.commit_delivery(self.context.messages, platform, selected)
            else:
                flagged_mgr.mark_contacted(platform)

        self.context.add_message(
            "user",
            user_message,
            model=platform,
            files=files,
            attachments=[
                {
                    "name": doc.name,
                    "path": doc.path,
                    "format": doc.format,
                    "pages_sent": doc.pages_included,
                    "page_count": doc.page_count,
                    "chars_sent": doc.char_count,
                    "truncated": doc.truncated,
                }
                for doc in plan.documents
            ] or None,
        )

        try:
            response = self.browser.extract_stable_response(platform)
        except TimeoutError as exc:
            raise ResponseCaptureTimeout(platform, str(exc)) from exc

        self.context.add_message("assistant", response, model=platform)
        return response

    def record_manual_response(self, platform: str, user_message: str, response: str) -> str:
        """Record a full turn when automation never sent the user message."""
        self.context.add_message("user", user_message, model=platform)
        self.context.add_message("assistant", response, model=platform)
        return response

    def complete_manual_response(self, response: str) -> str:
        """Add assistant reply when the user message is already in history."""
        if not self.context.messages or self.context.messages[-1]["role"] != "user":
            raise ValueError("No pending user message to complete.")
        platform = self.context.messages[-1]["model"]
        self.context.add_message("assistant", response, model=platform)
        return response

    def get_available_platforms(self) -> list[str]:
        """Return list of configured platform names."""
        return list(self._platforms.keys())
