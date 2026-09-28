"""Build SWE-style evaluation cases from merged GitHub PRs (local stand-in for the official dev set).

The pipeline mirrors the official curation described on the Data page:
1. Mine merged PRs that change both library code and tests (small diffs, no docs-only changes).
2. Problem statement = the linked issue's title and body (fallback: PR title and body), with the PR's
   code discussion removed so the fix isn't leaked.
3. patch = non-test code changes; test_patch = test changes (base = first parent of the merge commit).
4. Execution check: tests must FAIL with only test_patch applied and PASS with patch + test_patch.
   Only cases passing both checks are kept.

Usage: python -m g4agent.cases --repo Textualize/rich --max-cases 12 --out evaluations/cases/tasks.jsonl
Requires network + an authenticated `gh` CLI (read-only API calls).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from pathlib import Path

from .harness.tasks import Task, repo_cache
from .harness.verify import is_protected, verify

DOC_FILES = re.compile(r"(^|/)(CHANGELOG|CHANGES|HISTORY|README|AUTHORS|CONTRIBUTORS)[^/]*$|^docs?/|\.(md|rst|txt)$", re.I)


def gh_json(args: list[str]) -> object:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def split_diff(diff: str) -> tuple[str, str]:
    """Split a unified diff into (code_patch, test_patch), dropping docs/changelog files."""
    chunks = re.split(r"(?m)^(?=diff --git )", diff)
    code, tests = [], []
    for ch in chunks:
        m = re.match(r"diff --git a/(\S+) b/", ch)
        if not m:
            continue
        path = m.group(1)
        if DOC_FILES.search(path):
            continue
        (tests if is_protected(path) else code).append(ch)
    return "".join(code), "".join(tests)


def candidate_prs(repo: str, limit: int) -> list[dict]:
    prs = gh_json(["pr", "list", "-R", repo, "--state", "merged", "--limit", str(limit), "--json",
                   "number,title,body,mergeCommit,files,closingIssuesReferences,mergedAt"])
    out = []
    for pr in prs:
        files = [f["path"] for f in pr["files"]]
        src = [f for f in files if f.endswith(".py") and not is_protected(f) and not DOC_FILES.search(f)]
        tst = [f for f in files if f.endswith(".py") and is_protected(f)]
        churn = sum(f["additions"] + f["deletions"] for f in pr["files"] if f["path"] in src)
        if src and tst and len(src) <= 3 and churn <= 120 and pr.get("mergeCommit"):
            out.append(pr)
    return out


def problem_statement(repo: str, pr: dict) -> str:
    issues = pr.get("closingIssuesReferences") or []
    if not issues:
        m = re.search(r"(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)", pr.get("body") or "", re.I)
        issues = [{"number": int(m.group(1))}] if m else []
    for ref in issues[:1]:
        try:
            issue = gh_json(["issue", "view", str(ref["number"]), "-R", repo, "--json", "title,body"])
            return f"{issue['title']}\n\n{(issue['body'] or '').strip()}"[:6000]
        except subprocess.CalledProcessError:
            pass
    return ""  # PR-only descriptions often describe the fix itself; skip those cases


def build(repo: str, max_cases: int, scan: int, out: Path, workdir: Path | None) -> list[Task]:
    cache = repo_cache(repo)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=cache, check=False)
    existing = {}
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                t = json.loads(line)
                existing[t["instance_id"]] = t
    kept: list[Task] = []
    short = repo.split("/")[-1]
    for pr in candidate_prs(repo, scan):
        if len(kept) >= max_cases:
            break
        iid = f"{short}_{pr['number']}"
        if iid in existing:
            kept.append(Task(**{k: existing[iid].get(k, "") for k in
                                ("instance_id", "repo", "base_commit", "problem_statement", "hints_text",
                                 "patch", "test_patch", "created_at")}))
            continue
        merge = pr["mergeCommit"]["oid"]
        base = subprocess.run(["git", "rev-parse", f"{merge}^1"], cwd=cache, capture_output=True, text=True)
        if base.returncode != 0:
            continue
        base_sha = base.stdout.strip()
        diff = subprocess.run(["git", "diff", "--binary", base_sha, merge], cwd=cache, capture_output=True,
                              text=True).stdout
        code, tests = split_diff(diff)
        if not code or not tests:
            continue
        statement = problem_statement(repo, pr)
        if len(statement) < 80:
            print(f"  skip {iid}: no linked issue text", file=sys.stderr)
            continue
        task = Task(iid, repo, base_sha, statement, "", code, tests, pr.get("mergedAt", ""))
        fail = verify(task, "", allow_empty=True, workdir=workdir, timeout=300)
        if fail.resolved or fail.passed + fail.failures + fail.errors == 0:
            print(f"  skip {iid}: tests do not fail without the fix ({fail.error or 'passed'})", file=sys.stderr)
            continue
        good = verify(task, code, workdir=workdir, timeout=300)
        if not good.resolved:
            print(f"  skip {iid}: reference fix does not pass ({good.error or f'{good.failures}F/{good.errors}E'})",
                  file=sys.stderr)
            continue
        print(f"  keep {iid}: F2P verified ({fail.failures}F/{fail.errors}E -> {good.passed} passed)", file=sys.stderr)
        kept.append(task)
    out.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(existing)
    for t in kept:
        merged[t.instance_id] = {k: v for k, v in dataclasses.asdict(t).items() if k != "extra"}
    out.write_text("".join(json.dumps(v) + "\n" for v in merged.values()))
    return kept


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--max-cases", type=int, default=10)
    ap.add_argument("--scan", type=int, default=300, help="how many recent merged PRs to scan")
    ap.add_argument("--out", type=Path, default=Path("evaluations/cases/tasks.jsonl"))
    args = ap.parse_args(argv)
    kept = build(args.repo, args.max_cases, args.scan, args.out, None)
    print(f"{len(kept)} verified cases for {args.repo} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
