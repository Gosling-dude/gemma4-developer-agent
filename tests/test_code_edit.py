"""skills/code-edit/scripts/edit.py, run the way run_skill_script runs it (see test_skills.run)."""

import json

from test_skills import run

EDIT = "code-edit/scripts/edit.py"
SRC = "pkg/mathutil.py"


def esc(s: str) -> str:
    """What the model copies when it undoes only one of the two JSON escaping levels."""
    return json.dumps(s)[1:-1]


def test_exact_replace_edits_and_shows_diff(repo, tmp_path):
    out = run(EDIT, ["replace", SRC, "return low  # BUG: should return high", "return high"], repo, tmp_path)
    assert out.startswith("EDITED pkg/mathutil.py (exact match)")
    assert "+        return high" in out
    assert "return high" in (repo / SRC).read_text()


def test_escaped_copy_is_matched_and_unescaped(repo, tmp_path):
    src = repo / SRC
    src.write_text(src.read_text() + '\n\ndef label():\n    return "a \\"quoted\\" \\\\ word"\n')
    old = '    return "a \\"quoted\\" \\\\ word"'
    new = '    return "a \\"quoted\\" \\\\ WORD"'
    out = run(EDIT, ["replace", SRC, esc(old), esc(new)], repo, tmp_path)
    assert out.startswith("EDITED"), out
    assert 'return "a \\"quoted\\" \\\\ WORD"' in src.read_text()


def test_multiline_escaped_block_with_literal_newlines(repo, tmp_path):
    src = repo / SRC
    text = src.read_text()
    block = '    if value > high:\n        return low  # BUG: should return high'
    assert block in text
    out = run(EDIT, ["replace", SRC, esc(block), esc(block.replace("return low", "return high"))], repo, tmp_path)
    assert out.startswith("EDITED"), out
    assert "return high  # BUG" in src.read_text()


def test_syntax_breaking_edit_is_refused(repo, tmp_path):
    before = (repo / SRC).read_text()
    out = run(EDIT, ["replace", SRC, "return low  # BUG: should return high", "return (high"], repo, tmp_path)
    assert out.startswith("NOT EDITED: the result would not parse") and "SyntaxError" in out
    assert (repo / SRC).read_text() == before


def test_protected_and_missing_files(repo, tmp_path):
    out = run(EDIT, ["replace", "tests/test_mathutil.py", "a", "b"], repo, tmp_path)
    assert "grader resets" in out
    out = run(EDIT, ["replace", "pkg/nope.py", "a", "b"], repo, tmp_path)
    assert "does not exist" in out


def test_ambiguous_and_not_found(repo, tmp_path):
    out = run(EDIT, ["replace", SRC, "return", "return"], repo, tmp_path)
    assert "matches" in out and "places" in out
    out = run(EDIT, ["replace", SRC, "no such text anywhere", "x"], repo, tmp_path)
    assert out.startswith("NOT EDITED: OLD not found") and "lines PATH START END NEW" in out


def test_flattened_indentation_is_refused_not_guessed(repo, tmp_path):
    block = '    if value > high:\n        return low  # BUG: should return high'
    flat = "\n".join(x.strip() for x in block.split("\n"))
    out = run(EDIT, ["replace", SRC, flat, flat.replace("return low", "return high")], repo, tmp_path)
    assert "indentation" in out and out.startswith("NOT EDITED")


def test_lines_mode_replace_insert_delete(repo, tmp_path):
    src = repo / SRC
    lines = src.read_text().split("\n")
    n = next(i for i, x in enumerate(lines, 1) if "return low  # BUG" in x)
    out = run(EDIT, ["lines", SRC, str(n), str(n), "        return high"], repo, tmp_path)
    assert out.startswith("EDITED") and src.read_text().split("\n")[n - 1] == "        return high"
    out = run(EDIT, ["lines", SRC, "1", "0", "import math"], repo, tmp_path)
    assert out.startswith("EDITED") and src.read_text().startswith("import math\n")
    out = run(EDIT, ["lines", SRC, "1", "1", ""], repo, tmp_path)
    assert out.startswith("EDITED") and not src.read_text().startswith("import math")
    out = run(EDIT, ["lines", SRC, "999", "999", "x"], repo, tmp_path)
    assert "outside the file" in out


