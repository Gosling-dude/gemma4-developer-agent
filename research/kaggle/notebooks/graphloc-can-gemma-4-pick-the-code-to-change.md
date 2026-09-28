# GraphLoc: can Gemma 4 pick the code to change?
source: https://www.kaggle.com/code/zzgtylors/graphloc-can-gemma-4-pick-the-code-to-change  votes=1 bestPublicScore=None gpu=None runtime_s=10

# GraphLoc: can Gemma 4 pick the code to change?

GPU companion to the Paper Track writeup *Where Does the Graph Help? A Localization Audit of Gemma 4 Agent Code Graphs* and its CPU notebook [GraphLoc: auditing Gemma 4 agent code graphs](https://www.kaggle.com/code/zzgtylors/graphloc-auditing-gemma-4-agent-code-graphs).

Gemma 4 31B (`gemma-4-31b-it-qat-w4a16-ct`) is served with vLLM 0.19.1 from the official competition wheelhouse on 4x L4 with the harness settings (tensor parallel 4, 32k context, 0.90 GPU memory) and greedy decoding. For each of the 122 GraphLoc-129 tasks with a function-level gold it sees the issue and a numbered list of candidate definitions and returns up to three to edit. Pools, built on the provided graph (G0) and on the repaired graph (G+):

* `top10`: BM25 top 10;
* `hop1`: BM25 top 5 plus their one-hop graph neighbours (capped at 32);
* `same`: the BM25 list cut at the same size as `hop1` for that task.

Candidates are always listed in BM25 order, so `hop1` and `same` differ only in membership. A second pass enables Gemma's thinking mode on the G+ pools. `agg_gemma.py` reports accuracy, pool coverage, the BM25 baseline on the same pool and paired bootstrap tests. Code: Apache-2.0.

```python
import glob, os, shutil, subprocess
W = '/kaggle/working'
gl = sorted(glob.glob('/kaggle/input/**/graphloc.py', recursive=True), key=len)
print('graphloc.py from', gl[0]); shutil.copy(gl[0], f'{W}/graphloc.py')
whl = sorted(glob.glob('/kaggle/input/**/vllm-*.whl', recursive=True))
wd = os.path.dirname(whl[0]); print('wheelhouse', wd)
print(subprocess.run('pip list 2>/dev/null | grep -iE "^(torch|protobuf|transformers|triton|numpy) "', shell=True, capture_output=True, text=True).stdout)
r = subprocess.run(f'pip install --no-index --no-deps {wd}/*.whl', shell=True, capture_output=True, text=True)
print(r.stdout[-1500:], r.stderr[-1500:])
print(subprocess.run('python -c "import vllm, torch; print(vllm.__version__, torch.__version__, torch.cuda.device_count())"', shell=True, capture_output=True, text=True))
```
```
[output] graphloc.py from /kaggle/input/notebooks/zzgtylors/graphloc-auditing-gemma-4-agent-code-graphs/graphloc.py
wheelhouse /kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse
numpy                                    2.0.2
protobuf                                 5.29.5
torch                                    2.10.0+cu128
transformers                             5.0.0
triton                                   3.6.0

ers 5.0.0
    Uninstalling transformers-5.0.0:
      Successfully uninstalled transformers-5.0.0
  Attempting uninstall: safetensors
    Found existing installation: safetensors 0.7.0
    Uninstalling safetensors-0.7.0:
      Successfully uninstalled safetensors-0.7.0
  Attempting uninstall: google-genai
    Found existing installation: google-genai 1.68.0
    Uninstalling google-genai-1.68.0:
      Successfully uninstalled google-genai-1.68.0
  Attempting uninstall: google-adk
    Found existing installation: google-adk 1.29.0
    Uninstalling google-adk-1.29.0:
      Successfully uninstalled google-adk-1.29.0
Successfully installed adk-eval-core-0.1.0 adk-submission-0.2.11 anthropic-1.4.0 apache-tvm-ffi-0.1.13.post3 astor-0.8.1 bitsandbytes-0.46.1 cbor2-6.1.4 compressed-tensors-0.15.0.1 depyf-0.20.0 diskcache-5.6.3 flashinfer-cubin-0.6.6 flashinfer-python-0.6.6 gguf-0.19.0 google-adk-1.36.1 google-genai-2.11.0 ijson-3.5.1 interegular-0.3.3 llguidance-1.3.0 lm-format-enforcer-0.11.3 loguru-0.7.3 mistral-common-1.11.7 model-hosting-container-standards-0.1.1
```

```python
%%writefile /kaggle/working/build_prompts2.py
"""Candidate pools for the Gemma 4 selection study (GraphLoc-129, 122 tasks with a function-level gold).

For each task and graph (G0 = provided, G+ = repaired) we build equal-format prompts from:
  top10 : BM25 top 10
  hop1  : BM25 top 5 plus their 1-hop graph neighbours (candidate definitions only, capped)
  same  : BM25 top-n with n = |hop1| of the same task (same inspection budget, lexical depth)
Candidates inside every pool are listed in BM25 order, so pools differ only in membership."""
import json, os, sys, textwrap, ast
import numpy as np
sys.path.insert(0, os.environ.get('GL_CODE', '/kaggle/working'))
import graphloc as G

OUT = os.environ.get('GL_OUT', '/kaggle/working/results')
CACHE = os.environ.get('GL_CACHE', '/kaggle/tmp/snapcache')
CAP = int(os.environ.get('CAP', 32))
NSH = int(os.environ.get('NSHARDS', 1)); SH = int(os.environ.get('SHARD', 0))

HEADER = """You are an expert Python engineer. Find the code that must be changed to resolve this issue in the repository {repo}.

Issue:
<<<
{issue}
>>>

Candidate definitions (functions, methods or classes) from the repository:

{cands}

Which candidates must be modified to resolve the issue? Reply with a JSON object only, for example {{"ranking": [4, 1, 7]}}, listing up to 3 candidate numbers, most likely first."""


def strip_docstring(src):
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    node = tree.body[0] if tree.body else None
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(getattr(first, 'value', None), ast.Constant) and isinstance(first.value.value, str):
            lines = src.split('\n')
            del lines[first.lineno - 1:first.end_lineno]
            return '\n'.join(lines)
    return src


def snippet(text, max_lines=14, max_chars=800):
    text = strip_docstring(textwrap.dedent(text))
    lines = [l for l in text.split('\n') if l.strip()][:max_lines]
    return '\n'.join(lines)[:max_chars]


def pools(g, cand, texts, qtok):
    ids = g.ids
    ci = np.array([i for i in range(len(ids)) if cand[i]], dtype=int)
    s = np.zeros(len(ids))
    if len(ci):
        s[ci] = G.BM25([G.tokenize(ids[i].replace('.', ' ') + ' ' + texts[i]) for i in ci]).score(qtok)
    order = [int(i) for i in ci[np.argsort(-s[ci], kind='stable')] if s[i] > 0]
    rank = {i: r for r, i in enumerate(order)}
    top5 = order[:5]
    hop = []
    if top5:
        d = g.hops_from(top5, max_hops=1)
        hop = [int(j) for j in np.where(d <= 1)[0] if cand[j]]
    key = lambda i: (rank.get(i, len(order)), ids[i])
    hop1 = sorted(set(hop), key=key)
    truncated = len(hop1) > CAP
    hop1 = hop1[:CAP]
    same = order[:len(hop1)]
    return {'top10': order[:10], 'hop1': hop1, 'same': same}, truncated, s


def build(task, tasks):
    tid = task['instance_id']
    files = G.load_snapshot_py(tid, cache_dir=CACHE)
    g0 = G.Graph.from_json(G.resource_path(task, tasks, 'graphs'))
    fd = {p: (G.extract_defs(s)[0] or []) for p, s in files.items()}
    mm = G.assign_modules(fd, set(g0.ids))
    gold = set(G.gold_labels(task, files, mm)['symbols'])
    if not gold:
        return []
    nf0 = G.node_file_map(g0.ids, mm)
    nodes, texts, edges, nfp, kinds = G.build_gplus(files, mm)
    gp = G.Graph(nodes, texts, [(s, t) for s, t, _ in edges])
    issue = G.clean_issue(task['problem_statement'] + '\n' + (task.get('hints_text') or '')).strip()
    qtok = G.tokenize(issue)
    c0 = [not G.is_test_id(i) and not G.is_test_path(nf0.get(i, '')) for i in g0.ids]
    cp = [kinds[i] != 'module' and not G.is_test_path(nfp.get(i, '')) for i in gp.ids]
    rows = []
    for gname, g, cand, nf in (('g0', g0, c0, nf0), ('gp', gp, cp, nfp)):
        P, trunc, _ = pools(g, cand, g.texts, qtok)
        for cname, idx in P.items():
            cands = [g.ids[i] for i in idx]
            blocks = [f'[{j}] {c}  ({nf.get(c, "?")})\n' + textwrap.indent(snippet(g.texts[i]), '    ')
                      for j, (i, c) in enumerate(zip(idx, cands), 1)]
            prompt = HEADER.format(repo=task['repo'], issue=issue[:6000], cands='\n\n'.join(blocks))
            rows.append({'id': tid, 'cond': f'{gname}_{cname}', 'cands': cands, 'gold': sorted(gold),
                         'gold_in_pool': bool(gold & set(cands)), 'pool_size': len(cands),
                         'truncated': trunc if cname == 'hop1' else False, 'prompt': prompt})
    return rows


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    tasks = G.load_tasks()
    n = 0
    with open(f'{OUT}/prompts2_{SH}.jsonl', 'w') as f:
        for t in tasks[SH::NSH]:
            try:
                rs = build(t, tasks)
            except Exception as e:
                print('ERROR', t['instance_id'], repr(e), flush=True)
                continue
            for r in rs:
                f.write(json.dumps(r) + '\n'); n += 1
    print('shard', SH, 'prompts', n, flush=True)
```
```
[output] Writing /kaggle/working/build_prompts2.py

```

```python
%%writefile /kaggle/working/run_gemma2.py
"""Gemma 4 31B (QAT W4A16, vLLM, 4x L4, competition serving settings) picks the definitions to edit from each pool."""
import glob, json, os, re, sys, time
OUT = os.environ.get('GL_OUT', '/kaggle/working/results')
THINK = os.environ.get('THINK', '0') == '1'
TAG = 'think' if THINK else 'nothink'
CONDS = [c for c in os.environ.get('CONDS', '').split(',') if c]
MODEL = os.environ.get('MODEL_PATH') or os.path.dirname(sorted(
    [p for p in glob.glob('/kaggle/input/**/config.json', recursive=True) if 'gemma' in p.lower()], key=len)[0])
print('model', MODEL, 'think', THINK, flush=True)
from vllm import LLM, SamplingParams

rows = [json.loads(l) for p in sorted(glob.glob(f'{OUT}/prompts2_*.jsonl')) for l in open(p)]
rows = [r for r in rows if not CONDS or r['cond'] in CONDS]
if os.environ.get('LIMIT'):
    rows = rows[:int(os.environ['LIMIT'])]
kw = dict(model=MODEL, tensor_parallel_size=int(os.environ.get('TP', 4)), max_model_len=32768,
          gpu_memory_utilization=0.90, max_num_seqs=int(os.environ.get('MAX_SEQS', 64)), enable_prefix_caching=True, seed=0)
llm = LLM(limit_mm_per_prompt={'image': 0, 'audio': 0, 'video': 0}, **kw)
sp = SamplingParams(temperature=0.0, max_tokens=int(os.environ.get('MAXTOK', 4096 if THINK else 256)))
msgs = [[{'role': 'user', 'content': r['prompt']}] for r in rows]
t0 = time.time()
try:
    outs = llm.chat(msgs, sp, chat_template_kwargs={'enable_thinking': THINK})
except TypeError:
    outs = llm.chat(msgs, sp)
elapsed = time.time() - t0


def parse(text):
    ms = list(re.finditer(r'"ranking"\s*:\s*\[([^\]]*)\]', text))
    nums = re.findall(r'\d+', ms[-1].group(1)) if ms else re.findall(r'\b\d+\b', text[-200:])
    return [int(x) for x in nums][:3]


with open(f'{OUT}/gemma2_{TAG}.jsonl', 'w') as f:
    for r, o in zip(rows, outs):
        text = o.outputs[0].text
        picks = parse(text)
        ids = [r['cands'][p - 1] for p in picks if 1 <= p <= len(r['cands'])]
        f.write(json.dumps({'id': r['id'], 'cond': r['cond'], 'picks': ids, 'gold': r['gold'], 'cands': r['cands'],
                            'gold_in_pool': r['gold_in_pool'], 'pool_size': r['pool_size'], 'parsed': bool(picks),
                            'raw': text[-400:], 'n_prompt_tok': len(o.prompt_token_ids),
                            'n_out_tok': len(o.outputs[0].token_ids)}) + '\n')
print(json.dumps({'tag': TAG, 'n': len(rows), 'elapsed_s': round(elapsed, 1), 'model': MODEL}), flush=True)
```
```
[output] Overwriting /kaggle/working/run_gemma2.py

```

```python
%%writefile /kaggle/working/agg_gemma.py
"""Summarise Gemma 4 candidate selection: accuracy per pool, BM25 baseline on the same pool, paired bootstrap."""
import glob, json, os, collections
import numpy as np
OUT = os.environ.get('GL_OUT', '/kaggle/working/results')
rng = np.random.default_rng(0)


def boot(a, b, n=2000):
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    idx = rng.integers(0, len(d), size=(n, len(d)))
    m = d[idx].mean(1)
    return [round(float(d.mean()), 3), round(float(np.percentile(m, 2.5)), 3), round(float(np.percentile(m, 97.5)), 3),
            int(((a == 1) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())]


res = {}
for p in sorted(glob.glob(f'{OUT}/gemma2_*.jsonl')):
    tag = os.path.basename(p)[7:-6]
    rows = [json.loads(l) for l in open(p)]
    by = collections.defaultdict(dict)
    for r in rows:
        g = set(r['gold'])
        r['acc1'] = int(bool(r['picks'][:1]) and r['picks'][0] in g)
        r['acc3'] = int(bool(set(r['picks']) & g))
        r['bm1'] = int(bool(r['cands'][:1]) and r['cands'][0] in g)
        r['bm3'] = int(bool(set(r['cands'][:3]) & g))
        by[r['cond']][r['id']] = r
    summ = {}
    for c, d in sorted(by.items()):
        v = list(d.values())
        cov = [r['gold_in_pool'] for r in v]
        summ[c] = {'n': len(v), 'gemma@1': round(np.mean([r['acc1'] for r in v]), 3), 'gemma@3': round(np.mean([r['acc3'] for r in v]), 3),
                   'bm25@1': round(np.mean([r['bm1'] for r in v]), 3), 'bm25@3': round(np.mean([r['bm3'] for r in v]), 3),
                   'coverage': round(np.mean(cov), 3), 'gemma@1|covered': round(np.mean([r['acc1'] for r in v if r['gold_in_pool']]) if any(cov) else 0, 3),
                   'median_pool': float(np.median([r['pool_size'] for r in v])), 'parsed': int(sum(r['parsed'] for r in v)),
                   'mean_prompt_tok': int(np.mean([r['n_prompt_tok'] for r in v])), 'mean_out_tok': int(np.mean([r['n_out_tok'] for r in v]))}
    tests = {}
    for a, b in (('gp_same', 'gp_hop1'), ('g0_same', 'g0_hop1'), ('gp_top10', 'gp_same'), ('gp_top10', 'gp_hop1'), ('g0_hop1', 'gp_hop1'), ('g0_same', 'gp_same')):
        if a in by and b in by:
            ids = sorted(set(by[a]) & set(by[b]))
            for k in ('acc1', 'acc3'):
                tests[f'{b}_minus_{a}_{k}'] = boot([by[a][i][k] for i in ids], [by[b][i][k] for i in ids])
    for c in by:
        ids = sorted(by[c])
        tests[f'{c}_gemma_minus_bm25_@1'] = boot([by[c][i]['bm1'] for i in ids], [by[c][i]['acc1'] for i in ids])
    res[tag] = {'summary': summ, 'tests': tests}
json.dump(res, open(f'{OUT}/gemma2_summary.json', 'w'), indent=1)
for tag, v in res.items():
    print('==', tag)
    for c, s in v['summary'].items():
        print(c, json.dumps(s))
    for k, t in v['tests'].items():
        print(k, t)
```
```
[output] Writing /kaggle/working/agg_gemma.py

```

```python
import glob, hashlib, os, subprocess, time
W = '/kaggle/working'; R = W + '/results'; os.makedirs(R, exist_ok=True)
EXP = {'graphloc.py': 'ca4733abd4990ebadbf0a039a0e566f3', 'build_prompts2.py': '33aad61855fbd06c9b237e3414344ae8',
       'run_gemma2.py': '87d9a61f49d862220fe548f49feee756', 'agg_gemma.py': '46af6f1f686ca77d41084a3f049f8e55'}
for f, h in EXP.items():
    got = hashlib.md5((open(f'{W}/{f}').read().rstrip('\n') + '\n').encode()).hexdigest()
    print(f, got, 'OK' if got == h else 'MISMATCH')
    assert got == h, f
env = dict(os.environ, GL_CODE=W, GL_OUT=R, GL_CACHE='/kaggle/tmp/snapcache', NSHARDS='8')
t0 = time.time()
ps = [subprocess.Popen(['python', f'{W}/build_prompts2.py'], env=dict(env, SHARD=str(i)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for i in range(8)]
for p in ps:
    print(p.communicate()[0][-300:])
print('prompts', sum(1 for p in glob.glob(f'{R}/prompts2_*.jsonl') for _ in open(p)), round(time.time() - t0), 's')
mp = os.path.dirname(sorted([p for p in glob.glob('/kaggle/input/**/config.json', recursive=True) if '31b' in p.lower()], key=len)[0])
for think, conds in (('0', ''), ('1', 'gp_top10,gp_hop1,gp_same')):
    subprocess.run("pgrep -f '^VLLM::' | xargs -r kill -9", shell=True)
    with open(f'/kaggle/tmp/vllm_{think}.log', 'w') as lg:
        rc = subprocess.run(['python', f'{W}/run_gemma2.py'], env=dict(env, MODEL_PATH=mp, THINK=think, CONDS=conds), stdout=lg, stderr=subprocess.STDOUT, timeout=7200).returncode
    lines = open(f'/kaggle/tmp/vllm_{think}.log').read().splitlines()
    print('think', think, 'rc', rc, 'elapsed', round(time.time() - t0), 's')
    print('\n'.join([l for l in lines if l.startswith('{') or 'Error' in l][-20:]))
print(subprocess.run(['python', f'{W}/agg_gemma.py'], env=env, capture_output=True, text=True).stdout)
```
```
[output] graphloc.py ca4733abd4990ebadbf0a039a0e566f3 OK
build_prompts2.py 33aad61855fbd06c9b237e3414344ae8 OK
run_gemma2.py 87d9a61f49d862220fe548f49feee756 OK
agg_gemma.py 46af6f1f686ca77d41084a3f049f8e55 OK
shard 0 prompts 96

shard 1 prompts 84

shard 2 prompts 96

shard 3 prompts 90

shard 4 prompts 96

shard 5 prompts 96

shard 6 prompts 78

shard 7 prompts 96

prompts 732 49 s
think 0 rc 0 elapsed 977 s
{"tag": "nothink", "n": 732, "elapsed_s": 852.2, "model": "/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2"}
think 1 rc 0 elapsed 3558 s
{"tag": "think", "n": 366, "elapsed_s": 2505.9, "model": "/kaggle/input/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/2"}
== nothink
g0_hop1 {"n": 122, "gemma@1": 0.459, "gemma@3": 0.484, "bm25@1": 0.213, "bm25@3": 0.41, "coverage": 0.549, "gemma@1|covered": 0.836, "median_pool": 15.0, "parsed": 103, "mean_prompt_tok": 2756, "mean_out_tok": 38}
g0_same {"n": 122, "gemma@1": 0.5, "gemma@3": 0.525, "bm25@1": 0.213, "bm25@3": 0.41, "coverage": 0.631, "gemma@1|covered": 0.792, "median_pool": 15.0, "parsed": 113, "mean_prompt_tok": 2665, "mean_out_tok": 25}
g0_top10 {"n": 122, "gemma@1": 0.467, "gemma@3": 0.475, "bm25@1": 0.213, "bm25@3": 0.41, "coverage": 0.566, "gemma@1|covered": 0.826, "median_pool": 10.0, "parsed": 108, "mean_prompt_tok": 1702, "mean_out_tok": 35}
gp_hop1 {"n": 122, "gemma@1": 0.508, "gemma@3": 0.541, "bm25@1": 0.246, "bm25@3": 0.385, "coverage": 0.623, "gemma@1|covered": 0.816, "median_pool": 2
```

```python
import json, collections
for tag in ('nothink', 'think'):
    rows = [json.loads(l) for l in open(f'{R}/gemma2_{tag}.jsonl')]
    un = [r for r in rows if not r['parsed']]
    c = collections.Counter(('[]' in r['raw'].replace(' ', '')) for r in un)
    print(tag, len(un), 'empty-list', c[True], 'covered among unparsed', sum(r['gold_in_pool'] for r in un))
    for r in un[:3]:
        print('  ', r['cond'], r['gold_in_pool'], repr(r['raw'][-200:]))
    ab = [r for r in rows if not r['parsed']]
    for cond in sorted({r['cond'] for r in rows}):
        rr = [r for r in rows if r['cond'] == cond]
        print('  ', cond, 'abstain', sum(not r['parsed'] for r in rr), 'abstain&uncovered', sum((not r['parsed']) and not r['gold_in_pool'] for r in rr), 'uncovered', sum(not r['gold_in_pool'] for r in rr))
```
```
[output] nothink 79 empty-list 46 covered among unparsed 3
   g0_hop1 False '```json\n{"ranking": []}\n```'
   gp_hop1 False '```json\n{"ranking": []}\n```'
   gp_hop1 False 's the evaluated type hints) is typically initialized.\n\nSince the issue is about the *evaluation* of annotations (which happens during the setup/initialization of the route/dependant), the logic in the'
   g0_hop1 abstain 19 abstain&uncovered 19 uncovered 55
   g0_same abstain 9 abstain&uncovered 8 uncovered 45
   g0_top10 abstain 14 abstain&uncovered 13 uncovered 53
   gp_hop1 abstain 17 abstain&uncovered 17 uncovered 46
   gp_same abstain 11 abstain&uncovered 11 uncovered 41
   gp_top10 abstain 9 abstain&uncovered 8 uncovered 50
think 30 empty-list 5 covered among unparsed 6
   gp_hop1 False 'tually `fastapi/routing.py` but renamed?\n    No, the names are very clear: `scripts.translate.make_pr`, `scripts.topic_repos.main`, etc.\n\n    I will return an empty ranking.```json\n{"ranking": []}\n```'
   gp_hop1 False 'th more context.\nNone of the scripts use `router.routes` or `iter_route_contexts()`. They use `Github` API, `yaml`, `logging`, `typer`, etc.\n\nI will return an empty ranking.```json\n{"ranking": []}\n```'
   gp_top10 True 't attempted to complement the model values with values not explicitely in the model, if values for those fields were not already processed earlier."\n\n    If "Later" means "later in the same function",'
   gp_hop1 abstain 12 abstain&uncovered 9 uncovered 46
   gp_same abstain 8 a
```

```python
# graph-localize v1.1: strip URLs from the issue (link tokens such as "github", "com" pulled unrelated code to the top)
# and use the same mention rules as the study (CamelCase words, traceback frames, no bare numbers).
import glob, hashlib, importlib.util, json, multiprocessing, os, statistics, sys, time
W = '/kaggle/working'
NB = os.path.dirname(glob.glob('/kaggle/input/notebooks/**/graphloc.py', recursive=True)[0])
sys.path.insert(0, W); import graphloc as G
TT = {t['instance_id']: t for t in G.load_tasks()}
src = open(NB + '/skills/graph_localize/scripts/localize.py').read()
PATCH = [(r"""or re.search(r'[a-z][A-Z]', w)))
    return {m.strip('.') for m in ms}""", r"""or re.search(r'[a-z][A-Z]', w) or re.match(r'^[A-Z][a-z]+[A-Z]', w)))
    ms.update(re.findall(r'\bin ([A-Za-z_]\w+)\s*$', text, flags=re.M))  # traceback frames
    return {m.strip('.') for m in ms if not re.fullmatch(r'[\d.]+', m)}"""),
         (r"""    issue = re.sub(r'<!--.*?-->', ' ', issue, flags=re.S)
""", r"""    issue = re.sub(r'<!--.*?-->', ' ', issue, flags=re.S)
    issue = re.sub(r'https?://\S+', ' ', issue)  # links add noise tokens (github, com, ...)
""")]
for a, b in PATCH:
    assert src.count(a) == 1
    src = src.replace(a, b)
os.makedirs(f'{W}/skills/graph_localize/scripts', exist_ok=True)
open(f'{W}/skills/graph_localize/scripts/localize.py', 'w').write(src)
print('localize.py v1.1 md5', hashlib.md5(src.encode()).hexdigest())
spec = importlib.util.spec_from_file_location('L11', f'{W}/skills/graph_localize/scripts/localize.py')
L11 = importlib.util.module_from_spec(spec); spec.loader.exec_module(L11)


def ev(tid):
    files = G.load_snapshot_py(tid, cache_dir='/kaggle/tmp/snapcache')
    gold = set(G.gold_labels(TT[tid], files, {p: L11.module_name(p) for p in files})['symbols'])
    t0 = time.time()
    res = L11.rank(files, TT[tid]['problem_statement'] + '\n' + (TT[tid].get('hints_text') or ''), k=50)
    return tid, len(gold), G.first_hit_rank([r[0] for r in res], gold), time.time() - t0


with multiprocessing.Pool(8) as pool:
    out = [o for o in pool.map(ev, sorted(TT)) if o[1]]
for k in (1, 5, 10):
    print(f'H@{k}', round(sum(o[2] is not None and o[2] <= k for o in out) / len(out), 3), end='  ')
print('n', len(out), 'median s', round(statistics.median(o[3] for o in out), 2), 'max s', round(max(o[3] for o in out), 2))
```
```
[output] localize.py v1.1 md5 16a32c6e29ceb8ba6435622dac458c7e
H@1 0.238  H@5 0.443  H@10 0.598  n 122 median s 1.86 max s 2.46

```
