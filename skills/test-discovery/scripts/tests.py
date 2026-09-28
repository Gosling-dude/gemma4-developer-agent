"""Test discovery and condensed test runs, one tool call each.

Usage (args is a list of strings):
  tests.py related PATH_OR_SYMBOL [...]   test files/functions most related to a source file or symbol
  tests.py run TARGET [TARGET ...] [-k EXPR] [--timeout S]
                                          run pytest on the targets and print a condensed report
  tests.py info                           test framework, config and how tests are laid out

`run` never runs the whole suite. It needs at least one explicit target, e.g.
tests/test_utils.py or tests/test_utils.py::test_parse. The report puts the counts first, then
each failure's assertion/exception and the innermost repository frames.
"""

import os
import re
import subprocess
import sys
from collections import defaultdict

WS = os.environ.get("SWE_WORKSPACE") or ("/workspace" if os.path.isdir("/workspace") else os.getcwd())
LIMIT = 4500
_out = []


def emit(line=""):
    _out.append(line)


def flush():
    text = "\n".join(_out)
    if len(text) > LIMIT:
        text = text[:LIMIT] + "\n...[truncated by tests.py]"
    print(text)


def git(*args, timeout=60):
    try:
        return subprocess.run(["git", "-C", WS, *args], capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def is_test(path):
    p = "/" + path
    name = os.path.basename(path)
    return ("/tests/" in p or "/test/" in p or "/testing/" in p or name.startswith("test_")
            or name.endswith("_test.py"))


def test_files():
    return [f for f in git("ls-files", "*.py").splitlines() if is_test(f) and not f.endswith("conftest.py")]


# ----------------------------------------------------------------------------- related

def cmd_related(args):
    if not args:
        emit("usage: related PATH_OR_SYMBOL [...]")
        return
    tfiles = test_files()
    scores = defaultdict(float)
    reasons = defaultdict(set)
    for arg in args:
        if arg.endswith(".py"):
            stem = os.path.basename(arg)[:-3]
            if stem == "__init__":
                stem = os.path.basename(os.path.dirname(arg))
            module = arg[:-3].replace("/", ".").removeprefix("src.").removesuffix(".__init__")
            for t in tfiles:
                tstem = os.path.basename(t)[:-3]
                if tstem in (f"test_{stem}", f"{stem}_test", f"test_{stem}s") or tstem.startswith(f"test_{stem}_"):
                    scores[t] += 10
                    reasons[t].add("name match")
            names = [module, stem]
        else:
            names = [arg.split(".")[-1]]
        for name in names:
            out = git("grep", "-c", "-w", "-F", "-e", name, "--", *tfiles) if tfiles else ""
            for line in out.splitlines():
                path, _, cnt = line.rpartition(":")
                if cnt.isdigit():
                    scores[path] += min(int(cnt), 20) * 0.5
                    reasons[path].add(f"mentions {name} x{cnt}")
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:6]
    if not ranked:
        emit("no related tests found; try 'info' or run_command: git grep -l <name> -- tests")
        return
    emit("RELATED TEST FILES:")
    for path, s in ranked:
        emit(f"  {s:5.1f}  {path}  ({', '.join(sorted(reasons[path]))})")
    # Name the specific test functions that mention the symbols, so -k can target them.
    sym = [a.split(".")[-1] for a in args if not a.endswith(".py")]
    if sym:
        emit("\nTEST FUNCTIONS MENTIONING THE SYMBOL:")
        shown = 0
        for path, _ in ranked[:3]:
            try:
                lines = open(os.path.join(WS, path), encoding="utf-8", errors="replace").read().splitlines()
            except OSError:
                continue
            current = None
            for line in lines:
                m = re.match(r"^\s*(?:async\s+)?def\s+(test\w*)", line)
                if m:
                    current = m.group(1)
                elif current and any(re.search(rf"\b{re.escape(s)}\b", line) for s in sym):
                    emit(f"  {path}::{current}")
                    current = None
                    shown += 1
                    if shown >= 12:
                        break
    emit(f"\nRun: tests.py run {ranked[0][0]}   (add -k NAME to narrow)")


# ----------------------------------------------------------------------------- run

FAIL_HDR = re.compile(r"^_{3,} (.+?) _{3,}$")
SUMMARY = re.compile(r"^=*\s*(\d+ (?:passed|failed|errors?|skipped|deselected|xfailed|xpassed).*?|no tests ran) in [\d.]+s")


