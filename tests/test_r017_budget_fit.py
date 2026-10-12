"""R017: a faithful adaptation of the Budget-Fit single agent (reference archive members byte-match the bundle
independently reproduced at 0.18 public; docs/r017.md), plus our code-edit skill as the safe-edit fallback.

The retired R016 module tested R016's own configuration (R015 coder prompt lineage); this module carries the
still-applicable protections (single root, R013 tool guard, thinking, scripted edit runs, enforced budgets).
"""

import asyncio
import hashlib
import subprocess
from pathlib import Path

import yaml

from g4agent.compiler import compile_submission
from g4agent.harness.runner import run_agent
from g4agent.harness.tasks import Task
from g4agent.harness.tools import Budget
from g4agent.loader import load_yaml
from g4agent.packager import PROJECT, package
from g4agent.validator import validate_dir

from test_runner_integration import ScriptedLlm, _agent_of, _env

# Member sha256 of the Budget-Fit archive (verracodeguacas output, sha256 1cb73986...); identical to the members the
# independent reproduction (dmitriigluzdov, "Measure Before You Tune", QUICK_FILES) rebuilt and scored at 0.18.
REFERENCE = {
    "configs/sampling.yaml": "571a934e89911734927533f1d36cbcc7b8d493592febe63b217e911cf7ed4926",
    "eval_config.yaml": "916cf6cb34a6cc3de39837fa72cac681599b9ac2a3ee0b893adadfd36474c531",
    "prompts/system.md": "475cc9b7fcc0dc295532f5cb5e1928f26a491f501837ad08b1c79bdbe1a3eaa4",
}
REFERENCE_TOOLS = ["run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch",
                   "get_code_neighbors", "search_similar_code", "get_code_subgraph"]
CODE_EDIT_SHA256 = {  # our safe-edit mechanism, unchanged since V1.3 (121bd79)
    "skills/code-edit/SKILL.md": "122c970c0ec7622e09cc16af1b9c53ba2384274cdd9d0b3eaa970dab13e4ab9d",
    "skills/code-edit/scripts/edit.py": "13a38363c69cb514356c47a03ebff31bb10e2df63cd438a5602d65b2aead5787",
}
FALLBACK_ANCHOR = "- For documentation code tasks (e.g. FastAPI), edit executable code under `docs_src/`.\n"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _root() -> dict:
    return load_yaml(PROJECT, PROJECT / "agent.yaml").data


def _prompt() -> str:
    return (PROJECT / "prompts/system.md").read_text()


# --------------------------------------------------------------------------- fidelity to the reproduced reference


def test_sampling_and_budgets_are_the_reference_bytes():
    for rel in ("configs/sampling.yaml", "eval_config.yaml"):
        assert _sha((PROJECT / rel).read_bytes()) == REFERENCE[rel], rel
    ev = yaml.safe_load((PROJECT / "eval_config.yaml").read_text())["evaluation"]
    assert ev == {"timeout_seconds": 240, "max_tool_calls": 28, "max_time_minutes": 8, "max_turns": 80}
    s = yaml.safe_load((PROJECT / "configs/sampling.yaml").read_text())
    assert s["thinking_config"] == {"thinking_budget": 4096, "include_thoughts": True} and s["temperature"] == 0.2


def test_prompt_is_the_reference_plus_one_fallback_bullet():
    text = _prompt()
    i = text.index(FALLBACK_ANCHOR) + len(FALLBACK_ANCHOR)
    j = text.index("\n", i) + 1
    bullet = text[i:j]
    assert bullet.startswith("- If `edit_file` fails twice") and '"replace"' in bullet
    assert _sha((text[:i] + text[j:]).encode()) == REFERENCE["prompts/system.md"]


def test_root_is_the_reference_single_agent_with_code_edit():
    root = _root()
    assert root.get("agent_class", "LlmAgent") == "LlmAgent" and "sub_agents" not in root
    assert "include_contents" not in root                      # receives the harness task message
    assert root["model"] == "gemma-4-31b-it-qat-w4a16-ct"
    assert root["tools"] == REFERENCE_TOOLS and root["skills"] == ["skills/code-edit"]
    for rel, sha in CODE_EDIT_SHA256.items():
        assert _sha((PROJECT / rel).read_bytes()) == sha, rel


def test_package_is_six_files(tmp_path: Path):
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    files = sorted(p.relative_to(build).as_posix() for p in build.rglob("*") if p.is_file())
    assert files == ["agent.yaml", "configs/sampling.yaml", "eval_config.yaml", "prompts/system.md",
                     "skills/code-edit/SKILL.md", "skills/code-edit/scripts/edit.py"]


def test_validator_and_adk_compile_with_only_the_documented_warnings(tmp_path: Path):
    build = tmp_path / "build"                                   # the packaged tree, as submitted
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    report = validate_dir(build, compile_adk=True)
    assert report.ok, report.render()
    assert len(report.warnings) == 2
    assert any("28-call cap" in w and "measured full-run projection" in w for w in report.warnings)
    assert any("timeout_seconds=240" in w for w in report.warnings)
    agent = compile_submission(build)
    assert type(agent).__name__ == "LlmAgent" and not agent.sub_agents
    tc = agent.generate_content_config.thinking_config
    assert tc.include_thoughts is True and tc.thinking_budget == 4096


def test_time_cap_without_a_call_cap_is_still_an_error(submission: Path):
    """The 8-min cap is only accepted because the harness ends a session at max_tool_calls."""
    p = submission / "eval_config.yaml"
    p.write_text(p.read_text().replace("  max_tool_calls: 28\n", ""))
    errs = validate_dir(submission).errors
    assert any("can EXCEED the run budget" in e for e in errs), errs


