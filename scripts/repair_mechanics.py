"""Repair-mechanics metrics for a real-eval results dir (R014 diagnostic gate, docs/r014.md).

Usage: python scripts/repair_mechanics.py evaluations/results/<EXP> [--json out.json]

Per task, from the official traces (coder stage = steps authored by swe_coder):
  plan_gold        the localizer's FILE line names a file the gold patch changes
  first_action     'edit' if the coder's first successful edit precedes its first reproduction run, else 'repro'
  repro_before     reproduction/probe runs (python scripts or -c snippets, debugging-skill run/cmd) before the
                   first successful edit (all of them if it never edits)
  first_edit_call  coder tool-call index of the first successful edit (edit_file ok / code-edit EDITED)
  first_edit_s     coder-relative seconds to that edit
  max_identical    longest run of identical consecutive coder tool calls
  tests_after      an existing-test run (pytest / test-discovery run) after the last successful edit
  corrections      successful edits that follow a failed check (repro or test) made after an earlier edit
  time_cap         the harness logged "agent timed out" for the task (kernel log), or the result says so
"""

import json
import re
import statistics as st
import sys
from pathlib import Path


def _obs(step) -> str:
    return str((step.get("observation") or {}).get("content") or "").replace('\\"', '"')


def ok_edit(name, args, obs) -> bool:
    if name == "edit_file":
        return '"status": "ok"' in obs
    return name == "run_skill_script" and args.get("skill_name") == "code-edit" and "EDITED " in obs \
        and "NOT EDITED" not in obs


def is_repro(name, args) -> bool:
    if name == "run_skill_script":
        return args.get("skill_name") == "debugging" and (args.get("args") or [""])[0] in ("run", "cmd")
    if name != "run_command":
        return False
    cmd = args.get("command", "")
    return "pytest" not in cmd and bool(re.search(r"python3? (-c|/tmp/|repro|\S+\.py)", cmd))


def is_test(name, args) -> bool:
    return (name == "run_command" and "pytest" in args.get("command", "")) or \
        (name == "run_skill_script" and args.get("skill_name") == "test-discovery"
         and (args.get("args") or [""])[0] == "run")


def failed(obs) -> bool:
    return bool(re.search(r'"status": "error"|FAILED|Traceback|AssertionError|Error:|exit_code": [1-9]', obs))


def task_metrics(trace: dict, gold_files: list[str]) -> dict:
    plan, calls, c0 = None, [], None
    for s in trace["steps"]:
        ex = s.get("extra") or {}
        if ex.get("author") == "localizer" and ex.get("event_type") == "final":
            plan = s.get("message")
        if ex.get("author") != "swe_coder":
            continue
        c0 = ex.get("elapsed_s") or 0 if c0 is None else c0
        for c in s.get("tool_calls") or []:
            calls.append((c["function_name"], c.get("arguments") or {}, _obs(s), (ex.get("elapsed_s") or 0) - c0))
    m = re.search(r"^FILE:\s*(\S+)", plan or "", re.M)
    edits = [i for i, (n, a, o, _) in enumerate(calls) if ok_edit(n, a, o)]
    repros = [i for i, (n, a, _, _) in enumerate(calls) if is_repro(n, a)]
    fe = edits[0] if edits else None
    streak = best = 1 if calls else 0
    for i in range(1, len(calls)):
        same = calls[i][0] == calls[i - 1][0] and json.dumps(calls[i][1], sort_keys=True) == \
            json.dumps(calls[i - 1][1], sort_keys=True)
        streak = streak + 1 if same else 1
        best = max(best, streak)
    corrections, pending_fail = 0, False
    for i, (n, a, o, _) in enumerate(calls):
        if fe is not None and i > fe and (is_repro(n, a) or is_test(n, a)) and failed(o):
            pending_fail = True
        elif pending_fail and ok_edit(n, a, o):
            corrections += 1
            pending_fail = False
    return {
        "has_plan": plan is not None, "plan_file": m.group(1).strip("`") if m else None,
        "plan_gold": bool(m) and m.group(1).strip("`") in (gold_files or []),
        "coder_calls": len(calls), "edited": fe is not None,
        "first_action": None if fe is None and not repros else ("edit" if fe is not None and (not repros or fe < repros[0]) else "repro"),
        "repro_before": sum(1 for i in repros if fe is None or i < fe),
        "first_edit_call": None if fe is None else fe + 1,
        "first_edit_s": None if fe is None else round(calls[fe][3], 1),
        "max_identical": best,
        "tests_after": bool(edits) and any(is_test(n, a) for n, a, _, _ in calls[edits[-1] + 1:]),
        "corrections": corrections,
    }


