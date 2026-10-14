"""Per-task mechanics from official ATIF traces: the numbers the R019 evaluation protocol records (docs/r019.md §6).

Reads only what the Kaggle notebook downloaded (`<results>/g4_results/<variant>_task_results.jsonl` and
`<variant>/traces/trace_<task>.json`). Stdlib only; safe to run with `python3 -I`.

Per task and variant:
  resolved, status, error, counted tool calls, duration, LLM turns;
  first/last source edit (budget-counted call index, 1-based) and the edit channel;
  post-final-edit check: a run_command that runs a test or Python after the last edit and before the last submit;
  scratch artifacts in the final patch (non-source files: repro*/reproduce*/debug*/test_* at the repo root, ...);
  invalid tool operations: write_file/read_file/edit_file outside /workspace ("Path traversal"), BudgetExceeded
  rejections, edit_file calls missing old_string (not counted by the harness), code-edit fallback uses;
  submit_patch calls, empty submits (patch_size 0) and repeated submits;
  call-cap hit (28 counted calls), session timeout, turn-limit end, unregistered-tool calls.
Per variant: totals; per variant pair on the common tasks: wins / losses / ties.

Usage:
  python3 -I scripts/trace_mechanics.py RESULTS_DIR[:label] [RESULTS_DIR2[:label2] ...] [--variant NAME ...]
                                        [--out evaluations/analysis/<id>_mechanics.json]
A RESULTS_DIR may name one variant inside a results dir as DIR@variant (e.g. R018-score-boost@r017_control).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path

CALL_CAP = 28
SCRATCH = re.compile(r"^(repro|reproduce|debug|verify|scratch|check|demo|example|tmp|test_|tests?_)", re.I)
TEST_CMD = re.compile(r"\b(pytest|unittest|python3?\s+(-c\b|-m\b|/tmp/|\S+\.py))", re.I)
EDIT_TOOLS = ("edit_file", "write_file", "run_skill_script")


def load_results(results: Path, variant: str) -> dict[str, dict]:
    rows = {}
    path = results / f"{variant}_task_results.jsonl"
    for line in path.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            rows[d["instance_id"]] = d
    return rows


def calls_of(trace: dict) -> list[dict]:
    """Flatten ATIF steps into [{name, args, obs, counted}] in call order."""
    out = []
    for step in trace.get("steps", []):
        tcs = step.get("tool_calls") or []
        obs = step.get("observation") or {}
        results = obs.get("results") or ([obs] if obs else [])
        for i, tc in enumerate(tcs):
            content = ""
            if i < len(results):
                content = str(results[i].get("content") or "")
            out.append({"name": tc.get("function_name") or "", "args": tc.get("arguments") or {}, "obs": content,
                        "elapsed": (tc.get("extra") or {}).get("elapsed_s")})
    for c in out:
        c["counted"] = is_counted(c)
    return out


def is_counted(c: dict) -> bool:
    """Reproduces the harness's budget-counted calls (R018 trace analysis: exact for all 24 R017 tasks)."""
    if c["name"] in ("submit_patch", "get_status", "list_skills", "load_skill", "load_skill_resource"):
        return False
    if "BudgetExceeded" in c["obs"]:
        return False
    if "mandatory input parameters are not present" in c["obs"]:
        return False          # google-adk rejects the call before the tool (and its budget gate) runs
    if c["name"] not in ("run_command", "read_file", "edit_file", "write_file", "run_skill_script",
                         "get_code_neighbors", "search_similar_code", "get_code_subgraph"):
        return False          # an unregistered tool never reaches a budget gate
    return True


def is_source_edit(c: dict) -> bool:
    n, a, o = c["name"], c["args"], c["obs"]
    if n == "edit_file":
        return '"status": "ok"' in o
    if n == "write_file":
        fp = str(a.get("filepath", ""))
        return '"status": "ok"' in o and not SCRATCH.match(os.path.basename(fp)) and "/" in fp.strip("/")
    if n == "run_skill_script":
        return "EDITED " in o
    return False


def patch_files(patch: str) -> list[str]:
    return sorted({l[6:].split()[0] for l in (patch or "").splitlines() if l.startswith("+++ b/")})


