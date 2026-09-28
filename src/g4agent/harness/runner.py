"""Run a packaged submission on one task through google-adk, like the harness's Phase 1.

Reproduces the documented protocol (HARNESS_README section 5): session state (problem_description, hints),
the structured initial prompt, the outer loop with up to 3 continuation nudges, termination on
submit_patch, budgets, and patch extraction with fallback to the working-tree diff.

The model is any OpenAI-compatible endpoint (vLLM serving Gemma 4, a Gemma model on another
provider, etc.) configured via environment variables. See docs/experiments.md.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from google.adk.code_executors.base_code_executor import BaseCodeExecutor
from google.adk.code_executors.code_execution_utils import CodeExecutionInput, CodeExecutionResult
from google.adk.runners import Runner
from google.adk.agents.run_config import RunConfig
from google.adk.sessions import InMemorySessionService
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from ..compiler import compile_submission
from .graph import CodeGraph
from .tasks import Task
from .tools import Budget, LocalHarness

NUDGE_CUTOFF_TOOL = (
    "Your previous response reached the token limit before the tool call finished closing (<|tool_call|> was cut off). "
    "Do NOT repeat your prior reasoning in thought—emit your next tool call immediately, and if calling edit_file or "
    "write_file, split the change into smaller incremental edits.")
NUDGE_MAX_TOKENS = (
    "Your previous response reached the token limit while thinking before a tool call was completed. Do NOT repeat "
    "your analysis in thought—keep reasoning under a few sentences and emit your next tool call immediately, or call "
    "submit_patch when you have completed and verified your changes.")
NUDGE_NORMAL = ("Please continue your work using the available tools, or call submit_patch when you have completed "
                "and verified your changes.")
MAX_NUDGES = 3


def build_agent_prompt(task: Task, budget: Budget, workspace: Path, graph_available: bool) -> str:
    """Initial user message, following the 7 sections in HARNESS_README section 5.2."""
    parts = [f"You are evaluating a software engineering task for repository {task.repo}.\n\n"
             f"Problem Statement:\n{task.problem_statement}"]
    if task.hints_text.strip():
        parts.append(f"## Hints:\n{task.hints_text}")
    lines = ["## Task Budget (Session terminates when any budget is exhausted)",
             f"- Time allowance: {budget.time_minutes:.1f} minutes"]
    if budget.tool_calls is not None:
        lines.append(f"- Tool calls allowance: {budget.tool_calls} calls")
    if budget.turns is not None:
        lines.append(f"- Max loop iterations: {budget.turns} turns")
    parts.append("\n".join(lines))
    parts.append("## Execution Environment Rules\n"
                 f"- Single command timeout: {budget.command_timeout_seconds} seconds (commands exceeding this fail "
                 "without ending the session)\n"
                 "- Command output limit: 5000 characters\n"
                 "- File view limit: 150 lines per read_file call\n"
                 "- File character limit: 10000 characters per read_file call\n"
                 "- Environment is offline (no network/PyPI access). All repository and test dependencies are ALREADY "
                 "pre-installed. Do NOT attempt to run pip install or download packages.")
    parts.append("## Instructions\n"
                 "0. Work strictly under /workspace.\n"
                 "1. Inspect the existing code and follow its conventions.\n"
                 "2. Implement the change needed to resolve the problem statement.\n"
                 "3. Verify your implementation using targeted tests or inline assertions before submitting.\n"
                 "4. Call submit_patch once your change is complete.\n"
                 "5. Then reply with a short final text response.")
    if graph_available:
        parts.append("## Code Intelligence Tools\n"
                     "This repository has pre-built code graph and embedding data. Use these tools for fast, targeted "
                     "navigation:\n"
                     "- `search_similar_code(query)`: Find semantically similar functions/classes by keyword.\n"
                     "- `get_code_neighbors(node)`: Find callers, callees, and definitions related to a symbol.\n"
                     "- `get_code_subgraph(nodes)`: Get the induced subgraph for a set of symbols.")
    listing = subprocess.run("find . -maxdepth 3 -not -path './.git*' -not -name '*.pyc' -not -path '*__pycache__*' "
                             "| sort | head -150", shell=True, cwd=workspace, capture_output=True, text=True).stdout
    parts.append(f"## Workspace Layout\n```\n{listing.strip()}\n```")
    return "\n\n".join(parts)


class SandboxExecutor(BaseCodeExecutor):
    """Runs skill scripts with the task's Python and SWE_WORKSPACE, like the harness runs them in the container."""

    python: str = sys.executable
    env: dict[str, str] = {}
    timeout: int = 300
    stateful: bool = False
    optimize_data_file: bool = False

    def execute_code(self, invocation_context: Any, code_execution_input: CodeExecutionInput) -> CodeExecutionResult:
        try:
            r = subprocess.run([self.python, "-c", code_execution_input.code], capture_output=True, text=True,
                               timeout=self.timeout, env=self.env or None)
            return CodeExecutionResult(stdout=r.stdout[:5000], stderr=r.stderr[-5000:])
        except subprocess.TimeoutExpired:
            return CodeExecutionResult(stdout="", stderr=f"script timed out after {self.timeout}s")


@dataclasses.dataclass
class RunOutcome:
    patch: str
    submitted: bool
    stop_reason: str
    tool_calls: int
    llm_turns: int
    nudges_sent: int
    seconds: float
    prompt_tokens: int
    output_tokens: int
    tool_log: list[dict]
    error: str = ""


