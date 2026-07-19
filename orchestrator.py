"""
Orchestrator — the core routing logic engine.

Implements the hybrid context strategy:
  - Same model as last turn → send raw message (use platform's native history)
  - Different model → inject formatted transcript + user message (context switch)
"""

from __future__ import annotations

from typing import Any, Callable

from browser_manager import BrowserManager
from context_manager import ContextManager
from utils.exceptions import BrowserActionRequired, ResponseCaptureTimeout

StatusCallback = Callable[[str], None] | None

from context_compressor import ContextCompressor
from flagged_context_manager import FlaggedContextManager

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
    ):
        self.browser = browser
        self.context = context
        self.config = config
        self._platforms = config["platforms"]
        self._on_status = on_status

    def _status(self, message: str) -> None:
        if self._on_status:
            self._on_status(message)

    def send_message(
        self,
        platform: str,
        user_message: str,
        flagged_mgr: FlaggedContextManager | None = None,
        selected_red_ids: list[int] | None = None
    ) -> str:
        """
        Send a message to the specified platform and return the response.

        Implements the hybrid context strategy:
        - Condition A: same model → send raw text, let native history work
        - Condition B: different model → inject full transcript as context

        Parameters
        ----------
        platform : str
            Target platform name: "chatgpt", "claude", "gemini", or "deepseek".
        user_message : str
            The user's raw message text.
        flagged_mgr : FlaggedContextManager, optional
            The manager handling the red/green flag filtering.
        selected_red_ids: list[int], optional
            The indices of red-flagged messages explicitly selected by the user.

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

        if is_switch and self.context.messages:
            self._status(
                f"🔄 Context switch detected → injecting history into {platform}"
            )
            if flagged_mgr:
                selected = flagged_mgr.build_context(
                    self.context.messages, platform, selected_red_ids
                )
            else:
                compressor = ContextCompressor()
                selected = compressor.build_context(self.context.messages, user_message)
                
            transcript = self.context.build_context_transcript(messages=selected, max_chars=12000)
            if transcript:
                full_prompt = f"{transcript}\n\n**User:** {user_message}"
            else:
                full_prompt = user_message
        else:
            full_prompt = user_message

        try:
            self.browser.send_organic_prompt(platform, full_prompt)
        except RuntimeError as exc:
            raise BrowserActionRequired(platform, str(exc)) from exc

        self.context.add_message("user", user_message, model=platform)

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
