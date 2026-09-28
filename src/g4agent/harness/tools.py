"""The 9 harness tools, bound to one local workspace.

Signatures, JSON response shapes, truncation limits, budget accounting and the low-budget warning
follow HARNESS_README section 6. `/workspace` and `/tmp` inside commands are rewritten to this
task's sandbox directories, like the harness's subprocess backend does.
"""

from __future__ import annotations

import dataclasses
import difflib
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from .graph import CodeGraph

MAX_STDOUT_CHARS = 5_000
MAX_FILE_LINES = 150
MAX_FILE_CHARS = 10_000


@dataclasses.dataclass
class Budget:
    tool_calls: int | None = 40
    time_minutes: float = 4.5
    turns: int | None = 60
    command_timeout_seconds: int = 120


def ok(**kw: Any) -> str:
    return json.dumps({"status": "ok", **kw})


def err(error_type: str, message: str, details: dict | None = None) -> str:
    data: dict[str, Any] = {"status": "error", "error_type": error_type, "error_message": message}
    if details is not None:
        data["details"] = details
    return json.dumps(data)


class BudgetExhausted(Exception):
    pass


class LocalHarness:
    """Tool implementations plus session state for one task attempt."""

    def __init__(self, workspace: Path, tmp_dir: Path, budget: Budget, graph: CodeGraph | None = None,
                 env: dict[str, str] | None = None):
        self.workspace = workspace.resolve()
        self.tmp_dir = tmp_dir.resolve()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.budget = budget
        self.graph = graph
        self.env = env or dict(os.environ)
        self.tool_calls_used = 0
        self.patch_submitted = False
        self.submitted_patch = ""
        self.agent_start: float | None = None
        self.calls: list[dict] = []  # per-call log for analysis

    # ------------------------------------------------------------------ session / budget

    def start(self) -> None:
        self.agent_start = time.monotonic()

    def elapsed(self) -> float:
        return 0.0 if self.agent_start is None else time.monotonic() - self.agent_start

    def remaining_seconds(self) -> float:
        return self.budget.time_minutes * 60 - self.elapsed()

    def out_of_time(self) -> bool:
        return self.remaining_seconds() <= 0

    def _gate(self, name: str, count: bool, fn: Callable[[], str], args: dict) -> str:
        started = time.monotonic()
        if self.out_of_time():
            result = err("BudgetExceeded", "Session time budget exhausted.")
        elif count and self.budget.tool_calls is not None and self.tool_calls_used >= self.budget.tool_calls:
            result = err("BudgetExceeded", f"Tool call budget exhausted ({self.budget.tool_calls}).")
        else:
            if count:
                self.tool_calls_used += 1
            try:
                result = fn()
            except Exception as exc:  # tools must never raise into the agent loop
                result = err(type(exc).__name__, str(exc))
            result = self._attach_warning(result)
        self.calls.append({"tool": name, "args": _short(args), "counted": count,
                           "seconds": round(time.monotonic() - started, 2),
                           "status": _status(result), "t": round(self.elapsed(), 1)})
        return result

    def _attach_warning(self, raw: str) -> str:
        mx = self.budget.tool_calls
        if mx is None or mx < 20:
            return raw
        remaining = max(0, mx - self.tool_calls_used)
        if remaining > 10:
            return raw
        try:
            data = json.loads(raw)
            data.setdefault("budget_warning", f"Only {remaining} tool call(s) remaining ({self.tool_calls_used}/{mx} used). "
                                              "Finalize your edits and call submit_patch soon.")
            return json.dumps(data)
        except ValueError:
            return raw

    # ------------------------------------------------------------------ helpers

    def _rewrite(self, command: str) -> str:
        command = re.sub(r"(?<![\w.])/workspace(?=/|\b)", str(self.workspace), command)
        command = re.sub(r"(?<![\w.])/tmp(?=/|\b)", str(self.tmp_dir), command)
        return command

    def _path(self, filepath: str) -> Path:
        fp = filepath.strip()
        for prefix in ("/workspace/", "/workspace"):
            if fp.startswith(prefix):
                fp = fp[len(prefix):]
                break
        fp = fp.lstrip("/")
        if ".." in Path(fp).parts:
            raise ValueError(f"path traversal not allowed: {filepath}")
        return self.workspace / fp

    def _sh(self, command: str, timeout: float) -> subprocess.CompletedProcess:
        proc = subprocess.Popen(["/bin/bash", "-c", command], cwd=self.workspace, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.env, start_new_session=True)
        try:
            out, errout = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise
        return subprocess.CompletedProcess(command, proc.returncode, out, errout)

    # ------------------------------------------------------------------ tools (public names)

    def tool_functions(self) -> dict[str, Callable[..., str]]:
        h = self

        def run_command(command: str) -> str:
            """Executes a shell command in /bin/bash -c inside /workspace. Output is truncated to 5000 chars."""
            def go() -> str:
                timeout = min(h.budget.command_timeout_seconds, max(5, int(h.remaining_seconds())))
                try:
                    r = h._sh(h._rewrite(command), timeout)
                except subprocess.TimeoutExpired:
                    return err("TimeoutExceeded", f"Command timed out after {timeout} seconds.")
                out = r.stdout[:MAX_STDOUT_CHARS]
                errout = r.stderr[:MAX_STDOUT_CHARS]
                if r.returncode == 0:
                    return ok(stdout=out, stderr=errout, exit_code=0)
                return err("CommandError", f"Command exited with code {r.returncode}",
                           {"stdout": out, "stderr": errout, "exit_code": r.returncode})
            return h._gate("run_command", True, go, {"command": command})

        def submit_patch() -> str:
            """Stages untracked files (git add -N .) and captures the git diff from /workspace as the final patch."""
            def go() -> str:
                patch = h.extract_patch()
                h.submitted_patch = patch
                h.patch_submitted = True
                files = len(re.findall(r"^diff --git ", patch, re.M))
                return ok(patch_size=len(patch), files_changed=files)
            return h._gate("submit_patch", False, go, {})

        def get_status() -> str:
            """Returns live budget consumption and patch status."""
            def go() -> str:
                mx = h.budget.tool_calls
                return ok(tool_calls_used=h.tool_calls_used, patch_submitted=h.patch_submitted,
                          patch_size=len(h.submitted_patch),
                          tool_calls_remaining=None if mx is None else max(0, mx - h.tool_calls_used),
                          max_tool_calls=mx, time_seconds_remaining=round(max(0.0, h.remaining_seconds()), 1),
                          max_time_minutes=h.budget.time_minutes, agent_elapsed_seconds=round(h.elapsed(), 1),
                          max_turns=h.budget.turns, command_timeout_seconds=h.budget.command_timeout_seconds)
            return h._gate("get_status", False, go, {})

        def read_file(filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
            """Reads a file from /workspace with 1-indexed inclusive line slicing (max 150 lines / 10000 chars)."""
            def go() -> str:
                p = h._path(filepath)
                if not p.is_file():
                    return err("FileNotFoundError", f"File not found: {filepath}")
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                total = len(lines)
                s = max(1, int(start_line or 1))
                e = min(total, int(end_line) if end_line else total)
                chunk, chars, last = [], 0, s - 1
                for i in range(s, e + 1):
                    line = lines[i - 1]
                    if len(chunk) >= MAX_FILE_LINES or chars + len(line) > MAX_FILE_CHARS:
                        break
                    chunk.append(line)
                    chars += len(line)
                    last = i
                truncated = last < e
                return ok(filepath=str(p.relative_to(h.workspace)), content="".join(chunk), start_line=s,
                          end_line=last, total_lines=total, is_truncated=truncated)
            return h._gate("read_file", True, go, {"filepath": filepath, "start_line": start_line, "end_line": end_line})

        def edit_file(filepath: str, old_string: str, new_string: str, allow_multiple: bool = False) -> str:
            """Replaces old_string with new_string in an existing non-empty file inside /workspace."""
            def go() -> str:
                p = h._path(filepath)
                if not p.is_file():
                    return err("FileEditError", f"File does not exist: {filepath}")
                text = p.read_text(encoding="utf-8").replace("\r\n", "\n")
                if not text:
                    return err("FileEditError", "File is empty.")
                if not old_string:
                    return err("FileEditError", "old_string must not be empty.")
                new_text, n, strategy = apply_replacement(text, old_string.replace("\r\n", "\n"),
                                                          new_string.replace("\r\n", "\n"), allow_multiple)
                if n == 0:
                    return err("FileEditError", "old_string not found in file (exact, flexible and regex matching failed).")
                if new_text is None:
                    return err("FileEditError", f"old_string matches {n} locations; provide more context or set allow_multiple=true.")
                p.write_text(new_text, encoding="utf-8")
                rel = str(p.relative_to(h.workspace))
                diff = "".join(difflib.unified_diff(text.splitlines(True), new_text.splitlines(True),
                                                    f"a/{rel}", f"b/{rel}"))
                return ok(filepath=rel, occurrences=n, strategy=strategy, diff=diff[:MAX_STDOUT_CHARS],
                          is_truncated=len(diff) > MAX_STDOUT_CHARS)
            return h._gate("edit_file", True, go, {"filepath": filepath, "old_string": old_string,
                                                   "new_string": new_string})

        def write_file(filepath: str, content: str) -> str:
            """Creates or overwrites a file at /workspace/<filepath>, creating parent directories."""
            def go() -> str:
                p = h._path(filepath)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
                return ok(filepath=str(p.relative_to(h.workspace)), size=len(content.encode()))
            return h._gate("write_file", True, go, {"filepath": filepath, "content": content})

        def get_code_neighbors(node: str, edge_type: str | None = None, max_neighbors: int = 50) -> str:
            """Finds incoming and outgoing neighbors (callers, callees, definitions) of a symbol in the code graph."""
            def go() -> str:
                if h.graph is None:
                    return err("GraphUnavailable", "No code graph for this repository.")
                return json.dumps(h.graph.neighbors(node, edge_type, max_neighbors))
            return h._gate("get_code_neighbors", True, go, {"node": node, "edge_type": edge_type})

        def search_similar_code(query: str, k: int = 10) -> str:
            """Finds the top-k graph nodes most similar to the query symbol name (pass a symbol, not a sentence)."""
            def go() -> str:
                if h.graph is None:
                    return err("GraphUnavailable", "No embeddings for this repository.")
                return json.dumps(h.graph.similar(query, k))
            return h._gate("search_similar_code", True, go, {"query": query, "k": k})

        def get_code_subgraph(nodes: list[str]) -> str:
            """Extracts the induced subgraph (nodes and interconnecting edges) for a list of symbols."""
            def go() -> str:
                if h.graph is None:
                    return err("GraphUnavailable", "No code graph for this repository.")
                return json.dumps(h.graph.subgraph(nodes))
            return h._gate("get_code_subgraph", True, go, {"nodes": nodes})

        return {f.__name__: f for f in (run_command, submit_patch, get_status, read_file, edit_file, write_file,
                                        get_code_neighbors, search_similar_code, get_code_subgraph)}

    # ------------------------------------------------------------------ patch extraction

    def extract_patch(self) -> str:
        subprocess.run(["git", "add", "-N", "."], cwd=self.workspace, capture_output=True)
        r = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=self.workspace, capture_output=True, text=True)
        return r.stdout


