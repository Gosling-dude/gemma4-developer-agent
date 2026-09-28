"""Run a packaged submission through the OFFICIAL swegemma Evaluator against a model endpoint.

With the fake scripted server (scripts/fake_openai_server.py) this is a pipeline test; with a real vLLM
endpoint serving gemma-4-31b-it-qat-w4a16-ct it's a real evaluation (see scripts/run_real_eval.sh).

  evaluations/.cache/official_venv/bin/python scripts/official_pipeline_test.py \
      --submission build/sub --data evaluations/.cache/official_local --ids rich_4077 \
      --api-base http://127.0.0.1:8765/v1 --out evaluations/results/<id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True, help="tasks.jsonl + snapshots/ (+ wheels/, graphs/, embeddings/)")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--api-base", default=os.environ.get("G4_API_BASE"))
    ap.add_argument("--served-model", default=os.environ.get("G4_MODEL", "gemma-4-31b-it-qat-w4a16-ct"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--time-minutes", type=float, default=None, help="override eval_config max_time_minutes")
    args = ap.parse_args(argv)
    if not args.api_base:
        print("ERROR: no endpoint (set G4_API_BASE or --api-base)", file=sys.stderr)
        return 2

    import yaml
    from swegemma.config import EvalConfig, build_submission_limits
    from swegemma.evaluate import Evaluator
    from swegemma.models import load_tasks
    from swegemma.models.registry import setup_gemma_model_registry
    from adk_submission import discover_adapters
    from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS

    sub = args.submission.resolve()
    ev = (yaml.safe_load((sub / "eval_config.yaml").read_text()) or {}).get("evaluation", {}) \
        if (sub / "eval_config.yaml").exists() else {}
    manifest = discover_adapters(str(sub), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
    models = setup_gemma_model_registry(api_base=args.api_base, api_key=os.environ.get("G4_API_KEY", "EMPTY"),
                                        served_model=args.served_model, adapter_manifest=manifest)
    limits, gen = build_submission_limits()
    args.out.mkdir(parents=True, exist_ok=True)
    graphs = args.data / "graphs"
    cfg = EvalConfig(
        tasks_path=args.data / "tasks.jsonl", snapshots_dir=args.data / "snapshots", results_dir=args.out / "official",
        submission_dir=sub, models=models, sandbox="subprocess",
        wheels_dir=(args.data / "wheels") if (args.data / "wheels").exists() else None,
        timeout_seconds=int(ev.get("timeout_seconds", 300)),
        max_time_minutes=args.time_minutes or float(ev.get("max_time_minutes", 60.0)),
        max_tool_calls=int(ev.get("max_tool_calls", 100)),
        max_turns=int(ev["max_turns"]) if ev.get("max_turns") is not None else None,
        limits=limits, generation_constraints=gen, adapter_manifest=manifest,
        graph_dir=str(graphs), embeddings_dir=str(args.data / "embeddings"), verbose=False, display_mode="quiet")
    evaluator = Evaluator(cfg)
    tasks = [t for t in load_tasks(cfg.tasks_path) if not args.ids or t.instance_id in args.ids]
    rows = []
    for i, t in enumerate(tasks, 1):
        start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        r = asyncio.run(evaluator.evaluate_task(task=t, task_index=i, total_tasks=len(tasks)))
        row = {"instance_id": t.instance_id, "repo": t.repo, "start": start,
               "end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "resolved": bool(r.resolved),
               "test_exit_code": r.test_exit_code, "patch_chars": len(r.agent_patch or ""),
               "tool_calls": getattr(r, "tool_calls", None), "llm_calls": getattr(r, "total_llm_calls", None),
               "duration_s": round(r.duration_seconds or 0, 1), "error": r.error,
               "trace": str(getattr(r, "trace_json_path", "") or ""), "patch": r.agent_patch or "",
               "test_tail": (r.test_output or "")[-1200:]}
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k not in ("patch", "test_tail")}), flush=True)
    (args.out / "task_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    n = len(rows)
    summary = {"tasks": n, "resolved": sum(r["resolved"] for r in rows), "model": args.served_model,
               "api_base_host": args.api_base.split("//")[-1].split("/")[0], "submission": str(sub),
               "mean_duration_s": round(sum(r["duration_s"] for r in rows) / n, 1) if n else None}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