def make_model_factory() -> Any:
    """LiteLlm bound to $G4_API_BASE / $G4_MODEL / $G4_API_KEY (an OpenAI-compatible endpoint)."""
    import litellm
    from google.adk.models.lite_llm import LiteLlm

    litellm.drop_params = True  # as in the harness
    api_base = os.environ.get("G4_API_BASE")
    served = os.environ.get("G4_MODEL")
    if not served:
        raise RuntimeError("set G4_MODEL (and G4_API_BASE / G4_API_KEY) to run agents; see docs/experiments.md")

    def factory(_declared: str, _adapter: str | None) -> Any:
        kwargs: dict[str, Any] = {"model": served if "/" in served else f"openai/{served}", "num_retries": 5}
        if api_base:
            kwargs["api_base"] = api_base
        if os.environ.get("G4_API_KEY"):
            kwargs["api_key"] = os.environ["G4_API_KEY"]
        return LiteLlm(**kwargs)

    return factory


async def run_agent(submission_dir: Path, task: Task, workspace: Path, tmp_dir: Path, budget: Budget,
                    graph: CodeGraph | None, env: dict[str, str], trace_path: Path,
                    model_factory: Any = None) -> RunOutcome:
    harness = LocalHarness(workspace, tmp_dir, budget, graph, env)
    fns = harness.tool_functions()
    python = shutil.which("python3", path=env.get("PATH")) or sys.executable
    executor = SandboxExecutor(python=python, env=env, timeout=budget.command_timeout_seconds)
    agent = compile_submission(submission_dir, tool_factory=lambda n: FunctionTool(fns[n]),
                               model_factory=model_factory or make_model_factory(), code_executor=executor)
    runner = Runner(app_name="swegemma_eval", agent=agent, session_service=InMemorySessionService())
    state = {"problem_description": task.problem_statement}
    if task.hints_text.strip():
        state["hints"] = task.hints_text.strip()
    session = await runner.session_service.create_session(app_name="swegemma_eval", user_id="eval_user", state=state)
    run_config = RunConfig(max_llm_calls=budget.turns or 500)

    message = build_agent_prompt(task, budget, workspace, graph is not None)
    trace = trace_path.open("w")
    trace.write(json.dumps({"type": "prompt", "text": message}) + "\n")
    harness.start()
    started = time.monotonic()
    nudges = consecutive = turns = ptoks = otoks = 0
    stop, error = "", ""
    try:
        while True:
            turn_tool_call, last_text, finish = False, "", ""

            async def one_turn() -> None:
                nonlocal turn_tool_call, last_text, finish, turns, ptoks, otoks
                content = types.Content(role="user", parts=[types.Part(text=message)])
                async for ev in runner.run_async(user_id="eval_user", session_id=session.id, new_message=content,
                                                 run_config=run_config):
                    rec = _event_record(ev)
                    trace.write(json.dumps(rec) + "\n")
                    if ev.usage_metadata:
                        turns += 1
                        ptoks += ev.usage_metadata.prompt_token_count or 0
                        otoks += ev.usage_metadata.candidates_token_count or 0
                    if ev.get_function_calls():
                        turn_tool_call = True
                    if rec.get("text"):
                        last_text = rec["text"]
                    if ev.finish_reason:
                        finish = str(ev.finish_reason)
                    if harness.patch_submitted and ev.is_final_response():
                        return

            try:
                await asyncio.wait_for(one_turn(), timeout=max(1.0, harness.remaining_seconds()))
            except asyncio.TimeoutError:
                stop = "time_budget"
                break
            if harness.patch_submitted:
                stop = "submitted"
                break
            if harness.out_of_time():
                stop = "time_budget"
                break
            if budget.tool_calls is not None and harness.tool_calls_used >= budget.tool_calls:
                stop = "tool_budget"
                break
            if budget.turns is not None and turns >= budget.turns:
                stop = "turn_budget"
                break
            consecutive = 0 if turn_tool_call else consecutive + 1
            if consecutive > MAX_NUDGES:
                stop = "max_nudges"
                break
            if "<|tool_call>" in last_text and "<tool_call|>" not in last_text:
                message = NUDGE_CUTOFF_TOOL
            elif "MAX_TOKENS" in finish.upper() or "LENGTH" in finish.upper():
                message = NUDGE_MAX_TOKENS
            else:
                message = NUDGE_NORMAL
            nudges += 1
            trace.write(json.dumps({"type": "nudge", "text": message}) + "\n")
    except Exception as exc:  # model/server errors end the attempt; the working tree is still graded
        stop, error = "agent_error", f"{type(exc).__name__}: {exc}"
    finally:
        trace.close()
    patch = harness.submitted_patch if harness.patch_submitted else harness.extract_patch()
    return RunOutcome(patch, harness.patch_submitted, stop, harness.tool_calls_used, turns, nudges,
                      round(time.monotonic() - started, 1), ptoks, otoks, harness.calls, error)


def _event_record(ev: Any) -> dict:
    rec: dict[str, Any] = {"type": "event", "author": ev.author}
    texts, thoughts = [], []
    for part in (ev.content.parts if ev.content and ev.content.parts else []):
        if part.text:
            (thoughts if part.thought else texts).append(part.text)
        if part.function_call:
            rec.setdefault("calls", []).append({"name": part.function_call.name,
                                                "args": _trim(dict(part.function_call.args or {}))})
        if part.function_response:
            resp = part.function_response.response
            rec.setdefault("responses", []).append({"name": part.function_response.name,
                                                    "response": str(resp)[:1500]})
    if texts:
        rec["text"] = "\n".join(texts)[:4000]
    if thoughts:
        rec["thought"] = "\n".join(thoughts)[:4000]
    if ev.usage_metadata:
        rec["usage"] = {"prompt": ev.usage_metadata.prompt_token_count,
                        "output": ev.usage_metadata.candidates_token_count}
    return rec


def _trim(args: dict) -> dict:
    return {k: (v[:1500] if isinstance(v, str) else v) for k, v in args.items()}
