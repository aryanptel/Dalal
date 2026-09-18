import json
import re
from typing import Generator, Any, Optional

from dalal_ai.browser.browser_manager import BrowserManager
from dalal_ai.core.context_manager import ContextManager
from dalal_ai.core.document_extractor import prepare_attachments
from dalal_ai.core.flagged_context_manager import FlaggedContextManager
from utils.logger import logger

MODERATOR_SYSTEM_PROMPT = """
You are acting as the LEAD MODERATOR of an AI Swarm (managing {workers_str}).
Your task is to solve complex user problems by decomposing them into sub-tasks, delegating to worker agents, and delivering a final synthesized solution.

--- PROTOCOL INSTRUCTIONS ---

MODE 1: DELEGATION (When you need information or sub-tasks from worker agents)
If you require workers to gather facts, draft code, or audit ideas, output ONLY a valid JSON block:

```json
{{
  "status": "delegating",
  "plan": [
    {{
      "agent": "{example_agent_1}",
      "role": "Security Auditor",
      "task": "Examine the authentication module for vulnerabilities..."
    }},
    {{
      "agent": "{example_agent_2}",
      "role": "Performance Engineer",
      "task": "Analyze the time complexity of the database logic..."
    }}
  ]
}}
```
Do not output any text before or after the JSON block in Mode 1.

MODE 2: FINAL ANSWER (When you have enough information to solve the user's request)
Once all delegated sub-tasks are complete, or if no delegation is needed, output your final comprehensive answer in PURE, UNWRAPPED MARKDOWN. 
DO NOT wrap your final answer in JSON. DO NOT use the {{"status": "complete"}} format. Just write the Markdown normally.
"""

# A runaway plan would open a browser tab per sub-task, so cap it.
MAX_SUBTASKS_PER_ROUND = 8