def analyse(d: Path) -> dict:
    res = d / "g4_results"
    rows = {json.loads(l)["instance_id"]: json.loads(l) for l in (res / "root_task_results.jsonl").read_text().splitlines()}
    gold = {json.loads(l)["instance_id"]: json.loads(l) for l in (res / "gold_control.jsonl").read_text().splitlines()}
    log = next(d.glob("g4-*.log"), None)
    capped = set(re.findall(r"Task (\S+) agent timed out", log.read_text())) if log else set()
    out = {}
    for tid, r in rows.items():
        tp = res / "root" / "traces" / f"trace_{tid}.json"
        m = task_metrics(json.loads(tp.read_text()), gold[tid].get("patch_files") or []) if tp.exists() else {}
        m.update(resolved=bool(r["resolved"]), duration_s=r["duration_s"],
                 time_cap=tid in capped or "timeout" in (r.get("error") or ""),
                 harness_error="Sandbox execution error" in (r.get("error") or ""))
        out[tid] = m
    return out


def summary(per_task: dict) -> dict:
    gp = [m for m in per_task.values() if m.get("plan_gold")]
    gp_fail = [m for m in gp if not m["resolved"]]
    e = [m for m in gp if m["edited"]]
    med = lambda xs: st.median(xs) if xs else None
    return {
        "resolved": sum(m["resolved"] for m in per_task.values()), "tasks": len(per_task),
        "harness_errors": sum(m["harness_error"] for m in per_task.values()),
        "plans": sum(m.get("has_plan", False) for m in per_task.values()),
        "gold_file_plans": len(gp),
        "gold_plan_resolved": sum(m["resolved"] for m in gp),
        "gold_plan_edit_before_repro": sum(m["first_action"] == "edit" for m in gp),
        "gold_plan_never_edited": sum(not m["edited"] for m in gp),
        "gold_plan_repro_before_edit_median": med([m["repro_before"] for m in gp]),
        "gold_plan_first_edit_call_median": med([m["first_edit_call"] for m in e]),
        "gold_plan_first_edit_s_median": med([m["first_edit_s"] for m in e]),
        "gold_plan_unresolved_no_edit": sum(not m["edited"] for m in gp_fail),
        "gold_plan_unresolved_edited": sum(m["edited"] for m in gp_fail),
        "identical_streak_ge5": sum(m.get("max_identical", 0) >= 5 for m in per_task.values()),
        "tests_after_last_edit": f'{sum(m["tests_after"] for m in per_task.values() if m.get("edited"))}'
                                 f'/{sum(m.get("edited", False) for m in per_task.values())}',
        "tasks_with_validation_driven_correction": sum(m.get("corrections", 0) > 0 for m in per_task.values()),
        "time_caps": sum(m["time_cap"] for m in per_task.values()),
        "mean_duration_s": round(st.mean(m["duration_s"] for m in per_task.values()), 1),
    }


def main(argv: list[str]) -> int:
    d = Path(argv[0])
    per_task = analyse(d)
    s = summary(per_task)
    for k, v in s.items():
        print(f"{k:42} {v}")
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(json.dumps({"summary": s, "tasks": per_task}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
