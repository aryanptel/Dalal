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
        # Models this session has already talked to.  Tracked separately from
        # session_delivered because "first contact" and "has received messages"
        # are different questions: a first switch that carries no green flags
        # delivers nothing, and keying off an empty set would make every later
        # turn look like a first contact and re-send the whole green history.
        self.contacted: set[str] = set()
        self.max_tokens = max_tokens

    def reset_model(self, model_name: str) -> None:
        """Clear the delivery history for a specific model."""
        self.session_delivered.pop(model_name, None)
        self.contacted.discard(model_name)

    def clear_all(self) -> None:
        """Reset delivery history for all models."""
        self.session_delivered.clear()
        self.contacted.clear()

    def reset_model_context(self, model_name: str) -> None:
        """Alias for :meth:`reset_model` (kept for backward compatibility)."""
        self.reset_model(model_name)

    # ── Selection ─────────────────────────────────────────────────────────────

    def _select(
        self,
        chat_history: list[dict[str, Any]],
        target_model: str,
        selected_red_ids: Optional[list[int]] = None,
    ) -> list[tuple[int, dict[str, Any]]]:
        """
        Pure selection: the (index, message) pairs owed to *target_model*.

        No state is mutated here, so a caller can select, attempt the browser
        send, and only then record what was actually delivered.
        """
        red_ids = set(selected_red_ids or ())

        if not any(msg.get("flag") in {"green", "red"} for msg in chat_history):
            # Strict mode: with no flags anywhere, nothing is shared.
            return []

        delivered = self.session_delivered.get(target_model, set())
        is_first_time = target_model not in self.contacted

        picked: list[tuple[int, dict[str, Any]]] = []
        for i, msg in enumerate(chat_history):
            if i in delivered:
                continue
            flag = msg.get("flag")
            if is_first_time and flag == "green":
                picked.append((i, msg))
            elif flag == "red" and i in red_ids:
                picked.append((i, msg))
        return picked

    def build_context(
        self,
        chat_history: list[dict[str, Any]],
        target_model: str,
        selected_red_ids: Optional[list[int]] = None,
        commit: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Build the list of messages to inject into *target_model*.

        Behaviour
        ---------
        1. Strict mode: if no flags exist in *chat_history*, returns an empty
           list (no context sent).
        2. First contact with a model: gather all green-flagged messages.
        3. Later turns: gather only the explicitly selected red-flagged
           messages that have not been delivered to that model yet.

        Parameters
        ----------
        commit : bool
            ``True`` (default) marks the selection as delivered immediately —
            the historical behaviour.  Pass ``False`` to select without
            recording, then call :meth:`commit_delivery` once the prompt has
            actually reached the browser.  Committing up front loses the
            context permanently whenever the send then fails.

        Returns a chronologically ordered subset of *chat_history*.
        """
        picked = self._select(chat_history, target_model, selected_red_ids)
        if commit:
            self._commit(target_model, [i for i, _ in picked])
        return [msg for _, msg in picked]

    def _commit(self, target_model: str, indices: list[int]) -> None:
        self.contacted.add(target_model)
        delivered = self.session_delivered.setdefault(target_model, set())
        delivered.update(indices)

    def commit_delivery(
        self,
        chat_history: list[dict[str, Any]],
        target_model: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """
        Record that *messages* reached *target_model*.

        Matches by identity against *chat_history*, so it stays correct even if
        two messages happen to have the same text.
        """
        by_id = {id(msg): i for i, msg in enumerate(chat_history)}
        self._commit(target_model, [by_id[id(m)] for m in messages if id(m) in by_id])

    def mark_contacted(self, target_model: str) -> None:
        """
        Record a successful turn with *target_model* that carried no context.

        The empty entry is kept so the UI still offers a "reset context" control
        for a model that has been talked to but was never sent anything.
        """
        self._commit(target_model, [])

    def has_pending_context(
        self,
        chat_history: list[dict[str, Any]],
        target_model: str,
        selected_red_ids: Optional[list[int]] = None,
    ) -> bool:
        """Return True if there is undelivered context for *target_model*."""
        return bool(self._select(chat_history, target_model, selected_red_ids))
