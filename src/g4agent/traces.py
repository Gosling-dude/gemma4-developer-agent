"""Digest official ATIF traces (swegemma SessionTrace JSON) and patches for failure analysis.

Per task: tool-call counts, files inspected, commands run, repeated identical calls (loop signal),
LLM tokens, plus minimal-patch metrics (files and lines changed, test/config edits, scratch files).

Usage: python -m g4agent.traces RESULTS_DIR   (a dir with task_results.jsonl whose rows have 'trace' and 'patch')
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from .harness.verify import is_protected, patch_files


def trace_digest(path: Path) -> dict:
    data = json.loads(path.read_text())
    calls, tokens_in, tokens_out = [], 0, 0
    for step in data.get("steps", []):
        for tc in step.get("tool_calls") or []:
            args = tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {}
            usage = (tc.get("extra") or {}).get("usage") or {}
            tokens_in += usage.get("prompt_tokens") or 0
            tokens_out += usage.get("completion_tokens") or 0
            calls.append((tc.get("function_name"), json.dumps(args, sort_keys=True)))
    files = set()
    commands = []
    for name, a in calls:
        args = json.loads(a)
        if name in ("read_file", "edit_file", "write_file") and args.get("filepath"):
            files.add(str(args["filepath"]).removeprefix("/workspace/"))
        if name == "run_command":
            commands.append(str(args.get("command", ""))[:200])
            files.update(re.findall(r"[\w./-]+\.py", str(args.get("command", ""))))
        if name == "run_skill_script":
            commands.append(f"skill:{args.get('skill_name')}:{args.get('file_path')} {args.get('args')}"[:200])
    dup = Counter(calls)
    repeats = sum(n - 1 for n in dup.values() if n > 1)
    return {"n_tool_calls": len(calls), "tools": dict(Counter(n for n, _ in calls)), "files_inspected": sorted(files),
            "commands": commands, "repeated_identical_calls": repeats,
            "max_same_call": max(dup.values()) if dup else 0, "prompt_tokens": tokens_in, "output_tokens": tokens_out}


def patch_metrics(patch: str) -> dict:
    files = patch_files(patch)
    added = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in patch.splitlines() if l.startswith("-") and not l.startswith("---"))
    return {"files_changed": len(files), "lines_added": added, "lines_removed": removed,
            "test_or_config_files": [f for f in files if is_protected(f)],
            "scratch_files": [f for f in files if "/" not in f and f.endswith((".py", ".txt", ".log"))],
            "debug_prints": sum(1 for l in patch.splitlines() if l.startswith("+") and re.match(r"^\+\s*(print\(|breakpoint\(|import pdb)", l)),
            "malformed": bool(patch.strip()) and not patch.lstrip().startswith("diff --git")}


def main(argv: list[str]) -> int:
    d = Path(argv[0])
    rows = [json.loads(l) for l in (d / "task_results.jsonl").read_text().splitlines() if l.strip()]
    out = []
    for r in rows:
        rec = {"instance_id": r["instance_id"], "resolved": r.get("resolved")}
        if r.get("trace") and Path(r["trace"]).exists():
            rec.update(trace_digest(Path(r["trace"])))
        rec.update(patch_metrics(r.get("patch", "")))
        out.append(rec)
    (d / "trace_digest.json").write_text(json.dumps(out, indent=1))
    for rec in out:
        print(json.dumps({k: rec.get(k) for k in ("instance_id", "resolved", "n_tool_calls", "repeated_identical_calls",
                                                  "files_changed", "lines_added", "test_or_config_files")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
