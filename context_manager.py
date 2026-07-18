"""
Context Manager — local conversation history database.

Stores all messages (user + assistant) with timestamps and model labels.
Provides formatted transcript generation for cross-model context injection.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any


class ContextManager:
    """Tracks the full conversation history across all platforms."""

    def __init__(self, persist_path: str | None = None):
        self.messages: list[dict[str, Any]] = []
        self.last_used_model: str | None = None
        self._persist_path = persist_path

        # Load persisted history if it exists
        if persist_path and os.path.isfile(persist_path):
            try:
                with open(persist_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError("History file must contain an object")
                messages = data.get("messages", [])
                if not isinstance(messages, list):
                    raise ValueError("History messages must be a list")
                self.messages = [
                    message for message in messages
                    if isinstance(message, dict)
                    and message.get("role") in {"user", "assistant"}
                    and isinstance(message.get("content"), str)
                    and isinstance(message.get("model"), str)
                ]
                self.last_used_model = data.get("last_used_model")
                if not isinstance(self.last_used_model, str):
                    self.last_used_model = (
                        self.messages[-1]["model"] if self.messages else None
                    )
            except (json.JSONDecodeError, IOError, ValueError, TypeError):
                pass  # start fresh

    # ── Core Operations ───────────────────────────────────────────────────────

    def add_message(self, role: str, content: str, model: str) -> None:
        """
        Record a message in the local history.

        Parameters
        ----------
        role : str   "user" or "assistant"
        content : str   The message text
        model : str   Platform name (chatgpt / claude / gemini)
        """
        if role not in {"user", "assistant"}:
            raise ValueError("role must be 'user' or 'assistant'")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a non-empty string")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")

        self.messages.append({
            "role": role,
            "content": content,
            "model": model,
            "timestamp": datetime.now().isoformat(),
        })
        self.last_used_model = model
        self._auto_save()

    def is_model_switch(self, target_model: str) -> bool:
        """Return True if switching to a different model than the last one used."""
        if self.last_used_model is None:
            return False  # first message ever — no switch
        return self.last_used_model != target_model

    def build_context_transcript(self, max_chars: int = 12000) -> str:
        """
        Format the entire conversation history into a markdown transcript
        block suitable for pasting into a new platform's input box.

        Parameters
        ----------
        max_chars : int
            Maximum character length for the transcript. Oldest messages
            are trimmed first if the limit is exceeded.

        Returns
        -------
        str  The formatted transcript text.
        """
        if not self.messages:
            return ""

        if max_chars <= 0:
            return ""

        # Build lines in chronological order so the transcript remains natural.
        lines: list[str] = []
        for msg in self.messages:
            role_label = "User" if msg["role"] == "user" else f"Assistant ({msg['model']})"
            timestamp = msg.get("timestamp", "")
            line = f"**{role_label}** [{timestamp}]:\n{msg['content']}"
            lines.append(line)

        # Assemble the transcript
        header = (
            "### 📋 System Context — Conversation History\n"
            "The following is the full conversation history from previous exchanges "
            "with different AI models. Continue the conversation naturally based on "
            "this context.\n\n---\n\n"
        )
        footer = "\n\n---\n\n**Continue the conversation below. Respond to the user's latest message.**"

        body = "\n\n".join(lines)

        # Truncate from the front (oldest messages) if over limit.  A single
        # very long latest message is trimmed too, so the documented maximum
        # is always honoured.
        marker = "[...earlier messages trimmed...]\n\n"
        available = max_chars - len(header) - len(footer)
        if available <= 0:
            return (header + footer)[:max_chars]

        while len(body) > available and len(lines) > 1:
            lines.pop(0)
            body = marker + "\n\n".join(lines)

        if len(body) > available:
            if available <= len(marker):
                body = marker[:available]
            else:
                body = marker + body[-(available - len(marker)):]

        return header + body + footer

    def get_last_assistant_response(self) -> str | None:
        """Return the content of the most recent assistant message, or None."""
        for msg in reversed(self.messages):
            if msg["role"] == "assistant":
                return msg["content"]
        return None

    def clear(self) -> None:
        """Hard reset — wipe all history."""
        self.messages.clear()
        self.last_used_model = None
        self._auto_save()

    def get_stats(self) -> dict:
        """Return summary statistics."""
        user_msgs = sum(1 for m in self.messages if m["role"] == "user")
        asst_msgs = sum(1 for m in self.messages if m["role"] == "assistant")
        models_used = set(m["model"] for m in self.messages)
        total_chars = sum(len(m["content"]) for m in self.messages)
        return {
            "total_messages": len(self.messages),
            "user_messages": user_msgs,
            "assistant_messages": asst_msgs,
            "models_used": sorted(models_used),
            "total_characters": total_chars,
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _auto_save(self) -> None:
        """Persist state to disk if a path was configured."""
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump({
                    "messages": self.messages,
                    "last_used_model": self.last_used_model,
                }, f, indent=2, ensure_ascii=False)
        except IOError:
            pass  # non-critical
