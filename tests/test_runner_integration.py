"""End-to-end run of the real packaged V1 YAML through google-adk with a scripted model.

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


def test_v1_end_to_end_with_scripted_model(repo: Path, tmp_path: Path):
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    task = Task("toy_1", "local/toy", "HEAD", "clamp() returns the lower bound for values above `high`.")
    steps = [
        ("run_skill_script", {"skill_name": "repo-navigation", "file_path": "scripts/nav.py",
                              "args": ["find", "clamp"]}),
        ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": "return low  # BUG: should return high",
                       "new_string": "return high"}),
        ("run_skill_script", {"skill_name": "test-discovery", "file_path": "scripts/tests.py",
                              "args": ["run", "tests/test_mathutil.py"]}),
        "I think I'm done.",                      # text-only turn -> harness nudge
        ("run_skill_script", {"skill_name": "debugging", "file_path": "scripts/review.py", "args": []}),
        ("submit_patch", {}),
        "Fixed clamp upper bound.",
    ]
    llm = ScriptedLlm(model="scripted", steps=list(steps), seen_requests=[])
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin", "SWE_WORKSPACE": str(repo), "PYTHONPATH": str(repo)}
    import os, sys
    env["PATH"] = os.path.dirname(sys.executable) + ":" + env["PATH"]
    trace = tmp_path / "trace.jsonl"
    outcome = asyncio.run(run_agent(build, task, repo, tmp_path / "tmp", Budget(tool_calls=40, time_minutes=2),
                                    None, env, trace, model_factory=lambda *_: llm))

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
    # The system instruction the model saw is our prompt, with the skill list appended by ADK.
    sys_text = str(llm.seen_requests[0].config.system_instruction)
    assert "senior software engineer" in sys_text and "repo-navigation" in sys_text
    first_user = events[0]["text"]
    assert "Problem Statement:" in first_user and "## Workspace Layout" in first_user
