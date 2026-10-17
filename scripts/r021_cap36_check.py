"""Independent check of the R021 Stage 1 mechanism (max_tool_calls 28 -> 36) on the five runs we hold locally.

Reads only <results>/g4_results/<variant>_task_results.jsonl and <variant>/traces/trace_<task>.json.
Counting rules mirror scripts/trace_mechanics.py (R019 branch) so numbers line up with docs/r019.md.
This branch (from the R019 head) carries the R017, R018 and R019 result directories, so from the repo root:
  python3 -I scripts/r021_cap36_check.py evaluations/results
Used for docs/r021_stage1_decision.md.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

CAP, NEW_CAP, TIME_CAP = 28, 36, 480.0
EDIT_TOOLS = ("edit_file", "write_file", "run_skill_script")
SCRATCH = re.compile(r"(^|/)(repro|reproduce|debug|verify|scratch|check|demo|example|tmp|test_|tests?_)[^/]*$", re.I)
RUN_EDIT = re.compile(r"sed -i|git apply|patch -p|\bperl -pi\b")

RUNS = [  # label, results dir, variant
    ("R017", "R017-budget-fit", "root"),
    ("R018", "R018-score-boost", "root"),
    ("R018c", "R018-score-boost", "r017_control"),
    ("R019", "R019-tool-loop-guard", "root"),
    ("R019c", "R019-tool-loop-guard", "r017_control"),
]


def is_counted(name: str, obs: str) -> bool:
    if name in ("submit_patch", "get_status", "list_skills", "load_skill", "load_skill_resource"):
        return False
    if "BudgetExceeded" in obs or "mandatory input parameters are not present" in obs:
        return False
    return name in ("run_command", "read_file", "edit_file", "write_file", "run_skill_script",
                    "get_code_neighbors", "search_similar_code", "get_code_subgraph")


def is_edit(name: str, args: dict) -> bool:
    if name in EDIT_TOOLS:
        path = str(args.get("path") or args.get("file_path") or "")
        return not path.startswith("/tmp") and not SCRATCH.search(path)
    if name == "run_command":
        return bool(RUN_EDIT.search(str(args.get("command") or "")))
    return False


def calls_of(trace: dict) -> list[dict]:
    out = []
    for step in trace.get("steps", []):
        tcs = step.get("tool_calls") or []
        obs = step.get("observation") or {}
        results = obs.get("results") or ([obs] if obs else [])
        for i, tc in enumerate(tcs):
            content = str(results[i].get("content") or "") if i < len(results) else ""
            name = tc.get("function_name") or ""
            args = tc.get("arguments") or {}
            out.append({"name": name, "args": args, "obs": content,
                        "t": (tc.get("extra") or {}).get("elapsed_s"),
                        "counted": is_counted(name, content), "edit": is_edit(name, args)})
    return out


def episode(results_root: Path, rdir: str, variant: str, row: dict) -> dict:
    tr = results_root / rdir / "g4_results" / variant / "traces" / f"trace_{row['instance_id']}.json"
    calls = calls_of(json.loads(tr.read_text()))
    counted = [c for c in calls if c["counted"]]
    times = [c["t"] for c in counted if c["t"] is not None]
    refused = [c for c in calls if "BudgetExceeded" in c["obs"]]
    warn_idx = next((i + 1 for i, c in enumerate(counted) if "budget_warning" in c["obs"]), None)
    edit_idx = [i + 1 for i, c in enumerate(counted) if c["edit"] and "error" not in c["obs"][:200].lower()]
    src_files = [f for f in (row.get("patch_files") or []) if not SCRATCH.search(f)]
    err = row.get("error") or ""
    gaps = [b - a for a, b in zip(times, times[1:])][-10:]
    return {
        "task": row["instance_id"], "resolved": bool(row["resolved"]),
        "outcome": "R" if row["resolved"] else ("W" if src_files else "N"),
        "dur": float(row["duration_s"]), "n": len(counted),
        "cap_hit": len(counted) >= CAP,
        "timeout": "timeout" in err, "cap_end": "tool call budget" in err, "turn_end": "turns budget" in err,
        "t28": counted[CAP - 1]["t"] if len(counted) >= CAP else None,
        "refused": [(c["name"], c["edit"], c["t"]) for c in refused],
        "refused_edit": any(c["edit"] for c in refused),
        "refused_t": (refused[0]["t"] if refused else None),
        "warn_idx": warn_idx, "first_edit": edit_idx[0] if edit_idx else None,
        "gap": statistics.mean(gaps) if gaps else None,
    }


def main(results_root: Path) -> None:
    eps: dict[str, dict[str, dict]] = {}
    for label, rdir, variant in RUNS:
        rows = [json.loads(l) for l in (results_root / rdir / "g4_results" / f"{variant}_task_results.jsonl")
                .read_text().splitlines() if l.strip()]
        eps[label] = {r["instance_id"]: episode(results_root, rdir, variant, r) for r in rows}
    tasks = sorted(eps["R019"])

    print("== per run: cap/refusal mechanics (counted calls per trace_mechanics rules)")
    print(f"{'run':6} {'res':>3} {'capHit':>6} {'refusedEp':>9} {'refusedEdit':>11} {'timeouts':>8} "
          f"{'warnIdx':>8} {'mean_s':>7}")
    for label, _, _ in RUNS:
        e = eps[label].values()
        wi = sorted({x["warn_idx"] for x in e if x["warn_idx"]})
        print(f"{label:6} {sum(x['resolved'] for x in e):3d} {sum(x['cap_hit'] for x in e):6d} "
              f"{sum(bool(x['refused']) for x in e):9d} {sum(x['refused_edit'] for x in e):11d} "
              f"{sum(x['timeout'] for x in e):8d} {str(wi):>8} {statistics.mean(x['dur'] for x in e):7.1f}")

    print("\n== every episode with a BudgetExceeded refusal (what a 36-call cap would let through)")
    print(f"{'run':6} {'task':15} {'out':3} {'n':>3} {'t@28':>6} {'t_ref':>6} {'left_s':>6} {'gap_s':>5} "
          f"{'edit?':5} {'other runs (R17 R18 R18c R19 R19c)'}")
    refused_eps = []
    for label, _, _ in RUNS:
        for t in tasks:
            x = eps[label][t]
            if not x["refused"]:
                continue
            refused_eps.append((label, x))
            left = TIME_CAP - (x["refused_t"] or x["dur"])
            others = " ".join(eps[l][t]["outcome"] for l, _, _ in RUNS)
            print(f"{label:6} {t:15} {x['outcome']:3} {x['n']:3d} {x['t28'] or 0:6.0f} {x['refused_t'] or 0:6.0f} "
                  f"{left:6.0f} {x['gap'] or 0:5.1f} {'EDIT' if x['refused_edit'] else '-':5} {others}")

    print("\n== tasks with a refused edit in any run: outcomes across all five runs")
    hit = sorted({x["task"] for _, x in refused_eps if x["refused_edit"]})
    for t in hit:
        outs = [eps[l][t]["outcome"] for l, _, _ in RUNS]
        print(f"  {t:15} {' '.join(outs)}   resolved in {outs.count('R')}/5 runs")

    print("\n== budget_warning timing: first edit relative to the warning (resolved episodes)")
    for label, _, _ in RUNS:
        e = [x for x in eps[label].values() if x["resolved"] and x["first_edit"] and x["warn_idx"]]
        after = [x for x in e if x["first_edit"] > x["warn_idx"]]
        names = ", ".join("%s@%s" % (x["task"], x["first_edit"]) for x in after)
        print(f"  {label:6} resolved w/ warning seen: {len(e):2d}; first edit at/after warning: {len(after):2d} "
              f"({names})")

    print("\n== runtime projection at a 36-call cap (120 x mean + 15 min); 8-min session cap unchanged")
    for label, _, _ in RUNS:
        e = list(eps[label].values())
        base = statistics.mean(x["dur"] for x in e)
        new = []
        for x in e:
            d = x["dur"]
            if x["cap_hit"] and not x["timeout"]:
                d = min(TIME_CAP + 5, d + (NEW_CAP - CAP) * (x["gap"] or 15.0))
            new.append(d)
        worst = [TIME_CAP + 5 if (x["cap_hit"] and not x["timeout"]) else x["dur"] for x in e]
        f = lambda m: (120 * m + 900) / 3600
        print(f"  {label:6} now {base:6.1f}s -> {f(base):5.2f}h | est {statistics.mean(new):6.1f}s -> "
              f"{f(statistics.mean(new)):5.2f}h | cap-hit eps to 8 min {statistics.mean(worst):6.1f}s -> "
              f"{f(statistics.mean(worst)):5.2f}h")
    print("\n== run-to-run noise: the unchanged R017 archive run three times (R017, R018c, R019c)")
    same = ["R017", "R018c", "R019c"]
    for i, a in enumerate(same):
        for b in same[i + 1:]:
            w = sum(eps[b][t]["resolved"] and not eps[a][t]["resolved"] for t in tasks)
            l = sum(eps[a][t]["resolved"] and not eps[b][t]["resolved"] for t in tasks)
            print(f"  {a} -> {b}: W{w} L{l} discordant {w + l}/24")
    flips = [t for t in tasks if 0 < sum(eps[l][t]["resolved"] for l, _, _ in RUNS) < 5]
    print(f"  tasks that flip across the five runs: {len(flips)}/24 ({', '.join(flips)})")

    allmean = statistics.mean(x["dur"] for l, _, _ in RUNS for x in eps[l].values())
    print(f"  all five runs pooled mean {allmean:.1f}s -> {(120 * allmean + 900) / 3600:.2f}h; "
          f"10.5 h gate <=> mean <= {(10.5 * 3600 - 900) / 120:.1f}s")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
