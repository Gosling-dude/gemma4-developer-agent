---
name: test-discovery
description: Find the tests that cover a source file or symbol and run them with a condensed failure report (counts, assertion lines, innermost frames). Use to learn the expected behaviour before editing and to validate a fix after editing.
---

# Test discovery and targeted runs

Run with `run_skill_script(skill_name="test-discovery", file_path="scripts/tests.py", args=[...])`.

| Goal | args |
|---|---|
| Tests related to a file or symbol | `["related", "pkg/module.py", "func_name"]` |
| Run specific tests (condensed report) | `["run", "tests/test_x.py"]`, `["run", "tests/test_x.py", "-k", "name"]` |
| Test layout and config | `["info"]` |

## Rules
- **Targeted first.** Run the one or two most related test files. `run` refuses to run the whole
  suite, because a full run can use up the time budget.
- Pre-existing failures happen. Compare with the result **before** your edit
  (`git stash; ...; git stash pop` with run_command) before you start chasing a failure.
- The hidden grading tests are new or changed tests for the issue. Existing tests passing is
  necessary but not sufficient, so also run a reproduction of the issue itself (debugging skill).
- Never edit test files, `conftest.py` or `pytest.ini`: the grader resets them. Put scratch tests in `/tmp`.
- For a quick check, a one-off script in `/tmp` using the public API from the issue is often the fastest
  signal: `run_command("cd /workspace && python /tmp/repro.py")`.

See `references/pytest_cheatsheet.md` for selection syntax.
