"""
Flagged Context Manager — deterministic, user-controlled context filtering.

Provides precise control over what conversation context is shared with each
AI model during model switches, using explicit green/red flag annotations.

Green flags mark messages for automatic first-time injection.
Red flags mark messages available for on-demand selective injection.
"""

from __future__ import annotations

from typing import Any, Optional




class FlaggedContextManager:
    """
    Manages context delivery based on user-set message flags.

    Parameters
    ----------
    max_tokens : int
        Token budget passed to :class:`ContextCompressor` when falling back
        to algorithmic compression (i.e. when no flags exist). Default 4000.
    """

    def __init__(self, max_tokens: int = 4000) -> None:
        # Maps model_name → set of message indices already delivered to it
        self.session_delivered: dict[str, set[int]] = {}
        self.max_tokens = max_tokens

    def reset_model(self, model_name: str) -> None:
        """Clear the delivery history for a specific model."""
        self.session_delivered.pop(model_name, None)

    def clear_all(self) -> None:
        """Reset delivery history for all models."""
        self.session_delivered.clear()

    def reset_model_context(self, model_name: str) -> None:
        """Alias for :meth:`reset_model` (kept for backward compatibility)."""
        self.reset_model(model_name)

    def build_context(
        self,
        chat_history: list[dict[str, Any]],
        target_model: str,
        selected_red_ids: Optional[list[int]] = None,
    ) -> list[dict[str, Any]]:
        """
        Build the list of messages to inject into *target_model*.

        Behaviour
        ---------
        1. Strict mode: If no flags exist in *chat_history*, returns an empty
           list (no context sent).
        2. First time a model is seen: gather all green-flagged messages,
           mark them delivered.
        3. Subsequent uses: gather only explicitly selected red-flagged
           messages that haven't been delivered yet.

        Returns a chronologically ordered subset of *chat_history*.
        """
        if selected_red_ids is None:
            selected_red_ids = []

        # Check if there are any flags at all in the history
        has_any_flags = any(msg.get("flag") in {"green", "red"} for msg in chat_history)

        if not has_any_flags:
            # Strict mode: If no flags are set, do not send any context.
            return []

        if target_model not in self.session_delivered:
            self.session_delivered[target_model] = set()

        delivered_to_model = self.session_delivered[target_model]
        context_msgs: list[dict[str, Any]] = []
        is_first_time = len(delivered_to_model) == 0

        for i, msg in enumerate(chat_history):
            flag = msg.get("flag")

            if is_first_time and flag == "green":
                # First time interacting: send all green-flagged messages
                context_msgs.append(msg)
                delivered_to_model.add(i)
            elif flag == "red" and i in selected_red_ids and i not in delivered_to_model:
                # Attach requested red flags not yet delivered
                context_msgs.append(msg)
                delivered_to_model.add(i)

        return context_msgs

    def has_pending_context(
        self,
        chat_history: list[dict[str, Any]],
        target_model: str,
        selected_red_ids: Optional[list[int]] = None,
    ) -> bool:
        """Return True if there is undelivered context for *target_model*."""
        if selected_red_ids is None:
            selected_red_ids = []

        has_any_flags = any(msg.get("flag") in {"green", "red"} for msg in chat_history)
        if not has_any_flags:
            return False

        delivered_to_model = self.session_delivered.get(target_model, set())
        is_first_time = len(delivered_to_model) == 0

        for i, msg in enumerate(chat_history):
            flag = msg.get("flag")
            if is_first_time and flag == "green":
                return True
            if flag == "red" and i in selected_red_ids and i not in delivered_to_model:
                return True

        return False
