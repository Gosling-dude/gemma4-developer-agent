"""Run a command and turn its failure into a focused diagnosis.

Usage (args is a list of strings):
  diagnose.py run PYTHON_FILE [ARGS...]    run a reproduction script (keep it in /tmp)
  diagnose.py cmd SHELL COMMAND ...        run any shell command inside the repository

The output has the exit code, the tail of stdout/stderr, and for a Python traceback the source
around the innermost frames that are *inside the repository*. Library frames are skipped, since that
is rarely where the fix goes.
"""

import os
import re
import subprocess
import sys

WS = os.environ.get("SWE_WORKSPACE") or ("/workspace" if os.path.isdir("/workspace") else os.getcwd())
LIMIT = 4500
FRAME = re.compile(r'^\s*File "([^"]+)", line (\d+), in (\S+)')
_out = []


def emit(line=""):
    _out.append(line)


def flush():
    text = "\n".join(_out)
    if len(text) > LIMIT:
        text = text[:LIMIT] + "\n...[truncated by diagnose.py]"
    print(text)


def repo_frames(text):
    frames = []
    for line in text.splitlines():
        m = FRAME.match(line)
        if not m:
            continue
        path = m.group(1)
        if not os.path.isabs(path):
            path = os.path.join(WS, path)
        path = os.path.realpath(path)
        if path.startswith(os.path.realpath(WS) + os.sep) and "site-packages" not in path:
            frames.append((os.path.relpath(path, os.path.realpath(WS)), int(m.group(2)), m.group(3)))
    return frames


def show_context(rel, lineno, func, radius=4):
    try:
        lines = open(os.path.join(WS, rel), encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return
    emit(f"\n{rel}:{lineno} in {func}")
    for i in range(max(1, lineno - radius), min(len(lines), lineno + radius) + 1):
        mark = ">>" if i == lineno else "  "
        emit(f"{mark}{i:5d}| {lines[i - 1]}")


def run(cmd, shell=False, timeout=180):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run(cmd, cwd=WS, capture_output=True, text=True, timeout=timeout, shell=shell, env=env,
                           executable="/bin/bash" if shell else None)
    except subprocess.TimeoutExpired:
        emit(f"TIMEOUT after {timeout}s. Suspect an infinite loop, a blocking network call, or input().")
        return
    emit(f"exit={r.returncode}")
    out, err = r.stdout.strip(), r.stderr.strip()
    if out:
        emit("--- stdout (tail) ---" if len(out) > 1200 else "--- stdout ---")
        emit(out[-1200:])
    if err:
        emit("--- stderr (tail) ---" if len(err) > 1800 else "--- stderr ---")
        emit(err[-1800:])
    frames = repo_frames(err + "\n" + out)
    if frames:
        seen = set()
        picked = []
        for fr in reversed(frames):
            if (fr[0], fr[1]) not in seen:
                seen.add((fr[0], fr[1]))
                picked.append(fr)
            if len(picked) == 3:
                break
        emit("\n=== innermost repository frames (most likely fix locations) ===")
        for rel, ln, fn in picked:
            show_context(rel, ln, fn)
    elif r.returncode != 0:
        emit("\n(no repository frames in the traceback; the failure may be an assertion in your script)")


def main(argv):
    if argv and argv[0] == "--":
        argv = argv[1:]
    try:
        if len(argv) >= 2 and argv[0] == "run":
            run([sys.executable, *argv[1:]])
        elif len(argv) >= 2 and argv[0] == "cmd":
            run(" ".join(argv[1:]), shell=True)
        else:
            emit(__doc__)
    except Exception as exc:
        emit(f"diagnose.py error: {type(exc).__name__}: {exc}")
    flush()


if __name__ == "__main__":
    main(sys.argv[1:])
