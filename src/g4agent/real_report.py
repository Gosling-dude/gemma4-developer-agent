"""Per-task report for a REAL Gemma 4 run downloaded from the Kaggle notebook (g4agent.kaggle_kernel).

Reads only what the official swegemma Evaluator wrote (`*_task_results.jsonl`, `summary.json`, ATIF traces);
never invents a value: a field the run did not record is reported as null.

Per task: id, repo, runtime, tokens, tool/LLM calls, files inspected, files edited, tests run,
patch status, PASS/FAIL, failure category (which cap hit, harness exception that discarded the patch, ...),
edit_file "old_string not found" count, code-edit outcomes, repeat notices, the call/second of the first
successful edit, and (with --tasks) where the patch edits relative to the reference fix.
Per variant: summary; per variant pair: paired outcomes on the common tasks.

Usage: python -m g4agent.real_report RESULTS_DIR [--cap-minutes 5.5] [--tasks tasks.jsonl]
  RESULTS_DIR = output of `kaggle kernels output` (contains g4_results/ or g4_results_bundle.zip).
Writes RESULTS_DIR/report.json and RESULTS_DIR/report.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from .harness.verify import is_protected, patch_files
from .traces import trace_digest

KAGGLE_OUT = "/kaggle/working/g4_results/"


def find_results(d: Path) -> Path:
    for cand in (d / "g4_results", d):
        if list(cand.glob("*_task_results.jsonl")):
            return cand
    bundle = d / "g4_results_bundle.zip"
    if bundle.exists():
        zipfile.ZipFile(bundle).extractall(d / "g4_results")
        return d / "g4_results"
    raise SystemExit(f"no *_task_results.jsonl or g4_results_bundle.zip under {d}")


def local_trace(path: str, root: Path) -> Path | None:
    if not path:
        return None
    p = Path(path)
    if p.exists():
        return p
    if path.startswith(KAGGLE_OUT):
        q = root / path[len(KAGGLE_OUT):]
        return q if q.exists() else None
    return None


def failure_category(row: dict, cap_s: float) -> str | None:
    if row.get("resolved"):
        return None
    err = (row.get("error") or "").lower()
    status = (row.get("status") or "").upper()
    patch = row.get("patch")
    suffix = "" if patch else ", no patch"
    # Error strings of swegemma 0.2.7 harness/agent_runner.py
    if "tool call budget" in err:
        return "cap_hit: tool calls" + suffix
    if "turns budget" in err or "allowed llm turns" in err:
        return "cap_hit: turns" + suffix
    if status in ("TIMEOUT", "BUDGET_EXCEEDED") or "timeout" in err or "time limit" in err \
            or (row.get("duration_s") or 0) >= cap_s - 5:
        return "cap_hit: time" + suffix
    if "sandbox execution error" in err:
        # any non-timeout exception in the agent loop: the harness discards the patch, even a submitted one
        return "harness_exception (patch discarded)"
    if err and "without calling submit_patch" not in err:
        return "agent_or_infra_error"
    if patch is None:
        return "unknown (patch not recorded)"
    if not patch.strip():
        return "no_patch"
    files = patch_files(patch)
    if files and all(is_protected(f) for f in files):
        return "only_test_or_config_edits"
    return "wrong_fix (hidden tests fail)"


_HUNK_FUNC = re.compile(r"^@@[^@]*@@.*?\b(?:def|class)\s+(\w+)")
_DEF_LINE = re.compile(r"^[+-]\s*(?:async\s+)?(?:def|class)\s+(\w+)")


def patch_functions(patch: str) -> set[tuple[str, str]]:
    """(file, function) pairs a patch touches, from hunk headers and changed def/class lines."""
    out, cur = set(), None
    for line in patch.splitlines():
        if line.startswith("+++ "):
            cur = line[4:].removeprefix("b/")
        elif cur and not is_protected(cur):
            m = _HUNK_FUNC.match(line) or _DEF_LINE.match(line)
            if m:
                out.add((cur, m.group(1)))
    return out


def edit_location(patch: str | None, reference: str | None) -> str | None:
    """GraphLoc-style location class vs the reference fix (dev tasks only; analysis, never shown to the agent)."""
    if reference is None or patch is None:
        return None
    files = {f for f in patch_files(patch) if not is_protected(f)}
    if not files:
        return "no_patch" if not patch.strip() else "only_test_or_config_edits"
    gold_files = {f for f in patch_files(reference) if not is_protected(f)}
    if patch_functions(patch) & patch_functions(reference):
        return "gold_function"
    return "gold_file" if files & gold_files else "wrong_file"


def task_record(row: dict, root: Path, cap_s: float, references: dict | None = None) -> dict:
    tr = local_trace(row.get("trace", ""), root)
    dig = trace_digest(tr) if tr else {}
    cmds = dig.get("commands", [])
    patch = row.get("patch")
    edited = sorted(set(patch_files(patch))) if patch else sorted(row.get("patch_files") or [])
    return {
        "location": edit_location(patch, (references or {}).get(row["instance_id"])),
        **{k: dig.get(k) for k in ("edit_file_not_found", "code_edit_ok", "code_edit_refused", "repeat_notices",
                                   "first_edit_call", "first_edit_s", "mean_s_per_call", "max_same_call")},
        "variant": row.get("variant"), "task_id": row["instance_id"], "repo": row.get("repo"),
        "runtime_s": row.get("duration_s"), "start": row.get("start"), "end": row.get("end"),
        "total_tokens": row.get("total_tokens"), "prompt_tokens": dig.get("prompt_tokens"),
        "output_tokens": dig.get("output_tokens"),
        "tool_calls": row.get("tool_calls"), "llm_calls": row.get("llm_calls"),
        "tools": dig.get("tools"), "repeated_identical_calls": dig.get("repeated_identical_calls"),
        "files_inspected": dig.get("files_inspected"), "files_edited": edited,
        "tests_run": [c for c in cmds if "pytest" in c or "tests.py" in c] if tr else None,
        "patch_status": ("not recorded" if patch is None and not row.get("patch_chars") else
                         "empty" if not (patch or row.get("patch_chars")) else
                         f"{len(edited)} file(s), {row.get('patch_chars') or len(patch)} chars"),
        "result": "PASS" if row.get("resolved") else "FAIL",
        "failure_category": failure_category(row, cap_s),
        "status": row.get("status"), "error": (row.get("error") or "")[:300] or None,
        "trace_found": bool(tr),
    }


def variant_summaries(tasks: list[dict]) -> dict:
    out = {}
    for v in sorted({t["variant"] or "?" for t in tasks}):
        ts = [t for t in tasks if (t["variant"] or "?") == v]
        num = lambda k: [t[k] for t in ts if isinstance(t.get(k), (int, float))]
        mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
        out[v] = {"n": len(ts), "resolved": sum(t["result"] == "PASS" for t in ts),
                  "mean_runtime_s": mean(num("runtime_s")), "mean_tool_calls": mean(num("tool_calls")),
                  "mean_first_edit_call": mean(num("first_edit_call")),
                  "no_edit": sum(t["first_edit_call"] is None and t["trace_found"] for t in ts),
                  "edit_file_not_found": sum(num("edit_file_not_found")), "code_edit_ok": sum(num("code_edit_ok")),
                  "failures": dict(Counter(t["failure_category"] for t in ts if t["failure_category"])),
                  "locations": dict(Counter(t["location"] for t in ts if t["location"]))}
    return out


def paired(tasks: list[dict]) -> list[dict]:
    """For every pair of variants, the tasks both ran: resolved by both / only the first / only the second."""
    by = defaultdict(dict)
    for t in tasks:
        by[t["variant"] or "?"][t["task_id"]] = t["result"] == "PASS"
    out = []
    vs = sorted(by)
    for i, a in enumerate(vs):
        for b in vs[i + 1:]:
            common = sorted(set(by[a]) & set(by[b]))
            out.append({"a": a, "b": b, "tasks": len(common),
                        "both": sum(by[a][k] and by[b][k] for k in common),
                        "only_a": [k for k in common if by[a][k] and not by[b][k]],
                        "only_b": [k for k in common if by[b][k] and not by[a][k]]})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir", type=Path)
    ap.add_argument("--cap-minutes", type=float, default=5.5, help="max_time_minutes of the evaluated variant")
    ap.add_argument("--tasks", type=Path, default=None,
                    help="tasks.jsonl with reference patches (dev tasks only) for the edit-location classes")
    args = ap.parse_args(argv)
    references = None
    if args.tasks:
        references = {r["instance_id"]: r.get("patch") for r in
                      (json.loads(l) for l in args.tasks.read_text().splitlines() if l.strip())}
    root = find_results(args.results_dir)
    summary = json.loads((root / "summary.json").read_text()) if (root / "summary.json").exists() else {}
    gold = [json.loads(l) for l in (root / "gold_control.jsonl").read_text().splitlines()] \
        if (root / "gold_control.jsonl").exists() else []
    tasks = []
    for f in sorted(root.glob("*_task_results.jsonl")):
        tasks += [task_record(json.loads(l), root, args.cap_minutes * 60, references)
                  for l in f.read_text().splitlines() if l.strip()]
    n = len(tasks)
    rep = {"model": summary.get("model"), "server_start_s": summary.get("server_start_s"),
           "gold_control": [{"task_id": g["instance_id"], "gold_passes": g["resolved"]} for g in gold],
           "tasks": tasks, "resolved": sum(t["result"] == "PASS" for t in tasks), "n": n,
           "mean_runtime_s": round(sum(t["runtime_s"] or 0 for t in tasks) / n, 1) if n else None,
           "variants": variant_summaries(tasks), "paired": paired(tasks)}
    (args.results_dir / "report.json").write_text(json.dumps(rep, indent=1))
    lines = ["| Task | Repo | Runtime s | Tokens | Tool calls | Files inspected | Files edited | Tests run | Patch | Result | Failure |",
             "|---|---|---:|---:|---:|---|---|---:|---|---|---|"]
    for t in tasks:
        lines.append(f"| {t['task_id']} | {t['repo']} | {t['runtime_s']} | {t['total_tokens']} | {t['tool_calls']} | "
                     f"{len(t['files_inspected'] or [])} | {', '.join(t['files_edited']) or '–'} | "
                     f"{len(t['tests_run']) if t['tests_run'] is not None else '?'} | {t['patch_status']} | "
                     f"{t['result']} | {t['failure_category'] or '–'} |")
    lines.append(f"\nResolved {rep['resolved']}/{n}; mean runtime {rep['mean_runtime_s']} s; model {rep['model']}.")
    lines += ["\n| Variant | Tasks | Resolved | Mean s | Mean calls | Mean call of 1st edit | No edit | "
              "edit_file not found | code-edit ok | Failures | Locations |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for v, s in rep["variants"].items():
        lines.append(f"| {v} | {s['n']} | {s['resolved']} | {s['mean_runtime_s']} | {s['mean_tool_calls']} | "
                     f"{s['mean_first_edit_call']} | {s['no_edit']} | {s['edit_file_not_found']} | {s['code_edit_ok']} | "
                     f"{s['failures'] or '–'} | {s['locations'] or '–'} |")
    if rep["paired"]:
        lines += ["\n| A | B | Common tasks | Both | Only A | Only B |", "|---|---|---:|---:|---|---|"]
        for p in rep["paired"]:
            lines.append(f"| {p['a']} | {p['b']} | {p['tasks']} | {p['both']} | {', '.join(p['only_a']) or '–'} | "
                         f"{', '.join(p['only_b']) or '–'} |")
    (args.results_dir / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
