"""Safe source edits: escape-tolerant matching, syntax check before writing, protected-file guard.

Usage (args is a list of strings):
  edit.py replace PATH OLD NEW          replace the unique block OLD with NEW
  edit.py lines PATH START END NEW      replace lines START..END (1-indexed, inclusive) with NEW;
                                        END = START-1 inserts NEW before line START; NEW "" deletes

Why this exists: harness tool results reach the model JSON-escaped twice, so text copied from
read_file/run_command output often carries stray escapes (\\" for ", \\n for a newline, \\uXXXX for
non-ASCII) and edit_file then fails with "old_string not found". `replace` first tries an exact match,
then compares line by line after undoing up to two levels of escaping and ignoring surrounding
whitespace. Unchanged context lines are written back byte for byte from the file.

A Python file is parsed after the edit; if the edit would break the syntax, nothing is written and the
error is shown. Test files and the files the grader resets are refused.

Stdlib only. The repository is /workspace (or $SWE_WORKSPACE when running outside the sandbox).
"""

import ast
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys


def _find_workspace():
    """run_skill_script chdirs into a temp dir, so cwd is useless; see nav.py for the same lookup."""
    for cand in (os.environ.get("SWE_WORKSPACE"), "/workspace", os.environ.get("PWD"), os.getcwd()):
        if cand and os.path.isdir(os.path.join(cand, ".git")):
            return cand
    return os.environ.get("SWE_WORKSPACE") or os.environ.get("PWD") or os.getcwd()


WS = _find_workspace()
LIMIT = 4500
PROTECTED_NAMES = ("conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")
_ESC = re.compile(r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|x[0-9a-fA-F]{2}|.)", re.S)
_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\", "/": "/"}


def git(*args, timeout=30):
    try:
        return subprocess.run(["git", "-C", WS, *args], capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def repeat_count(argv):
    """How often this exact call already ran with the repository and argument files unchanged (0 = new)."""
    state = git("rev-parse", "HEAD") + git("status", "--porcelain") + git("diff")
    for a in argv:
        if a.startswith("/") and os.path.isfile(a):
            try:
                state += hashlib.sha1(open(a, "rb").read()).hexdigest()
            except OSError:
                pass
    key = hashlib.sha1(json.dumps([WS, os.path.basename(__file__), argv, state]).encode()).hexdigest()
    path = os.environ.get("G4AGENT_STATE", "/tmp/.g4agent_calls")
    try:
        seen = open(path).read().split()
    except OSError:
        seen = []
    try:
        with open(path, "a") as fh:
            fh.write(key + "\n")
    except OSError:
        pass
    return seen.count(key)


def unescape_once(s):
    """Undo one level of JSON/Python string escaping; unknown escapes are kept as they are."""
    def sub(m):
        e = m.group(1)
        if e in _SIMPLE:
            return _SIMPLE[e]
        if e[0] in "uUx" and len(e) > 1:
            try:
                return chr(int(e[1:], 16))
            except ValueError:
                return m.group(0)
        return m.group(0)
    out = _ESC.sub(sub, s)
    try:  # JSON writes characters outside the BMP (emoji) as surrogate pairs; join them
        return out.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        return out


def canon(line):
    """Escape- and whitespace-insensitive form of one line, used only for comparing lines."""
    for _ in range(3):
        u = unescape_once(line)
        if u == line:
            break
        line = u
    return " ".join(line.split())


def is_protected(path):
    p = "/" + path.replace("\\", "/").lstrip("./")
    name = os.path.basename(p)
    return (name in PROTECTED_NAMES or name.startswith("test_") or name.endswith("_test.py")
            or "/tests/" in p or "/test/" in p)


def variants(text):
    """Candidate readings of the model's text: as given, then with one and two levels of escaping undone."""
    out = [("exact", text)]
    once = unescape_once(text)
    if once != text:
        out.append(("unescaped x1", once))
        twice = unescape_once(once)
        if twice != once:
            out.append(("unescaped x2", twice))
    return out


def _trim(lines):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def line_matches(file_lines, old_lines):
    """Start indices where old_lines match file_lines line by line (escape/whitespace-insensitive)."""
    want = [canon(x) for x in old_lines]
    have = [canon(x) for x in file_lines]
    n = len(want)
    return [i for i in range(len(have) - n + 1) if have[i:i + n] == want]


def relative_indents(lines):
    """Indentation of each non-blank line relative to the first line (compares block shapes)."""
    ind = [len(x) - len(x.lstrip()) for x in lines if x.strip()]
    return [n - ind[0] for n in ind] if ind else []


def reindent(new_lines, old_first, file_first):
    """If the model's block is indented differently from the file, shift the new lines the same way."""
    old_ind = old_first[: len(old_first) - len(old_first.lstrip())]
    file_ind = file_first[: len(file_first) - len(file_first.lstrip())]
    if old_ind == file_ind:
        return new_lines
    out = []
    for ln in new_lines:
        if ln.startswith(old_ind):
            out.append(file_ind + ln[len(old_ind):])
        else:
            out.append(ln)
    return out


def syntax_error(path, text):
    if not path.endswith(".py"):
        return None
    try:
        ast.parse(text)
        return None
    except SyntaxError as exc:
        lines = text.splitlines()
        ln = exc.lineno or 0
        ctx = "\n".join(f"{i:5d}| {lines[i - 1]}" for i in range(max(1, ln - 2), min(len(lines), ln + 2) + 1))
        return f"SyntaxError: {exc.msg} (line {ln})\n{ctx}"


def show_diff(path, before, after):
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), f"a/{path}", f"b/{path}", n=2, lineterm="")
    return "\n".join(list(diff)[2:])


