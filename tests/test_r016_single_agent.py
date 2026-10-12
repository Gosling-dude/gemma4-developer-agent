"""R016: the R015 coder is the root agent; the localizer -> coder SequentialAgent of R012-R015 is removed.

Evidence (docs/r015.md): on the 2026-10-09 harness, with thinking on, the read-only localizer took a median ~230 s of
the 330 s task budget and 5/24 R015 sessions never left it. R016 keeps R015's model, tools, skills, sampling (thinking
on, thoughts kept) and eval_config; the prompt changes only where it depended on the removed plan handoff.

The R012-R015 architecture tests live on their branches with the agents they test; this module carries their
still-applicable protections (pinned bytes, tool guard, thinking, repair-first order, scripted edit runs).
"""

import asyncio
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from g4agent.compiler import compile_submission
from g4agent.harness.runner import run_agent
from g4agent.harness.tasks import Task
from g4agent.harness.tools import Budget
from g4agent.loader import load_yaml
from g4agent.packager import PROJECT, package
from g4agent.validator import validate_dir

from test_runner_integration import ScriptedLlm, _agent_of, _env

R015_REV = "d5872503db78a9c17d1e08706eafa30a77a2ed83"
R015_PROMPT_SHA256 = "2863c37481ce0daf73ecdcd0801a606460f71f6325ff19a0003a881ae832eadb"
V13_TOOLS = ["run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch",
             "get_code_neighbors", "search_similar_code", "get_code_subgraph"]
V13_SKILLS = ["skills/repo-navigation", "skills/test-discovery", "skills/debugging", "skills/code-edit"]

# Unchanged from the evaluated R015 build (d587250): sampling (thinking on), budgets, every skill the coder uses.
R015_SHA256 = {
    "configs/sampling.yaml": "eaba91b18eec28488f07a29de2179121e9a2d68ac0227b12f0e60e395335f334",
    "eval_config.yaml": "48c97a48ac1b85a7db47862f25f5b302e1fffe51ae3a3328470ae8d0d78779d5",
    "skills/code-edit/SKILL.md": "122c970c0ec7622e09cc16af1b9c53ba2384274cdd9d0b3eaa970dab13e4ab9d",
    "skills/code-edit/scripts/edit.py": "13a38363c69cb514356c47a03ebff31bb10e2df63cd438a5602d65b2aead5787",
    "skills/debugging/SKILL.md": "8651b7bba0d4144abdaf2f6e4be4c2f2e2b1fbad50d5bbc3292a18fe7db87174",
    "skills/debugging/references/failure_taxonomy.md": "0d8ab924949ede9683a9b1999a12ed9527e9ebb0fcf68daaf0d1e5370f2bea76",
    "skills/debugging/scripts/diagnose.py": "a1a7e229892cad524b93009f41900d51d195ffadee3147938778face30146fe0",
    "skills/debugging/scripts/review.py": "4eff53e7b2c63910ee375374e953174d18cf3c312269f44a1c135fad789b82bd",
    "skills/repo-navigation/SKILL.md": "7d7885bd2ecaa813f8a88bc5c800f4e252d646413dd74236025c1c3cfcb997a6",
    "skills/repo-navigation/references/graph_tools.md": "783e428a8c2c7dd67f32ca7f169d1f83d4dc637bf34b01ca4fc76a84808497e5",
    "skills/repo-navigation/scripts/nav.py": "e600e8b2a91c947bea405f005cd19b39adc71eedbf8eed547a384ab23db113c2",
    "skills/test-discovery/SKILL.md": "10a814252b03b5ae7e89ecc4e4d7d919073dda8c0487af80c75c2e48215d6d3d",
    "skills/test-discovery/references/pytest_cheatsheet.md": "87261e2acff15b3844fb11d7f832fde4011e158ce178ba327eb3502297ee3bf1",
    "skills/test-discovery/scripts/tests.py": "bfc207aece7129720ee8d6fccdf3f1c779cb19a9613ddf36c96165bf6a9177b1",
}

