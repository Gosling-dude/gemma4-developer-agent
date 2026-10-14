"""R019: R017's Budget-Fit agent with its tool budget guarded against the waste the R017/R018 traces show
(docs/r019.md): scratch files through run_command heredocs in /tmp, the code-edit fallback keyed to the edit_file
error that occurs, a finish step (one check + git status, cleanup, one submit) and a stop rule for an empty patch.

Replaces the R018 module; carries the still-applicable R017/R018 protections (reference bytes, single root, R013 tool
guard, thinking, enforced budgets, scripted real-ADK runs).

What is structural and what is not: write_file/read_file/edit_file reject paths outside /workspace in swegemma
itself (and now in our local re-implementation, with the same message); submit_patch is `budget_gated(count_tool_call=
False)`, so it stays callable after the 28-call cap, and the sandboxed submission schema resolves `before_tool_callbacks`
from a callback registry the scorer never passes. The empty-patch stop rule is therefore prompt-level; the harness
bounds the loop only through max_turns (80) and its 3 continuation nudges. The tests below say which is which.
"""

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from g4agent.compiler import compile_submission
from g4agent.harness.runner import run_agent
from g4agent.harness.tasks import Task
from g4agent.harness.tools import Budget, LocalHarness
from g4agent.loader import load_yaml
from g4agent.packager import PROJECT, package
from g4agent.validator import validate_dir

from test_runner_integration import ScriptedLlm, _agent_of, _env

# R017 (archive 51a6ef89..., docs/r017.md): sampling and eval_config are the Budget-Fit reference bytes.
R017_BYTES = {
    "configs/sampling.yaml": "571a934e89911734927533f1d36cbcc7b8d493592febe63b217e911cf7ed4926",
    "eval_config.yaml": "916cf6cb34a6cc3de39837fa72cac681599b9ac2a3ee0b893adadfd36474c531",
}
R017_PROMPT_SHA256 = "1a6c9face534ea52599de6640c611e9b54ff013906cb3c29e6ed96a4271c65ae"
R017_AGENT_SHA256 = "573036cd31f58cfe9b3feab3660cda1103705d08582c267c4ab5d4962c22b27b"
R017_CONTROL = PROJECT / "variants/r017_control"        # the overlay that rebuilds the R017 archive byte for byte
CODE_EDIT_SHA256 = {  # our safe-edit mechanism, unchanged since V1.3 (121bd79)
    "skills/code-edit/SKILL.md": "122c970c0ec7622e09cc16af1b9c53ba2384274cdd9d0b3eaa970dab13e4ab9d",
    "skills/code-edit/scripts/edit.py": "13a38363c69cb514356c47a03ebff31bb10e2df63cd438a5602d65b2aead5787",
}
GRAPH_TOOLS = {"get_code_neighbors", "search_similar_code", "get_code_subgraph"}
# What swegemma 0.2.11 answers to write_file('/tmp/...') (15 calls in 14/24 R018 tasks, each counted).
TRAVERSAL_ERROR = "Path traversal detected"
# What google-adk answers when Gemma's edit_file call drops old_string (21/54 R017 calls).
MISSING_PARAM_ERROR = "mandatory input parameters are not present"
OFFICIAL_PY = PROJECT / "evaluations/.cache/official_venv/bin/python"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _root() -> dict:
    return load_yaml(PROJECT, PROJECT / "agent.yaml").data


def _prompt() -> str:
    return (PROJECT / "prompts/system.md").read_text()


def _r017_prompt() -> str:
    text = (R017_CONTROL / "prompts/system.md").read_text()
    assert _sha(text.encode()) == R017_PROMPT_SHA256
    return text


# ------------------------------------------------------------------------------ R017 configuration preserved


def test_model_sampling_timeout_and_call_budget_are_r017_bytes():
    for rel, sha in R017_BYTES.items():
        assert _sha((PROJECT / rel).read_bytes()) == sha, rel
    ev = yaml.safe_load((PROJECT / "eval_config.yaml").read_text())["evaluation"]
    assert ev == {"timeout_seconds": 240, "max_tool_calls": 28, "max_time_minutes": 8, "max_turns": 80}
    s = yaml.safe_load((PROJECT / "configs/sampling.yaml").read_text())
    assert s["thinking_config"] == {"thinking_budget": 4096, "include_thoughts": True}
    assert (s["temperature"], s["top_p"], s["max_output_tokens"]) == (0.2, 0.95, 8192)


