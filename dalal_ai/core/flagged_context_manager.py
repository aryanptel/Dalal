"""
Flagged Context Manager

Provides context filtering based on explicit user flags (green/red) to precisely
control what context is shared with each AI model.
"""

from __future__ import annotations

from typing import Any, Optional

from dalal_ai.core.context_compressor import ContextCompressor


class FlaggedContextManager:
    def __init__(self, max_tokens: int = 4000):
        # Maps model_name to a set of message indices that have been delivered to it
        self.session_delivered: dict[str, set[int]] = {}
        self.max_tokens = max_tokens

    def reset_model(self, model_name: str) -> None:
        """Clear the delivery history for a specific model."""
        if model_name in self.session_delivered:
            del self.session_delivered[model_name]
            
    def clear_all(self) -> None:
        """Reset session_delivered entirely."""
        self.session_delivered.clear()

    def reset_model_context(self, model_name: str) -> None:
        """Alias for reset_model for backwards compatibility."""
        self.reset_model(model_name)

    def build_context(
        self,
        chat_history: list[dict[str, Any]],
        target_model: str,
        selected_red_ids: Optional[list[int]] = None
    ) -> list[dict[str, Any]]:
        """
        Builds the context list of messages to be sent to the target model.
        Returns a subset of chat_history.
        """
        if selected_red_ids is None:
            selected_red_ids = []

        # Check if there are any flags at all in the history
        has_any_flags = any(msg.get("flag") in {"green", "red"} for msg in chat_history)

        if not has_any_flags:
            # Fallback to the mathematical compressor for backward compatibility
            compressor = ContextCompressor()
            # In older implementation compressor might not take max_tokens in build_context,
            # but the spec asks to use it if available or just fallback.
            return compressor.build_context(chat_history, "")

        if target_model not in self.session_delivered:
            self.session_delivered[target_model] = set()

        delivered_to_model = self.session_delivered[target_model]
        context_msgs = []
        is_first_time = len(delivered_to_model) == 0

        for i, msg in enumerate(chat_history):
            flag = msg.get("flag")

            if is_first_time and flag == "green":
                # First time interacting: Send all green-flagged messages
                context_msgs.append(msg)
                delivered_to_model.add(i)
            elif flag == "red" and i in selected_red_ids and i not in delivered_to_model:
                # Attach requested red flags that haven't been delivered yet (works for both first time and subsequent times)
                context_msgs.append(msg)
                delivered_to_model.add(i)

        return context_msgs

    def has_pending_context(
        self,
        chat_history: list[dict[str, Any]],
        target_model: str,
        selected_red_ids: Optional[list[int]] = None
    ) -> bool:
        """Returns True if there is context that needs to be delivered to the target model."""
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
            elif flag == "red" and i in selected_red_ids and i not in delivered_to_model:
                return True

        return False
