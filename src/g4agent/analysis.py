"""Failure taxonomy: classify each task attempt, and aggregate results.

Categories (the primary reason an attempt failed; checked in this order):
  submission_issue        patch empty after edits / failed to apply
  timeout_budget          session ended by time/tool/turn budget with no usable patch
  agent_error             model/server error ended the run
  no_attempt              the agent stopped without editing anything (gave up, looped on nudges)
  localization_failure    edited files don't overlap the reference fix and the agent never opened them
  wrong_root_cause        the agent opened a reference file but edited elsewhere
  incomplete_modification edited a subset of the reference files and tests still fail
  incorrect_modification  edited the right file(s) but the hidden tests fail
  resolved                success

Secondary tags: never_ran_tests, edited_protected_files, used_graph_tools, used_skills, nudged,
touched_extra_files. The categories follow the list in the project brief (issue misunderstanding and
dependency misunderstanding aren't separable from traces automatically; they're refined by hand in
evaluations/analysis/).

Usage: python -m g4agent.analysis evaluations/results/<exp_id> [more dirs...]   (comparison table)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from .harness.tasks import Task
from .harness.verify import is_protected, patch_files


def _tool_names(rec: dict) -> list[str]:
    return [c.get("tool", "") for c in rec.get("tool_log") or []]


def _read_paths(rec: dict) -> set[str]:
    paths = set()
    for c in rec.get("tool_log") or []:
        a = c.get("args") or {}
        if c.get("tool") in ("read_file", "edit_file", "write_file") and a.get("filepath"):
            paths.add(str(a["filepath"]).removeprefix("/workspace/").lstrip("/"))
        if c.get("tool") == "run_command":
            paths.update(re.findall(r"[\w./-]+\.py", str(a.get("command", ""))))
    return paths


def classify(task: Task, rec: dict) -> tuple[str, list[str]]:
    gold = set(patch_files(task.patch))
    tools = _tool_names(rec)
    tags = []
    if "run_command" in tools and not any("pytest" in str((c.get("args") or {}).get("command", ""))
                                          for c in rec.get("tool_log") or [] if c.get("tool") == "run_command"):
        tags.append("never_ran_tests")
    if any(t in tools for t in ("get_code_neighbors", "search_similar_code", "get_code_subgraph")):
        tags.append("used_graph_tools")
    if rec.get("nudges_sent"):
        tags.append("nudged")
    if rec.get("resolved"):
        return "resolved", tags
    stop = rec.get("stop_reason", "")
    if stop == "agent_error":
        return "agent_error", tags
    if rec.get("patch_chars", 0) and not rec.get("patch_applied", True):
        return "submission_issue", tags
    if not rec.get("patch_chars"):
        if stop in ("time_budget", "tool_budget", "turn_budget"):
            return "timeout_budget", tags
        return "no_attempt", tags
    edited = set(rec.get("edited_files") or [])
    if any(is_protected(f) for f in edited):
        tags.append("edited_protected_files")
    src_edited = {f for f in edited if not is_protected(f)}
    if src_edited - gold:
        tags.append("touched_extra_files")
    if not src_edited & gold:
        opened = _read_paths(rec)
        return ("wrong_root_cause" if opened & gold else "localization_failure"), tags
    if gold - src_edited:
        return "incomplete_modification", tags
    return "incorrect_modification", tags


def summarize(results: list[dict]) -> dict:
    n = len(results)
    resolved = sum(1 for r in results if r.get("resolved"))
    cats = Counter(r.get("category", "?") for r in results)
    tags = Counter(t for r in results for t in r.get("tags", []))
    secs = [r.get("seconds") or 0 for r in results]
    return {"tasks": n, "resolved": resolved, "resolution_rate": round(resolved / n, 4) if n else 0.0,
            "categories": dict(cats), "tags": dict(tags),
            "mean_seconds": round(sum(secs) / n, 1) if n else 0,
            "mean_tool_calls": round(sum(r.get("tool_calls") or 0 for r in results) / n, 1) if n else 0}


def compare(dirs: list[Path]) -> str:
    rows = ["| exp | variant | agent | tasks | resolved | rate | mean s | mean calls | top failure |",
            "|---|---|---|---|---|---|---|---|---|"]
    for d in dirs:
        s = json.loads((d / "summary.json").read_text())
        fails = {k: v for k, v in s["categories"].items() if k != "resolved"}
        top = max(fails, key=fails.get) if fails else "-"
        rows.append(f"| {s['exp_id']} | {s['variant']} | {s['agent']} | {s['tasks']} | {s['resolved']} | "
                    f"{s['resolution_rate']:.1%} | {s['mean_seconds']} | {s['mean_tool_calls']} | {top} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    dirs = [Path(a) for a in (argv if argv is not None else sys.argv[1:])]
    if not dirs:
        print(__doc__)
        return 1
    print(compare(dirs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