def test_root_is_r017_single_agent_with_the_same_model_tools_and_skill():
    root = _root()
    r017 = yaml.load((R017_CONTROL / "agent.yaml").read_text().replace("!include ", ""), Loader=yaml.SafeLoader)
    assert _sha((R017_CONTROL / "agent.yaml").read_bytes()) == R017_AGENT_SHA256
    for key in ("name", "model", "tools", "skills", "description"):
        assert root[key] == r017[key], key                     # only the leading comment and the prompt differ
    assert (r017["instruction"], r017["generate_content_config"]) == ("prompts/system.md", "configs/sampling.yaml")
    assert root["instruction"] == _prompt()
    assert root.get("agent_class", "LlmAgent") == "LlmAgent" and "sub_agents" not in root
    assert "include_contents" not in root                      # receives the harness task message
    assert root["model"] == "gemma-4-31b-it-qat-w4a16-ct" and GRAPH_TOOLS <= set(root["tools"])
    for rel, sha in CODE_EDIT_SHA256.items():
        assert _sha((PROJECT / rel).read_bytes()) == sha, rel  # safe-edit mechanism unchanged


def test_prompt_is_r017_plus_the_enumerated_r019_changes():
    """Every R017 line is kept except the ones R019 replaces; every new line belongs to one of the four changes."""
    old = [l.rstrip() for l in _r017_prompt().splitlines()]
    new = [l.rstrip() for l in _prompt().splitlines()]
    removed = [l for l in old if l not in new]
    added = [l for l in new if l not in old]
    expected_removed = [
        "- If `edit_file` fails twice on the same change (old_string not found)",   # fallback trigger corrected
        "### 4. Immediate Patch Submission",                                           # finish step
        "- Once your targeted test passes:",
        "  1. Call `submit_patch` immediately.",
        "  2. Verify `patch_size > 0` and `files_changed > 0`.",
        "  3. Output a short summary of the fix to end the session.",
        "- After your edit: one compile check or one targeted test, a correction",    # budget: finish reserve
        "- Do NOT conclude without submitting a non-empty patch (`patch_size > 0`)",  # the rule that fed the loop
    ]
    assert len(removed) == len(expected_removed)
    for line, prefix in zip(removed, expected_removed):
        assert line.startswith(prefix), (line, prefix)
    themes = {
        "fallback": lambda l: MISSING_PARAM_ERROR in l,
        "scratch": lambda l: "Scratch scripts live in `/tmp`" in l,
        "finish": lambda l: l.startswith(("### 4. Finish", "1. After your final edit", "2. If the check fails",
                                          "3. `git status --short`", "4. Call `submit_patch` once",
                                          "5. After a non-empty submit")),
        "budget": lambda l: l.startswith(("- Once a tool result carries `budget_warning`", "- Keep 3 calls in hand")),
        "stop": lambda l: l.startswith("- Do NOT conclude that the codebase is already clean"),
    }
    for line in added:
        assert any(t(line) for t in themes.values()), line
    assert {k for k, t in themes.items() if any(t(l) for l in added)} == set(themes)
    assert "{" not in _prompt() and "}" not in _prompt()         # no ADK placeholders (validator rule)


# ------------------------------------------------------------------------------------- A. scratch files


def test_scratch_instructions_refer_only_to_supported_operations():
    """The only /tmp route is run_command; write_file/edit_file are never shown with a /tmp path."""
    text = _prompt()
    assert "cat > /tmp/repro.py <<'EOF'" in text and "python3 /tmp/repro.py" in text and "in the same command" in text
    for tool in ("write_file", "edit_file", "read_file"):
        assert not re.search(rf"{tool}\([^)]*/tmp", text), tool          # no call form with a /tmp argument
        assert not re.search(rf"{tool}\b[^.\n]*\binto\s+`?/tmp", text), tool
    assert f'`write_file` to `/tmp/...` is rejected ("{TRAVERSAL_ERROR}")' in text
    assert "still costs a tool call" in text
    assert "Never create files inside `/workspace` that are not part of the fix" in text
    # R018's phrasing, which produced the rejected calls, is gone.
    assert "Any scratch script goes in `/tmp`" not in text


