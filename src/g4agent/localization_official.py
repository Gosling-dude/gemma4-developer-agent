"""Localization benchmark on the OFFICIAL public dev tasks (no LLM).

Tasks: evaluations/.cache/official_dev/tasks_min.jsonl, built by `--build` from public sources: problem
statements as the official harness rendered them (task message in public real-run traces), base commits and
gold files/symbols from the public GraphLoc-129 labels. Workspaces: `git archive <base_commit>` of the public repo.
Graphs: the public async-aware repaired graphs (woldywei, 130 tasks; `calls` edges only). The official
embeddings are not available here, so search_similar_code is measured from real traces instead
(g4agent.trace_taxonomy), not simulated.

Measures, per term-extraction filter set:
  terms_hit_gold_symbol  an extracted term names a gold symbol (identifier extraction kept the real identifier)
  recall@1/3/5           a gold source file is in the top k, for the graph-tool policies:
    A  nav_find only
    B  nav_find + 1-hop neighbours of the top-3 files (always expand)
    C  nav_find; follow outgoing `calls` of a named symbol ONLY when it delegates to another file
    D  graph first: callee files of the named symbols, then nav_find

Usage: python -m g4agent.localization_official [--build] [--filters env,urls] [--out ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from . import localization as L
from .harness.graph import CodeGraph
from .harness.tasks import CACHE, PROJECT, Task, prepare_workspace
from .harness.verify import is_protected

TASKS = CACHE / "official_dev" / "tasks_min.jsonl"
GRAPHS = CACHE / "third_party" / "woldywei__gemma4-repaired-graphs-regen"
LABELS = CACHE / "third_party" / "zzgtylors__graphloc-end-to-end-failure-analysis-resource" / "graphloc129" / "graphloc129_labels.jsonl"


def build(out: Path = TASKS) -> int:
    """Problem statements from every public trace we hold + GraphLoc labels -> tasks_min.jsonl."""
    labels = {json.loads(l)["instance_id"]: json.loads(l) for l in LABELS.open()}
    ps: dict[str, str] = {}
    for f in sorted((CACHE / "third_party").rglob("trace_*.json")):
        tid = f.stem[len("trace_"):]
        if tid in ps or tid not in labels:
            continue
        try:
            steps = json.loads(f.read_text())["steps"]
        except (ValueError, KeyError):
            continue
        msg = next((str(s.get("message")) for s in steps if s.get("source") == "user"
                    and "Problem Statement:" in str(s.get("message"))), None)
        if not msg:
            continue
        i = msg.find("Problem Statement:\n") + len("Problem Statement:\n")
        ends = [e for e in (msg.find(x, i) for x in ("\n## Task Budget", "\n## Execution Environment Rules",
                                                     "\n## Instructions:")) if e > 0]
        ps[tid] = msg[i:min(ends)].rstrip()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        for tid, lab in sorted(labels.items()):
            if tid in ps:
                fh.write(json.dumps({**{k: lab[k] for k in ("instance_id", "repo", "base_commit", "gold_files",
                                                            "new_files", "gold_symbols")},
                                     "problem_statement": ps[tid]}) + "\n")
    return len(ps)


def load_graph(tid: str, ws: Path) -> CodeGraph | None:
    p = GRAPHS / f"{tid}.json"
    if not p.exists():
        return None
    g = CodeGraph.load_official(p, None)
    # repaired graphs have dotted ids and no file attribute: map each node to the longest module path that exists
    cache: dict[str, str | None] = {}
    for nid, node in g.nodes.items():
        parts = nid.split(".")
        for k in range(len(parts), 0, -1):
            mod = ".".join(parts[:k])
            if mod not in cache:
                base = ws / Path(*parts[:k])
                cache[mod] = next((str(c.relative_to(ws)) for c in (base.with_suffix(".py"), base / "__init__.py")
                                   if c.is_file()), None)
            if cache[mod]:
                node["file"] = cache[mod]
                break
    return g


def delegating_callees(terms: list[str], ranked: list[str], graph: CodeGraph) -> list[str]:
    """Policy C: follow outgoing calls only for named symbols whose calls leave their own file."""
    file_of = {nid: n.get("file") for nid, n in graph.nodes.items() if n.get("file")}
    for t in terms:
        rid = graph.resolve(t)
        if not rid or rid not in file_of:
            continue
        own = file_of[rid]
        if any(file_of.get(e["target"]) not in (None, own) for e in graph.out.get(rid, []) if e["type"] == "calls"):
            return L.nav_callees(ranked, terms, graph)
    return ranked


def graph_first(terms: list[str], ranked: list[str], graph: CodeGraph) -> list[str]:
    """Policy D: files of the named symbols and their callees before anything nav_find found."""
    via = L.nav_callees([], terms, graph)
    file_of = {nid: n.get("file") for nid, n in graph.nodes.items() if n.get("file")}
    named = [file_of.get(graph.resolve(t) or "") for t in terms]
    out: list[str] = []
    for p in [f for f in named if f] + via + ranked:
        if p not in out and not is_protected(p):
            out.append(p)
    return out


def evaluate(tasks: list[dict]) -> dict:
    ks = (1, 3, 5)
    pol = ("grep", "A_nav", "B_expand", "C_conditional", "D_graph_first")
    rows = []
    for t in tasks:
        gold = {f for f in t["gold_files"] if f.endswith(".py") and not is_protected(f)}
        if not gold:
            continue
        sym_names = {s["id"].split(".")[-1] for s in t.get("gold_symbols") or []}
        task = Task(t["instance_id"], t["repo"], t["base_commit"], t["problem_statement"])
        with tempfile.TemporaryDirectory() as td:
            ws = prepare_workspace(task, Path(td) / "ws")
            terms = L.extract_terms(t["problem_statement"])
            ranked, scores, _ = L.nav_find(ws, terms)
            graph = load_graph(t["instance_id"], ws)
            rk = {"grep": L.grep_count(ws, terms), "A_nav": ranked}
            if graph is not None:
                rk["B_expand"] = L.nav_graph(ranked, scores, graph)
                rk["C_conditional"] = delegating_callees(terms, ranked, graph)
                rk["D_graph_first"] = graph_first(terms, ranked, graph)
        row = {"instance_id": t["instance_id"], "repo": t["repo"], "gold": sorted(gold), "terms": terms,
               "terms_hit_gold_symbol": int(bool(sym_names & {x.split(".")[-1] for x in terms})),
               "has_graph": graph is not None, "top3": {p: r[:3] for p, r in rk.items()}}
        for p, r in rk.items():
            for k in ks:
                row[f"{p}@{k}"] = L.recall(r, gold, k)
        rows.append(row)
        print(f"{t['instance_id']}: terms={terms} gold={sorted(gold)} A@1={row['A_nav@1']} A@5={row['A_nav@5']}", flush=True)
    summary: dict = {"n": len(rows), "terms_hit_gold_symbol": round(sum(r["terms_hit_gold_symbol"] for r in rows) / max(1, len(rows)), 3)}
    for p in pol:
        sub = [r for r in rows if f"{p}@1" in r]
        for k in ks:
            summary[f"{p}@{k}"] = round(sum(r[f"{p}@{k}"] for r in sub) / max(1, len(sub)), 3)
        summary[f"{p}_n"] = len(sub)
    g = [r for r in rows if r["has_graph"]]
    summary["graph_subset"] = {f"{p}@{k}": round(sum(r[f"{p}@{k}"] for r in g) / max(1, len(g)), 3)
                               for p in pol for k in ks}
    summary["graph_subset"]["n"] = len(g)
    by_repo = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)
    summary["A_nav_by_repo"] = {k: {"n": len(v), "@1": round(sum(r["A_nav@1"] for r in v) / len(v), 3),
                                    "@5": round(sum(r["A_nav@5"] for r in v) / len(v), 3)} for k, v in by_repo.items()}
    return {"summary": summary, "per_task": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", action="store_true", help="(re)build tasks_min.jsonl from public traces + labels")
    ap.add_argument("--filters", default="env,urls")
    ap.add_argument("--out", type=Path, default=PROJECT / "evaluations" / "analysis" / "localization_official.json")
    a = ap.parse_args(argv)
    if a.build or not TASKS.exists():
        print(f"built {build()} tasks -> {TASKS}")
    L.FILTERS.clear()
    L.FILTERS.update(f for f in a.filters.split(",") if f and f != "none")
    tasks = [json.loads(l) for l in TASKS.open()]
    res = evaluate(tasks)
    res["config"] = {"filters": sorted(L.FILTERS), "nav_sha": L._sha(L.NAV), "tasks": len(tasks),
                     "graphs": "woldywei repaired (async-aware, calls only); not the official graphs"}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
