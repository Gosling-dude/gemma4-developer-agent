"""R013: the localizer must never be shown a tool it does not have (R012: 2/24 tasks crashed on run_command).

Evidence (R012-v13-handoff traces rich_3061, rich_3105): load_skill("repo-navigation") returned the shared
SKILL.md, whose fallback line recommends run_command("git grep ..."); after an empty `find` the localizer called
run_command, google-adk raised ValueError("Tool 'run_command' not found") and the task ended with no patch.
adk-submission 0.2.11 has an empty callback registry, so the call cannot be caught at run time; R013 prevents it.
"""

import asyncio
import hashlib
from pathlib import Path

from g4agent import rules
from g4agent.harness.runner import run_agent
from g4agent.harness.tasks import Task
from g4agent.harness.tools import Budget
from g4agent.loader import load_yaml
from g4agent.packager import PROJECT, package
from g4agent.validator import validate_dir

from test_runner_integration import ScriptedLlm, _agent_of, _env

READONLY = "skills/repo-navigation-readonly"
SKILL_TOOLS = {"list_skills", "load_skill", "load_skill_resource", "run_skill_script"}


def _localizer() -> dict:
    return load_yaml(PROJECT, PROJECT / "sub_agents/localizer.yaml").data


def _missing_tools(cfg: dict) -> set[str]:
    return set(rules.HARNESS_TOOLS) - set(cfg["tools"])


def test_localizer_uses_the_readonly_skill_with_identical_nav():
    loc = _localizer()
    assert loc["skills"] == [READONLY]
    assert loc["tools"] == ["read_file", "get_status", "get_code_neighbors", "search_similar_code",
                            "get_code_subgraph"]                              # unchanged from R012
    shared = (PROJECT / "skills/repo-navigation/scripts/nav.py").read_bytes()
    assert (PROJECT / READONLY / "scripts/nav.py").read_bytes() == shared     # same behaviour, no new capability
    assert hashlib.sha256(shared).hexdigest() == \
        "e600e8b2a91c947bea405f005cd19b39adc71eedbf8eed547a384ab23db113c2"    # = 121bd79 / R012


def test_nothing_the_localizer_sees_names_a_tool_it_lacks():
    loc = _localizer()
    missing = _missing_tools(loc)
    assert {"run_command", "edit_file", "write_file", "submit_patch"} <= missing
    for p in (PROJECT / READONLY).rglob("*"):
        if p.is_file() and p.suffix in (".md", ".txt"):
            text = p.read_text()
            assert not [t for t in missing if t in text], p
    instr = loc["instruction"]
    assert not [t for t in missing if f"{t}(" in instr]
    assert 'skill_name="repo-navigation-readonly"' in instr and 'skill_name="repo-navigation"' not in instr
    # Explicit contract: the CHECK line carries what the localizer may not run.
    assert "No other tool exists in this stage" in instr and "write it in the CHECK line" in instr
    for field in ("FILE:", "SYMBOL:", "CAUSE:", "EDIT:", "CHECK:"):
        assert instr.count(f"\n{field}") == 1


def test_validator_rejects_the_r012_localizer_skill(submission: Path):
    """The R012 defect, statically: the shared skill doc names run_command, which the localizer lacks."""
    p = submission / "sub_agents" / "localizer.yaml"
    p.write_text(p.read_text().replace(f"  - {READONLY}\n", "  - skills/repo-navigation\n"))
    errs = validate_dir(submission).errors
    assert any("skills/repo-navigation/SKILL.md names tool 'run_command'" in e for e in errs), errs


def test_validator_rejects_a_call_to_a_missing_tool_in_the_instruction(submission: Path):
    p = submission / "prompts" / "localizer.md"
    p.write_text(p.read_text() + '\nIf stuck, run_command("git grep -n term").\n')
    errs = validate_dir(submission).errors
    assert any("instruction shows a call to 'run_command'" in e for e in errs), errs


