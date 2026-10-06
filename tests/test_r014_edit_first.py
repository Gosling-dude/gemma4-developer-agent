"""R014: the coder applies a code-confirmed repair plan before reproducing (R013 + one coder-prompt change).

Evidence (R013-v13-toolguard traces, docs/r014.md): in 0/21 correct-file-plan tasks did the coder edit before
reproducing; 6 of the 10 correct-file failures exhausted the budget in reproduction/probe loops before the plan's
fix landed. The model follows the workflow's step order literally, so R014 reorders it: decide from the code
(step 3), edit (steps 4-5, unchanged mechanics), then reproduce and verify (step 6).
"""

import asyncio
import hashlib
import shutil
from pathlib import Path

import pytest

from g4agent.harness.runner import run_agent
from g4agent.harness.tasks import Task
from g4agent.harness.tools import Budget
from g4agent.packager import PROJECT, package
from g4agent.validator import validate_dir

from test_runner_integration import PLAN, ScriptedLlm, _agent_of, _env

R013_PROMPT_SHA256 = "78e6565537add9e0503050df918d1b5667c683e54dae4ed7dd524114428e080b"  # 1cbcbd7:prompts/system.md

# The only R013 -> R014 change: (R013 text, R014 text), applied in order.
R014_CHANGES = [
    ("""3. REPRODUCE (1–2 calls, strongly recommended). Write a minimal script with run_command, e.g.
   cat > /tmp/repro.py <<'EOF' ... EOF
   and run it with the debugging skill: args=["run", "/tmp/repro.py"]. The script should print or assert
   the behaviour the issue describes. This confirms the root cause and later confirms the fix.
""", """3. REPAIR FIRST (no tool call). Decide from the code you just read, not from a script:
   - The code confirms the plan's CAUSE: the plan's EDIT is your hypothesis. Do steps 4 and 5 now and
     reproduce only in step 6, after the edit. A script run before the first edit adds nothing the code
     has not shown you, and an unfinished repro loop leaves no patch.
   - The plan is empty, unknown, or the code contradicts it: locate (step 2), then at most 2 script runs
     (written as in step 6) to find the cause, then steps 4 and 5.
   Probing never takes most of the budget before the first edit: with half the time or tool calls used and
   no edit yet, make the best-supported edit now (step 5), then verify it.
"""),
    ("""6. VERIFY (2–4 calls). Rerun the repro. Then run the most related existing tests:""",
     """6. VERIFY, REPRODUCING AFTER THE EDIT (2–4 calls). Check the fix with a minimal script that prints or asserts
   the behaviour the issue describes:
   cat > /tmp/repro.py <<'EOF' ... EOF
   then run it as: timeout 20 python3 /tmp/repro.py (a script that hangs then costs 20 s, not the session).
   If two versions of the script don't show the issue's behaviour, stop scripting and rely on the tests.
   Then run the most related existing tests:"""),
    ("""   command. Don't start more than 3 repair rounds on one hypothesis.
""", """   command. Don't start more than 3 repair rounds on one hypothesis.
   Tests are evidence, not the spec. An existing test that asserts exactly the behaviour the issue reports
   as the bug is stale, not a regression: the grader replaces it with the updated test. Keep a fix that
   matches the issue; don't change the code back to satisfy that test, and don't edit the test. Repair or
   revert only for failures in behaviour the issue does not ask to change.
"""),
]