# The only prompt changes vs R015, all forced by removing the plan handoff: (R015 text, R016 text).
R016_PROMPT_CHANGES = [
    ("\n# Issue\n{problem_description}\n\n{hints?}\n", ""),   # the harness message carries the issue verbatim now
    ("""2. START FROM THE PLAN. The read-only localizer stage left this plan; it may be empty, incomplete or wrong.
   Start from {repair_plan?}
   Before editing, read the code it names yourself with nav.py show/read (below; the edit needs those numbered
   lines) and check its CAUSE against that code. If the plan is empty, says unknown, or doesn't match the
   code, LOCATE yourself (1–3 calls): use the navigation script with the 2–5 most specific terms, most specific first:
""", """2. LOCATE (1–3 calls). Use the navigation script with the 2–5 most specific terms, most specific first:
"""),                                                         # = the V1.3 step 2, before R012 added the plan
    ("""   - The code confirms the plan's CAUSE: the plan's EDIT is your hypothesis. Do steps 4 and 5 now and
     reproduce only in step 6, after the edit. A script run before the first edit adds nothing the code
     has not shown you, and an unfinished repro loop leaves no patch.
   - The plan is empty, unknown, or the code contradicts it: locate (step 2), then at most 2 script runs
     (written as in step 6) to find the cause, then steps 4 and 5.
""", """   - The code shows why the behaviour is wrong: that is your hypothesis. Do steps 4 and 5 now and
     reproduce only in step 6, after the edit. A script run before the first edit adds nothing the code
     has not shown you, and an unfinished repro loop leaves no patch.
   - The code you read does not show the cause: at most 2 script runs (written as in step 6) to find it,
     then steps 4 and 5.
"""),
]


def _prompt() -> str:
    return (PROJECT / "prompts/system.md").read_text()


def _root() -> dict:
    return load_yaml(PROJECT, PROJECT / "agent.yaml").data


# ----------------------------------------------------------------------------------------------- static


def test_root_is_one_llm_agent_with_the_r015_coder_configuration():
    root = _root()
    assert root.get("agent_class", "LlmAgent") == "LlmAgent" and root["name"] == "swe_coder"
    assert "sub_agents" not in root and "output_key" not in root
    assert "include_contents" not in root                       # receives the harness task message directly
    assert root["tools"] == V13_TOOLS and root["skills"] == V13_SKILLS
    assert root["model"] == "gemma-4-31b-it-qat-w4a16-ct"
    assert root["generate_content_config"] == yaml.safe_load((PROJECT / "configs/sampling.yaml").read_text())
    assert root["generate_content_config"]["thinking_config"] == {"thinking_budget": 4096, "include_thoughts": True}


def test_unchanged_files_are_the_r015_bytes():
    for rel, sha in R015_SHA256.items():
        assert hashlib.sha256((PROJECT / rel).read_bytes()).hexdigest() == sha, rel


def test_prompt_is_r015_minus_the_plan_handoff_only():
    text = _prompt()
    for old, new in reversed(R016_PROMPT_CHANGES):
        assert text.count(new) == (1 if new else text.count(new)), new[:60]
        text = text.replace(new, old, 1) if new else text
    # Re-insert the issue block where R015 had it (directly after the opening paragraph).
    head, rest = text.split("\n# Operating rules", 1)
    text = head + R016_PROMPT_CHANGES[0][0] + "\n# Operating rules" + rest
    assert hashlib.sha256(text.encode()).hexdigest() == R015_PROMPT_SHA256


