"""Code graph + embeddings backing the three graph tools.

Two sources:
- Official competition files: `graphs/<id>.json` (NetworkX node-link, nodes have id/name/text, edges
  have source/target/type/key) and `embeddings/<id>.npz` (one 256-d float32 vector per node id).
- `build_from_repo`: our AST-based approximation for repositories without official files. Node ids are
  fully-qualified Python paths, as in the official schema. Edges are `contains`, `calls`, `imports` and
  `inherits`. Embeddings are hashed bags of identifier sub-tokens (256-d). This is only a
  **lexical proxy** for the official learned embeddings, and results measured with it are labelled as such.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np

DIM = 256


class CodeGraph:
    def __init__(self, nodes: dict[str, dict], edges: list[dict], vectors: dict[str, np.ndarray] | None = None):
        self.nodes = nodes                      # id -> {"id","name","text", ...}
        self.edges = edges                      # {"source","target","type"}
        self.out: dict[str, list[dict]] = defaultdict(list)
        self.inc: dict[str, list[dict]] = defaultdict(list)
        for e in edges:
            self.out[e["source"]].append(e)
            self.inc[e["target"]].append(e)
        self.vectors = vectors or {}
        self._ids = list(self.nodes)
        self._lower = {i.lower(): i for i in self._ids}
        self._matrix = None

    # ------------------------------------------------------------------ loading

    @classmethod
    def load_official(cls, graph_json: Path, npz: Path | None) -> "CodeGraph":
        data = json.loads(graph_json.read_text())
        nodes = {n["id"]: n for n in data.get("nodes", [])}
        edges = [{"source": e["source"], "target": e["target"], "type": e.get("type", "")}
                 for e in data.get("edges", data.get("links", []))]
        vectors = {}
        if npz and npz.exists():
            with np.load(npz) as z:
                vectors = {k: z[k].astype(np.float32) for k in z.files}
        return cls(nodes, edges, vectors)

    def save(self, graph_json: Path, npz: Path) -> None:
        graph_json.parent.mkdir(parents=True, exist_ok=True)
        npz.parent.mkdir(parents=True, exist_ok=True)
        payload = {"directed": True, "multigraph": True, "graph": {"generator": "g4agent-ast-approx"},
                   "nodes": list(self.nodes.values()),
                   "edges": [dict(e, key=0) for e in self.edges]}
        graph_json.write_text(json.dumps(payload))
        np.savez_compressed(npz, **self.vectors)

    # ------------------------------------------------------------------ resolution

    def resolve(self, name: str) -> str | None:
        """exact -> '.'/'/' suffix -> case-insensitive -> substring (shortest wins)."""
        if name in self.nodes:
            return name
        suffix = [i for i in self._ids if i.endswith("." + name) or i.endswith("/" + name)]
        if suffix:
            return min(suffix, key=len)
        low = self._lower.get(name.lower())
        if low:
            return low
        sub = [i for i in self._ids if name.lower() in i.lower()]
        return min(sub, key=len) if sub else None

    # ------------------------------------------------------------------ tool backends

    def neighbors(self, node: str, edge_type: str | None, max_neighbors: int) -> dict:
        rid = self.resolve(node)
        if rid is None:
            return {"status": "error", "error_type": "NodeNotFound", "error_message": f"No graph node matches {node!r}"}
        want = edge_type.lower() if edge_type else None
        items = []
        for e in self.out.get(rid, []):
            if want is None or e["type"].lower() == want:
                items.append({"node": e["target"], "direction": "outgoing", "type": e["type"]})
        for e in self.inc.get(rid, []):
            if want is None or e["type"].lower() == want:
                items.append({"node": e["source"], "direction": "incoming", "type": e["type"]})
        items = items[: max(1, int(max_neighbors))]
        return {"status": "ok", "node": rid, "neighbors": items, "count": len(items)}

    def similar(self, query: str, k: int) -> dict:
        if not self.vectors:
            return {"status": "error", "error_type": "EmbeddingsUnavailable", "error_message": "no embeddings"}
        rid = self.resolve(query)
        if rid is None or rid not in self.vectors:
            return {"status": "error", "error_type": "NodeNotFound",
                    "error_message": f"Query {query!r} does not match a known symbol; pass a class/function name."}
        if self._matrix is None:
            self._vec_ids = [i for i in self._ids if i in self.vectors]
            m = np.stack([self.vectors[i] for i in self._vec_ids])
            self._matrix = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        q = self.vectors[rid] / (np.linalg.norm(self.vectors[rid]) + 1e-9)
        sims = self._matrix @ q
        order = np.argsort(-sims)
        results = []
        for idx in order:
            nid = self._vec_ids[idx]
            if nid == rid:
                continue
            text = self.nodes.get(nid, {}).get("text", "") or ""
            results.append({"node_name": nid, "code": text[:400], "similarity": round(float(sims[idx]), 4)})
            if len(results) >= int(k):
                break
        return {"status": "ok", "query": rid, "results": results, "count": len(results)}

    def subgraph(self, names: list[str]) -> dict:
        ids = [r for r in (self.resolve(n) for n in names) if r]
        idset = set(ids)
        edges = [{"from": e["source"], "to": e["target"], "type": e["type"]}
                 for e in self.edges if e["source"] in idset and e["target"] in idset]
        return {"status": "ok", "nodes": ids, "edges": edges, "node_count": len(ids), "edge_count": len(edges)}


# ---------------------------------------------------------------------- AST approximation

_SPLIT = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def subtokens(text: str) -> list[str]:
    toks = []
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        for part in ident.split("_"):
            toks += [t.lower() for t in _SPLIT.findall(part)]
    return toks


def hashed_embedding(text: str) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    counts: dict[str, int] = defaultdict(int)
    for t in subtokens(text):
        counts[t] += 1
    for t, c in counts.items():
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        v[h % DIM] += (1 if (h >> 8) & 1 else -1) * (1 + math.log(c))
    n = np.linalg.norm(v)
    return v / n if n else v


def _module_name(rel: str) -> str:
    mod = rel[:-3].replace("/", ".")
    for p in ("src.", "lib."):
        if mod.startswith(p):
            mod = mod[len(p):]
    return re.sub(r"\.__init__$", "", mod)


def build_from_repo(repo: Path, include_tests: bool = False) -> CodeGraph:
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=repo, capture_output=True, text=True).stdout.split()
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    calls: list[tuple[str, str, str]] = []   # (caller_id, called_leaf, module)
    bases: list[tuple[str, str]] = []
    imports: list[tuple[str, str]] = []
    for rel in files:
        if not include_tests and (rel.startswith(("tests/", "test/", "docs", "docs_src/")) or "/tests/" in rel):
            continue
        try:
            src = (repo / rel).read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except (SyntaxError, ValueError, OSError):
            continue
        mod = _module_name(rel)
        nodes[mod] = {"id": mod, "name": mod, "text": src[:2000], "file": rel}
        lines = src.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports += [(mod, a.name) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append((mod, node.module))

        def visit(body, parent_id):
            for n in body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    nid = f"{parent_id}.{n.name}"
                    text = "\n".join(lines[n.lineno - 1:n.end_lineno])
                    nodes[nid] = {"id": nid, "name": nid, "text": text, "file": rel,
                                  "start_line": n.lineno, "end_line": n.end_lineno}
                    edges.append({"source": parent_id, "target": nid, "type": "contains"})
                    if isinstance(n, ast.ClassDef):
                        for b in n.bases:
                            leaf = b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", None)
                            if leaf:
                                bases.append((nid, leaf))
                        visit(n.body, nid)
                    else:
                        for c in ast.walk(n):
                            if isinstance(c, ast.Call):
                                f = c.func
                                leaf = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                                if leaf:
                                    calls.append((nid, leaf, mod))
        visit(tree.body, mod)

    by_leaf: dict[str, list[str]] = defaultdict(list)
    for nid in nodes:
        by_leaf[nid.rsplit(".", 1)[-1]].append(nid)
    seen = set()
    for caller, leaf, mod in calls:
        targets = by_leaf.get(leaf, [])
        same = [t for t in targets if t.startswith(mod + ".")]
        for t in (same or targets)[:3]:
            key = (caller, t)
            if t != caller and key not in seen:
                seen.add(key)
                edges.append({"source": caller, "target": t, "type": "calls"})
    for cls, leaf in bases:
        for t in by_leaf.get(leaf, [])[:2]:
            edges.append({"source": cls, "target": t, "type": "inherits"})
    for mod, target in set(imports):
        if target in nodes:
            edges.append({"source": mod, "target": target, "type": "imports"})
    vectors = {nid: hashed_embedding(nid.rsplit(".", 1)[-1] + " " + n["text"][:3000]) for nid, n in nodes.items()}
    return CodeGraph(nodes, edges, vectors)
