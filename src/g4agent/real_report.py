"""Per-task report for a REAL Gemma 4 run downloaded from the Kaggle notebook (g4agent.kaggle_kernel).

Reads only what the official swegemma Evaluator wrote (`*_task_results.jsonl`, `summary.json`, ATIF traces);
never invents a value: a field the run did not record is reported as null.

Per task: id, repo, runtime, tokens, tool/LLM calls, files inspected, files edited, tests run,
patch status, PASS/FAIL, failure category.

Usage: python -m g4agent.real_report RESULTS_DIR [--cap-minutes 5.0]
  RESULTS_DIR = output of `kaggle kernels output` (contains g4_results/ or g4_results_bundle.zip).
Writes RESULTS_DIR/report.json and RESULTS_DIR/report.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
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
    if status in ("TIMEOUT", "BUDGET_EXCEEDED") or "timeout" in err or "time limit" in err \
            or (row.get("duration_s") or 0) >= cap_s - 5:
        return "cap_hit (time/call/turn budget)" + ("" if patch else ", no patch")
    if err:
        return "agent_or_infra_error"
    if patch is None:
        return "unknown (patch not recorded)"
    if not patch.strip():
        return "no_patch"
    files = patch_files(patch)
    if files and all(is_protected(f) for f in files):
        return "only_test_or_config_edits"
    return "wrong_fix (hidden tests fail)"


def task_record(row: dict, root: Path, cap_s: float) -> dict:
    tr = local_trace(row.get("trace", ""), root)
    dig = trace_digest(tr) if tr else {}
    cmds = dig.get("commands", [])
    patch = row.get("patch")
    edited = sorted(set(patch_files(patch))) if patch else sorted(row.get("patch_files") or [])
    return {
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results_dir", type=Path)
    ap.add_argument("--cap-minutes", type=float, default=5.0, help="max_time_minutes of the evaluated variant")
    args = ap.parse_args(argv)
    root = find_results(args.results_dir)
    summary = json.loads((root / "summary.json").read_text()) if (root / "summary.json").exists() else {}
    gold = [json.loads(l) for l in (root / "gold_control.jsonl").read_text().splitlines()] \
        if (root / "gold_control.jsonl").exists() else []
    tasks = []
    for f in sorted(root.glob("*_task_results.jsonl")):
        tasks += [task_record(json.loads(l), root, args.cap_minutes * 60)
                  for l in f.read_text().splitlines() if l.strip()]
    n = len(tasks)
    rep = {"model": summary.get("model"), "server_start_s": summary.get("server_start_s"),
           "gold_control": [{"task_id": g["instance_id"], "gold_passes": g["resolved"]} for g in gold],
           "tasks": tasks, "resolved": sum(t["result"] == "PASS" for t in tasks), "n": n,
           "mean_runtime_s": round(sum(t["runtime_s"] or 0 for t in tasks) / n, 1) if n else None}
    (args.results_dir / "report.json").write_text(json.dumps(rep, indent=1))
    lines = ["| Task | Repo | Runtime s | Tokens | Tool calls | Files inspected | Files edited | Tests run | Patch | Result | Failure |",
             "|---|---|---:|---:|---:|---|---|---:|---|---|---|"]
    for t in tasks:
        lines.append(f"| {t['task_id']} | {t['repo']} | {t['runtime_s']} | {t['total_tokens']} | {t['tool_calls']} | "
                     f"{len(t['files_inspected'] or [])} | {', '.join(t['files_edited']) or '–'} | "
                     f"{len(t['tests_run']) if t['tests_run'] is not None else '?'} | {t['patch_status']} | "
                     f"{t['result']} | {t['failure_category'] or '–'} |")
    lines.append(f"\nResolved {rep['resolved']}/{n}; mean runtime {rep['mean_runtime_s']} s; model {rep['model']}.")
    (args.results_dir / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