def test_prompt_is_self_contained_and_keeps_the_repair_first_order():
    text = _prompt()
    for gone in ("repair_plan", "{problem_description}", "localizer", "plan's", "START FROM THE PLAN"):
        assert gone not in text, gone
    order = [text.index(s) for s in ("1. UNDERSTAND", "2. LOCATE", "3. REPAIR FIRST", "4. HYPOTHESIS",
                                     "5. EDIT.", "6. VERIFY", "7. REVIEW", "8. SUBMIT")]
    assert order == sorted(order)
    assert text.count("cat > /tmp/repro.py") == 1 and text.index("cat > /tmp/repro.py") > text.index("6. VERIFY")
    assert "timeout 20 python3 /tmp/repro.py" in text
    assert "most of the budget before the first edit" in text          # no open-ended pre-edit probing
    assert "Tests are evidence, not the spec" in text                   # stale bug-encoding tests (R014)
    for hatch in ("sed -i", "writelines", "readlines", "lines[start"):   # no manual-splice edit path
        assert hatch not in text


def test_package_contains_only_the_single_agent_tree(tmp_path: Path):
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    files = {p.relative_to(build).as_posix() for p in build.rglob("*") if p.is_file()}
    assert "agent.yaml" in files and not any(f.startswith("sub_agents/") for f in files)
    assert not [f for f in files if "localizer" in f or "repo-navigation-readonly" in f]


def test_validator_and_adk_compile_accept_the_single_agent(submission: Path):
    report = validate_dir(submission, compile_adk=True)
    assert report.ok and not report.warnings, report.render()
    agent = compile_submission(submission)
    assert type(agent).__name__ == "LlmAgent" and agent.name == "swe_coder" and not agent.sub_agents
    tc = agent.generate_content_config.thinking_config
    assert tc.include_thoughts is True and tc.thinking_budget == 4096


# ------------------------------------------------------------------- R013 undeclared-tool guard, single agent


def test_guard_rejects_a_skill_that_names_a_tool_the_agent_lacks(submission: Path):
    """The skills name run_command; dropping it from the root's tools must fail validation (R013 rule)."""
    p = submission / "agent.yaml"
    p.write_text(p.read_text().replace("  - run_command\n", ""))
    errs = validate_dir(submission).errors
    assert any("names tool 'run_command'" in e for e in errs), errs


def test_guard_rejects_a_call_to_a_missing_tool_in_the_instruction(submission: Path):
    p = submission / "agent.yaml"
    p.write_text(p.read_text().replace("  - get_code_subgraph\n", ""))
    (submission / "prompts" / "system.md").write_text(_prompt() + '\nThen call get_code_subgraph(["a", "b"]).\n')
    errs = validate_dir(submission).errors
    assert any("instruction shows a call to 'get_code_subgraph'" in e for e in errs), errs


# ------------------------------------------------------------------------- scripted runs (real google-adk)


def _run(steps, repo: Path, tmp_path: Path, tool_calls: int = 40):
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    task = Task("toy_1", "local/toy", "HEAD", "clamp() returns the lower bound for values above `high`.")
    llm = ScriptedLlm(model="scripted", steps=list(steps), seen_requests=[])
    outcome = asyncio.run(run_agent(build, task, repo, tmp_path / "tmp", Budget(tool_calls=tool_calls, time_minutes=2),
                                    None, _env(repo), tmp_path / "t.jsonl", model_factory=lambda *_: llm))
    return outcome, llm


FIND = ("run_skill_script", {"skill_name": "repo-navigation", "file_path": "scripts/nav.py", "args": ["find", "clamp"]})
SHOW = ("run_skill_script", {"skill_name": "repo-navigation", "file_path": "scripts/nav.py", "args": ["show", "clamp"]})
BUG = "return low  # BUG: should return high"
REPRO = ("run_command", {"command": "python3 -c \"from pkg.mathutil import clamp; print(clamp(50, 0, 10))\""})
TESTS = ("run_skill_script", {"skill_name": "test-discovery", "file_path": "scripts/tests.py",
                              "args": ["run", "tests/test_mathutil.py"]})