def test_repeat_notice_only_when_nothing_changed(repo, tmp_path):
    args = ["replace", SRC, "no such text anywhere", "x"]
    assert "NOTE: identical call" not in run(EDIT, args, repo, tmp_path)
    assert "NOTE: identical call" in run(EDIT, args, repo, tmp_path)
    run(EDIT, ["replace", SRC, "return low  # BUG: should return high", "return high"], repo, tmp_path)
    assert "NOTE: identical call" not in run(EDIT, args, repo, tmp_path)  # the tree changed in between


def test_nav_read_numbered_range_and_repeat_notice(repo, tmp_path):
    out = run("repo-navigation/scripts/nav.py", ["read", SRC, "4", "6"], repo, tmp_path)
    assert out.startswith(f"{SRC}  lines 4-6 of") and "    4| " in out and "    7| " not in out
    assert "next: read" in out
    assert "NOTE: identical call" in run("repo-navigation/scripts/nav.py", ["read", SRC, "4", "6"], repo, tmp_path)


def test_tests_run_repeat_notice(repo, tmp_path):
    args = ["run", "tests/test_mathutil.py"]
    assert "NOTE: identical call" not in run("test-discovery/scripts/tests.py", args, repo, tmp_path)
    assert "NOTE: identical call" in run("test-discovery/scripts/tests.py", args, repo, tmp_path)


def _tmpfile(text: str) -> str:
    """What `cat > /tmp/x <<'EOF' ... EOF` leaves behind (a trailing newline)."""
    import tempfile
    fh = tempfile.NamedTemporaryFile("w", dir="/tmp", suffix=".txt", delete=False)
    fh.write(text + "\n")
    fh.close()
    return fh.name


def test_lines_new_text_from_tmp_file(repo, tmp_path):
    """V1.3 edit channel: code via a heredoc file, the edit call carries only short arguments."""
    src = repo / SRC
    before = src.read_text().split("\n")
    n = next(i for i, x in enumerate(before, 1) if "return low  # BUG" in x)
    new = _tmpfile('        return high  # "fixed" \\ ok')
    out = run(EDIT, ["lines", SRC, str(n), str(n), "@" + new], repo, tmp_path)
    assert out.startswith("EDITED"), out
    lines = src.read_text().split("\n")
    assert lines[n - 1] == '        return high  # "fixed" \\ ok'  # quotes/backslash arrive byte-exact
    assert len(lines) == len(before)  # the heredoc's trailing newline is dropped, no blank line added


def test_indented_heredoc_terminator_is_dropped(repo, tmp_path):
    """`      EOF` (indented) doesn't end a bash heredoc, so it lands in the file; edit.py drops it."""
    src = repo / SRC
    n = next(i for i, x in enumerate(src.read_text().split("\n"), 1) if "return low  # BUG" in x)
    new = _tmpfile("        return high\n      EOF")
    out = run(EDIT, ["lines", SRC, str(n), str(n), "@" + new], repo, tmp_path)
    assert out.startswith("EDITED"), out
    assert "EOF" not in src.read_text()


def test_argfile_found_in_subprocess_sandbox_tmpdir(repo, tmp_path, monkeypatch):
    """The official subprocess sandbox writes run_command's /tmp/x to $TMPDIR/x (E008 found this)."""
    import uuid
    sbtmp = tmp_path / "sandbox_tmp"
    sbtmp.mkdir()
    name = f"g4agent-{uuid.uuid4().hex}.txt"
    (sbtmp / name).write_text("        return high\n")
    monkeypatch.setenv("TMPDIR", str(sbtmp))
    src = repo / SRC
    n = next(i for i, x in enumerate(src.read_text().split("\n"), 1) if "return low  # BUG" in x)
    out = run(EDIT, ["lines", SRC, str(n), str(n), f"@/tmp/{name}"], repo, tmp_path)
    assert out.startswith("EDITED"), out


