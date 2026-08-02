import json
import re
from typing import Generator, Any, Optional

from dalal_ai.browser.browser_manager import BrowserManager
from dalal_ai.core.context_manager import ContextManager
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

class SwarmOrchestrator:
    def __init__(self, browser_manager: BrowserManager, context_manager: ContextManager):
        self.browser = browser_manager
        self.context = context_manager

    def _extract_json(self, text: str) -> dict:
        """Robustly extract JSON block from text."""
        
        # Sanitize text: AI models often output LaTeX (e.g., \ref) inside JSON strings,
        # which creates invalid JSON escape sequences. We double-escape any backslash
        # that isn't part of a standard JSON escape sequence (like \", \\, \n).
        # We also allow \r and \t just in case they meant a literal tab/return, but
        # usually it's \ref or \textbf which are invalid.
        sanitized_text = re.sub(r'\\(?=[^"\\\\nrtbf])', r'\\\\', text)

        # Try to find markdown json block
        match = re.search(r'```json\s*(\{.*?\})\s*```', sanitized_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1), strict=False)
            except json.JSONDecodeError:
                pass
        
        # Try generic markdown block
        match = re.search(r'```\s*(\{.*?\})\s*```', sanitized_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1), strict=False)
            except json.JSONDecodeError:
                pass

        # Fallback to finding raw braces (greedy)
        match = re.search(r'\{.*\}', sanitized_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0), strict=False)
            except json.JSONDecodeError:
                pass
                
        # Final fallback: Manual regex extraction if the model completely butchered the JSON format
        status_match = re.search(r'"status"\s*:\s*"([^"]+)"', text)
        if status_match:
            status = status_match.group(1)
            if status == "complete":
                # Use greedy (.*) to capture everything up to the final quote, allowing for unescaped quotes inside
                answer_match = re.search(r'"answer"\s*:\s*"(.*)"\s*\}?$', text, re.DOTALL | re.IGNORECASE)
                if answer_match:
                    raw_answer = answer_match.group(1).strip()
                    try:
                        import codecs
                        raw_answer = codecs.decode(raw_answer, 'unicode_escape')
                    except Exception:
                        pass
                    return {"status": "complete", "answer": raw_answer}
                else:
                    # If we can't find answer nicely, just dump the whole text
                    return {"status": "complete", "answer": text}

        raise ValueError("Could not extract valid JSON from response")

    def execute_swarm_task(
        self, 
        prompt: str, 
        moderator: str, 
        workers: list[str], 
        flagged_mgr: Optional[FlaggedContextManager] = None,
        selected_red_ids: Optional[list[int]] = None,
        max_rounds: int = 3
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
        
        # Build context for moderator if flagged_mgr is provided
        if flagged_mgr:
            selected = flagged_mgr.build_context(self.context.messages, moderator, selected_red_ids)
            transcript = self.context.build_context_transcript(messages=selected)
            if transcript:
                mod_system = f"{transcript}\n\n{mod_system}"

        full_prompt = f"{mod_system}\n\nUSER REQUEST:\n{prompt}"
        
        self.context.add_message("user", prompt, moderator, flag="green", swarm_role="moderator")
        
        current_prompt = full_prompt
        round_num = 1
        
        while round_num <= max_rounds:
            yield {"type": "status", "message": f"Round {round_num}: Waiting for {moderator.capitalize()} (Moderator) plan..."}
            
            # Send to Moderator
            self.browser.send_organic_prompt(moderator, current_prompt)
            mod_response = self.browser.extract_stable_response(moderator)
            
            # Phase 2 & 3: Parse and Dispatch
            try:
                plan_json = self._extract_json(mod_response)
            except ValueError:
                logger.warning(f"Failed to parse JSON from moderator on round {round_num}. Treating as complete.")
                plan_json = {"status": "complete", "answer": mod_response}
                
            status = plan_json.get("status", "complete")
            
            if status == "complete":
                answer = plan_json.get("answer", mod_response)
                self.context.add_message("assistant", answer, moderator, swarm_role="moderator")
                yield {"type": "complete", "answer": answer}
                return
                
            elif status == "delegating":
                plan = plan_json.get("plan", [])
                plan_str = json.dumps(plan_json, indent=2)
                yield {"type": "status", "message": f"Round {round_num}: Delegating tasks to {len(plan)} workers in parallel...\n```json\n{plan_str}\n```"}
                
                # Dispatch in parallel
                prompts_to_send = []
                for subtask in plan:
                    agent = subtask.get("agent", example_agent_1).lower()
                    role = subtask.get("role", "Worker")
                    task = subtask.get("task", "")
                    
                    worker_prompt = f"Role: {role}\nTask: {task}"
                    
                    # Inject flagged context to worker if available
                    if flagged_mgr:
                        selected = flagged_mgr.build_context(self.context.messages, agent, [])
                        transcript = self.context.build_context_transcript(messages=selected)
                        if transcript:
                            worker_prompt = f"{transcript}\n\n**Swarm Task:**\n{worker_prompt}"
                            
                    prompts_to_send.append((agent, worker_prompt))
                    
                    self.context.add_message("user", worker_prompt, agent, swarm_role="worker")
                
                # Send prompts in batch
                self.browser.send_prompts_batch(prompts_to_send)
                
                # Extract responses in batch (Parallel Network Wait)
                platforms_to_extract = [p[0] for p in prompts_to_send]
                responses = self.browser.extract_responses_batch(platforms_to_extract)
                
                # Aggregate results via XML
                xml_results = []
                for subtask in plan:
                    agent = subtask.get("agent", example_agent_1).lower()
                    role = subtask.get("role", "Worker")
                    worker_response = responses.get(agent, "[No response or timeout]")
                    
                    xml_block = f'<worker name="{agent}" role="{role}">\n{worker_response}\n</worker>'
                    xml_results.append(xml_block)
                    
                    self.context.add_message("assistant", worker_response, agent, swarm_role="worker")
                
                aggregated_xml = "\n\n".join(xml_results)
                
                # Inject back to moderator
                current_prompt = f"Worker results:\n{aggregated_xml}\n\nReview the results. Output FORMAT 2 if complete, or FORMAT 1 to delegate further."
                yield {"type": "status", "message": f"Round {round_num}: Re-injecting results to Moderator..."}
                
            round_num += 1
            
        yield {"type": "complete", "answer": "Max rounds reached. Swarm terminated early."}
