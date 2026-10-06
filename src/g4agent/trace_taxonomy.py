"""Failure taxonomy and tool-call economics from REAL Gemma 4 trajectories on the official dev set.

Source: the public GraphLoc end-to-end runs (zzgtylors, Kaggle, 2026-09-26): official swegemma harness,
gemma-4-31b-it-qat-w4a16-ct on 4x L4, 106 sound dev tasks x 2 agents (base prompt, +localization skill)
x 3 repeat runs = 636 trajectories with full ATIF traces; gold files/symbols from their GraphLoc-129 labels.
Their agent is NOT ours (thinking on, 25 min / 40 calls / 60 turns, 12 agents per server), so per-call
times don't transfer; call counts, edit failures, loops and failure locations are model behaviour and do.

Every run gets ONE primary category (first failing stage, rules in `primary_category`) plus flags.
Rules are deterministic and use only the trace, the patch, the harness result and the gold labels.
Categories that need reading the model's intent (issue misunderstanding, dependency misunderstanding)
are NOT assigned: no deterministic signal exists, and inventing one would be guessing.

Usage: python -m g4agent.trace_taxonomy [--root evaluations/.cache/third_party] [--out evaluations/analysis]
Writes failure_records_F001.jsonl (one record per run) and failure_taxonomy_F001.json (aggregates).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .harness.verify import is_protected, patch_files

RUNS = ("run1", "run2", "run3")
# scratch scripts the agent leaves at the repository root (never library code)
SCRATCH = re.compile(r"^(repro\w*|reproduce\w*|debug\w*|test_\w+|check\w*|verify\w*|tmp\w*|scratch\w*)\.py$")
SEARCH = re.compile(r"^\s*(cd \S+ && )?(git grep|grep|rg|find|ls|git log|git show|tree|locate)\b")
READ = re.compile(r"^\s*(cd \S+ && )?(cat|sed -n|head|tail|nl|awk|less|more)\b")
TEST = re.compile(r"\b(pytest|unittest|tox|nox)\b")
REVIEW = re.compile(r"^\s*(cd \S+ && )?git (diff|status|stash|checkout|restore)\b")
INPLACE = re.compile(r"\bsed -i|\bperl -pi|\bpatch -p|\bgit apply\b")
PYRUN = re.compile(r"\bpython3?\b")


def call_category(name: str, args: dict) -> str:
    """search / read / graph / edit / test / debug / review / submit / status / other."""
    if name == "submit_patch":
        return "submit"
    if name == "get_status":
        return "status"
    if name in ("get_code_neighbors", "get_code_subgraph"):
        return "graph"
    if name == "search_similar_code":
        return "search"
    if name == "read_file":
        return "read"
    if name == "edit_file":
        return "edit"
    if name == "write_file":
        path = str(args.get("filepath", "")).removeprefix("/workspace/").removeprefix("./")
        return "debug" if path.startswith("/tmp") or SCRATCH.search(path) else "edit"
    if name == "run_command":
        cmd = str(args.get("command", ""))
        if INPLACE.search(cmd):
            return "edit"
        if TEST.search(cmd):
            return "test"
        if REVIEW.search(cmd):
            return "review"
        if SEARCH.search(cmd):
            return "search"
        if READ.search(cmd):
            return "read"
        if PYRUN.search(cmd):
            return "debug"
    return "other"


def edit_outcome(name: str, obs: str) -> str | None:
    """For edit_file: ok / arg_missing / not_found / no_change / other_error. None for other tools."""
    if name != "edit_file":
        return None
    o = obs.replace('\\"', '"')
    if '"status": "ok"' in o:
        return "ok"
    if "mandatory input parameters are not present" in o:
        return "arg_missing"
    if "old_string not found" in o:
        return "not_found"
    if "No changes to apply" in o:
        return "no_change"
    return "other_error"


def read_key(name: str, args: dict) -> tuple | None:
    if name == "read_file":
        return (str(args.get("filepath", "")).removeprefix("/workspace/"), args.get("start_line"), args.get("end_line"))
    if name == "run_command" and READ.search(str(args.get("command", ""))):
        return ("cmd", str(args.get("command", "")).strip())
    return None


def touched_path(name: str, args: dict) -> str | None:
    if name in ("read_file", "edit_file", "write_file"):
        return str(args.get("filepath", "")).removeprefix("/workspace/").removeprefix("./")
    return None


def analyse_trace(path: Path, gold_files: set[str]) -> dict:
    steps = json.loads(path.read_text()).get("steps", [])
    gold_mods = [(g, g[:-3].replace("/", ".").removesuffix(".__init__")) for g in gold_files if g.endswith(".py")]
    calls = []
    for st in steps:
        obs = str((st.get("observation") or {}).get("content") or "")
        for tc in st.get("tool_calls") or []:
            args = tc.get("arguments") if isinstance(tc.get("arguments"), dict) else {}
            calls.append((tc.get("function_name") or "", args, obs))
    cats = Counter()
    edits = Counter()
    first_edit = first_gold_edit = first_gold_seen = None
    reads_seen: dict[tuple, int] = {}
    redundant_reads = 0
    edited_since: set[str] = set()
    prev_sig, streak, max_streak = None, 0, 0
    sig_seen: dict[str, str] = {}
    repeated = repeated_no_info = big_no_info = 0
    ssc = []  # search_similar_code: (chars, gold file in result)
    tests_run = 0
    for i, (name, args, obs) in enumerate(calls, 1):
        cat = call_category(name, args)
        cats[cat] += 1
        sig = name + json.dumps(args, sort_keys=True)
        streak = streak + 1 if sig == prev_sig else 1
        max_streak = max(max_streak, streak)
        prev_sig = sig
        if sig in sig_seen:
            repeated += 1
            if sig_seen[sig] == obs:
                repeated_no_info += 1
                big_no_info += len(obs) > 5000
        sig_seen[sig] = obs
        eo = edit_outcome(name, obs)
        if eo:
            edits[eo] += 1
        p = touched_path(name, args)
        mentioned = p or str(args.get("command", ""))
        if first_gold_seen is None and any(g in mentioned for g in gold_files) and cat in ("read", "edit", "search"):
            first_gold_seen = i
        ok_edit = (eo == "ok") or (cat == "edit" and name != "edit_file" and "error" not in obs[:200].lower())
        if ok_edit and first_edit is None and not (p and is_protected(p)):
            first_edit = i
        if ok_edit and first_gold_edit is None and any(g in mentioned for g in gold_files):
            first_gold_edit = i
        if ok_edit and p:
            edited_since.add(p)
        k = read_key(name, args)
        if k is not None:
            f = k[0]
            if k in reads_seen and f not in edited_since:
                redundant_reads += 1
            reads_seen[k] = i
            edited_since.discard(f)
        if cat == "test":
            tests_run += 1
        if name == "search_similar_code":  # results are dotted node ids (pkg.module.Symbol), not paths
            nonempty = '"count": 0' not in obs
            ssc.append((len(obs), any(m + "." in obs or g in obs for g, m in gold_mods), nonempty))
    return {"n_calls": len(calls), "calls_by_category": dict(cats), "edit_file": dict(edits),
            "first_edit_call": first_edit, "first_gold_edit_call": first_gold_edit,
            "first_gold_seen_call": first_gold_seen, "redundant_reads": redundant_reads,
            "repeated_calls": repeated, "repeated_calls_same_output": repeated_no_info,
            "repeated_big_outputs": big_no_info, "max_identical_streak": max_streak, "tests_run": tests_run,
            "search_similar_code": ssc, "last_tool": calls[-1][0] if calls else None}


def primary_category(r: dict) -> str:
    """First failing stage; the order is the pipeline order ISSUE -> LOCATE -> EDIT -> TEST -> SUBMIT."""
    if r["resolved"]:
        return "resolved"
    err = r["error"].lower()
    src = r["patch_source_files"]
    if "contextwindowexceeded" in err or ("sandbox execution error" in err):
        return "agent_error (exception discards patch)"
    if not src:  # no library source change: scratch/test-only patches count as no patch
        t = r["trace"]
        if t["max_identical_streak"] >= 3:
            return "tool loop"
        if t["edit_file"].get("ok", 0) == 0 and sum(t["edit_file"].values()) > 0:
            return "edit_file failure"
        if "timeout" in err or "budget" in err:
            return "timeout (no source edit)"
        return "patch not submitted"
    gold = set(r["gold_files"])
    if not gold & set(src):
        return "wrong file" if r["trace"]["first_gold_seen_call"] else "repository localization"
    if r["task_has_function_gold"] and not r["edits_gold_function"]:
        return "wrong symbol"
    if r["failure_3p"] == "only other tests fail":
        return "regression"
    if gold - set(src) - set(r["gold_new_files"]):
        return "incomplete patch"
    if r["failure_3p"] in ("tests could not run", "patch did not apply"):
        return "test failure (patch/test infra)"
    return "right location, wrong patch"


def flags(r: dict) -> list[str]:
    t, out = r["trace"], []
    if t["max_identical_streak"] >= 3:
        out.append("loop>=3")
    if t["edit_file"].get("arg_missing") or t["edit_file"].get("not_found"):
        out.append("edit_file_error")
    if r["scratch_files"]:
        out.append("scratch_files_in_patch")
    if r["patch_source_files"] and (r["scratch_files"] or len(r["patch_source_files"]) > max(1, len(r["gold_files"]))):
        out.append("unnecessary_edits")
    if r["protected_files"]:
        out.append("test_or_config_edit")
    if not t["tests_run"]:
        out.append("no_tests_run")
    if t["redundant_reads"] >= 3:
        out.append("redundant_reads>=3")
    if len(r["patch_source_files"]) > max(1, len(r["gold_files"])):
        out.append("more_files_than_gold")
    return out


def load(root: Path) -> list[dict]:
    labels = {json.loads(l)["instance_id"]: json.loads(l)
              for l in (root / "zzgtylors__graphloc-end-to-end-failure-analysis-resource/graphloc129/graphloc129_labels.jsonl").open()}
    csv_rows = {(r["run"], r["arm"], r["instance_id"]): r
                for r in csv.DictReader((root / "zzgtylors__graphloc-end-to-end-failure-analysis-resource/e2e_runs.csv").open())}
    out = []
    for run in RUNS:
        base = root / "graphloc_e2e" / run / "e2e"
        for f in sorted((base / "records").glob("*.jsonl")):
            for line in f.open():
                rec = json.loads(line)
                if rec["arm"] == "gold":
                    continue
                key = (run, rec["arm"], rec["id"])
                c = csv_rows.get(key)
                if c is None:  # task not in the 106 paired tasks
                    continue
                lab = labels[rec["id"]]
                tpath = base / rec["trace"].split("/e2e/", 1)[1]
                files = patch_files(rec.get("patch") or "")
                r = {"run": run, "arm": rec["arm"], "instance_id": rec["id"], "repo": lab["repo"],
                     "resolved": bool(rec["resolved"]), "error": rec.get("error") or "",
                     "duration_min": round(rec["duration"] / 60, 2), "tool_calls_harness": rec["tool_calls"],
                     "gold_files": lab["gold_files"], "gold_new_files": lab.get("new_files") or [],
                     "task_has_function_gold": c["task_has_function_gold"] == "1",
                     "edits_gold_function": c["edits_gold_function"] == "1", "failure_3p": c["failure"],
                     "patch_files": files,
                     "patch_source_files": [p for p in files if not is_protected(p) and not SCRATCH.search(p)],
                     "protected_files": [p for p in files if is_protected(p)],
                     "scratch_files": [p for p in files if SCRATCH.search(p) and not is_protected(p)],
                     "patch_lines": sum(1 for l in (rec.get("patch") or "").splitlines()
                                        if l[:1] in "+-" and not l.startswith(("+++", "---"))),
                     "trace": analyse_trace(tpath, set(lab["gold_files"]))}
                r["category"] = primary_category(r)
                r["flags"] = flags(r)
                out.append(r)
    return out


def _q(xs: list[float]) -> dict:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {}
    pick = lambda p: xs[min(len(xs) - 1, int(p * len(xs)))]
    return {"n": len(xs), "mean": round(statistics.mean(xs), 1), "p50": pick(0.5), "p75": pick(0.75), "p90": pick(0.9), "max": xs[-1]}


def aggregate(rows: list[dict]) -> dict:
    agg: dict = {"n_runs": len(rows), "resolved": sum(r["resolved"] for r in rows)}
    agg["primary_categories"] = dict(Counter(r["category"] for r in rows).most_common())
    agg["flags_all_runs"] = dict(Counter(f for r in rows for f in r["flags"]).most_common())
    agg["flags_failed_runs"] = dict(Counter(f for r in rows if not r["resolved"] for f in r["flags"]).most_common())
    agg["resolve_rate_by_flag"] = {f: [sum(r["resolved"] for r in rows if f in r["flags"]), sum(f in r["flags"] for r in rows)]
                                   for f in agg["flags_all_runs"]}
    # tool-call economics
    econ = {}
    for label, sub in (("all", rows), ("resolved", [r for r in rows if r["resolved"]]),
                       ("failed", [r for r in rows if not r["resolved"]])):
        cats = Counter()
        for r in sub:
            cats.update(r["trace"]["calls_by_category"])
        n = max(1, len(sub))
        econ[label] = {"runs": len(sub), "calls": _q([r["trace"]["n_calls"] for r in sub]),
                       "per_run_by_category": {k: round(v / n, 2) for k, v in cats.most_common()},
                       "redundant_reads_per_run": round(sum(r["trace"]["redundant_reads"] for r in sub) / n, 2),
                       "repeated_calls_per_run": round(sum(r["trace"]["repeated_calls"] for r in sub) / n, 2),
                       "repeated_same_output_per_run": round(sum(r["trace"]["repeated_calls_same_output"] for r in sub) / n, 2),
                       "first_edit_call": _q([r["trace"]["first_edit_call"] for r in sub]),
                       "first_gold_seen_call": _q([r["trace"]["first_gold_seen_call"] for r in sub]),
                       "no_edit_share": round(sum(r["trace"]["first_edit_call"] is None for r in sub) / n, 3)}
    agg["tool_call_economics"] = econ
    # edit_file
    ef = Counter()
    for r in rows:
        ef.update(r["trace"]["edit_file"])
    agg["edit_file_outcomes"] = dict(ef)
    agg["edit_file_fail_rate"] = round(1 - ef.get("ok", 0) / max(1, sum(ef.values())), 3)
    agg["runs_with_edit_file_error"] = sum("edit_file_error" in r["flags"] for r in rows)
    # search_similar_code utility and risk
    ssc = [x for r in rows for x in r["trace"]["search_similar_code"]]
    ssc_err_runs = [r for r in rows if r["trace"]["search_similar_code"] and "contextwindow" in r["error"].lower()]
    agg["search_similar_code"] = {
        "calls": len(ssc), "runs_using": sum(bool(r["trace"]["search_similar_code"]) for r in rows),
        "nonempty_results": sum(n for _, _, n in ssc),
        "gold_file_in_result": sum(g for _, g, _ in ssc), "chars": _q([c for c, _, _ in ssc]),
        "calls_over_20k_chars": sum(c > 20000 for c, _, _ in ssc),
        "context_overflow_runs_that_used_it": len(ssc_err_runs),
        "context_overflow_runs_total": sum("contextwindow" in r["error"].lower() for r in rows),
        "resolve_rate_if_used": [sum(r["resolved"] for r in rows if r["trace"]["search_similar_code"]),
                                 sum(bool(r["trace"]["search_similar_code"]) for r in rows)],
        "resolve_rate_if_not_used": [sum(r["resolved"] for r in rows if not r["trace"]["search_similar_code"]),
                                     sum(not r["trace"]["search_similar_code"] for r in rows)]}
    graph = [r for r in rows if r["trace"]["calls_by_category"].get("graph")]
    agg["graph_tools"] = {"runs_using": len(graph), "calls": sum(r["trace"]["calls_by_category"]["graph"] for r in graph)}
    # patch size vs gold
    res = [r for r in rows if r["resolved"]]
    agg["patch_lines"] = {"resolved": _q([r["patch_lines"] for r in res]),
                          "failed_with_patch": _q([r["patch_lines"] for r in rows if not r["resolved"] and r["patch_files"]])}
    # budget sensitivity in CALLS (time does not transfer: 12 agents shared one server)
    agg["resolved_runs_calls_to_last_needed"] = _q([r["trace"]["n_calls"] for r in res])
    agg["resolved_within_calls"] = {n: sum(r["trace"]["n_calls"] <= n for r in res) for n in (10, 15, 20, 25, 30, 40)}
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    agg["by_arm"] = {a: {"n": len(v), "resolved": sum(x["resolved"] for x in v),
                         "categories": dict(Counter(x["category"] for x in v).most_common())} for a, v in by_arm.items()}
    by_repo = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)
    agg["by_repo"] = {k: {"n": len(v), "resolved": sum(x["resolved"] for x in v)} for k, v in sorted(by_repo.items())}
    return agg


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="evaluations/.cache/third_party")
    ap.add_argument("--out", default="evaluations/analysis")
    ap.add_argument("--id", default="F001")
    a = ap.parse_args(argv)
    rows = load(Path(a.root))
    agg = aggregate(rows)
    out = Path(a.out)
    with (out / f"failure_records_{a.id}.jsonl").open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    agg["source"] = {"data": "GraphLoc end-to-end runs 1-3 (Kaggle notebooks zzgtylors/graphloc-end-to-end-*), public outputs",
                     "label": "3P data, real gemma-4-31b-it-qat-w4a16-ct, official swegemma harness; classification VERIFIED (this script)",
                     "agent": "not ours: thinking on, 25 min / 40 calls / 60 turns, 12 concurrent agents per vLLM server"}
    (out / f"failure_taxonomy_{a.id}.json").write_text(json.dumps(agg, indent=1))
    print(json.dumps({k: agg[k] for k in ("n_runs", "resolved", "primary_categories", "edit_file_outcomes",
                                          "edit_file_fail_rate")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


def digest_results_dir(results: Path, rows: list[dict], labels: dict) -> list[dict]:
    """Same trace metrics for any official-harness results dir (traces/trace_<id>.json) plus its result rows.
    rows: dicts with instance_id/id, resolved, duration_seconds, error/agent_error, patch (optional)."""
    out = []
    for row in rows:
        tid = row.get("instance_id") or row.get("id")
        tp = results / "traces" / f"trace_{tid}.json"
        if not tp.exists():
            continue
        gold = set((labels.get(tid) or {}).get("gold_files") or [])
        t = analyse_trace(tp, gold)
        dur = row.get("duration_seconds") or 0
        out.append({"instance_id": tid, "resolved": bool(row.get("resolved")),
                    "error": row.get("agent_error") or row.get("error") or "", "duration_s": dur,
                    "s_per_call": round(dur / t["n_calls"], 1) if t["n_calls"] else None, "trace": t})
    return out