def test_local_harness_rejects_out_of_workspace_paths_like_swegemma(repo: Path, tmp_path: Path):
    """The rejected call is counted first (budget_gated increments before the tool runs)."""
    h = LocalHarness(repo, tmp_path / "tmp", Budget(tool_calls=28))
    t = h.tool_functions()
    r = json.loads(t["write_file"]("/tmp/repro.py", "print('x')\n"))
    assert r["status"] == "error" and r["error_type"] == "FileWriteError"
    assert r["error_message"] == "Path traversal detected: '/tmp/repro.py' escapes workspace root."
    assert json.loads(t["read_file"]("/etc/passwd"))["error_type"] == "FileReadError"
    assert json.loads(t["edit_file"]("../x.py", "a", "b"))["error_type"] == "FileEditError"
    assert h.tool_calls_used == 3 and not (tmp_path / "tmp" / "repro.py").exists()
    assert json.loads(t["write_file"]("/workspace/pkg/new.py", "X = 1\n"))["status"] == "ok"
    ok = json.loads(t["run_command"]("cat > /tmp/repro.py <<'EOF'\nprint('x')\nEOF\npython3 /tmp/repro.py"))
    assert ok["status"] == "ok" and ok["stdout"] == "x\n" and (tmp_path / "tmp" / "repro.py").exists()


@pytest.mark.skipif(not OFFICIAL_PY.exists(), reason="official harness venv missing (scripts/setup_official_harness.sh)")
def test_official_swegemma_rejects_tmp_paths_with_the_message_the_prompt_quotes():
    code = ("from pathlib import Path\nfrom swegemma.tools.workspace import _resolve_workspace_path\n"
            "for p in ('/tmp/repro.py', '/etc/passwd', '../x'):\n"
            "    try: _resolve_workspace_path(p, Path('/workspace')); print('OK', p)\n"
            "    except ValueError as e: print('ERR', e)\n"
            "print('OK', _resolve_workspace_path('/workspace/a.py', Path('/workspace')))\n")
    out = subprocess.run([str(OFFICIAL_PY), "-c", code], capture_output=True, text=True, check=True).stdout
    lines = out.strip().splitlines()
    assert lines[0] == "ERR Path traversal detected: '/tmp/repro.py' escapes workspace root."
    assert lines[1].startswith("ERR") and lines[2].startswith("ERR") and lines[3] == "OK /workspace/a.py"
    assert TRAVERSAL_ERROR in _prompt()


# ------------------------------------------------------------------------------- package / validator / guards


def test_package_is_six_files(tmp_path: Path):
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    files = sorted(p.relative_to(build).as_posix() for p in build.rglob("*") if p.is_file())
    assert files == ["agent.yaml", "configs/sampling.yaml", "eval_config.yaml", "prompts/system.md",
                     "skills/code-edit/SKILL.md", "skills/code-edit/scripts/edit.py"]


def test_r017_control_variant_rebuilds_the_r017_archive(tmp_path: Path):
    """The same-kernel control is the R017 archive 51a6ef89..., byte for byte (deterministic packager)."""
    assert package("r017_control", tmp_path / "c.zip", compile_adk=False) == 0
    assert _sha((tmp_path / "c.zip").read_bytes()) == "51a6ef8979e03fed1e77a9148436a8be5c6a57ccd18c61eec924068985576e60"


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


def test_guard_rejects_a_skill_that_names_a_tool_the_agent_lacks(submission: Path):
    p = submission / "agent.yaml"
    p.write_text(p.read_text().replace("  - run_command\n", ""))      # code-edit's SKILL.md names run_command
    assert any("names tool 'run_command'" in e for e in validate_dir(submission).errors)


def test_guard_rejects_a_call_to_an_unregistered_tool_in_the_instruction(submission: Path):
    p = submission / "agent.yaml"
    p.write_text(p.read_text().replace("  - get_code_subgraph\n", ""))
    (submission / "prompts" / "system.md").write_text(_prompt() + '\nThen call get_code_subgraph(["a", "b"]).\n')
    assert any("instruction shows a call to 'get_code_subgraph'" in e for e in validate_dir(submission).errors)


