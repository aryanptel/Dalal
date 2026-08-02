"""
Context Manager — local conversation history database.

Stores all messages (user + assistant) with timestamps and model labels.
Provides formatted transcript generation for cross-model context injection.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

from utils.logger import logger


class ContextManager:
    """Tracks the full conversation history across all platforms."""

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self.messages: list[dict[str, Any]] = []
        self.last_used_model: Optional[str] = None
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

                # Ensure all loaded messages have a flag field
                flags_loaded = 0
                for msg in self.messages:
                    if "flag" not in msg:
                        msg["flag"] = None
                    elif msg["flag"] is not None:
                        flags_loaded += 1

                logger.info(
                    f"Restored {len(self.messages)} messages with {flags_loaded} flags set."
                )

                self.last_used_model = data.get("last_used_model")
                if not isinstance(self.last_used_model, str):
                    self.last_used_model = (
                        self.messages[-1]["model"] if self.messages else None
                    )
            except (json.JSONDecodeError, IOError, ValueError, TypeError) as exc:
                logger.warning(f"Could not load history from {persist_path}: {exc}")

    # ── Core Operations ───────────────────────────────────────────────────────

    def add_message(self, role: str, content: str, model: str, flag: Optional[str] = None, swarm_role: Optional[str] = None) -> None:
        """
        Record a message in the local history.

        Parameters
        ----------
        role : str   "user" or "assistant"
        content : str   The message text
        model : str   Platform name (chatgpt / claude / gemini)
        flag : Optional[str]  "green", "red", or None
        swarm_role : Optional[str]  "moderator", "worker", or None
        """
        if role not in {"user", "assistant"}:
            raise ValueError("role must be 'user' or 'assistant'")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content must be a non-empty string")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        if flag not in {None, "green", "red"}:
            raise ValueError("flag must be 'green', 'red', or None")

        self.messages.append({
            "role": role,
            "content": content,
            "model": model,
            "flag": flag,
            "swarm_role": swarm_role,
            "timestamp": datetime.now().isoformat(),
        })
        self.last_used_model = model
        self._auto_save()

    def is_model_switch(self, target_model: str) -> bool:
        """Return True if switching to a different model than the last one used."""
        if self.last_used_model is None:
            return False  # first message ever — no switch
        return self.last_used_model != target_model

    def update_flag(self, index: int, new_flag: Optional[str]) -> None:
        """Update the flag for a specific message and save."""
        if 0 <= index < len(self.messages):
            if new_flag not in {None, "green", "red"}:
                raise ValueError("flag must be 'green', 'red', or None")
            self.messages[index]["flag"] = new_flag
            self._auto_save()

    def build_context_transcript(
        self,
        max_chars: Optional[int] = 20000,
        messages: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        """
        Format conversation history into a markdown transcript block suitable
        for pasting into a new platform's input box.

        Parameters
        ----------
        max_chars : Optional[int]
            Maximum character length for the transcript. Oldest messages
            are trimmed first if the limit is exceeded. If None, no truncation occurs.
        messages : list[dict[str, Any]], optional
            Specific list of messages to format. Defaults to self.messages.

        Returns
        -------
        str  The formatted transcript text.
        """
        msgs_to_format = messages if messages is not None else self.messages
        if not msgs_to_format:
            return ""

        if max_chars is not None and max_chars <= 0:
            return ""

        # Build lines in chronological order so the transcript remains natural.
        lines: list[str] = []
        for msg in msgs_to_format:
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

        return header + body + footer

    def get_last_assistant_response(self) -> Optional[str]:
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

    def get_stats(self) -> dict[str, Any]:
        """Return basic statistics about the current history."""
        total_chars = sum(len(m["content"]) for m in self.messages)
        models = {m["model"] for m in self.messages if m["role"] == "assistant"}
        user_count = sum(1 for m in self.messages if m["role"] == "user")
        assistant_count = sum(1 for m in self.messages if m["role"] == "assistant")
        return {
            "total_messages": len(self.messages),
            "total_characters": total_chars,
            "models_used": list(models),
            "user_messages": user_count,
            "assistant_messages": assistant_count,
        }

    def export_session(self, export_dir: str) -> tuple[str, str]:
        """Export current session as JSON and Markdown files to *export_dir*."""
        os.makedirs(export_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        json_path = os.path.join(export_dir, f"session_export_{timestamp}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "last_used_model": self.last_used_model,
                "messages": self.messages
            }, f, indent=2)

        md_path = os.path.join(export_dir, f"session_transcript_{timestamp}.md")
        lines = ["# Chat Session Transcript\n"]
        for msg in self.messages:
            role_label = "User" if msg["role"] == "user" else f"Assistant ({msg['model']})"
            ts = msg.get("timestamp", "")
            lines.append(f"### {role_label} [{ts}]\n\n{msg['content']}\n\n---\n")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return json_path, md_path

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
