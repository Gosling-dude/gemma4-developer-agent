"""Build a Kaggle notebook that runs REAL Gemma 4 evaluations with the OFFICIAL harness.

The generated kernel mirrors the organizers' Getting Started notebook (same data sources, machine
shape, vLLM settings and swegemma Evaluator with the subprocess sandbox):
  - datasets: metric/gemma-4-developer-agent-wheelhouse; competition: gemma-4-developer-agent
  - model: google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2; machine: NvidiaL4 (4x L4); no internet
Our packaged variants are embedded as base64 zips, so no extra dataset upload is needed.

Per run:
  1. gold control: each selected task graded with its REFERENCE patch (environment soundness only;
     the agent never sees the patch). Tasks whose gold patch fails are excluded from agent scoring.
  2. every variant (e.g. v0, v1) runs on the same sound tasks, sequentially, sharing one vLLM server.
  3. /kaggle/working/g4_results/: per-variant task_results.jsonl, summary.json, official traces/logs.

Usage:
  python -m g4agent.kaggle_kernel --variants v0 root --n-tasks 3 --repo Textualize/rich
  kaggle kernels push -p build/kaggle_real_eval        # needs YOUR Kaggle credentials (never in git)
  kaggle kernels output <you>/g4-real-eval -p evaluations/results/kaggle_<id>
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
import tempfile
from pathlib import Path

from .packager import PROJECT, package

MODEL_SOURCE = "google/gemma-4/Other/gemma-4-31b-it-qat-w4a16-ct/2"
MODEL_DIR = "/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2"

CELL_SETUP = r'''
import glob, importlib, os, shutil, subprocess, sys
from pathlib import Path
os.environ.update({'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'TRANSFORMERS_NO_TF': '1',
    'VLLM_WORKER_MULTIPROC_METHOD': 'spawn', 'VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS': '1',
    'VLLM_ENGINE_READY_TIMEOUT_S': '1200', 'VLLM_NO_USAGE_STATS': '1', 'OTEL_SDK_DISABLED': 'true',
    'PYTORCH_CUDA_ALLOC_CONF': 'expandable_segments:True'})
WHEELHOUSE_DIR = next(Path(p) for p in ['/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse',
                                        '/kaggle/input/gemma-4-developer-agent-wheelhouse'] if Path(p).exists())
for pat in ('/usr/local/lib/python*/dist-packages/*cutlass*.pth', '/usr/local/lib/python*/site-packages/*cutlass*.pth'):
    for pth in glob.glob(pat):
        try: os.unlink(pth)
        except OSError: pass
tmp_whl = Path('/tmp/wheelhouse'); tmp_whl.mkdir(parents=True, exist_ok=True)
for w in WHEELHOUSE_DIR.glob('*.whl'):
    if 'cutlass' in w.name.lower(): continue
    name = w.name.replace('cu128', '+cu128') if ('cu128' in w.name and '+' not in w.name) else w.name
    if not (tmp_whl / name).exists(): os.symlink(w, tmp_whl / name)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', '--force-reinstall',
                *sorted(str(w) for w in tmp_whl.glob('*.whl'))], check=True)
importlib.invalidate_caches()
print('wheelhouse installed')
'''

CELL_CONFIG = r'''
import base64, io, json, time, zipfile
RUN = json.loads(RUN_JSON)
DATA_DIR = Path('/kaggle/input/competitions/gemma-4-developer-agent')
if not DATA_DIR.exists():
    DATA_DIR = Path('/kaggle/input/gemma-4-developer-agent')
OUT = Path('/kaggle/working/g4_results'); OUT.mkdir(parents=True, exist_ok=True)
AGENTS = {}
for name, b64 in VARIANT_ZIPS.items():
    d = Path('/kaggle/working/agents') / name
    shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
    zipfile.ZipFile(io.BytesIO(base64.b64decode(b64))).extractall(d)
    AGENTS[name] = d
print('variants:', {k: sorted(p.name for p in v.iterdir()) for k, v in AGENTS.items()})
'''

CELL_TASKS = r'''
from swegemma.models import load_tasks
TASKS_PATH = DATA_DIR / 'tasks.jsonl'
all_tasks = load_tasks(TASKS_PATH)
known_dead = set(RUN.get('exclude', []))
pool = [t for t in all_tasks if (not RUN.get('repo') or t.repo == RUN['repo']) and t.instance_id not in known_dead]
if RUN.get('task_ids'):
    pool = [t for t in all_tasks if t.instance_id in set(RUN['task_ids'])]
pool = sorted(pool, key=lambda t: t.instance_id)
candidates = pool[: RUN['n_candidates']]
print(f'{len(all_tasks)} tasks in dataset; candidates: {[t.instance_id for t in candidates]}')
'''

CELL_SERVER = r'''
import litellm, torch
from adk_submission import VllmConfig, VllmServer, discover_adapters
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, EvalConfig, build_submission_limits
from swegemma.models.discovery import validate_single_declared_model
litellm.drop_params = True
TARGET = 'gemma-4-31b-it-qat-w4a16-ct'
declared = {n: validate_single_declared_model(d) for n, d in AGENTS.items()}
print('declared models:', declared)
assert all(str(m).endswith(TARGET) for m in declared.values()), 'every variant must declare ' + TARGET
gpu_count = torch.cuda.device_count() if torch.cuda.is_available() else 0
assert gpu_count >= 1, 'no GPU: this notebook must run on the 4x L4 accelerator'
tp = 4 if gpu_count >= 4 else (2 if gpu_count >= 2 else 1)
t0 = time.time()
server = VllmServer(VllmConfig(model=MODEL_DIR, port=8000, host='127.0.0.1', tool_call_parser='gemma4',
    reasoning_parser='gemma4', max_model_len=32768,
    dtype='bfloat16' if torch.cuda.is_bf16_supported() else 'auto', gpu_memory_utilization=0.90,
    enable_auto_tool_choice=True, enable_lora=True, max_loras=8, max_lora_rank=128,
    tensor_parallel_size=tp, startup_timeout=60 * 20), adapter_manifest=None)
server.start()
SERVER_START_S = round(time.time() - t0, 1)
models = server.create_model_registry(aliases=[TARGET], model_prefix='openai/', api_key='EMPTY')
print(f'vLLM up in {SERVER_START_S}s (tp={tp}, gpus={gpu_count})')
'''

CELL_EVAL = r'''
import asyncio, concurrent.futures, yaml
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps._configs import EventsCompactionConfig
from swegemma.evaluate import Evaluator

def run_sync(fn):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(fn())).result()
    return asyncio.run(fn())

def make_config(agent_dir, results_dir):
    ev = (yaml.safe_load((agent_dir / 'eval_config.yaml').read_text()) or {}).get('evaluation', {}) \
        if (agent_dir / 'eval_config.yaml').exists() else {}
    limits, gen = build_submission_limits()
    return EvalConfig(tasks_path=TASKS_PATH, snapshots_dir=DATA_DIR / 'snapshots', results_dir=results_dir,
        submission_dir=agent_dir, models=models, sandbox='subprocess',
        timeout_seconds=int(ev.get('timeout_seconds', 300)), max_time_minutes=float(ev.get('max_time_minutes', 60.0)),
        max_tool_calls=int(ev.get('max_tool_calls', 100)),
        max_turns=int(ev['max_turns']) if ev.get('max_turns') is not None else None,
        limits=limits, generation_constraints=gen,
        adapter_manifest=discover_adapters(str(agent_dir), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS),
        context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
        events_compaction_config=EventsCompactionConfig(compaction_interval=15, overlap_size=2,
                                                        token_threshold=14336, event_retention_size=5),
        graph_dir=str(DATA_DIR / 'graphs'), embeddings_dir=str(DATA_DIR / 'embeddings'),
        wheels_dir=DATA_DIR / 'wheels', verbose=False)

class GoldEvaluator(Evaluator):
    """Environment control: Phase 1 returns the reference patch (no model call, nothing shown to an agent)."""
    async def _run_agent_sandbox(self, task, *args, **kwargs):
        from adk_eval_core.tracing import SessionTrace
        return task.patch, None, SessionTrace()

def record(r, variant, t_start, t_end):
    return {'variant': variant, 'instance_id': r.instance_id, 'repo': r.repo, 'resolved': bool(r.resolved),
            'test_exit_code': r.test_exit_code, 'patch_chars': len(r.agent_patch or ''),
            'patch_files': sorted(set(l[6:].split()[0] for l in (r.agent_patch or '').splitlines()
                                      if l.startswith('+++ b/'))),
            'tool_calls': getattr(r, 'tool_calls', None), 'llm_calls': getattr(r, 'total_llm_calls', None),
            'total_tokens': getattr(r, 'total_tokens', None), 'status': getattr(r, 'status', None),
            'duration_s': round(r.duration_seconds or 0, 1), 'error': r.error, 'start': t_start, 'end': t_end,
            'trace': str(getattr(r, 'trace_json_path', '') or ''), 'patch': r.agent_patch or '',
            'test_tail': (r.test_output or '')[-1500:]}

sound = candidates
if RUN.get('gold_control', True):
    gold_ev = GoldEvaluator(make_config(next(iter(AGENTS.values())), OUT / 'gold_control'))
    rows = []
    for i, t in enumerate(candidates, 1):
        ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        r = run_sync(lambda: gold_ev.evaluate_task(task=t, task_index=i, total_tasks=len(candidates)))
        rows.append(record(r, 'gold_control', ts, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        print('gold', t.instance_id, rows[-1]['resolved'], rows[-1]['duration_s'])
    (OUT / 'gold_control.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in rows))
    sound = [t for t, x in zip(candidates, rows) if x['resolved']]
sound = sound[: RUN['n_tasks']]
print('sound tasks used for agents:', [t.instance_id for t in sound])

summary = {'run': RUN, 'server_start_s': SERVER_START_S, 'model': TARGET, 'variants': {}}
for name, agent_dir in AGENTS.items():
    ev = Evaluator(make_config(agent_dir, OUT / name))
    rows = []
    for i, t in enumerate(sound, 1):
        ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        r = run_sync(lambda: ev.evaluate_task(task=t, task_index=i, total_tasks=len(sound)))
        rows.append(record(r, name, ts, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())))
        print(name, t.instance_id, 'resolved=', rows[-1]['resolved'], 'calls=', rows[-1]['tool_calls'],
              'dur=', rows[-1]['duration_s'], 'err=', (rows[-1]['error'] or '')[:120])
        with (OUT / f'{name}_task_results.jsonl').open('a') as fh:
            fh.write(json.dumps(rows[-1]) + '\n')
    n = len(rows)
    summary['variants'][name] = {'tasks': n, 'resolved': sum(x['resolved'] for x in rows),
        'mean_duration_s': round(sum(x['duration_s'] for x in rows) / n, 1) if n else None,
        'mean_tool_calls': round(sum((x['tool_calls'] or 0) for x in rows) / n, 1) if n else None}
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
'''

CELL_TRACES = r'''
# Condense official traces: tool usage, files read, commands run (for failure analysis offline).
def walk(o, acc):
    if isinstance(o, dict):
        if isinstance(o.get('function_name'), str):  # ATIF step.tool_calls[] entry
            args = o.get('arguments')
            acc.append({'tool': o['function_name'], 'args': args if isinstance(args, dict) else str(args)[:300],
                        'elapsed_s': (o.get('extra') or {}).get('elapsed_s')})
        for v in o.values(): walk(v, acc)
    elif isinstance(o, list):
        for v in o: walk(v, acc)
digest = {}
for f in OUT.glob('*_task_results.jsonl'):
    for line in f.read_text().splitlines():
        x = json.loads(line); calls = []
        if x['trace'] and Path(x['trace']).exists():
            try: walk(json.loads(Path(x['trace']).read_text()), calls)
            except Exception as e: calls = [{'error': str(e)}]
        digest[f"{x['variant']}/{x['instance_id']}"] = calls[:400]
(OUT / 'tool_calls_digest.json').write_text(json.dumps(digest, indent=1)[:20_000_000])
shutil.make_archive('/kaggle/working/g4_results_bundle', 'zip', OUT)
print('wrote', OUT, 'and g4_results_bundle.zip')
try: server.stop()
except Exception: pass
'''


def _nb(cells: list[tuple[str, str]]) -> dict:
    return {"cells": [{"cell_type": t, "metadata": {}, "source": s.strip("\n").splitlines(True),
                       **({"outputs": [], "execution_count": None} if t == "code" else {})} for t, s in cells],
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
            "nbformat": 4, "nbformat_minor": 5}


def build(variants: list[str], run: dict, out_dir: Path, slug: str, title: str) -> Path:
    zips: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as td:
        for v in variants:
            zp = Path(td) / f"{v}.zip"
            if package(None if v == "root" else v, zp, compile_adk=False) != 0:
                raise SystemExit(f"packaging failed for {v}")
            zips["v1" if v == "root" else v] = base64.b64encode(zp.read_bytes()).decode()
    header = (f"RUN_JSON = {json.dumps(json.dumps(run))}\nVARIANT_ZIPS = {json.dumps(zips)}\n"
              f"MODEL_DIR = {MODEL_DIR!r}\n")
    cells = [("markdown", f"# {title}\nReal Gemma 4 evaluation with the official swegemma harness. Generated by "
                          "`python -m g4agent.kaggle_kernel`. Results: `/kaggle/working/g4_results/`."),
             ("code", header), ("code", CELL_SETUP), ("code", CELL_CONFIG), ("code", CELL_TASKS),
             ("code", CELL_SERVER), ("code", CELL_EVAL), ("code", CELL_TRACES)]
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    (out_dir / "g4-real-eval.ipynb").write_text(json.dumps(_nb(cells), indent=1))
    meta = {"id": f"{{KAGGLE_USERNAME}}/{slug}", "title": title, "code_file": "g4-real-eval.ipynb",
            "language": "python", "kernel_type": "notebook", "is_private": True, "enable_gpu": True,
            "enable_tpu": False, "enable_internet": False, "machine_shape": "NvidiaL4",
            "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"],
            "competition_sources": ["gemma-4-developer-agent"], "kernel_sources": [],
            "model_sources": [MODEL_SOURCE]}
    (out_dir / "kernel-metadata.json").write_text(json.dumps(meta, indent=2))
    return out_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variants", nargs="+", default=["v0", "root"], help="'root' = current agent.yaml")
    ap.add_argument("--n-tasks", type=int, default=3, help="agent tasks (after gold control)")
    ap.add_argument("--n-candidates", type=int, default=None, help="tasks gold-checked (default n_tasks+3)")
    ap.add_argument("--repo", default="Textualize/rich", help="restrict to one repo ('' for all)")
    ap.add_argument("--task-ids", nargs="*", default=None)
    ap.add_argument("--exclude", nargs="*", default=["rich_3472", "rich_3486"],
                    help="tasks reported unsolvable on the py3.13 grader (discussion 743973)")
    ap.add_argument("--no-gold-control", action="store_true")
    ap.add_argument("--slug", default="g4-real-eval")
    ap.add_argument("--out", type=Path, default=PROJECT / "build" / "kaggle_real_eval")
    args = ap.parse_args(argv)
    run = {"n_tasks": args.n_tasks, "n_candidates": args.n_candidates or args.n_tasks + 3, "repo": args.repo,
           "task_ids": args.task_ids, "exclude": args.exclude, "gold_control": not args.no_gold_control,
           "variants": args.variants}
    out = build(args.variants, run, args.out, args.slug, args.slug)  # Kaggle derives the slug from the title
    print(f"kernel written to {out}\n  set the id in kernel-metadata.json (replace {{KAGGLE_USERNAME}}), then:\n"
          f"  kaggle kernels push -p {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