def apply_replacement(text: str, old: str, new: str, allow_multiple: bool) -> tuple[str | None, int, str]:
    """3-tier matching (exact -> whitespace-flexible lines -> token regex), like adk-eval-core.

    Returns (new_text or None if ambiguous, match_count, strategy).
    """
    n = text.count(old)
    if n:
        if n > 1 and not allow_multiple:
            return None, n, "exact"
        return text.replace(old, new) if allow_multiple else text.replace(old, new, 1), n, "exact"

    # Tier 2: line-by-line match ignoring leading/trailing whitespace; re-indent the replacement.
    lines = text.split("\n")
    old_lines = [l.strip() for l in old.strip("\n").split("\n")]
    matches = [i for i in range(len(lines) - len(old_lines) + 1)
               if [l.strip() for l in lines[i:i + len(old_lines)]] == old_lines]
    if matches:
        if len(matches) > 1 and not allow_multiple:
            return None, len(matches), "flexible"
        new_lines_raw = new.strip("\n").split("\n")
        old_indent = _indent(old.strip("\n").split("\n")[0])
        for i in reversed(matches):
            base = _indent(lines[i])
            rebased = [(base + l[len(old_indent):] if l.startswith(old_indent) else base + l.lstrip()) if l.strip() else ""
                       for l in new_lines_raw]
            lines[i:i + len(old_lines)] = rebased
        return "\n".join(lines), len(matches), "flexible"

    # Tier 3: tokenize around delimiters and allow flexible whitespace between tokens.
    tokens = [t for t in re.split(r"(\s+|[():\[\]{}<>=,])", old) if t and not t.isspace()]
    if not tokens:
        return None, 0, "regex"
    pattern = r"\s*".join(re.escape(t) for t in tokens)
    found = list(re.finditer(pattern, text))
    if not found:
        return None, 0, "regex"
    if len(found) > 1 and not allow_multiple:
        return None, len(found), "regex"
    out = text
    for m in reversed(found):
        out = out[:m.start()] + new + out[m.end():]
    return out, len(found), "regex"


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _short(args: dict) -> dict:
    return {k: (v[:300] + "..." if isinstance(v, str) and len(v) > 300 else v) for k, v in args.items()}


def _status(result: str) -> str:
    try:
        data = json.loads(result)
        return data.get("status", "?") if data.get("status") != "error" else f"error:{data.get('error_type')}"
    except ValueError:
        return "?"