def condense(output):
    """Extract the summary line and a compact view of each failure from `pytest --tb=short -rfE` output."""
    lines = output.splitlines()
    summary = next((m.group(1) for l in reversed(lines) if (m := SUMMARY.search(l))), None)
    blocks = []
    current = None
    for line in lines:
        m = FAIL_HDR.match(line.strip())
        if m and not line.startswith("=="):
            current = [m.group(1)]
            blocks.append(current)
        elif line.startswith("=") and current is not None:
            current = None
        elif current is not None:
            current.append(line)
    failures = []
    for block in blocks:
        name, body = block[0], block[1:]
        keep = []
        for l in body:
            s = l.rstrip()
            if s.startswith("E ") or re.match(r"^\S.*\.py:\d+: ", s) or s.startswith(">"):
                keep.append(s)
        # Keep the last frames and error lines; that's where the diagnosis usually is.
        failures.append((name, keep[-14:]))
    short = [l for l in lines if l.startswith(("FAILED ", "ERROR "))]
    return summary, failures, short


def cmd_run(args):
    targets, extra, timeout = [], [], 240
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-k" and i + 1 < len(args):
            extra += ["-k", args[i + 1]]
            i += 2
            continue
        if a == "--timeout" and i + 1 < len(args):
            timeout = int(float(args[i + 1]))
            i += 2
            continue
        if a.startswith("-"):
            extra.append(a)
        else:
            targets.append(a)
        i += 1
    if not targets:
        emit("refusing to run the whole suite: pass explicit test files or node ids")
        return
    cmd = [sys.executable, "-m", "pytest", *targets, *extra, "-q", "--tb=short", "-rfE",
           "-p", "no:cacheprovider", "--color=no"]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run(cmd, cwd=WS, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        emit(f"TIMEOUT after {timeout}s running: {' '.join(cmd[2:])}")
        emit("Narrow the target (single test node) or check for an infinite loop / network wait.")
        return
    out = r.stdout + "\n" + r.stderr
    summary, failures, short = condense(out)
    emit(f"exit={r.returncode}  {summary or 'no pytest summary line'}")
    emit(f"cmd: pytest {' '.join(targets + extra)}")
    if r.returncode == 0:
        emit("ALL SELECTED TESTS PASSED")
        return
    if r.returncode == 5:
        emit("NO TESTS COLLECTED: wrong path or -k expression")
    if ("ERROR collecting" in out or "ImportError" in out) and not failures:
        emit("COLLECTION/IMPORT ERROR (the code may not import; check the traceback):")
        tail = [l for l in out.splitlines() if l.strip()][-25:]
        for l in tail:
            emit("  " + l[:160])
        return
    for name, keep in failures[:6]:
        emit(f"\n--- {name}")
        for l in keep:
            emit("  " + l[:170])
    if len(failures) > 6:
        emit(f"\n... {len(failures) - 6} more failures")
    if short:
        emit("\nFAILED/ERROR nodes:")
        for l in short[:15]:
            emit("  " + l[:170])
    if not failures and not short:
        for l in [l for l in out.splitlines() if l.strip()][-30:]:
            emit("  " + l[:160])


def cmd_info(_args):
    for cfg in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "conftest.py"):
        p = os.path.join(WS, cfg)
        if os.path.exists(p):
            text = open(p, encoding="utf-8", errors="replace").read()
            marker = "[tool.pytest" in text or "[pytest]" in text or "[tool:pytest]" in text or cfg == "conftest.py"
            emit(f"{cfg}{'  (pytest config)' if marker else ''}")
    tf = test_files()
    dirs = defaultdict(int)
    for f in tf:
        dirs[os.path.dirname(f) or "."] += 1
    emit(f"{len(tf)} test files; dirs: " + ", ".join(f"{d}({n})" for d, n in sorted(dirs.items(), key=lambda kv: -kv[1])[:8]))
    uses_unittest = git("grep", "-l", "unittest.TestCase", "--", *tf[:400]).count("\n") if tf else 0
    emit(f"framework: pytest runner; {uses_unittest} files use unittest.TestCase")
    emit("Do not edit tests/conftest.py/pytest.ini: the grader resets them.")


COMMANDS = {"related": cmd_related, "run": cmd_run, "info": cmd_info}


def main(argv):
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv or argv[0] not in COMMANDS:
        emit(__doc__)
    else:
        try:
            COMMANDS[argv[0]](argv[1:])
        except Exception as exc:
            emit(f"tests.py error: {type(exc).__name__}: {exc}")
    flush()


if __name__ == "__main__":
    main(sys.argv[1:])
