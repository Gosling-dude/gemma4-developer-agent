---
name: code-edit
description: The reliable way to edit library source. Write the new code to a /tmp file with a run_command heredoc, then replace a numbered line range with it; no old text is copied, so escaping in tool output can't break the match. Refuses edits that would leave a Python file unparseable, that repeat a line just outside the range, or that touch test/config files.
---

# Safe code edits

Run with `run_skill_script(skill_name="code-edit", file_path="scripts/edit.py", args=[...])`.

Default two-step edit (short tool arguments; the code travels in a heredoc):
1. `run_command`: `cat > /tmp/new.txt <<'EOF'` + the complete replacement lines with their indentation + `EOF`
2. `args=["lines", "pkg/module.py", "120", "124", "@/tmp/new.txt"]`

| Goal | args |
|---|---|
| Replace numbered lines 120-124 | `["lines", "pkg/module.py", "120", "124", "@/tmp/new.txt"]` |
| Insert before line 120 | `["lines", "pkg/module.py", "120", "119", "@/tmp/new.txt"]` |
| Delete lines 120-124 | `["lines", "pkg/module.py", "120", "124", ""]` |
| Replace a unique block of text | `["replace", "pkg/module.py", "@/tmp/old.txt", "@/tmp/new.txt"]` |

- Take line numbers from `nav.py show` or `nav.py read` output (repo-navigation skill), after your last edit.
- Short one-line code can be passed inline instead of `@/tmp/...`.
- `replace` tries an exact match, then a line-by-line match that ignores escaping and surrounding
  whitespace. Unchanged context lines are kept exactly as they are in the file.
- Nothing is written when the result would not parse, or when the new text starts with the line just
  above START or ends with the line just below END (an off-by-one that would duplicate it).
- Test files, conftest.py, pytest.ini, pyproject.toml, setup.cfg and tox.ini are refused: the grader resets them.
- The output is the diff of the change. Line numbers after the edited block shift by the lines you added or removed.
