from pathlib import Path

from g4agent.analysis import classify, summarize
from g4agent.harness.tasks import Task
from g4agent.harness.verify import is_protected, patch_files
from g4agent.localization import extract_terms


def test_protected_paths():
    assert is_protected("tests/test_x.py")
    assert is_protected("pkg/conftest.py")
    assert is_protected("pyproject.toml")
    assert is_protected("src/foo_test.py")
    assert not is_protected("pkg/testing_utils.py")
    assert not is_protected("pkg/core.py")


def test_patch_files():
    p = "diff --git a/pkg/a.py b/pkg/a.py\n--- a/pkg/a.py\n+++ b/pkg/a.py\ndiff --git a/t/b.py b/t/b.py\n"
    assert patch_files(p) == ["pkg/a.py", "t/b.py"]


def _task() -> Task:
    return Task("x_1", "o/x", "abc", "issue", patch="diff --git a/pkg/core.py b/pkg/core.py\n")


def test_classify_categories():
    t = _task()
    assert classify(t, {"resolved": True})[0] == "resolved"
    assert classify(t, {"patch_chars": 0, "stop_reason": "time_budget"})[0] == "timeout_budget"
    assert classify(t, {"patch_chars": 0, "stop_reason": "max_nudges"})[0] == "no_attempt"
    assert classify(t, {"patch_chars": 10, "patch_applied": False})[0] == "submission_issue"
    base = {"patch_chars": 10, "patch_applied": True}
    assert classify(t, {**base, "edited_files": ["pkg/other.py"]})[0] == "localization_failure"
    assert classify(t, {**base, "edited_files": ["pkg/other.py"],
                        "tool_log": [{"tool": "read_file", "args": {"filepath": "/workspace/pkg/core.py"}}]}
                    )[0] == "wrong_root_cause"
    assert classify(t, {**base, "edited_files": ["pkg/core.py"]})[0] == "incorrect_modification"


def test_summarize():
    s = summarize([{"resolved": True, "category": "resolved"}, {"resolved": False, "category": "no_attempt"}])
    assert s["resolution_rate"] == 0.5 and s["categories"]["no_attempt"] == 1


def test_extract_terms_prefers_code_identifiers():
    text = ("`Console.print` raises when `soft_wrap=True`\n"
            'Traceback:\n  File "rich/console.py", line 10, in render_lines\nValueError: bad width')
    terms = extract_terms(text)
    assert "render_lines" in terms and "Console.print" in terms and "soft_wrap" in terms
    assert "the" not in terms
