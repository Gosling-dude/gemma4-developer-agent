"""Offline localization benchmark (no LLM needed).

For each case: extract search terms from the issue text deterministically (a stand-in for the terms
the model would pick), rank source files with several strategies, and score the ranking against the
files the reference patch edits (recall@k: is any gold file in the top k?).

Strategies:
  grep_count    raw hit counts of the terms (naive baseline, like `git grep -c`)
  nav_find      skills/repo-navigation/scripts/nav.py find (idf weighting + definition boost)
  nav_callees   nav_find's top file, then files reached by 1-2 hops of `calls` edges out of the issue's named
                symbols (the graph-reasoning move the prompt recommends), then the rest of nav_find
  nav_graph     nav_find, then 1-hop graph expansion (callers/callees/contains) of the top-3 files' defined
                symbols, adding neighbour files with a decayed score
  similar       search_similar_code on each term that resolves to a graph node (embedding neighbours)

Graph/embedding results use the official graph when available, otherwise the AST approximation with
lexical-proxy embeddings (see harness/graph.py). That is recorded in the output.

Usage: python -m g4agent.localization --tasks evaluations/cases/tasks.jsonl --out evaluations/analysis/localization.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from .harness.graph import CodeGraph, build_from_repo
from .harness.tasks import PROJECT, Task, load_tasks, prepare_workspace
from .harness.verify import is_protected, patch_files

NAV = PROJECT / "skills" / "repo-navigation" / "scripts" / "nav.py"
STOP = set("""the a an and or not is are was were be been to of in on for with this that it its as at by from
if else when then than into out up down can could should would will may might must do does did done have has
had use used using get set true false none self cls return def class import print value values data type types
error errors issue bug fix work works working example code file files line lines test tests expected actual output
python version rich request requests response string str int list dict object method function argument param
parameter default option options new old instead also like just only same different traceback
most recent call last""".split())


_BOX = re.compile(r"[\u2500-\u257f]")
_KV_DUMP = re.compile(r"^\s*[\w.\-]+\s*[=:]\s*[^\s].{0,60}$")
_ENV_HINT = re.compile(r"(python -m \S+\.diagnose|pip (freeze|list)|platform|version|environment|os:|terminal)", re.I)


def strip_environment_dump(text: str) -> str:
    """Drop issue-template environment reports (box-drawn diagnostics, key=value dumps, version lines)."""
    keep = []
    for line in text.splitlines():
        if _BOX.search(line) or _KV_DUMP.match(line) or (_ENV_HINT.search(line) and len(line) < 100):
            continue
        keep.append(line)
    return "\n".join(keep)


FILTERS = {"env", "urls"}  # which noise filters extract_terms applies (ablation switch)
_URLISH = re.compile(r"(readthedocs|github|\.(io|com|org|html?|md|rst|txt)$)", re.I)


def extract_terms(text: str, limit: int = 6) -> list[str]:
    """Pick specific identifiers from issue text: code spans, tracebacks, Camel/snake/dotted names."""
    if "env" in FILTERS:
        text = strip_environment_dump(text)
    cands: dict[str, float] = defaultdict(float)
    for span in re.findall(r"`([^`\n]{2,60})`", text):
        for ident in re.findall(r"[A-Za-z_][\w.]*", span):
            cands[ident] += 3
    for func in re.findall(r'File "[^"]+", line \d+, in (\w+)', text):
        cands[func] += 4
    for ident in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b", text):
        cands[ident] += 2
    for ident in re.findall(r"\b(?:[A-Z][a-z0-9]+){2,}\b|\b[a-z0-9]+(?:_[a-z0-9]+)+\b", text):
        cands[ident] += 2
    for ident in re.findall(r"\b[A-Za-z_]\w{3,}\b", text):
        cands[ident] += 0.2
    out = []
    for term, score in sorted(cands.items(), key=lambda kv: (-kv[1], -len(kv[0]))):
        base = term.split(".")[-1]
        dotted = "." in term
        if (not dotted and (base.lower() in STOP or len(base) < 4)) or term.lower() in STOP \
                or term.startswith(("http", "www")) or base.isdigit() or term.endswith((".py", ".com", ".org")) \
                or ("urls" in FILTERS and _URLISH.search(term)):
            continue
        if any(term == o or term in o.split(".") for o in out):
            continue
        out.append(term)
        if len(out) >= limit:
            break
    return out


def grep_count(ws: Path, terms: list[str]) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for t in terms:
        out = subprocess.run(["git", "grep", "-c", "-F", "-e", t, "--", "*.py"], cwd=ws, capture_output=True,
                             text=True).stdout
        for line in out.splitlines():
            path, _, c = line.rpartition(":")
            if c.isdigit() and not is_protected(path):
                scores[path] += int(c)
    return [p for p, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


def nav_find(ws: Path, terms: list[str]) -> tuple[list[str], dict[str, float], list[str]]:
    r = subprocess.run([sys.executable, str(NAV), "find", *terms], capture_output=True, text=True,
                       env={"SWE_WORKSPACE": str(ws), "PATH": "/usr/bin:/bin:/opt/homebrew/bin"})
    ranked, scores, defs = [], {}, []
    section = ""
    for line in r.stdout.splitlines():
        if line.startswith("DEFINITIONS"):
            section = "defs"
        elif line.startswith("TOP SOURCE"):
            section = "top"
        elif line.startswith("RELATED TEST"):
            section = "tests"
        elif section == "defs" and line.startswith("  "):
            defs.append(line.strip())
        elif section == "top":
            m = re.match(r"^\s+([\d.]+)\s+(\S+\.py)$", line)
            if m:
                ranked.append(m.group(2))
                scores[m.group(2)] = float(m.group(1))
    return ranked, scores, defs


def nav_graph(ranked: list[str], scores: dict[str, float], graph: CodeGraph) -> list[str]:
    file_of = {nid: n.get("file") for nid, n in graph.nodes.items() if n.get("file")}
    by_file: dict[str, list[str]] = defaultdict(list)
    for nid, f in file_of.items():
        by_file[f].append(nid)
    new = dict(scores)
    for path in ranked[:3]:
        base = scores.get(path, 1.0)
        for nid in by_file.get(path, [])[:40]:
            for e in graph.out.get(nid, []) + graph.inc.get(nid, []):
                other = e["target"] if e["source"] == nid else e["source"]
                f = file_of.get(other)
                if f and f != path and not is_protected(f):
                    new[f] = new.get(f, 0.0) + 0.02 * base
    return [p for p, _ in sorted(new.items(), key=lambda kv: -kv[1])]


def nav_callees(ranked: list[str], terms: list[str], graph: CodeGraph, hops: int = 2) -> list[str]:
    """Keep nav's top file, then files reached by following `calls` edges out of the issue's named symbols."""
    file_of = {nid: n.get("file") for nid, n in graph.nodes.items() if n.get("file")}
    scores: dict[str, float] = defaultdict(float)
    for i, t in enumerate(terms):
        rid = graph.resolve(t)
        if not rid or rid.count(".") < 1 or rid not in file_of:
            continue
        frontier, seen = [rid], {rid}
        for hop in range(1, hops + 1):
            nxt = []
            for nid in frontier:
                for e in graph.out.get(nid, []):
                    if e["type"] != "calls" or e["target"] in seen:
                        continue
                    seen.add(e["target"])
                    nxt.append(e["target"])
                    f = file_of.get(e["target"])
                    if f and not is_protected(f):
                        scores[f] += 1.0 / (hop * (1 + 0.3 * i))
            frontier = nxt
    callee_files = [p for p, _ in sorted(scores.items(), key=lambda kv: -kv[1])]
    out = ranked[:1]
    for p in callee_files + ranked[1:]:
        if p not in out:
            out.append(p)
    return out


def similar(terms: list[str], graph: CodeGraph) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for t in terms:
        res = graph.similar(t, 10)
        if res.get("status") != "ok":
            continue
        q = graph.nodes.get(res["query"], {}).get("file")
        if q:
            scores[q] += 1.0
        for i, r in enumerate(res["results"]):
            f = graph.nodes.get(r["node_name"], {}).get("file")
            if f and not is_protected(f):
                scores[f] += r["similarity"] / (1 + i)
    return [p for p, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


def recall(ranked: list[str], gold: set[str], k: int) -> int:
    return int(bool(set(ranked[:k]) & gold))


def evaluate(tasks: list[Task], data_dir: Path | None) -> dict:
    per_task = []
    ks = (1, 3, 5)
    strategies = ("grep_count", "nav_find", "nav_graph", "nav_callees", "similar")
    for task in tasks:
        gold = {f for f in patch_files(task.patch) if f.endswith(".py") and not is_protected(f)}
        with tempfile.TemporaryDirectory() as td:
            ws = prepare_workspace(task, Path(td) / "ws", data_dir)
            graph_json = data_dir / "graphs" / f"{task.instance_id}.json" if data_dir else None
            if graph_json and graph_json.exists():
                graph, gsrc = CodeGraph.load_official(graph_json, data_dir / "embeddings" / f"{task.instance_id}.npz"), "official"
            else:
                graph, gsrc = build_from_repo(ws), "ast-approx"
            terms = extract_terms(task.problem_statement)
            ranked_nav, scores, _ = nav_find(ws, terms)
            rankings = {
                "grep_count": grep_count(ws, terms),
                "nav_find": ranked_nav,
                "nav_graph": nav_graph(ranked_nav, scores, graph),
                "nav_callees": nav_callees(ranked_nav, terms, graph),
                "similar": similar(terms, graph),
            }
        row = {"instance_id": task.instance_id, "gold": sorted(gold), "terms": terms, "graph": gsrc,
               "top3": {s: rankings[s][:3] for s in strategies}}
        for s in strategies:
            for k in ks:
                row[f"{s}@{k}"] = recall(rankings[s], gold, k)
        per_task.append(row)
        print(f"{task.instance_id}: terms={terms} gold={sorted(gold)} " +
              " ".join(f"{s}@3={row[f'{s}@3']}" for s in strategies), flush=True)
    n = len(per_task) or 1
    summary = {f"{s}@{k}": round(sum(r[f"{s}@{k}"] for r in per_task) / n, 3) for s in strategies for k in ks}
    return {"n": len(per_task), "summary": summary, "per_task": per_task}


def _sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", type=Path, default=PROJECT / "evaluations" / "cases" / "tasks.jsonl")
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=PROJECT / "evaluations" / "analysis" / "localization.json")
    ap.add_argument("--filters", default="env,urls", help="term-extraction noise filters: env,urls or none")
    args = ap.parse_args(argv)
    FILTERS.clear()
    FILTERS.update(f for f in args.filters.split(",") if f and f != "none")
    res = evaluate(load_tasks(args.tasks), args.data_dir)
    res["config"] = {"filters": sorted(FILTERS), "nav_sha": _sha(NAV)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2))
    print(json.dumps(res["summary"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
