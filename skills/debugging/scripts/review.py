"""Pre-submit patch review: the exact diff that submit_patch would capture, plus problems to fix.

Usage:  review.py            (no arguments)

Checks:
  - untracked files in /workspace (they get into the patch, e.g. repro scripts)
  - edits to test files / conftest.py / pytest.ini / pyproject.toml / setup.cfg / tox.ini
    (the grader resets these, so the fix can't depend on them)
  - leftover debugging code (print/breakpoint/pdb) in added lines
  - changed Python files that fail to compile
  - an empty diff
Then prints the diff (truncated). Ends with VERDICT: READY or VERDICT: FIX FIRST.
"""

import os
import re
import subprocess
import sys

def _find_workspace():
    """The repository root. run_skill_script chdirs into a temp dir first, so cwd is useless; in the Docker
    scorer the repo is /workspace, in the subprocess sandbox (Kaggle notebooks) it is the launching shell's $PWD."""
    for cand in (os.environ.get("SWE_WORKSPACE"), "/workspace", os.environ.get("PWD"), os.getcwd()):
        if cand and os.path.isdir(os.path.join(cand, ".git")):
            return cand
    return os.environ.get("SWE_WORKSPACE") or os.environ.get("PWD") or os.getcwd()


WS = _find_workspace()
LIMIT = 4500
PROTECTED = re.compile(r"(^|/)(conftest\.py|pytest\.ini|\.pytest\.ini|pyproject\.toml|setup\.cfg|tox\.ini|"
                       r"sitecustomize\.py|usercustomize\.py)$|\.pth$")
_out = []


def emit(line=""):
    _out.append(line)


def flush():
    text = "\n".join(_out)
    if len(text) > LIMIT:
        text = text[:LIMIT] + "\n...[truncated by review.py]"
    print(text)


def git(*args):
    return subprocess.run(["git", "-C", WS, *args], capture_output=True, text=True, timeout=60)


def is_test(path):
    p = "/" + path
    name = os.path.basename(path)
    return ("/tests/" in p or "/test/" in p or "/testing/" in p or name.startswith("test_")
            or name.endswith("_test.py"))


def main():
    base = "_swegemma_baseline" if git("rev-parse", "-q", "--verify", "_swegemma_baseline").returncode == 0 else "HEAD"
    problems, notes = [], []
    status = git("status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    untracked = [l[3:] for l in status if l.startswith("??")]
    for u in untracked:
        scratchy = any(w in os.path.basename(u).lower() for w in ("repro", "debug", "scratch", "tmp", "temp"))
        if "/" not in u or scratchy:
            problems.append(f"untracked file will be in the patch: {u} (delete it: run_command rm {u})")
        else:
            notes.append(f"new file included in patch: {u}")
    changed = [f for f in git("diff", "--name-only", base).stdout.splitlines() if f] + untracked
    for f in changed:
        if PROTECTED.search(f):
            problems.append(f"edited runner config {f}: the grader resets it (revert: git checkout {base} -- {f})")
        elif is_test(f):
            notes.append(f"test file {f} changed: the grader resets it, so the fix must not depend on it")
    diff = git("diff", base, "--", ".").stdout
    for u in untracked:
        # Show new files' content too, like `git add -N` would.
        diff += git("diff", "--no-index", "/dev/null", u).stdout
    added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    for l in added:
        s = l.strip()
        if re.match(r"^(print\(|breakpoint\(\)|import pdb|pdb\.set_trace)", s):
            problems.append(f"debug code in added line: {s[:80]}")
    for f in changed:
        full = os.path.join(WS, f)
        if f.endswith(".py") and os.path.exists(full):
            try:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    compile(fh.read(), f, "exec")
            except SyntaxError as exc:
                problems.append(f"syntax error in {f}:{exc.lineno}: {exc.msg}")
    src_changed = [f for f in changed if f.endswith(".py") and not is_test(f) and not PROTECTED.search(f)]
    if not diff.strip():
        problems.append("the diff is EMPTY: submitting now scores zero")
    elif not src_changed:
        problems.append("no non-test source file changed: the grader will see no fix")
    stat = git("diff", "--stat", base).stdout.strip().splitlines()
    emit("DIFF STAT: " + (stat[-1].strip() if stat else "(none)"))
    for f in changed:
        emit(f"  {f}")
    for n in notes:
        emit("note: " + n)
    for p in problems:
        emit("PROBLEM: " + p)
    emit("\n" + (diff[:3000] + ("\n...[diff truncated]" if len(diff) > 3000 else "")))
    emit("VERDICT: " + ("FIX FIRST" if problems else "READY (re-check the diff matches the issue, then submit_patch)"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        emit(f"review.py error: {type(exc).__name__}: {exc}")
    flush()
