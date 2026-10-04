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


def test_r012_handoff_end_to_end_with_scripted_model(repo: Path, tmp_path: Path):
    """Packaged R012 tree: read-only localizer -> repair_plan -> V1.3 coder edits, tests, reviews, submits."""
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    task = Task("toy_1", "local/toy", "HEAD", "clamp() returns the lower bound for values above `high`.")
    steps = [
        # stage 1: localizer
        ("run_skill_script", {"skill_name": "repo-navigation", "file_path": "scripts/nav.py",
                              "args": ["find", "clamp"]}),
        PLAN,
        # stage 2: coder
        ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": "return low  # BUG: should return high",
                       "new_string": "return high"}),
        ("run_skill_script", {"skill_name": "test-discovery", "file_path": "scripts/tests.py",
                              "args": ["run", "tests/test_mathutil.py"]}),
        "I think I'm done.",                      # text-only turn -> harness nudge -> the sequence restarts
        PLAN,                                     # localizer, second pass: repeats the plan, no tool call
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
    nav = next(r for r in responses if r["name"] == "run_skill_script")
    assert "pkg/mathutil.py" in nav["response"] and "DEFINITIONS" in nav["response"]
    test_run = [r for r in responses if r["name"] == "run_skill_script"][1]
    assert "ALL SELECTED TESTS PASSED" in test_run["response"]
    review = [r for r in responses if r["name"] == "run_skill_script"][2]
    assert "VERDICT: READY" in review["response"]
    first_user = events[0]["text"]
    assert "Problem Statement:" in first_user and "## Workspace Layout" in first_user

    reqs = llm.seen_requests
    assert [_agent_of(r) for r in reqs] == ["localizer", "localizer", "coder", "coder", "coder",
                                            "localizer", "coder", "coder", "coder"]
    loc, coder = reqs[0], reqs[2]
    # Localizer: read-only tool set; sees the harness prompt (issue); first pass has no earlier plan.
    assert set(loc.tools_dict) == {"read_file", "get_status", "get_code_neighbors", "search_similar_code",
                                   "get_code_subgraph", "list_skills", "load_skill", "load_skill_resource",
                                   "run_skill_script"}
    assert "Problem Statement:" in _contents_text(loc)
    assert "Plan from an earlier pass: \n" in str(loc.config.system_instruction)
    # Coder: V1.3 tools; issue and plan arrive through its instruction; the localizer's tool output does not.
    assert {"run_command", "edit_file", "write_file", "submit_patch"} <= set(coder.tools_dict)
    coder_sys = str(coder.config.system_instruction)
    assert "clamp() returns the lower bound" in coder_sys and "Start from FILE: pkg/mathutil.py" in coder_sys
    assert "DEFINITIONS" not in _contents_text(coder) and "Problem Statement:" not in _contents_text(coder)
    # Nudge: the localizer re-runs with its plan in the instruction (it repeats it without tool calls).
    assert "Plan from an earlier pass: FILE: pkg/mathutil.py" in str(reqs[5].config.system_instruction)


def test_r012_coder_works_without_a_usable_plan(repo: Path, tmp_path: Path):
    """A malformed or empty localizer reply must not stop the coder from locating and fixing on its own."""
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    task = Task("toy_1", "local/toy", "HEAD", "clamp() returns the lower bound for values above `high`.")
    steps = [
        "I could not",                            # localizer: malformed plan, no tool calls
        ("run_skill_script", {"skill_name": "repo-navigation", "file_path": "scripts/nav.py",
                              "args": ["find", "clamp"]}),
        ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": "return low  # BUG: should return high",
                       "new_string": "return high"}),
        ("submit_patch", {}),
        "Fixed.",
    ]
    llm = ScriptedLlm(model="scripted", steps=list(steps), seen_requests=[])
    outcome = asyncio.run(run_agent(build, task, repo, tmp_path / "tmp", Budget(tool_calls=40, time_minutes=2),
                                    None, _env(repo), tmp_path / "t.jsonl", model_factory=lambda *_: llm))
    assert outcome.stop_reason == "submitted" and "return high" in outcome.patch, outcome
    coder = llm.seen_requests[1]
    assert _agent_of(coder) == "coder" and "Start from I could not" in str(coder.config.system_instruction)
