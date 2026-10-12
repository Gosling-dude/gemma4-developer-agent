"""End-to-end run of the real packaged YAML (R012: localizer -> V1.3 coder) through google-adk with a scripted model.

This exercises everything except the language model itself: YAML compile, SkillToolset + run_skill_script
through our sandbox executor, harness tools, the nudge loop, submit_patch, and Phase-2 verification.
"""

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from g4agent.harness.runner import run_agent
from g4agent.harness.tasks import Task
from g4agent.harness.tools import Budget
from g4agent.packager import package


class ScriptedLlm(BaseLlm):
    """Replays a fixed list of steps. A step is (tool_name, args) or a plain text reply."""

    steps: list = []
    seen_requests: list = []

    async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        self.seen_requests.append(llm_request)
        step = self.steps.pop(0) if self.steps else "done"
        if isinstance(step, str):
            part = types.Part(text=step)
        else:
            part = types.Part(function_call=types.FunctionCall(name=step[0], args=step[1]))
        yield LlmResponse(content=types.Content(role="model", parts=[part]),
                          usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=10,
                                                                                   candidates_token_count=5))


PLAN = ("FILE: pkg/mathutil.py\nSYMBOL: clamp\nCAUSE: pkg/mathutil.py:5-6 returns low for values above high\n"
        "EDIT: return high in that branch\nCHECK: tests/test_mathutil.py")


def _env(repo: Path) -> dict:
    import os, sys
    return {"PATH": os.path.dirname(sys.executable) + ":/usr/bin:/bin:/opt/homebrew/bin",
            "SWE_WORKSPACE": str(repo), "PYTHONPATH": str(repo)}


def _agent_of(request) -> str:
    return "localizer" if "read-only LOCALIZER" in str(request.config.system_instruction) else "coder"


def _contents_text(request) -> str:
    return " ".join(str(p.text or "") + str(p.function_response or "") for c in request.contents for p in c.parts)


def test_single_agent_end_to_end_with_scripted_model(repo: Path, tmp_path: Path):
    """Packaged R016 tree: one coder agent receives the harness task message, locates, edits, tests, reviews, submits."""
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    task = Task("toy_1", "local/toy", "HEAD", "clamp() returns the lower bound for values above `high`.")
    steps = [
        ("run_skill_script", {"skill_name": "repo-navigation", "file_path": "scripts/nav.py", "args": ["find", "clamp"]}),
        ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": "return low  # BUG: should return high",
                       "new_string": "return high"}),
        ("run_skill_script", {"skill_name": "test-discovery", "file_path": "scripts/tests.py",
                              "args": ["run", "tests/test_mathutil.py"]}),
        "I think I'm done.",                      # text-only turn -> harness nudge -> the same agent continues
        ("run_skill_script", {"skill_name": "debugging", "file_path": "scripts/review.py", "args": []}),
        ("submit_patch", {}),
        "Fixed clamp upper bound.",
    ]
    llm = ScriptedLlm(model="scripted", steps=list(steps), seen_requests=[])
    trace = tmp_path / "trace.jsonl"
    outcome = asyncio.run(run_agent(build, task, repo, tmp_path / "tmp", Budget(tool_calls=40, time_minutes=2),
                                    None, _env(repo), trace, model_factory=lambda *_: llm))

    assert outcome.stop_reason == "submitted", outcome
    assert outcome.submitted and "return high" in outcome.patch
    assert outcome.nudges_sent == 1
    events = [json.loads(l) for l in trace.read_text().splitlines()]
    responses = [r for e in events for r in e.get("responses", [])]
    runs = [r for r in responses if r["name"] == "run_skill_script"]
    assert "pkg/mathutil.py" in runs[0]["response"] and "DEFINITIONS" in runs[0]["response"]
    assert "ALL SELECTED TESTS PASSED" in runs[1]["response"] and "VERDICT: READY" in runs[2]["response"]

    reqs = llm.seen_requests
    assert reqs and all(_agent_of(r) == "coder" for r in reqs)          # one agent, no localizer stage
    first = reqs[0]
    # The issue, budget and workspace tree arrive in the harness message itself (include_contents default).
    assert "Problem Statement:" in _contents_text(first) and "## Workspace Layout" in _contents_text(first)
    assert "clamp() returns the lower bound" in _contents_text(first)
    sys_text = str(first.config.system_instruction)
    assert "repair_plan" not in sys_text and "localizer" not in sys_text.lower() and "Start from" not in sys_text
    assert {"run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch",
            "get_code_neighbors", "search_similar_code", "get_code_subgraph",
            "load_skill", "run_skill_script"} <= set(first.tools_dict)
    # After the nudge the same agent keeps its history (its earlier tool output is still in context).
    assert "DEFINITIONS" in _contents_text(reqs[-1])
