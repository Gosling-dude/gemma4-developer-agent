"""Reproducible experiments: package a variant, run it on cases, verify, classify failures, record.

Every run writes evaluations/results/<exp_id>/:
  config.json         experiment id, timestamp, variant, git revision, budgets, model settings, case list
  task_results.jsonl  one line per task (resolved, stop reason, tool calls, tokens, failure category)
  patches/<id>.patch  extracted agent patches
  traces/<id>.jsonl   ADK event traces (thoughts, tool calls, truncated responses)
  summary.json        resolution rate and failure-category counts

Agents:
  --agent adk     the packaged YAML via google-adk + an OpenAI-compatible endpoint ($G4_MODEL, ...)
  --agent oracle  applies the reference patch through the harness tools (pipeline self-test, no model)
  --agent noop    submits nothing (baseline check: every task must fail)

Usage:
  python -m g4agent.experiment --exp-id E001 --variant v0 --agent adk --tasks evaluations/cases/tasks.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import analysis
from .harness.graph import CodeGraph, build_from_repo
from .harness.tasks import PROJECT, Task, load_tasks, prepare_workspace, workspace_env
from .harness.tools import Budget, LocalHarness
from .harness.verify import patch_files, verify
from .packager import package

RESULTS = PROJECT / "evaluations" / "results"


def load_budget(submission: Path) -> Budget:
    import yaml

    b = Budget()
    cfg = submission / "eval_config.yaml"
    if cfg.exists():
        ev = (yaml.safe_load(cfg.read_text()) or {}).get("evaluation", {})
        b.time_minutes = float(ev.get("max_time_minutes", 60.0))
        b.tool_calls = ev.get("max_tool_calls", 100)
        b.turns = ev.get("max_turns", 500)
        b.command_timeout_seconds = int(ev.get("timeout_seconds", 300))
    return b


def graph_for(task: Task, workspace: Path, data_dir: Path | None) -> tuple[CodeGraph, str]:
    if data_dir and (data_dir / "graphs" / f"{task.instance_id}.json").exists():
        return CodeGraph.load_official(data_dir / "graphs" / f"{task.instance_id}.json",
                                       data_dir / "embeddings" / f"{task.instance_id}.npz"), "official"
    cache_json = PROJECT / "evaluations" / ".cache" / "graphs" / f"{task.instance_id}.json"
    cache_npz = cache_json.with_suffix(".npz")
    if cache_json.exists():
        return CodeGraph.load_official(cache_json, cache_npz), "ast-approx"
    g = build_from_repo(workspace)
    g.save(cache_json, cache_npz)
    return g, "ast-approx"


def oracle_agent(task: Task, harness: LocalHarness) -> None:
    """Apply the gold patch through run_command + submit_patch, exercising extraction end to end."""
    fns = harness.tool_functions()
    pf = harness.tmp_dir / "gold.patch"
    pf.write_text(task.patch)
    fns["run_command"]("git apply /tmp/gold.patch")
    fns["submit_patch"]()


def run(exp_id: str, variant: str | None, agent: str, tasks_path: Path, data_dir: Path | None,
        only: list[str] | None, notes: str, budget_override: dict) -> Path:
    out = RESULTS / exp_id
    if out.exists():
        raise SystemExit(f"{out} exists; experiment ids are immutable, pick a new one")
    (out / "patches").mkdir(parents=True)
    (out / "traces").mkdir()
    tasks = [t for t in load_tasks(tasks_path) if not only or t.instance_id in only]
    submission = out / "submission"
    rc = package(variant, out / "submission.zip", compile_adk=False, keep_build=submission)
    if rc != 0:
        raise SystemExit("packaging failed")
    budget = load_budget(submission)
    for k, v in budget_override.items():
        setattr(budget, k, v)
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT, capture_output=True, text=True).stdout.strip())
    config = {
        "exp_id": exp_id, "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "variant": variant or "root(v1)", "agent": agent, "git_rev": rev + ("+dirty" if dirty else ""),
        "budget": dataclasses.asdict(budget), "tasks_file": str(tasks_path), "tasks": [t.instance_id for t in tasks],
        "model": {"G4_MODEL": os.environ.get("G4_MODEL"), "G4_API_BASE": os.environ.get("G4_API_BASE")}
        if agent == "adk" else None,
        "notes": notes,
    }
    (out / "config.json").write_text(json.dumps(config, indent=2))
    results = []
    for task in tasks:
        print(f"== {task.instance_id}", flush=True)
        rec = run_one(task, agent, submission, budget, data_dir, out)
        rec["category"], rec["tags"] = analysis.classify(task, rec)
        results.append(rec)
        with (out / "task_results.jsonl").open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"   resolved={rec['resolved']} stop={rec.get('stop_reason')} calls={rec.get('tool_calls')} "
              f"t={rec.get('seconds')}s category={rec['category']}", flush=True)
    summary = analysis.summarize(results)
    summary.update(exp_id=exp_id, variant=config["variant"], agent=agent)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return out


def run_one(task: Task, agent: str, submission: Path, budget: Budget, data_dir: Path | None, out: Path) -> dict:
    rec: dict = {"instance_id": task.instance_id}
    with tempfile.TemporaryDirectory() as td:
        ws = prepare_workspace(task, Path(td) / "workspace", data_dir)
        env = workspace_env(task.repo, ws)
        graph, graph_src = graph_for(task, ws, data_dir)
        rec["graph_source"] = graph_src
        if agent == "adk":
            from .harness.runner import run_agent

            outcome = asyncio.run(run_agent(submission, task, ws, Path(td) / "tmp", budget, graph, env,
                                            out / "traces" / f"{task.instance_id}.jsonl"))
            rec.update({k: v for k, v in dataclasses.asdict(outcome).items() if k != "patch"})
            patch = outcome.patch
        else:
            harness = LocalHarness(ws, Path(td) / "tmp", budget, graph, env)
            harness.start()
            if agent == "oracle":
                oracle_agent(task, harness)
            patch = harness.submitted_patch if harness.patch_submitted else harness.extract_patch()
            rec.update(stop_reason="submitted" if harness.patch_submitted else "noop",
                       tool_calls=harness.tool_calls_used, tool_log=harness.calls, seconds=round(harness.elapsed(), 1))
    (out / "patches" / f"{task.instance_id}.patch").write_text(patch)
    vr = verify(task, patch, data_dir=data_dir)
    rec["edited_files"] = patch_files(patch)
    rec.update(resolved=vr.resolved, patch_applied=vr.applied, verify_error=vr.error, passed=vr.passed,
               failures=vr.failures, errors=vr.errors, patch_chars=len(patch),
               verify_tail=vr.output_tail[-800:] if not vr.resolved else "")
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exp-id", required=True)
    ap.add_argument("--variant", default=None)
    ap.add_argument("--agent", choices=("adk", "oracle", "noop"), default="adk")
    ap.add_argument("--tasks", type=Path, default=PROJECT / "evaluations" / "cases" / "tasks.jsonl")
    ap.add_argument("--data-dir", type=Path, default=None, help="official competition data directory")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--notes", default="")
    ap.add_argument("--time-minutes", type=float, default=None, help="override eval_config max_time_minutes")
    args = ap.parse_args(argv)
    override = {"time_minutes": args.time_minutes} if args.time_minutes else {}
    run(args.exp_id, args.variant, args.agent, args.tasks, args.data_dir, args.only, args.notes, override)
    return 0


if __name__ == "__main__":
    sys.exit(main())