def test_diagnose_runs_repro_from_sandbox_tmpdir(repo, tmp_path, monkeypatch):
    import uuid
    sbtmp = tmp_path / "sandbox_tmp"
    sbtmp.mkdir()
    name = f"g4agent-repro-{uuid.uuid4().hex}.py"
    (sbtmp / name).write_text("print('REPRO RAN')\n")
    monkeypatch.setenv("TMPDIR", str(sbtmp))
    out = run("debugging/scripts/diagnose.py", ["run", f"/tmp/{name}"], repo, tmp_path)
    assert "exit=0" in out and "REPRO RAN" in out
    out = run("debugging/scripts/diagnose.py", ["cmd", "python3", f"/tmp/{name}"], repo, tmp_path)
    assert "exit=0" in out and "REPRO RAN" in out


def test_parse_refusal_suggests_statement_range(repo, tmp_path):
    """R005 rich_2725: replacing one line of a multi-line call broke the syntax; say which lines to replace."""
    src = repo / SRC
    src.write_text(src.read_text() + "\n\nVALUE = max(\n    1,\n    2,\n)\n")
    lines = src.read_text().split("\n")
    s = next(i for i, x in enumerate(lines, 1) if x.startswith("VALUE = max("))
    out = run(EDIT, ["lines", SRC, str(s + 1), str(s + 1), "    1),"], repo, tmp_path)
    assert out.startswith("NOT EDITED: the result would not parse") and "HINT:" in out
    assert f"START={s} END={s + 3}" in out, out


def test_replace_old_and_new_from_tmp_files(repo, tmp_path):
    old = _tmpfile("        return low  # BUG: should return high")
    new = _tmpfile("        return high")
    out = run(EDIT, ["replace", SRC, "@" + old, "@" + new], repo, tmp_path)
    assert out.startswith("EDITED"), out
    assert "return high" in (repo / SRC).read_text()


def test_missing_argfile_and_decorator_text(repo, tmp_path):
    out = run(EDIT, ["lines", SRC, "1", "0", "@/tmp/g4agent-no-such-file.txt"], repo, tmp_path)
    assert out.startswith("NOT EDITED") and "does not exist" in out and "<<'EOF'" in out
    out = run(EDIT, ["lines", SRC, "1", "0", "import functools"], repo, tmp_path)
    assert out.startswith("EDITED")
    # a decorator starts with "@" but is code, not a file reference
    src = repo / SRC
    n = next(i for i, x in enumerate(src.read_text().split("\n"), 1) if x.startswith("def "))
    out = run(EDIT, ["lines", SRC, str(n), str(n - 1), "@functools.lru_cache(None)"], repo, tmp_path)
    assert out.startswith("EDITED"), out
    assert "@functools.lru_cache(None)\ndef " in src.read_text()


def test_lines_boundary_duplicate_is_refused(repo, tmp_path):
    """Off-by-one: NEW repeats the (kept) line above START or below END."""
    src = repo / SRC
    before = src.read_text()
    lines = before.split("\n")
    n = next(i for i, x in enumerate(lines, 1) if "return low  # BUG" in x)
    above = lines[n - 2]
    assert len(above.strip()) >= 10, above
    out = run(EDIT, ["lines", SRC, str(n), str(n), above + "\n        return high"], repo, tmp_path)
    assert out.startswith("NOT EDITED") and f"START={n - 1}" in out
    assert src.read_text() == before
    out = run(EDIT, ["lines", SRC, str(n - 1), str(n), above + "\n        return high"], repo, tmp_path)
    assert out.startswith("EDITED"), out
