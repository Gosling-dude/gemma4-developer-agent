---
name: code-edit
description: Edit library source safely when edit_file fails. Tolerates the backslash/quote escaping that tool output adds, can replace a numbered line range instead of matching text, and refuses any edit that would leave a Python file unparseable. Use after an edit_file "old_string not found" error or for edits of lines containing quotes, backslashes or non-ASCII text.
---

# Safe code edits

Run with `run_skill_script(skill_name="code-edit", file_path="scripts/edit.py", args=[...])`.

| Goal | args |
|---|---|
| Replace a unique block of text | `["replace", "pkg/module.py", "OLD TEXT", "NEW TEXT"]` |
| Replace numbered lines 120-124 | `["lines", "pkg/module.py", "120", "124", "NEW TEXT"]` |
| Insert before line 120 | `["lines", "pkg/module.py", "120", "119", "NEW TEXT"]` |

- Take line numbers from `nav.py show` or `nav.py read` output (repo-navigation skill).
- `replace` tries an exact match, then a line-by-line match that ignores escaping and surrounding
  whitespace. Unchanged context lines are kept exactly as they are in the file.
- Nothing is written when the result would not parse; the error and its lines are shown instead.
- Test files, conftest.py, pytest.ini, pyproject.toml, setup.cfg and tox.ini are refused: the grader resets them.
- The output is the diff of the change. Line numbers after the edited block shift by the lines you added or removed.