# ------------------------------------------------------------------------- scripted runs (real google-adk)

BUG = "return low  # BUG: should return high"
GREP = ("run_command", {"command": "git grep -n 'def clamp' -- '*.py' | head -20"})
READ = ("read_file", {"filepath": "pkg/mathutil.py", "start_line": 1, "end_line": 20})
FIX = ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": BUG, "new_string": "return high"})
PROBE = ("run_command", {"command": "python3 -c \"from pkg.mathutil import clamp; print(clamp(50, 0, 10))\""})
# The R019 finish command: the targeted check and the diff summary in one counted call.
FINISH = ("run_command", {"command": "python3 -m pytest tests/test_mathutil.py -q 2>&1 | tail -15; git status --short"})
SUBMIT = ("submit_patch", {})
TMP_REPRO = ("run_command", {"command": "cat > /tmp/repro.py <<'EOF'\nfrom pkg.mathutil import clamp\n"
                                        "print(clamp(50, 0, 10))\nEOF\npython3 /tmp/repro.py"})
BAD_TMP_WRITE = ("write_file", {"filepath": "/tmp/repro.py", "content": "print('x')\n"})
FALLBACK_STEPS = [
    ("run_command", {"command": "cat > /tmp/old.txt <<'EOF'\n        return low  # BUG: should return high\nEOF"}),
    ("run_command", {"command": "cat > /tmp/new.txt <<'EOF'\n        return high\nEOF"}),
    ("run_skill_script", {"skill_name": "code-edit", "file_path": "scripts/edit.py",
                          "args": ["replace", "pkg/mathutil.py", "@/tmp/old.txt", "@/tmp/new.txt"]}),
]


def _run(steps, repo: Path, tmp_path: Path, tool_calls: int = 28, turns: int = 80):
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    task = Task("toy_1", "local/toy", "HEAD", "clamp() returns the lower bound for values above `high`.")
    llm = ScriptedLlm(model="scripted", steps=list(steps), seen_requests=[])
    tmp = tmp_path / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = {**_env(repo), "TMPDIR": str(tmp.resolve())}         # as the subprocess sandbox sets it
    outcome = asyncio.run(run_agent(build, task, repo, tmp, Budget(tool_calls=tool_calls, time_minutes=2, turns=turns),
                                    None, env, tmp_path / "t.jsonl", model_factory=lambda *_: llm))
    return outcome, llm


def _responses(llm, name: str) -> list[str]:
    """Tool responses of one tool, in order, from the last request (which carries the whole history)."""
    last = llm.seen_requests[-1]
    return [str(p.function_response.response) for c in last.contents for p in c.parts
            if p.function_response and p.function_response.name == name]


def _log(outcome, name: str) -> list[dict]:
    return [e for e in outcome.tool_log if e["tool"] == name]


def test_contract_flow_grep_read_edit_finish_submit(repo: Path, tmp_path: Path):
    outcome, llm = _run([GREP, READ, FIX, FINISH, SUBMIT, "Fixed clamp."], repo, tmp_path)
    assert outcome.stop_reason == "submitted" and "return high" in outcome.patch and outcome.tool_calls == 4
    assert all(_agent_of(r) == "coder" for r in llm.seen_requests)
    assert "Scratch scripts live in `/tmp`" in str(llm.seen_requests[0].config.system_instruction)


def test_invalid_tmp_write_is_counted_once_and_the_run_command_route_lands_the_scratch(repo: Path, tmp_path: Path):
    """The R018 failure shape, then the supported route: the rejected write costs a call, the heredoc works, and
    nothing from /tmp reaches the patch."""
    outcome, llm = _run([GREP, READ, FIX, BAD_TMP_WRITE, TMP_REPRO, FINISH, SUBMIT, "Fixed."], repo, tmp_path)
    rejected = _responses(llm, "write_file")
    assert len(rejected) == 1 and TRAVERSAL_ERROR in rejected[0] and "FileWriteError" in rejected[0]
    assert [e["status"] for e in _log(outcome, "write_file")] == ["error:FileWriteError"]
    assert _log(outcome, "write_file")[0]["counted"] is True and outcome.tool_calls == 6
    repro = [r for r in _responses(llm, "run_command") if '"stdout": "10' in r]
    assert repro, _responses(llm, "run_command")                                     # the scratch ran from /tmp
    assert (tmp_path / "tmp" / "repro.py").exists() and not (repo / "repro.py").exists()
    assert outcome.stop_reason == "submitted" and "repro.py" not in outcome.patch and "return high" in outcome.patch
    assert "write_file" not in [e["tool"] for e in outcome.tool_log[4:]]            # not retried through write_file


