"""Custom exceptions for the web orchestrator."""

from __future__ import annotations

class OrchestratorError(Exception):
    """Base exception."""


class BrowserActionRequired(OrchestratorError):
    """Automation failed; user must complete an action in the browser."""

    def __init__(self, platform: str, detail: str) -> None:
        self.platform = platform
        self.detail = detail
        super().__init__(detail)


class ResponseCaptureTimeout(OrchestratorError):
    """Timed out waiting for a model response."""

    def __init__(self, platform: str, detail: str) -> None:
        self.platform = platform
        self.detail = detail
        super().__init__(detail)