# Everything else the R013 control ships, pinned to its 1cbcbd7 bytes.
R013_SHA256 = {
    "prompts/localizer.md": "adbdfd27e11da067a1fb6062aa44f40b7b57e1bfd69cc0da8f30b98af9b83f53",
    "agent.yaml": "3fc987282e87d1e7106d9af99c3394b170cb9b222f664afeaab1560544fc74fd",
    "sub_agents/coder.yaml": "129a5b9e0b60164fb98a5101ae7cbf267da4f5c2f8a4f925c3e84839184d7f3c",
    "sub_agents/localizer.yaml": "33e9b7d378d71fa7934505da9a5b22f10f439ca7e6430c13b3d3d0e1a3b4e709",
    "eval_config.yaml": "48c97a48ac1b85a7db47862f25f5b302e1fffe51ae3a3328470ae8d0d78779d5",
    "configs/sampling.yaml": "332e8adc50a3d6b71f78974c54e251ec1b4c6d7be8df6ec54321b458c06de890",
    "configs/localizer_sampling.yaml": "116dc6501c78ae34e285b8bc88696752130fb13c57a90e8684fadbb401e1a57c",
    "src/g4agent/validator.py": "63bdd3e863b86d5643e60bc5dc34659f5c29deb9ebdead3c22389975534ed019",
    "skills/repo-navigation-readonly/SKILL.md": "3ff07d453b302e76d7deaa62f58ad6b20dcfd890a66d0a1ac9674eb5bd4ded57",
    "skills/repo-navigation-readonly/scripts/nav.py": "e600e8b2a91c947bea405f005cd19b39adc71eedbf8eed547a384ab23db113c2",
    "skills/repo-navigation-readonly/references/graph_tools.md":
        "cbf5cf97c12b3f1687485d1047f5f1f8912d1b68c25887bcf093b33a10db9efa",
    "skills/code-edit/SKILL.md": "122c970c0ec7622e09cc16af1b9c53ba2384274cdd9d0b3eaa970dab13e4ab9d",
    "skills/code-edit/scripts/edit.py": "13a38363c69cb514356c47a03ebff31bb10e2df63cd438a5602d65b2aead5787",
    "skills/debugging/SKILL.md": "8651b7bba0d4144abdaf2f6e4be4c2f2e2b1fbad50d5bbc3292a18fe7db87174",
    "skills/debugging/scripts/diagnose.py": "a1a7e229892cad524b93009f41900d51d195ffadee3147938778face30146fe0",
    "skills/debugging/scripts/review.py": "4eff53e7b2c63910ee375374e953174d18cf3c312269f44a1c135fad789b82bd",
    "skills/test-discovery/SKILL.md": "10a814252b03b5ae7e89ecc4e4d7d919073dda8c0487af80c75c2e48215d6d3d",
    "skills/test-discovery/scripts/tests.py": "bfc207aece7129720ee8d6fccdf3f1c779cb19a9613ddf36c96165bf6a9177b1",
    "skills/repo-navigation/SKILL.md": "7d7885bd2ecaa813f8a88bc5c800f4e252d646413dd74236025c1c3cfcb997a6",
    "skills/repo-navigation/scripts/nav.py": "e600e8b2a91c947bea405f005cd19b39adc71eedbf8eed547a384ab23db113c2",
}


def r013_prompt(text: str) -> str:
    """Undo the R014 change; the result must be the R013 coder prompt byte for byte."""
    for old, new in reversed(R014_CHANGES):
        assert text.count(new) == 1, new[:60]
        text = text.replace(new, old, 1)
    return text


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _prompt() -> str:
    return (PROJECT / "prompts/system.md").read_text()


# ----------------------------------------------------------------------------------------------- static


def test_r014_is_r013_plus_exactly_the_documented_coder_prompt_change():
    assert _sha(r013_prompt(_prompt()).encode()) == R013_PROMPT_SHA256


def test_everything_else_is_the_r013_control():
    """Localizer, tool guard, plan format, coder tools, edit workflow, sampling, budgets: R013 bytes."""
    for rel, sha in R013_SHA256.items():
        assert _sha((PROJECT / rel).read_bytes()) == sha, rel


def test_workflow_order_is_inspect_plan_edit_then_reproduce():
    text = _prompt()
    plan, repair, edit, verify = (text.index(s) for s in
                                  ("2. START FROM THE PLAN.", "3. REPAIR FIRST", "5. EDIT.", "6. VERIFY"))
    assert plan < repair < edit < verify
    # The only reproduction template sits in step 6, after the edit; nothing before step 5 runs a script.
    assert text.count("cat > /tmp/repro.py") == 1 and text.index("cat > /tmp/repro.py") > verify
    assert "timeout 20 python3 /tmp/repro.py" in text[verify:]
    # Reasoning and inspection stay: the plan is checked against code read with nav.py before any edit,
    # a contradicted plan falls back to locating, and the hypothesis step is unchanged.
    assert "check its CAUSE against that code" in text[plan:repair]
    assert "The plan is empty, unknown, or the code contradicts it" in text[repair:edit]
    assert '4. HYPOTHESIS (no tool call). One sentence: "The bug is in X because Y; changing Z fixes it."' in text
    assert "most of the budget before the first edit" in text[repair:edit]


def test_stale_bug_encoding_tests_do_not_revert_a_fix():
    """rich_3470: a gold-equivalent fix was reverted to satisfy an existing test that encoded the bug."""
    verify = _prompt()[_prompt().index("6. VERIFY"):_prompt().index("7. REVIEW")]
    assert "Tests are evidence, not the spec" in verify
    assert "stale, not a regression" in verify and "don't change the code back to satisfy that test" in verify
    assert "don't edit the test" in verify                     # tests stay protected (operating rules)


def test_no_manual_splice_escape_hatch():
    """rich_3052: a manual file splice produced a SyntaxError. R014 adds no edit path; step 5 is R013's."""
    text = _prompt()
    for hatch in ("sed -i", "writelines", "open(", "readlines", "> rich/", "lines[start"):
        assert hatch not in text, hatch
    r013 = r013_prompt(text)
    step5 = lambda t: t[t.index("5. EDIT."):t.index("6. VERIFY")]
    assert step5(text) == step5(r013)


def test_r013_tool_guard_still_passes(submission: Path):
    report = validate_dir(submission, compile_adk=True)
    assert report.ok and not report.warnings, report.render()


# ------------------------------------------------------------------------- scripted runs (real google-adk)


