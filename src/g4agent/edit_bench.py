"""Edit-robustness benchmark (no LLM): official edit_file matching vs skills/code-edit/scripts/edit.py.

Background (discussion 744272, and our own E006 request log): swegemma tool results reach the model
JSON-encoded twice, so text the model copies out of read_file/run_command output often carries stray
escapes. This benchmark takes real blocks of source, builds the (old_string, new_string) pair a model
would send for a small edit (append one statement), corrupts both strings the way the thread reports,
and checks whether each editor produces the intended program (same AST as the intended file).

Corruption modes (applied identically to old and new):
  clean        the text as it is in the file (control)
  esc1_lines   quotes, backslashes and non-ASCII escaped once, real newlines ("unescaped one level of two")
  esc1_full    the whole block escaped once, newlines as a literal backslash-n
  esc2_lines   escaped twice per line (no unescaping at all)
  dedent       leading indentation removed from every line (whitespace drift control)

Outcomes per case: correct (AST equal to the intended file), wrong (changed, but a different program),
refused (no change).
"wrong" is the dangerous outcome: a silent bad edit.

Run with the official venv, which provides swegemma/adk_eval_core:
  evaluations/.cache/official_venv/bin/python -m g4agent.edit_bench --out evaluations/analysis/edit_M001.json
(PYTHONPATH=src is set by scripts/run_edit_bench.sh.)
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
EDIT_PY = PROJECT / "skills" / "code-edit" / "scripts" / "edit.py"
MODES = ("clean", "esc1_lines", "esc1_full", "esc2_lines", "dedent")


def load_edit_module():
    spec = importlib.util.spec_from_file_location("g4_edit", EDIT_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def esc(s: str) -> str:
    return json.dumps(s, ensure_ascii=True)[1:-1]


def corrupt(block: str, mode: str) -> str:
    lines = block.split("\n")
    if mode == "clean":
        return block
    if mode == "esc1_lines":
        return "\n".join(esc(x) for x in lines)
    if mode == "esc1_full":
        return esc(block)
    if mode == "esc2_lines":
        return "\n".join(esc(esc(x)) for x in lines)
    if mode == "dedent":
        return "\n".join(x.lstrip() for x in lines)
    raise ValueError(mode)


def special(block: str) -> bool:
    return any(c in block for c in "\"\\") or any(ord(c) > 127 for c in block)


def sample_cases(repo: Path, n: int, seed: int) -> list[dict]:
    files = [f for f in subprocess.run(["git", "-C", str(repo), "ls-files", "*.py"], capture_output=True,
                                       text=True).stdout.split() if "test" not in f]
    rng = random.Random(seed)
    cases, tries = [], 0
    want_special = n // 2
    while len(cases) < n and tries < n * 200:
        tries += 1
        f = rng.choice(files)
        text = (repo / f).read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")
        if len(lines) < 10:
            continue
        k = rng.randint(2, 4)
        i = rng.randrange(0, len(lines) - k)
        block_lines = lines[i:i + k]
        if not block_lines[0].strip() or not block_lines[-1].strip():
            continue
        block = "\n".join(block_lines)
        if text.count(block) != 1:
            continue
        is_sp = special(block)
        n_sp = sum(c["special"] for c in cases)
        if is_sp and n_sp >= want_special or not is_sp and len(cases) - n_sp >= n - want_special:
            continue
        indent = block_lines[-1][: len(block_lines[-1]) - len(block_lines[-1].lstrip())]
        new_block = block + "\n" + indent + "_g4_edited = 1"
        intended = text.replace(block, new_block, 1)
        try:
            ast.parse(intended)
        except SyntaxError:
            continue
        cases.append({"file": f, "line": i + 1, "block": block, "new": new_block, "text": text,
                      "intended": intended, "special": is_sp})
    return cases


def run_official(text: str, old: str, new: str) -> str | None:
    from swegemma.edit import apply_replacement
    try:
        return apply_replacement(text, old, new).new_content
    except Exception:
        return None


def run_editpy(mod, text: str, old: str, new: str) -> str | None:
    results, _how = mod.plan_replace(text, old, new)
    if results is None:
        return None
    for after in results:  # same rule as edit.py's commit(): first candidate that parses
        if after == text:
            return None
        try:
            ast.parse(after)
            return after
        except SyntaxError:
            continue
    return None


def outcome(result: str | None, case: dict) -> str:
    if result is None or result == case["text"]:
        return "refused"
    if result == case["intended"]:
        return "correct"
    try:
        return "correct" if ast.dump(ast.parse(result)) == ast.dump(ast.parse(case["intended"])) else "wrong"
    except SyntaxError:
        return "wrong"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", nargs="+", default=[str(PROJECT / "evaluations/.cache/repos/Textualize__rich")])
    ap.add_argument("--n", type=int, default=200, help="cases per repo")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.out.exists():
        print(f"refusing to overwrite {a.out} (experiment ids are immutable)", file=sys.stderr)
        return 2
    mod = load_edit_module()
    tallies = defaultdict(Counter)
    examples = []
    n_cases = 0
    for repo in a.repos:
        for case in sample_cases(Path(repo), a.n, a.seed):
            n_cases += 1
            for mode in MODES:
                old, new = corrupt(case["block"], mode), corrupt(case["new"], mode)
                group = "special" if case["special"] else "plain"
                for editor, fn in (("official_edit_file", lambda t, o, w: run_official(t, o, w)),
                                   ("edit_py", lambda t, o, w: run_editpy(mod, t, o, w))):
                    res = outcome(fn(case["text"], old, new), case)
                    tallies[(editor, mode, group)][res] += 1
                    if res == "wrong" and len(examples) < 20:
                        examples.append({"editor": editor, "mode": mode, "file": case["file"], "line": case["line"]})
    rows = []
    for (editor, mode, group), c in sorted(tallies.items()):
        total = sum(c.values())
        rows.append({"editor": editor, "mode": mode, "group": group, "n": total, **c,
                     "correct_rate": round(c["correct"] / total, 3)})
    rev = subprocess.run(["git", "-C", str(PROJECT), "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True).stdout.strip()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"git_rev": rev, "repos": a.repos, "cases": n_cases, "seed": a.seed,
                                 "rows": rows, "wrong_examples": examples}, indent=1))
    print(f"{'editor':20s} {'mode':11s} {'group':8s} {'n':>4s} {'correct':>8s} {'wrong':>6s} {'refused':>8s}")
    for r in rows:
        print(f"{r['editor']:20s} {r['mode']:11s} {r['group']:8s} {r['n']:4d} {r.get('correct', 0):8d} "
              f"{r.get('wrong', 0):6d} {r.get('refused', 0):8d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