def test_locate_edit_then_validation_drives_a_correction(repo: Path, tmp_path: Path):
    """No plan: the agent locates itself, edits, a post-edit test exposes a wrong edit, one correction, submit."""
    steps = [FIND, SHOW,
             ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": BUG, "new_string": "return high - 1"}),
             REPRO, TESTS,
             ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": "return high - 1", "new_string": "return high"}),
             TESTS,
             ("run_skill_script", {"skill_name": "debugging", "file_path": "scripts/review.py", "args": []}),
             ("submit_patch", {}), "Fixed."]
    outcome, llm = _run(steps, repo, tmp_path)
    assert outcome.stop_reason == "submitted" and "return high" in outcome.patch and "high - 1" not in outcome.patch
    assert all(_agent_of(r) == "coder" for r in llm.seen_requests)
    outs = [str(p.function_response.response) for r in llm.seen_requests for c in r.contents for p in c.parts
            if p.function_response and p.function_response.name == "run_skill_script"]
    assert any("FAIL" in x for x in outs) and any("ALL SELECTED TESTS PASSED" in x for x in outs)


def test_edit_first_keeps_the_fix_when_probing_exhausts_the_budget(repo: Path, tmp_path: Path):
    """Same budget and probe loop: editing first leaves the fix in the graded tree; probing first leaves none."""
    fix = ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": BUG, "new_string": "return high"})
    loop = [REPRO] * 30
    first, _ = _run([FIND, SHOW, fix, *loop], repo, tmp_path / "a", tool_calls=8)
    assert first.stop_reason == "tool_budget" and "return high" in first.patch, first
    subprocess.run(["git", "checkout", "--", "."], cwd=repo, check=True)
    late, _ = _run([FIND, SHOW, *loop, fix], repo, tmp_path / "b", tool_calls=8)
    assert late.stop_reason == "tool_budget" and "pkg/mathutil.py" not in late.patch, late


def test_an_undeclared_tool_call_is_not_silently_accepted_locally(repo: Path, tmp_path: Path):
    """Characterization of our local runner (google-adk without the harness plugin): an unknown tool ends the run.

    The 2026-10-09 official harness adds ToolErrorPlugin, which returns the error to the model instead; the R013
    validator guard prevents the agent from being shown missing tools in either case.
    """
    outcome, _ = _run([("apply_patch", {"diff": "x"})], repo, tmp_path)
    assert outcome.stop_reason == "agent_error" and "apply_patch" in outcome.error and not outcome.patch


@pytest.mark.skipif(shutil.which("timeout") is None, reason="coreutils timeout absent (macOS); present on Kaggle Linux")
def test_timeout_wrapped_repro_does_not_stall_the_session(repo: Path, tmp_path: Path):
    fix = ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": BUG, "new_string": "return high"})
    hang = ("run_command", {"command": "timeout 2 python3 -c 'while True: pass'"})
    outcome, _ = _run([FIND, fix, hang, ("submit_patch", {}), "Done."], repo, tmp_path)
    assert outcome.stop_reason == "submitted" and "return high" in outcome.patch


# --------------------------------------------------- coverage carried over from the retired R012-R015 modules

V13_PROMPT_SHA256 = "b2a3fa87a02787a895335110624546a6c976880c388eb7bb3e58fb2ff5a18258"   # 121bd79 (R009/V1.3)

