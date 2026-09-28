"""Repository navigation helper: several searches in one tool call.

Usage (args is a list of strings):
  nav.py find TERM [TERM ...]      rank source files by relevance to identifiers/strings from the issue
  nav.py outline PATH [PATH ...]   classes/functions of a file with line ranges
  nav.py show SYMBOL [PATH]        source of a function/class/method with line numbers
  nav.py usages SYMBOL             where a name is defined, called, imported (source and tests separately)
  nav.py layout                    build system, packages, test dirs, key config files

Stdlib only. Output is capped at about 4500 characters so it fits the harness output limit.
The repository is /workspace (or $SWE_WORKSPACE when running outside the sandbox).
"""

import ast
import math
import os
import re
import subprocess
import sys
from collections import defaultdict

WS = os.environ.get("SWE_WORKSPACE") or ("/workspace" if os.path.isdir("/workspace") else os.getcwd())
LIMIT = 4500
SKIP_DIRS = ("docs/", "doc/", "site/", "build/", "dist/", ".venv/", "venv/", "node_modules/")
_out = []


def emit(line=""):
    _out.append(line)


def flush():
    text = "\n".join(_out)
    if len(text) > LIMIT:
        text = text[:LIMIT] + "\n...[truncated by nav.py]"
    print(text)


def git(*args, timeout=60):
    try:
        r = subprocess.run(["git", "-C", WS, *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def tracked_py_files():
    files = [f for f in git("ls-files", "*.py").splitlines() if f]
    if not files:  # not a git repo: walk the tree
        for base, dirs, names in os.walk(WS):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules")]
            files += [os.path.relpath(os.path.join(base, n), WS) for n in names if n.endswith(".py")]
    return files


def is_test(path):
    p = "/" + path
    name = os.path.basename(path)
    return ("/tests/" in p or "/test/" in p or "/testing/" in p or name.startswith("test_")
            or name.endswith("_test.py") or name == "conftest.py")


def grep_fixed(term):
    """{path: [(lineno, text)]} for a fixed-string search over tracked .py files."""
    out = git("grep", "-n", "-I", "-F", "--no-color", "-e", term, "--", "*.py", timeout=60)
    hits = defaultdict(list)
    for line in out.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[1].isdigit():
            hits[parts[0]].append((int(parts[1]), parts[2].strip()))
    return hits


# ----------------------------------------------------------------------------- find

DEF_RE = r"^\s*(async\s+def|def|class)\s+{name}\b"


def cmd_find(terms):
    terms = [t.strip() for t in terms if t.strip()]
    if not terms:
        emit("usage: find TERM [TERM ...]")
        return
    all_files = tracked_py_files()
    n_files = max(1, len(all_files))
    scores = defaultdict(float)
    evidence = defaultdict(list)
    defs = []
    test_scores = defaultdict(float)
    term_stats = []
    def_names_used = set()
    for i, term in enumerate(terms):
        hits = grep_fixed(term)
        # A dotted name also counts as its last component, e.g. "Response.json" -> "json".
        short = term.split(".")[-1] if "." in term and " " not in term else None
        if not hits and short:
            hits = grep_fixed(short)
        hits = {p: l for p, l in hits.items() if not any(p.startswith(d) for d in SKIP_DIRS)}
        df = len(hits)
        term_stats.append(f"{term}:{df}")
        if df == 0:
            continue
        idf = math.log(1 + n_files / df)
        order_w = 1.0 / (1 + 0.3 * i)  # earlier terms are the more specific ones
        name = short or term
        def_re = None
        if re.match(r"^[A-Za-z_]\w*$", name) and name not in def_names_used:
            def_names_used.add(name)
            def_re = re.compile(DEF_RE.format(name=re.escape(name)))
        def_files = set()
        for path, lines in hits.items():
            for ln, text in lines:
                if def_re and def_re.match(text):
                    def_files.add(path)
                    defs.append(f"{path}:{ln}: {text[:110]}")
        src_defs = [p for p in def_files if not is_test(p)] or list(def_files)
        for path, lines in hits.items():
            # Capped mention score; a definition counts more the fewer places define the name.
            s = idf * min(1 + math.log(len(lines)), 3.0)
            if path in def_files:
                s += 8 * idf / len(src_defs)
            s *= order_w
            if is_test(path):
                test_scores[path] += s
            else:
                scores[path] += s
                if len(evidence[path]) < 4:
                    evidence[path].extend(lines[: 4 - len(evidence[path])])
    # A dotted term naming a module ("pkg.sub.mod") points straight at its file.
    tracked = set(all_files)
    for i, term in enumerate(terms):
        if "." not in term or " " in term:
            continue
        parts = term.split(".")
        for k in range(len(parts), 1, -1):
            base = "/".join(parts[:k])
            hit = next((c for c in (f"{base}.py", f"{base}/__init__.py", f"src/{base}.py", f"src/{base}/__init__.py")
                        if c in tracked and not is_test(c)), None)
            if hit:
                scores[hit] += 6.0 / (1 + 0.3 * i)
                evidence[hit] = evidence[hit] or [(0, f"module named in issue: {term}")]
                break
    emit("term document-frequency (files containing it): " + ", ".join(term_stats))
    if defs:
        emit("\nDEFINITIONS:")
        for d in sorted(dict.fromkeys(defs), key=lambda d: is_test(d.split(":", 1)[0]))[:12]:
            emit("  " + d)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:8]
    emit("\nTOP SOURCE FILES (score, path, sample lines):")
    if not ranked:
        emit("  none. Try other spellings, error-message fragments, or the search_similar_code tool.")
    for path, s in ranked:
        emit(f"  {s:5.1f}  {path}")
        for ln, text in sorted(set(evidence[path]))[:3]:
            emit(f"         {ln}: {text[:120]}")
    tests = sorted(test_scores.items(), key=lambda kv: -kv[1])[:5]
    if tests:
        emit("\nRELATED TEST FILES:")
        for path, s in tests:
            emit(f"  {s:5.1f}  {path}")
    emit("\nNext: 'show SYMBOL' or read_file on the top file; don't read whole files.")


# ----------------------------------------------------------------------------- outline / show

def parse(path):
    full = path if os.path.isabs(path) else os.path.join(WS, path)
    with open(full, encoding="utf-8", errors="replace") as fh:
        src = fh.read()
    return src, ast.parse(src)


def walk_defs(tree):
    """(qualname, node, depth) for classes/functions in source order."""
    out = []

    def rec(body, prefix, depth):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = f"{prefix}{node.name}"
                out.append((q, node, depth))
                if depth < 2:
                    rec(node.body, q + ".", depth + 1)
    rec(tree.body, "", 0)
    return out


def start_line(node):
    decos = getattr(node, "decorator_list", [])
    return min([node.lineno] + [d.lineno for d in decos])


def cmd_outline(paths):
    for path in paths:
        try:
            src, tree = parse(path)
        except (OSError, SyntaxError) as exc:
            emit(f"{path}: cannot parse ({exc})")
            continue
        n = src.count("\n") + 1
        emit(f"{path} ({n} lines)")
        for q, node, depth in walk_defs(tree):
            kind = "class" if isinstance(node, ast.ClassDef) else "def"
            emit(f"  {'  ' * depth}{kind} {q.split('.')[-1]}  [{start_line(node)}-{node.end_lineno}]")


def find_symbol(symbol, paths):
    parts = symbol.split(".")
    leaf = parts[-1]
    if not paths:
        # POSIX ERE only: git grep on some platforms lacks \s and \b.
        pattern = rf"^[[:space:]]*(async[[:space:]]+)?(def|class)[[:space:]]+{leaf}([^A-Za-z0-9_]|$)"
        hits = git("grep", "-n", "-E", "--no-color", pattern, "--", "*.py").splitlines()
        paths = []
        for h in hits:
            p = h.split(":", 1)[0]
            if p not in paths:
                paths.append(p)
        paths.sort(key=lambda p: (is_test(p), len(p)))
    found = []
    for path in paths:
        try:
            src, tree = parse(path)
        except (OSError, SyntaxError):
            continue
        for q, node, _ in walk_defs(tree):
            if q == symbol or q.endswith("." + symbol) or (len(parts) == 1 and q.split(".")[-1] == leaf):
                found.append((path, q, node, src))
    return found


def cmd_show(args):
    if not args:
        emit("usage: show SYMBOL [PATH]")
        return
    symbol, paths = args[0], args[1:]
    found = find_symbol(symbol, paths)
    if not found:
        emit(f"symbol {symbol!r} not found. Try 'find {symbol}' or 'usages {symbol}'.")
        return
    if len(found) > 1:
        emit(f"{len(found)} matches: " + "; ".join(f"{p}:{start_line(n)} {q}" for p, q, n, _ in found[:8]))
    path, q, node, src = found[0]
    lines = src.splitlines()
    a, b = start_line(node), node.end_lineno
    shown_b = min(b, a + 119)
    emit(f"\n{path}  {q}  lines {a}-{b}")
    for i in range(a, shown_b + 1):
        emit(f"{i:5d}| {lines[i - 1]}")
    if shown_b < b:
        emit(f"... {b - shown_b} more lines: read_file('{path}', {shown_b + 1}, {b})")


# ----------------------------------------------------------------------------- usages / layout

def cmd_usages(args):
    if not args:
        emit("usage: usages SYMBOL")
        return
    name = args[0].split(".")[-1]
    out = git("grep", "-n", "-w", "--no-color", "-e", name, "--", "*.py").splitlines()
    src, tests = [], []
    for line in out:
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        entry = f"{parts[0]}:{parts[1]}: {parts[2].strip()[:110]}"
        (tests if is_test(parts[0]) else src).append(entry)
    emit(f"'{name}': {len(src)} source hits, {len(tests)} test hits")
    emit("SOURCE:")
    for e in src[:25]:
        emit("  " + e)
    if tests:
        emit("TESTS:")
        for e in tests[:10]:
            emit("  " + e)


def cmd_layout(_args):
    top = sorted(os.listdir(WS))
    emit("top-level: " + " ".join(t for t in top if not t.startswith(".")))
    for cfg in ("pyproject.toml", "setup.cfg", "setup.py", "tox.ini", "pytest.ini", "requirements.txt"):
        if os.path.exists(os.path.join(WS, cfg)):
            emit(f"config: {cfg}")
    files = tracked_py_files()
    pkgs = defaultdict(int)
    tdirs = defaultdict(int)
    for f in files:
        parts = f.split("/")
        (tdirs if is_test(f) else pkgs)[parts[0] if len(parts) > 1 else "."] += 1
    emit("source dirs (py files): " + ", ".join(f"{k}({v})" for k, v in sorted(pkgs.items(), key=lambda kv: -kv[1])[:8]))
    emit("test dirs (py files): " + ", ".join(f"{k}({v})" for k, v in sorted(tdirs.items(), key=lambda kv: -kv[1])[:5]))
    emit(git("log", "--oneline", "-3").strip())


COMMANDS = {"find": cmd_find, "outline": cmd_outline, "show": cmd_show, "usages": cmd_usages, "layout": cmd_layout}


def main(argv):
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv or argv[0] not in COMMANDS:
        emit(__doc__)
    else:
        try:
            COMMANDS[argv[0]](argv[1:])
        except Exception as exc:  # never crash the agent's turn on a helper bug
            emit(f"nav.py error: {type(exc).__name__}: {exc}")
    flush()


if __name__ == "__main__":
    main(sys.argv[1:])