def test_temporary_artifacts_are_removed_before_the_single_submit(repo: Path, tmp_path: Path):
    """A stray workspace file shows up in `git status --short`; one cleanup call keeps it out of the one submit."""
    stray = ("write_file", {"filepath": "repro.py", "content": "print('x')\n"})
    cleanup = ("run_command", {"command": "rm repro.py; git checkout -- tests/test_mathutil.py; git status --short"})
    test_touch = ("edit_file", {"filepath": "tests/test_mathutil.py", "old_string": "== 10", "new_string": "== 11"})
    outcome, llm = _run([GREP, READ, FIX, stray, test_touch, FINISH, cleanup, SUBMIT, "Fixed."], repo, tmp_path)
    finish_out = [r for r in _responses(llm, "run_command") if "test_mathutil" in r and "repro.py" in r]
    assert finish_out and "?? repro.py" in finish_out[0] and " M tests/test_mathutil.py" in finish_out[0]
    clean_out = _responses(llm, "run_command")[-1]
    assert "repro.py" not in clean_out and "tests/" not in clean_out and " M pkg/mathutil.py" in clean_out
    assert outcome.stop_reason == "submitted" and len(_log(outcome, "submit_patch")) == 1
    assert "repro.py" not in outcome.patch and "tests/test_mathutil.py" not in outcome.patch
    assert "return high" in outcome.patch


def test_one_targeted_check_runs_after_the_final_edit_in_one_call(repo: Path, tmp_path: Path):
    outcome, llm = _run([GREP, READ, FIX, FINISH, SUBMIT, "Fixed."], repo, tmp_path)
    after_last_edit = [e["tool"] for e in outcome.tool_log[outcome.tool_log.index(_log(outcome, "edit_file")[-1]) + 1:]]
    assert after_last_edit == ["run_command", "submit_patch"]                      # exactly one check, then submit
    out = _responses(llm, "run_command")[-1]
    assert "3 passed" in out and " M pkg/mathutil.py" in out                        # test result + diff summary together


# ---------------------------------------------------------------------------- B. the empty-patch submission loop


def test_submit_patch_stays_free_after_the_cap_so_only_the_turn_budget_bounds_a_loop(repo: Path, tmp_path: Path):
    """Characterization, not a guard: fastapi_14873 (R018) called submit_patch 49 times after its 28th call and was
    ended by the 80-turn limit. Locally the same happens: every post-cap submit is accepted, uncounted and empty.
    No submission-side mechanism can intercept it (callback registry absent), so the stop rule lives in the prompt."""
    outcome, llm = _run([GREP, READ, *[PROBE] * 26, *[SUBMIT] * 60, "stopping"], repo, tmp_path, turns=40)
    assert outcome.tool_calls == 28 and not outcome.patch
    subs = _log(outcome, "submit_patch")
    assert len(subs) >= 10 and all(e["status"] == "ok" and e["counted"] is False for e in subs)
    assert all('"patch_size": 0' in r for r in _responses(llm, "submit_patch"))
    assert outcome.stop_reason in ("turn_budget", "agent_error") and outcome.llm_turns <= 40


def test_prompt_stops_the_loop_and_no_longer_demands_a_non_empty_patch_at_all_costs():
    text = _prompt()
    assert "`files_changed: 0` means the repository is unchanged" in text
    assert "calling `submit_patch` again cannot change that" in text
    assert "If you have no tool calls left, reply with one sentence" in text
    assert "Do not call `submit_patch` again unless you changed a file after it" in text
    assert "repeating `submit_patch` or re-sending a refused edit cannot create a patch" in text
    assert "Do NOT conclude without submitting a non-empty patch" not in text      # R017's loop-feeding rule
    assert "Verify `patch_size > 0`" not in text