def _run(steps, repo: Path, tmp_path: Path, tool_calls: int = 40):
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    task = Task("toy_1", "local/toy", "HEAD", "clamp() returns the lower bound for values above `high`.")
    llm = ScriptedLlm(model="scripted", steps=list(steps), seen_requests=[])
    outcome = asyncio.run(run_agent(build, task, repo, tmp_path / "tmp", Budget(tool_calls=tool_calls, time_minutes=2),
                                    None, _env(repo), tmp_path / "t.jsonl", model_factory=lambda *_: llm))
    return outcome, llm


LOCALIZE = [("run_skill_script", {"skill_name": "repo-navigation-readonly", "file_path": "scripts/nav.py",
                                  "args": ["find", "clamp"]}), PLAN]
INSPECT = ("run_skill_script", {"skill_name": "repo-navigation", "file_path": "scripts/nav.py",
                                "args": ["show", "clamp"]})
BUG = "return low  # BUG: should return high"
REPRO = ("run_command", {"command": "python3 -c \"from pkg.mathutil import clamp; print(clamp(50, 0, 10))\""})
TESTS = ("run_skill_script", {"skill_name": "test-discovery", "file_path": "scripts/tests.py",
                              "args": ["run", "tests/test_mathutil.py"]})


def test_plan_edit_lands_before_reproduction_and_validation_drives_a_correction(repo: Path, tmp_path: Path):
    """Inspect -> plan's edit (slightly wrong) -> repro + tests expose it -> one focused correction -> submit."""
    steps = [*LOCALIZE,
             INSPECT,
             ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": BUG, "new_string": "return high - 1"}),
             REPRO,                                            # step 6: reproduce after the edit
             TESTS,                                            # fails: clamp(50, 0, 10) == 9
             ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": "return high - 1",
                            "new_string": "return high"}),
             TESTS,                                            # passes
             ("run_skill_script", {"skill_name": "debugging", "file_path": "scripts/review.py", "args": []}),
             ("submit_patch", {}), "Fixed clamp upper bound."]
    outcome, llm = _run(steps, repo, tmp_path)
    assert outcome.stop_reason == "submitted", outcome
    assert "return high" in outcome.patch and "high - 1" not in outcome.patch
    coder = next(r for r in llm.seen_requests if _agent_of(r) == "coder")
    sys_text = str(coder.config.system_instruction)
    # The coder receives the plan, then the repair-first step, before any reproduction template.
    assert sys_text.index("Start from FILE: pkg/mathutil.py") < sys_text.index("3. REPAIR FIRST") \
        < sys_text.index("5. EDIT.") < sys_text.index("cat > /tmp/repro.py")
    responses = [str(p.function_response.response) for r in llm.seen_requests for c in r.contents
                 for p in c.parts if p.function_response and p.function_response.name == "run_skill_script"]
    test_runs = [x for x in responses if "tests/test_mathutil.py" in x or "PASSED" in x or "FAILED" in x]
    assert any("FAIL" in x for x in test_runs) and any("ALL SELECTED TESTS PASSED" in x for x in test_runs)


def test_edit_first_keeps_the_fix_when_reproduction_exhausts_the_budget(repo: Path, tmp_path: Path):
    """Same budget, same endless probe loop: edit-first leaves the fix in the graded tree; repro-first leaves nothing.

    The harness grades the working tree when a budget runs out (rich_3480/3063/3061: R013 never reached the edit).
    """
    fix = ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": BUG, "new_string": "return high"})
    loop = [REPRO] * 30
    edit_first, _ = _run([*LOCALIZE, INSPECT, fix, *loop], repo, tmp_path / "a", tool_calls=10)
    assert edit_first.stop_reason == "tool_budget" and "return high" in edit_first.patch, edit_first

    import subprocess
    subprocess.run(["git", "checkout", "--", "."], cwd=repo, check=True)
    repro_first, _ = _run([*LOCALIZE, INSPECT, *loop, fix], repo, tmp_path / "b", tool_calls=10)
    # The fix edit is refused (BudgetExceeded); only probe by-products (__pycache__) remain in the tree.
    assert repro_first.stop_reason == "tool_budget", repro_first
    assert "pkg/mathutil.py" not in repro_first.patch and "return high" not in repro_first.patch


@pytest.mark.skipif(shutil.which("timeout") is None, reason="coreutils timeout absent (macOS); present on Kaggle Linux")
def test_timeout_wrapped_repro_does_not_stall_the_session(repo: Path, tmp_path: Path):
    """rich_3480: a repro of an infinite loop hung for the 300 s command limit. The step-6 template bounds it."""
    hang = ("run_command", {"command": "timeout 2 python3 -c 'while True: pass'"})
    fix = ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": BUG, "new_string": "return high"})
    outcome, _ = _run([*LOCALIZE, INSPECT, fix, hang, ("submit_patch", {}), "Done."], repo, tmp_path)
    assert outcome.stop_reason == "submitted" and "return high" in outcome.patch, outcome
