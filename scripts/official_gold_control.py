"""Grade reference patches (and empty patches) with the OFFICIAL swegemma Evaluator, no model involved.

Checks (a) whether each task is sound in a given environment and (b) that our local grader agrees
with the official one. It's the same code path the Kaggle real-eval notebook uses for its gold control.
Run with the official venv:
  evaluations/.cache/official_venv/bin/python scripts/official_gold_control.py \
      --data evaluations/.cache/official_local [--ids rich_4077 ...] [--empty]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True, help="dir with tasks.jsonl, snapshots/, wheels/")
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--empty", action="store_true", help="grade an EMPTY patch instead (must fail)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args(argv)

    from adk_eval_core.tracing import SessionTrace
    from swegemma.config import EvalConfig, build_submission_limits
    from swegemma.evaluate import Evaluator
    from swegemma.models import load_tasks
    from swegemma.models.registry import setup_gemma_model_registry

    mode = "empty" if args.empty else "gold"

    class ControlEvaluator(Evaluator):
        async def _run_agent_sandbox(self, task, *a, **k):
            return ("" if args.empty else task.patch), None, SessionTrace()

    out = args.out or args.data / f"official_{mode}_control.jsonl"
    limits, gen = build_submission_limits()
    cfg = EvalConfig(tasks_path=args.data / "tasks.jsonl", snapshots_dir=args.data / "snapshots",
                     results_dir=args.data / f"results_{mode}", submission_dir=args.data, models=setup_gemma_model_registry(),
                     sandbox="subprocess", wheels_dir=args.data / "wheels", timeout_seconds=args.timeout,
                     limits=limits, generation_constraints=gen, verbose=False, display_mode="quiet")
    ev = ControlEvaluator(cfg)
    tasks = [t for t in load_tasks(cfg.tasks_path) if not args.ids or t.instance_id in args.ids]
    rows = []
    for i, t in enumerate(tasks, 1):
        t0 = time.time()
        r = asyncio.run(ev.evaluate_task(task=t, task_index=i, total_tasks=len(tasks)))
        row = {"instance_id": t.instance_id, "mode": mode, "resolved": bool(r.resolved), "exit": r.test_exit_code,
               "error": (r.error or "")[:300], "seconds": round(time.time() - t0, 1),
               "tail": (r.test_output or "")[-600:]}
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "tail"}), flush=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"{mode}: {sum(r['resolved'] for r in rows)}/{len(rows)} resolved -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