# R014's three prompt changes as they read in R016 (step 3 no longer refers to a plan): (V1.3 text, R016 text).
R014_CHANGES_IN_R016 = [
    ("""3. REPRODUCE (1–2 calls, strongly recommended). Write a minimal script with run_command, e.g.
   cat > /tmp/repro.py <<'EOF' ... EOF
   and run it with the debugging skill: args=["run", "/tmp/repro.py"]. The script should print or assert
   the behaviour the issue describes. This confirms the root cause and later confirms the fix.
""", """3. REPAIR FIRST (no tool call). Decide from the code you just read, not from a script:
   - The code shows why the behaviour is wrong: that is your hypothesis. Do steps 4 and 5 now and
     reproduce only in step 6, after the edit. A script run before the first edit adds nothing the code
     has not shown you, and an unfinished repro loop leaves no patch.
   - The code you read does not show the cause: at most 2 script runs (written as in step 6) to find it,
     then steps 4 and 5.
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


def test_prompt_is_v13_plus_only_the_r014_repair_first_changes():
    """(from test_handoff + test_r014) Without the plan handoff, R016 = the V1.3 prompt + R014's three changes."""
    text = _prompt()
    for old, new in R014_CHANGES_IN_R016:
        assert text.count(new) == 1, new[:60]
        text = text.replace(new, old, 1)
    assert hashlib.sha256(text.encode()).hexdigest() == V13_PROMPT_SHA256


def test_stale_bug_encoding_tests_do_not_revert_a_fix():
    """(from test_r014) rich_3470: a gold-equivalent fix was reverted to satisfy a test that encoded the bug."""
    verify = _prompt()[_prompt().index("6. VERIFY"):_prompt().index("7. REVIEW")]
    for rule in ("Tests are evidence, not the spec", "stale, not a regression",
                 "don't change the code back to satisfy that test", "don't edit the test"):
        assert rule in verify, rule


def test_nothing_the_agent_sees_names_a_tool_it_lacks():
    """(from test_r013, generalized from the localizer) Instruction and skills only show registered tools."""
    from g4agent import rules
    import re
    root = _root()
    missing = set(rules.HARNESS_TOOLS) - set(root["tools"])
    texts = [_prompt()] + [p.read_text() for s in root["skills"] for p in (PROJECT / s).rglob("*")
                           if p.is_file() and p.suffix in (".md", ".txt")]
    for t in texts:
        assert not [m for m in missing if re.search(rf"\b{m}\b", t)]
    # Every tool shown in call form in the instruction is a harness tool the root has, or a skill tool.
    called = set(re.findall(r"\b([a-z_]+)\(", _prompt()))
    skill_tools = {"load_skill", "run_skill_script", "load_skill_resource", "list_skills"}
    assert {c for c in called if c in rules.HARNESS_TOOLS or c in skill_tools} <= set(root["tools"]) | skill_tools


def test_package_differs_from_r015_only_by_the_architecture_change(tmp_path: Path):
    """(from test_r015) Package R016 and the evaluated R015 build; every other file must be byte-identical."""
    import sys
    r015 = tmp_path / "r015"
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(r015), R015_REV], cwd=PROJECT, check=True)
    try:
        builds = {}
        for name, src in (("r016", PROJECT), ("r015", r015)):
            out = tmp_path / f"{name}_build"
            r = subprocess.run([sys.executable, "-c",
                                f"import sys; sys.path.insert(0, {str(src / 'src')!r});"
                                f"from g4agent.packager import package; from pathlib import Path;"
                                f"raise SystemExit(package(None, Path({str(tmp_path / (name + '.zip'))!r}),"
                                f" compile_adk=False, keep_build=Path({str(out)!r})))"], capture_output=True, text=True)
            assert r.returncode == 0, r.stdout + r.stderr
            builds[name] = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
        new, old = builds["r016"], builds["r015"]
        assert not set(new) - set(old)                                    # nothing added
        assert sorted(k for k in new if new[k] != old[k]) == ["agent.yaml", "prompts/system.md"]
        removed = sorted(set(old) - set(new))
        assert removed and all(r.startswith(("sub_agents/", "skills/repo-navigation-readonly/")) or
                               r in ("prompts/localizer.md", "configs/localizer_sampling.yaml") for r in removed), removed
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(r015)], cwd=PROJECT, check=False)


def test_rendered_instruction_keeps_locate_repair_edit_verify_order(repo: Path, tmp_path: Path):
    """(from test_r014) The instruction the model actually receives has the steps in order and no plan slot."""
    _, llm = _run([FIND, ("submit_patch", {}), "Done."], repo, tmp_path)
    sys_text = str(llm.seen_requests[0].config.system_instruction)
    idx = [sys_text.index(s) for s in ("2. LOCATE", "3. REPAIR FIRST", "5. EDIT.", "cat > /tmp/repro.py", "7. REVIEW")]
    assert idx == sorted(idx) and "{repair_plan" not in sys_text and "Start from" not in sys_text