class SwarmOrchestrator:
    def __init__(
        self,
        browser_manager: BrowserManager,
        context_manager: ContextManager,
        config: Optional[dict[str, Any]] = None,
    ):
        self.browser = browser_manager
        self.context = context_manager
        self.config = config or {}

    def _attachment_char_cap(self) -> Optional[int]:
        """Per-file character ceiling from config; None disables capping."""
        cap = (self.config.get("attachments") or {}).get("max_chars_per_file")
        try:
            cap = int(cap)
        except (TypeError, ValueError):
            return None
        return cap if cap > 0 else None

    def _record(
        self, content: str, model: str, swarm_role: str, role: str = "assistant"
    ) -> None:
        """
        Append to history, tolerating an empty body.

        ContextManager rejects empty content, and a worker that timed out or was
        never reached returns exactly that — which used to raise mid-round and
        abort the whole swarm run after the expensive part was already done.
        """
        text = (content or "").strip()
        if not text:
            text = f"[{model} returned no content]"
        try:
            self.context.add_message(role, text, model, swarm_role=swarm_role)
        except ValueError as exc:
            logger.warning(f"Could not record {swarm_role} message for {model}: {exc}")

    # ── Moderator reply parsing ──────────────────────────────────────────────

    @staticmethod
    def _sanitize_json(text: str) -> str:
        r"""
        Double any backslash that is not a legal JSON escape.

        Models routinely put LaTeX (``\\frac``) or Windows paths (``C:\\Users``)
        inside JSON strings, which is invalid JSON.  Legal escapes
        (``\\" \\\\ \\/ \\b \\f \\n \\r \\t \\uXXXX``) are left alone.
        """
        return re.sub(r'\\(?![\\"\\\\/bfnrtu])', r'\\\\', text)

    @staticmethod
    def _iter_json_candidates(text: str):
        r"""
        Yield every balanced ``{...}`` span in *text*, outermost first.

        A greedy ``\{.*\}`` regex swallows prose that merely contains braces
        (LaTeX, code samples), so a balanced scan is used instead.  Braces
        inside JSON string literals are skipped.
        """
        fenced = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        for block in fenced:
            yield block

        depth = 0
        start = -1
        in_string = False
        escaped = False
        for i, ch in enumerate(text):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start >= 0:
                        yield text[start:i + 1]

    def _parse_moderator_reply(self, text: str) -> tuple[str, Any]:
        """
        Classify a moderator reply.

        Returns ``("delegate", plan_dict)`` only when the reply really is a
        delegation plan — a JSON object with ``status == "delegating"`` and a
        non-empty ``plan`` list.  Everything else is the final answer, returned
        as ``("final", markdown)``.

        The old code guessed: any parseable object counted, and an unparseable
        one was rebuilt with ``codecs.unicode_escape``, which corrupts LaTeX and
        Windows paths in the very answers it was trying to rescue.  Mode 2
        replies are plain Markdown by protocol, so "not a valid plan" is the
        correct and safe default.
        """
        for candidate in self._iter_json_candidates(text):
            for attempt in (candidate, self._sanitize_json(candidate)):
                try:
                    obj = json.loads(attempt, strict=False)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(obj, dict):
                    break
                plan = obj.get("plan")
                if obj.get("status") == "delegating" and isinstance(plan, list) and plan:
                    return "delegate", obj
                answer = obj.get("answer")
                if isinstance(answer, str) and answer.strip():
                    # Moderator wrapped its final answer in JSON anyway.
                    return "final", answer.strip()
                break
        return "final", text

    # ── Worker tab assignment ────────────────────────────────────────────────

    @staticmethod
    def _assign_worker_tabs(plan: list[dict], worker_ids: list[str]) -> list[str]:
        """
        Map each sub-task's requested ``agent`` onto a real worker tab id.

        The moderator writes free text, so it may answer ``"deepseek"`` with no
        index, name a worker that was never offered, or ask for an index that
        does not exist.  A bare platform name is the dangerous case: tab index 0
        is the *moderator's own* tab, so an unresolved ``"deepseek"`` used to
        drop a worker prompt straight into the moderator's conversation and
        corrupt the round.  Every id is therefore snapped onto ``worker_ids``,
        preferring an unused tab of the platform the moderator actually asked
        for.
        """
        by_platform: dict[str, list[str]] = {}
        for wid in worker_ids:
            by_platform.setdefault(wid.split(":", 1)[0], []).append(wid)

        used: set[str] = set()

        def first_free(candidates: list[str]) -> Optional[str]:
            for cand in candidates:
                if cand not in used:
                    return cand
            return candidates[0] if candidates else None

        assigned: list[str] = []
        for position, subtask in enumerate(plan):
            requested = str(subtask.get("agent", "") or "").strip().lower()
            platform = requested.split(":", 1)[0]

            if requested in worker_ids and requested not in used:
                tab = requested
            elif platform in by_platform:
                tab = first_free(by_platform[platform])
            else:
                tab = first_free(worker_ids) or worker_ids[position % len(worker_ids)]

            assigned.append(tab)
            used.add(tab)
        return assigned

    @staticmethod
    def _split_into_waves(assigned: list[str]) -> list[list[int]]:
        """
        Group sub-task positions so that no tab appears twice in one wave.

        Two prompts sent to the same tab before either reply is read loses the
        first reply outright.  Extra sub-tasks for a busy tab run in a later
        wave instead of being dropped or overwritten.
        """
        waves: list[list[int]] = []
        wave_tabs: list[set[str]] = []
        for position, tab in enumerate(assigned):
            for index, tabs in enumerate(wave_tabs):
                if tab not in tabs:
                    waves[index].append(position)
                    tabs.add(tab)
                    break
            else:
                waves.append([position])
                wave_tabs.append({tab})
        return waves

    def execute_swarm_task(
        self, 
        prompt: str, 
        moderator: str, 
        workers: list[str], 
        flagged_mgr: Optional[FlaggedContextManager] = None,
        selected_red_ids: Optional[list[int]] = None,
        max_rounds: int = 3,
        files: Optional[list[str]] = None,
        page_ranges: Optional[dict[str, tuple[int, int]]] = None,
    ) -> Generator[dict[str, Any], None, None]:
        """
        Execute the 4-Phase Swarm Loop.
        Yields status updates for the UI.
        """
        # Assign indices to workers
        worker_ids = []
        counts = {}
        
        # Reserve the primary index for the moderator so it's not reused!
        counts[moderator] = 1 
        
        for w in workers:
            counts[w] = counts.get(w, 0)
            worker_ids.append(f"{w}:{counts[w]}")
            counts[w] += 1
            
        workers_str = "[" + ", ".join(worker_ids) + "]"
        example_agent_1 = worker_ids[0] if len(worker_ids) > 0 else "chatgpt:0"
        example_agent_2 = worker_ids[1] if len(worker_ids) > 1 else example_agent_1

        # Phase 1: Initial Moderator Prompt
        mod_system = MODERATOR_SYSTEM_PROMPT.format(
            workers_str=workers_str,
            example_agent_1=example_agent_1,
            example_agent_2=example_agent_2
        )
        
        # Build context for moderator if flagged_mgr is provided.  Delivery is
        # committed only once the prompt has actually reached the tab.
        all_files = list(files) if files else []
        moderator_context: list[dict[str, Any]] = []
        if flagged_mgr:
            moderator_context = flagged_mgr.build_context(
                self.context.messages, moderator, selected_red_ids, commit=False
            )
            for msg in moderator_context:
                if msg.get("files"):
                    all_files.extend(msg["files"])
            transcript = self.context.build_context_transcript(messages=moderator_context)
            if transcript:
                mod_system = f"{transcript}\n\n{mod_system}"

        # One plan, reused for every tab: extraction is cached, so a 300-page
        # PDF is parsed once no matter how many workers receive it.
        attachment_plan = prepare_attachments(
            all_files,
            max_chars=self._attachment_char_cap(),
            page_ranges=page_ranges,
        )

        full_prompt = f"{mod_system}\n\nUSER REQUEST:\n{prompt}"
        if attachment_plan.inline_suffix:
            full_prompt += attachment_plan.inline_suffix
        
        self.context.add_message("user", prompt, moderator, flag="green", swarm_role="moderator", files=files)
        
        current_prompt = full_prompt
        mod_response = ""
        round_num = 1
        
        while round_num <= max_rounds:
            yield {"type": "status", "message": f"Round {round_num}: Waiting for {moderator.capitalize()} (Moderator) plan..."}
            
            # Send to Moderator
            if round_num == 1:
                self.browser.send_organic_prompt(
                    moderator,
                    current_prompt,
                    files=attachment_plan.native_paths,
                    file_texts=attachment_plan.fallback_text,
                )
                if flagged_mgr and moderator_context:
                    flagged_mgr.commit_delivery(
                        self.context.messages, moderator, moderator_context
                    )
                    moderator_context = []
            else:
                self.browser.send_organic_prompt(moderator, current_prompt)
            mod_response = self.browser.extract_stable_response(moderator)
            
            # Phase 2 & 3: Parse and Dispatch
            kind, payload = self._parse_moderator_reply(mod_response)

            if kind == "final":
                answer = payload if isinstance(payload, str) and payload.strip() else mod_response
                self._record(answer, moderator, "moderator")
                yield {"type": "complete", "answer": answer}
                return

            plan = [item for item in payload.get("plan", []) if isinstance(item, dict)]
            if not plan:
                self._record(mod_response, moderator, "moderator")
                yield {"type": "complete", "answer": mod_response}
                return
            if len(plan) > MAX_SUBTASKS_PER_ROUND:
                logger.warning(
                    f"Moderator asked for {len(plan)} sub-tasks; capping at {MAX_SUBTASKS_PER_ROUND}."
                )
                plan = plan[:MAX_SUBTASKS_PER_ROUND]

            assigned = self._assign_worker_tabs(plan, worker_ids)
            plan_str = json.dumps({"status": "delegating", "plan": plan}, indent=2)
            yield {
                "type": "status",
                "message": (
                    f"Round {round_num}: delegating {len(plan)} sub-task(s) to "
                    f"{', '.join(sorted(set(assigned)))}...\n```json\n{plan_str}\n```"
                ),
            }

            # Build one prompt per sub-task, addressed to its resolved tab.
            worker_prompts: list[str] = []
            pending_context: list[Any] = []
            for position, subtask in enumerate(plan):
                tab = assigned[position]
                role = str(subtask.get("role", "Worker"))
                task = str(subtask.get("task", "")).strip()

                worker_prompt = f"Role: {role}\nTask: {task}"
                selected: list[dict[str, Any]] = []
                if flagged_mgr:
                    # Selection is not committed until the prompt actually lands
                    # in the tab, otherwise a failed send burns the context.
                    selected = flagged_mgr.build_context(
                        self.context.messages, tab, [], commit=False
                    )
                    transcript = self.context.build_context_transcript(messages=selected)
                    if transcript:
                        worker_prompt = f"{transcript}\n\n**Swarm Task:**\n{worker_prompt}"

                # Workers used to receive nothing but task text — the attachment
                # went to the moderator alone, so "have three models read this
                # paper" could not work. They get the same documents now, on the
                # round where the documents were supplied.
                if round_num == 1 and attachment_plan.has_attachments:
                    worker_prompt += attachment_plan.inline_suffix

                worker_prompts.append(worker_prompt)
                pending_context.append(selected)
                self._record(worker_prompt, tab, "worker", role="user")

            # Dispatch.  Sub-tasks that share a tab run in later waves: two
            # prompts in one tab before either reply is read loses the first.
            responses: list[str] = ["[No response]"] * len(plan)
            for wave_no, wave in enumerate(self._split_into_waves(assigned), start=1):
                if len(wave) < len(plan):
                    yield {
                        "type": "status",
                        "message": f"Round {round_num}: wave {wave_no} — {len(wave)} worker(s) running...",
                    }
                worker_files = (
                    attachment_plan.native_paths if round_num == 1 else []
                )
                worker_fallback = (
                    attachment_plan.fallback_text if round_num == 1 else ""
                )
                failures = self.browser.send_prompts_batch(
                    [
                        (assigned[i], worker_prompts[i], worker_files, worker_fallback)
                        for i in wave
                    ]
                ) or {}

                live = [i for i in wave if assigned[i] not in failures]
                for i in wave:
                    if assigned[i] in failures:
                        responses[i] = f"[Could not send task to {assigned[i]}: {failures[assigned[i]]}]"
                    elif flagged_mgr and pending_context[i]:
                        flagged_mgr.commit_delivery(
                            self.context.messages, assigned[i], pending_context[i]
                        )

                extracted = self.browser.extract_responses_batch([assigned[i] for i in live])
                for slot, i in enumerate(live):
                    if slot < len(extracted):
                        responses[i] = extracted[slot]

            # Aggregate results for the moderator.
            xml_results = []
            for position, subtask in enumerate(plan):
                tab = assigned[position]
                role = str(subtask.get("role", "Worker"))
                worker_response = responses[position] or "[Empty response]"
                xml_results.append(
                    f'<worker name="{tab}" role="{role}">\n{worker_response}\n</worker>'
                )
                self._record(worker_response, tab, "worker")

            aggregated_xml = "\n\n".join(xml_results)
            current_prompt = (
                f"Worker results:\n{aggregated_xml}\n\n"
                "Review the results. Output MODE 2 (plain Markdown) if you can now "
                "answer the user, or MODE 1 (a JSON plan) to delegate further."
            )
            yield {"type": "status", "message": f"Round {round_num}: Re-injecting results to Moderator..."}

            round_num += 1

        # Out of rounds: the moderator's last reply is the best answer we have,
        # so surface and persist it instead of throwing the round away.
        final_answer = mod_response or "Max rounds reached without an answer."
        self._record(final_answer, moderator, "moderator")
        yield {
            "type": "complete",
            "answer": (
                f"_Swarm stopped after {max_rounds} round(s); "
                f"showing the moderator's last reply._\n\n{final_answer}"
            ),
        }