# ----------------------------------------------------------------------------------- R013 undeclared-tool guard


def test_guard_rejects_a_skill_that_names_a_tool_the_agent_lacks(submission: Path):
    p = submission / "agent.yaml"
    p.write_text(p.read_text().replace("  - run_command\n", ""))      # code-edit's SKILL.md names run_command
    assert any("names tool 'run_command'" in e for e in validate_dir(submission).errors)


def test_guard_rejects_a_call_to_a_missing_tool_in_the_instruction(submission: Path):
    p = submission / "agent.yaml"
    p.write_text(p.read_text().replace("  - get_code_subgraph\n", ""))
    (submission / "prompts" / "system.md").write_text(_prompt() + '\nThen call get_code_subgraph(["a", "b"]).\n')
    assert any("instruction shows a call to 'get_code_subgraph'" in e for e in validate_dir(submission).errors)


# ------------------------------------------------------------------------- scripted runs (real google-adk)

BUG = "return low  # BUG: should return high"
GREP = ("run_command", {"command": "git grep -n 'def clamp' -- '*.py' | head -20"})
READ = ("read_file", {"filepath": "pkg/mathutil.py", "start_line": 1, "end_line": 20})
TEST = ("run_command", {"command": "python3 -m pytest -q tests/test_mathutil.py"})
PROBE = ("run_command", {"command": "python3 -c \"from pkg.mathutil import clamp; print(clamp(50, 0, 10))\""})


def _run(steps, repo: Path, tmp_path: Path, tool_calls: int = 28):
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    task = Task("toy_1", "local/toy", "HEAD", "clamp() returns the lower bound for values above `high`.")
    llm = ScriptedLlm(model="scripted", steps=list(steps), seen_requests=[])
    tmp = tmp_path / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = {**_env(repo), "TMPDIR": str(tmp.resolve())}         # as the subprocess sandbox sets it
    outcome = asyncio.run(run_agent(build, task, repo, tmp, Budget(tool_calls=tool_calls, time_minutes=2, turns=80),
                                    None, env, tmp_path / "t.jsonl", model_factory=lambda *_: llm))
    return outcome, llm


def test_contract_flow_grep_read_edit_test_submit(repo: Path, tmp_path: Path):
    steps = [GREP, READ, ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": BUG, "new_string": "return high"}),
             TEST, ("submit_patch", {}), "Fixed clamp."]
    outcome, llm = _run(steps, repo, tmp_path)
    assert outcome.stop_reason == "submitted" and "return high" in outcome.patch
    assert all(_agent_of(r) == "coder" for r in llm.seen_requests)
    assert "Budget: 28 tool calls, 8 minutes" in str(llm.seen_requests[0].config.system_instruction)


def test_edit_file_failure_falls_back_to_code_edit_replace(repo: Path, tmp_path: Path):
    """Safe-edit fallback: edit_file misses (escaped text), code-edit `replace` from /tmp files lands the fix."""
    bad = ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": "return low  \\# BUG", "new_string": "return high"})
    steps = [GREP, READ, bad, bad,
             ("run_command", {"command": "cat > /tmp/old.txt <<'EOF'\n        return low  # BUG: should return high\nEOF"}),
             ("run_command", {"command": "cat > /tmp/new.txt <<'EOF'\n        return high\nEOF"}),
             ("run_skill_script", {"skill_name": "code-edit", "file_path": "scripts/edit.py",
                                   "args": ["replace", "pkg/mathutil.py", "@/tmp/old.txt", "@/tmp/new.txt"]}),
             TEST, ("submit_patch", {}), "Fixed."]
    outcome, llm = _run(steps, repo, tmp_path)
    assert outcome.stop_reason == "submitted" and "return high" in outcome.patch and BUG not in outcome.patch.split("+")[-1]
    outs = [str(p.function_response.response) for r in llm.seen_requests for c in r.contents for p in c.parts
            if p.function_response and p.function_response.name == "run_skill_script"]
    assert any("EDITED pkg/mathutil.py" in x for x in outs)


def test_hard_call_cap_ends_the_session_and_keeps_an_early_edit(repo: Path, tmp_path: Path):
    """28 calls: no call beyond the cap executes, and an edit made by call 3 survives an endless probe loop.

    Our local runner refuses calls past the cap but only ends the session between turns (here: at its LLM-call
    limit); swegemma 0.2.11's agent_runner ends the loop at the cap ("Agent exceeded tool call budget").
    """
    fix = ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": BUG, "new_string": "return high"})
    outcome, _ = _run([GREP, READ, fix, *[PROBE] * 60], repo, tmp_path, tool_calls=28)
    executed = [e for e in outcome.tool_log if e.get("counted") and not str(e.get("status")).startswith("error:Budget")]
    assert outcome.tool_calls == 28 and len(executed) == 28 and "return high" in outcome.patch
    assert any(str(e.get("status")).startswith("error:Budget") for e in outcome.tool_log)   # call 29+ refused
    subprocess.run(["git", "checkout", "--", "."], cwd=repo, check=True)
    late, _ = _run([GREP, READ, *[PROBE] * 60, fix], repo, tmp_path / "late", tool_calls=28)
    assert late.tool_calls == 28 and "pkg/mathutil.py" not in late.patch                    # the late edit never ran


def test_an_undeclared_tool_call_is_not_silently_accepted_locally(repo: Path, tmp_path: Path):
    """Our local runner (no harness ToolErrorPlugin) ends on an unknown tool; the official harness returns an error."""
    outcome, _ = _run([("apply_patch", {"diff": "x"})], repo, tmp_path)
    assert outcome.stop_reason == "agent_error" and "apply_patch" in outcome.error and not outcome.patch