def test_coder_is_untouched_by_the_guard(submission: Path):
    """The coder has every harness tool, so the guard never fires for it or its (shared) skills."""
    report = validate_dir(submission)
    assert report.ok, report.render()
    assert not [e for e in report.errors if "coder" in e]


def _run(steps, repo: Path, tmp_path: Path):
    build = tmp_path / "build"
    assert package(None, tmp_path / "s.zip", compile_adk=False, keep_build=build) == 0
    task = Task("toy_3105", "local/toy", "HEAD", "Fix the bug reported in #3104.")
    llm = ScriptedLlm(model="scripted", steps=list(steps), seen_requests=[])
    outcome = asyncio.run(run_agent(build, task, repo, tmp_path / "tmp", Budget(tool_calls=40, time_minutes=2),
                                    None, _env(repo), tmp_path / "t.jsonl", model_factory=lambda *_: llm))
    return outcome, llm


NOT_FOUND_PLAN = ("FILE: unknown\nSYMBOL: unknown\nCAUSE: nav find '#3104' matched no file; the issue names no symbol\n"
                  "EDIT: unknown\nCHECK: run git log --grep='#3104' and the test suite to find the regression")


def test_r012_crash_path_now_hands_off_instead_of_crashing(repo: Path, tmp_path: Path):
    """Replays rich_3105 through real ADK: load the skill, an empty `find`, then the step R012 crashed on.

    With the read-only skill the model is no longer told to fall back to run_command; following its contract it
    records the git/test idea in CHECK, and the coder (which has run_command) carries on and submits.
    """
    steps = [
        ("load_skill", {"skill_name": "repo-navigation-readonly"}),
        ("run_skill_script", {"skill_name": "repo-navigation-readonly", "file_path": "scripts/nav.py",
                              "args": ["find", "#3104"]}),
        NOT_FOUND_PLAN,
        ("run_skill_script", {"skill_name": "repo-navigation", "file_path": "scripts/nav.py",
                              "args": ["find", "clamp"]}),
        ("edit_file", {"filepath": "pkg/mathutil.py", "old_string": "return low  # BUG: should return high",
                       "new_string": "return high"}),
        ("submit_patch", {}),
        "Fixed.",
    ]
    outcome, llm = _run(steps, repo, tmp_path)
    assert outcome.stop_reason == "submitted" and "return high" in outcome.patch, outcome
    reqs = llm.seen_requests
    assert [_agent_of(r) for r in reqs[:3]] == ["localizer"] * 3
    loc = reqs[0]
    assert set(loc.tools_dict) == {"read_file", "get_status", "get_code_neighbors", "search_similar_code",
                                   "get_code_subgraph"} | SKILL_TOOLS
    loaded = " ".join(str(p.function_response) for c in reqs[1].contents for p in c.parts if p.function_response)
    assert "repo-navigation-readonly" in loaded and "CHECK line" in loaded
    assert not [t for t in _missing_tools(_localizer()) if t in loaded]    # what R012 showed: run_command(...)
    coder = next(r for r in reqs if _agent_of(r) == "coder")
    assert "CHECK: run git log --grep='#3104'" in str(coder.config.system_instruction)


def test_an_undeclared_tool_call_still_ends_the_task(repo: Path, tmp_path: Path):
    """Characterization, not a fix: if the model calls run_command anyway, ADK raises and the task ends.

    This is why R013 prevents the call instead of catching it: a submission cannot register a callback, so
    there is no run-time recovery. The R013 metric (docs/r013.md) is the count of such crashes on Kaggle.
    """
    steps = [("run_command", {"command": "git log -n 10 --grep=\"#3104\""})]
    outcome, _ = _run(steps, repo, tmp_path)
    assert outcome.stop_reason == "agent_error", outcome
    assert "Tool 'run_command' not found" in outcome.error
    assert not outcome.patch