def is_scratch_path(p: str) -> bool:
    base = os.path.basename(p)
    return bool(SCRATCH.match(base)) and ("/" not in p or p.startswith(("tests/", "test/")))


def analyse(row: dict, trace_path: Path) -> dict:
    trace = json.loads(trace_path.read_text()) if trace_path.exists() else {"steps": []}
    calls = calls_of(trace)
    counted_idx = 0
    index_of = {}                       # position in calls -> budget-counted call number
    for i, c in enumerate(calls):
        if c["counted"]:
            counted_idx += 1
            index_of[i] = counted_idx
    edits = [i for i, c in enumerate(calls) if is_source_edit(c)]
    submits = [i for i, c in enumerate(calls) if c["name"] == "submit_patch"]
    empty_submits = [i for i in submits if '"patch_size": 0' in calls[i]["obs"]]
    last_submit = submits[-1] if submits else len(calls)
    post_checks = []
    if edits:
        for i in range(edits[-1] + 1, min(last_submit, len(calls)) if submits else len(calls)):
            c = calls[i]
            if c["name"] == "run_command" and TEST_CMD.search(str(c["args"].get("command", ""))):
                post_checks.append(i)
    files = patch_files(row.get("patch", ""))
    error = row.get("error") or ""
    return {
        "resolved": bool(row.get("resolved")),
        "status": row.get("status"),
        "error": error or None,
        "calls": row.get("tool_calls"),
        "counted_from_trace": counted_idx,
        "llm_calls": row.get("llm_calls"),
        "dur": row.get("duration_s"),
        "edited": bool(edits),
        "first_edit_call": index_of.get(edits[0]) if edits else None,
        "last_edit_call": index_of.get(edits[-1]) if edits else None,
        "edit_channels": sorted({calls[i]["name"] for i in edits}),
        "post_final_edit_check": bool(post_checks),
        "post_final_edit_check_cmds": [str(calls[i]["args"].get("command", ""))[:80] for i in post_checks][:3],
        "patch_files": files,
        "scratch_in_patch": [f for f in files if is_scratch_path(f)],
        "test_files_in_patch": [f for f in files if "/tests/" in "/" + f or os.path.basename(f).startswith("test_")],
        "invalid_path_ops": sum(1 for c in calls if "Path traversal" in c["obs"]),
        "budget_rejections": sum(1 for c in calls if "BudgetExceeded" in c["obs"]),
        "missing_old_string": sum(1 for c in calls if c["name"] == "edit_file"
                                  and "mandatory input parameters are not present" in c["obs"]),
        "fallback_uses": sum(1 for c in calls if c["name"] == "run_skill_script"),
        "fallback_edits": sum(1 for c in calls if c["name"] == "run_skill_script" and "EDITED " in c["obs"]),
        "workspace_scratch_writes": sum(1 for c in calls if c["name"] == "write_file"
                                        and SCRATCH.match(os.path.basename(str(c["args"].get("filepath", ""))))
                                        and '"status": "ok"' in c["obs"]),
        "rm_calls": sum(1 for c in calls if c["name"] == "run_command"
                        and re.match(r"\s*rm\b", str(c["args"].get("command", "")))),
        "submits": len(submits),
        "empty_submits": len(empty_submits),
        "repeated_empty_submits": max(0, len(empty_submits) - 1),
        "submits_after_cap": sum(1 for i in submits if all(not calls[j]["counted"] for j in range(i, len(calls)))
                                 and counted_idx >= CALL_CAP and i > max(index_of, default=-1)),
        "cap_hit": (row.get("tool_calls") or 0) >= CALL_CAP,
        "timeout": "session timeout" in error,
        "turn_limit": "turns budget" in error or "LLM turns" in error,
        "unknown_tool_calls": sum(1 for c in calls if c["name"] and c["name"] not in (
            "run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch",
            "get_code_neighbors", "search_similar_code", "get_code_subgraph", "load_skill", "run_skill_script",
            "list_skills", "load_skill_resource")),
    }