def read(path):
    full = os.path.join(WS, path)
    with open(full, encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read()


def write(path, text):
    with open(os.path.join(WS, path), "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def plan_replace(content, old, new):
    """(new_content, strategy) or (None, reason)."""
    if not old.strip():
        return None, "OLD is empty. Use: lines PATH START END NEW to insert."
    tried = []
    for label, o in variants(old):
        c = content.count(o)
        if c == 1:
            candidates = [n for lab, n in variants(new) if lab == label] + [new]
            return [content.replace(o, n, 1) for n in dict.fromkeys(candidates)], f"{label} match"
        tried.append(f"{label}: {c} matches")
        if c > 1:
            return None, f"OLD matches {c} places ({label}). Add 1-2 neighbouring lines to make it unique."
    # Line-by-line comparison, insensitive to escaping and surrounding whitespace.
    nl = "\r\n" if "\r\n" in content else "\n"
    file_lines = content.split(nl)
    for label, o in variants(old):
        old_lines = _trim(o.replace("\r\n", "\n").split("\n"))
        if not old_lines:
            continue
        starts = line_matches(file_lines, old_lines)
        if len(starts) > 1:
            return None, f"OLD matches {len(starts)} places after normalising. Add neighbouring lines."
        if len(starts) == 1:
            i = starts[0]
            block = file_lines[i:i + len(old_lines)]
            if relative_indents(old_lines) != relative_indents(block):
                return None, (f"OLD matches line {i + 1} only if indentation is ignored, and its indentation differs "
                              "from the file, so NEW's indentation can't be trusted. Use: lines PATH START END NEW "
                              "with the file's exact indentation.")
            by_canon = {canon(f): f for f in block}
            results = []
            new_variants = [n for lab, n in variants(new) if lab == label] + [new]
            for n in dict.fromkeys(new_variants):
                new_lines = n.replace("\r\n", "\n").split("\n")
                new_lines = reindent(new_lines, old_lines[0], block[0])
                # Context lines the model copied are written back exactly as they are in the file.
                new_lines = [by_canon.get(canon(x), x) if x.strip() else x for x in new_lines]
                results.append(nl.join(file_lines[:i] + new_lines + file_lines[i + len(old_lines):]))
            return results, f"line match ({label}, whitespace/escape-insensitive) at line {i + 1}"
    return None, ("OLD not found (" + "; ".join(tried) + "). Print the exact lines with "
                  "nav.py read PATH START END, then use: lines PATH START END NEW")


def cmd_replace(args):
    if len(args) != 3:
        return "usage: replace PATH OLD NEW  (three strings after 'replace')"
    path, old, new = args
    content = read(path)
    results, how = plan_replace(content, old, new)
    if results is None:
        return f"NOT EDITED: {how}"
    return commit(path, content, results, how)


def cmd_lines(args):
    if len(args) != 4:
        return "usage: lines PATH START END NEW  (END = START-1 inserts before START)"
    path, start, end, new = args
    try:
        a, b = int(start), int(end)
    except ValueError:
        return "NOT EDITED: START and END must be line numbers"
    content = read(path)
    nl = "\r\n" if "\r\n" in content else "\n"
    lines = content.split(nl)
    if a < 1 or a > len(lines) + 1 or b < a - 1 or b > len(lines):
        return f"NOT EDITED: line range {a}-{b} is outside the file (1-{len(lines)})"
    results = []
    for _, n in variants(new):
        new_lines = [] if n == "" else n.replace("\r\n", "\n").split("\n")
        results.append(nl.join(lines[:a - 1] + new_lines + lines[b:]))
    return commit(path, content, results, f"replaced lines {a}-{b}")


def commit(path, before, results, how):
    """Write the first candidate that keeps the file parseable; otherwise write nothing."""
    first_err = None
    for after in results:
        if after == before:
            return "NOT EDITED: the change is a no-op (NEW equals the current text)."
        err = syntax_error(path, after)
        if err is None:
            write(path, after)
            return f"EDITED {path} ({how}).\n{show_diff(path, before, after)}"
        first_err = first_err or err
    if syntax_error(path, before):  # the file was already broken; don't block the fix
        write(path, results[0])
        return f"EDITED {path} ({how}); note: the file did not parse before this edit either.\n" \
               f"{show_diff(path, before, results[0])}"
    return f"NOT EDITED: the result would not parse, file unchanged.\n{first_err}"


COMMANDS = {"replace": cmd_replace, "lines": cmd_lines}


def main(argv):
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return
    if len(argv) > 1 and is_protected(argv[1]):
        print(f"NOT EDITED: {argv[1]} is a test or config file that the grader resets. Fix the library code.")
        return
    note = ""
    if repeat_count(argv):
        note = "NOTE: identical call already made with the code unchanged; the result is the same. Change approach.\n"
    try:
        out = COMMANDS[argv[0]](argv[1:])
    except FileNotFoundError:
        out = f"NOT EDITED: {argv[1]} does not exist (paths are relative to the repository root)."
    except Exception as exc:  # never crash the agent's turn on a helper bug
        out = f"edit.py error: {type(exc).__name__}: {exc}"
    text = note + out
    print(text if len(text) <= LIMIT else text[:LIMIT] + "\n...[diff truncated by edit.py]")


if __name__ == "__main__":
    main(sys.argv[1:])