def test_retry_after_an_empty_submit_requires_a_changed_tree(repo: Path, tmp_path: Path):
    """Recovery path: an empty submit is answered with files_changed 0; the next submit only carries content after a
    real edit, and the session ends on the first non-empty submit plus a final message."""
    outcome, llm = _run([GREP, READ, SUBMIT, FIX, FINISH, SUBMIT, "Fixed."], repo, tmp_path)
    subs = _responses(llm, "submit_patch")
    assert len(subs) == 2 and '"files_changed": 0' in subs[0] and '"files_changed": 1' in subs[1]
    assert outcome.stop_reason == "submitted" and "return high" in outcome.patch and outcome.tool_calls == 4


def test_the_harness_ends_the_session_on_a_final_message_after_a_submit(repo: Path, tmp_path: Path):
    """What the stop rule relies on: text with no tool call after submit_patch terminates the loop (swegemma
    agent_runner: 'Agent submitted patch and returned final completion message')."""
    outcome, _ = _run([GREP, READ, FIX, FINISH, SUBMIT, "Done.", SUBMIT, SUBMIT], repo, tmp_path)
    assert outcome.stop_reason == "submitted" and len(_log(outcome, "submit_patch")) == 1


# ------------------------------------------------------------------- carried from R017/R018 (still applicable)


def test_edit_file_failure_falls_back_to_code_edit_replace(repo: Path, tmp_path: Path):
    bad = ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": "return low  \\# BUG", "new_string": "return high"})
    outcome, llm = _run([GREP, READ, bad, bad, *FALLBACK_STEPS, FINISH, SUBMIT, "Fixed."], repo, tmp_path)
    assert outcome.stop_reason == "submitted" and "+        return high" in outcome.patch
    assert any("EDITED pkg/mathutil.py" in x for x in _responses(llm, "run_skill_script"))


def test_malformed_edit_file_returns_the_error_the_bullet_names_then_code_edit_lands_the_fix(repo: Path, tmp_path: Path):
    malformed = ("edit_file", {"filepath": "pkg/mathutil.py",
                               "new_string": 'return high",old_string:\'return low  # BUG: should return high'})
    outcome, llm = _run([GREP, READ, malformed, *FALLBACK_STEPS, FINISH, SUBMIT, "Fixed."], repo, tmp_path)
    edit_errors = _responses(llm, "edit_file")
    assert edit_errors and MISSING_PARAM_ERROR in edit_errors[0] and "old_string" in edit_errors[0]
    bullet = next(l for l in _prompt().splitlines() if MISSING_PARAM_ERROR in l)
    assert "do not resend it" in bullet and '"replace"' in bullet and "@/tmp/old.txt" in bullet
    assert outcome.stop_reason == "submitted" and "+        return high" in outcome.patch


def test_hard_call_cap_ends_the_session_and_keeps_an_early_edit(repo: Path, tmp_path: Path):
    outcome, _ = _run([GREP, READ, FIX, *[PROBE] * 60], repo, tmp_path, tool_calls=28)
    executed = [e for e in outcome.tool_log if e.get("counted") and not str(e.get("status")).startswith("error:Budget")]
    assert outcome.tool_calls == 28 and len(executed) == 28 and "return high" in outcome.patch
    assert any(str(e.get("status")).startswith("error:Budget") for e in outcome.tool_log)   # call 29+ refused
    subprocess.run(["git", "checkout", "--", "."], cwd=repo, check=True)
    late, _ = _run([GREP, READ, *[PROBE] * 60, FIX], repo, tmp_path / "late", tool_calls=28)
    assert late.tool_calls == 28 and "pkg/mathutil.py" not in late.patch                    # the late edit never ran


def test_an_undeclared_tool_call_is_not_silently_accepted_locally(repo: Path, tmp_path: Path):
    outcome, _ = _run([("apply_patch", {"diff": "x"})], repo, tmp_path)
    assert outcome.stop_reason == "agent_error" and "apply_patch" in outcome.error and not outcome.patch