def summarise(rows: dict[str, dict]) -> dict:
    n = len(rows)
    vals = list(rows.values())
    durs = [r["dur"] for r in vals if r["dur"] is not None]
    edited = [r for r in vals if r["edited"]]
    return {
        "tasks": n,
        "resolved": sum(r["resolved"] for r in vals),
        "wrong_fix": sum(1 for r in vals if r["edited"] and not r["resolved"]),
        "no_edit": sum(1 for r in vals if not r["edited"] and not r["resolved"]),
        "scratch_patches": sum(1 for r in vals if r["scratch_in_patch"]),
        "test_file_patches": sum(1 for r in vals if r["test_files_in_patch"]),
        "invalid_path_ops": sum(r["invalid_path_ops"] for r in vals),
        "tasks_with_invalid_path_ops": sum(1 for r in vals if r["invalid_path_ops"]),
        "budget_rejections": sum(r["budget_rejections"] for r in vals),
        "missing_old_string": sum(r["missing_old_string"] for r in vals),
        "fallback_uses": sum(r["fallback_uses"] for r in vals),
        "workspace_scratch_writes": sum(r["workspace_scratch_writes"] for r in vals),
        "rm_calls": sum(r["rm_calls"] for r in vals),
        "submits": sum(r["submits"] for r in vals),
        "empty_submits": sum(r["empty_submits"] for r in vals),
        "tasks_with_repeated_empty_submits": sum(1 for r in vals if r["repeated_empty_submits"]),
        "max_submits_in_a_task": max((r["submits"] for r in vals), default=0),
        "post_final_edit_check": f"{sum(1 for r in edited if r['post_final_edit_check'])}/{len(edited)}",
        "cap_hits": sum(r["cap_hit"] for r in vals),
        "timeouts": sum(r["timeout"] for r in vals),
        "turn_limit_ends": sum(r["turn_limit"] for r in vals),
        "unknown_tool_calls": sum(r["unknown_tool_calls"] for r in vals),
        "median_first_edit_call_resolved": statistics.median(
            [r["first_edit_call"] for r in vals if r["resolved"] and r["first_edit_call"]]) if any(
            r["resolved"] and r["first_edit_call"] for r in vals) else None,
        "mean_s": round(statistics.mean(durs), 1) if durs else None,
        "median_s": round(statistics.median(durs), 1) if durs else None,
        "projected_full_run_h": round((120 * statistics.mean(durs) + 15 * 60) / 3600, 2) if durs else None,
        "max_llm_calls": max((r["llm_calls"] or 0 for r in vals), default=0),
    }


def paired(a: dict[str, dict], b: dict[str, dict]) -> dict:
    common = sorted(set(a) & set(b))
    wins = [t for t in common if a[t]["resolved"] and not b[t]["resolved"]]
    losses = [t for t in common if b[t]["resolved"] and not a[t]["resolved"]]
    return {"common": len(common), "wins": wins, "losses": losses,
            "ties": len(common) - len(wins) - len(losses), "net": len(wins) - len(losses)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="RESULTS_DIR[@variant][:label]")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)
    runs: dict[str, dict[str, dict]] = {}
    for spec in args.runs:
        label = None
        if ":" in spec and not spec.startswith("/") or spec.count(":") == 1 and "@" in spec.split(":")[0]:
            spec, label = spec.rsplit(":", 1)
        variant = "root"
        if "@" in spec:
            spec, variant = spec.split("@", 1)
        d = Path(spec)
        results = d / "g4_results" if (d / "g4_results").is_dir() else d
        label = label or f"{d.name}@{variant}"
        rows = load_results(results, variant)
        runs[label] = {tid: analyse(r, results / variant / "traces" / f"trace_{tid}.json") for tid, r in rows.items()}
    labels = list(runs)
    report = {"note": args.note, "summary": {l: summarise(runs[l]) for l in labels},
              "paired": {f"{a}_vs_{b}": paired(runs[a], runs[b]) for i, a in enumerate(labels) for b in labels[i + 1:]},
              "tasks": {tid: {l: runs[l].get(tid) for l in labels} for tid in sorted({t for l in labels for t in runs[l]})}}
    text = json.dumps(report, indent=1)
    if args.out:
        args.out.write_text(text)
        print(f"wrote {args.out}")
    for l in labels:
        print(l, json.dumps(report["summary"][l]))
    for k, v in report["paired"].items():
        print(k, json.dumps(v))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
