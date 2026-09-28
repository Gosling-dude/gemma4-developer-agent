"""Phase-2 verification, following HARNESS_README section 8.2.

fresh workspace -> apply agent patch (fallback passes) -> reset protected test/config files the
patch touched -> apply test_patch -> pytest on the test files named in test_patch, with JUnit XML ->
resolved iff exit 0 and JUnit has >0 passed, 0 failures, 0 errors.

Simplification (documented): the official grader also checks named FAIL_TO_PASS / PASS_TO_PASS nodes;
the public tasks.jsonl has no such lists, so we require every collected test in those files to pass.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .tasks import Task, prepare_workspace, workspace_env

PROTECTED = re.compile(r"(^|/)(conftest\.py|pytest\.ini|\.pytest\.ini|pyproject\.toml|tox\.ini|setup\.cfg|"
                       r"sitecustomize\.py|usercustomize\.py|_swegemma_stubs\.py)$|\.pth$")


def is_protected(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    in_test_dir = bool(re.search(r"(^|/)(tests?|testing)/", path)) and path.endswith(".py")
    return bool(PROTECTED.search(path)) or name.startswith("test_") or name.endswith("_test.py") or in_test_dir


def patch_files(patch: str) -> list[str]:
    return sorted(set(re.findall(r"^diff --git a/(\S+) b/", patch, re.M)))


@dataclasses.dataclass
class VerifyResult:
    resolved: bool
    applied: bool
    apply_method: str = ""
    exit_code: int | None = None
    passed: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    reset_files: list[str] = dataclasses.field(default_factory=list)
    error: str = ""
    output_tail: str = ""


def apply_patch(ws: Path, patch: str) -> tuple[bool, str]:
    pf = ws.parent / f".{ws.name}.agent.patch"
    pf.write_text(patch if patch.endswith("\n") else patch + "\n")
    attempts = [
        ("git apply", ["git", "apply", "--unsafe-paths", str(pf)]),
        ("git apply -3", ["git", "apply", "-3", str(pf)]),
        ("git apply --ignore-whitespace", ["git", "apply", "--ignore-space-change", "--ignore-whitespace", str(pf)]),
        ("git apply --recount", ["git", "apply", "--recount", str(pf)]),
        ("git apply -p0", ["git", "apply", "-p0", str(pf)]),
        ("patch -p1", ["patch", "-p1", "--batch", "--forward", "-l", "-i", str(pf)]),
    ]
    try:
        for name, cmd in attempts:
            if subprocess.run(cmd, cwd=ws, capture_output=True).returncode == 0:
                return True, name
            subprocess.run(["git", "checkout", "-q", "--", "."], cwd=ws, capture_output=True)
        return False, ""
    finally:
        pf.unlink(missing_ok=True)


def verify(task: Task, agent_patch: str, *, data_dir: Path | None = None, timeout: int = 900,
           workdir: Path | None = None, allow_empty: bool = False) -> VerifyResult:
    """Grade `agent_patch`. `allow_empty=True` runs the tests without any fix (fail-to-pass baseline)."""
    if not agent_patch.strip() and not allow_empty:
        return VerifyResult(False, False, error="empty patch")
    with tempfile.TemporaryDirectory(dir=workdir) as td:
        ws = prepare_workspace(task, Path(td) / "workspace", data_dir)
        applied, method = apply_patch(ws, agent_patch) if agent_patch.strip() else (True, "none")
        if not applied:
            return VerifyResult(False, False, error="Failed to apply agent patch")
        test_files = patch_files(task.test_patch)
        reset = sorted(set(test_files) | {f for f in patch_files(agent_patch) if is_protected(f)})
        for f in reset:
            subprocess.run(["git", "checkout", "HEAD", "--", f], cwd=ws, capture_output=True)
            subprocess.run(["git", "clean", "-fq", "--", f], cwd=ws, capture_output=True)
        ok, _ = apply_patch(ws, task.test_patch)
        if not ok:
            return VerifyResult(False, True, method, reset_files=reset, error="test_patch failed to apply")
        targets = [f for f in test_files if f.endswith(".py") and (ws / f).exists()
                   and not f.endswith("conftest.py")]
        if not targets:
            return VerifyResult(False, True, method, reset_files=reset, error="no test targets in test_patch")
        junit = Path(td) / "junit.xml"
        env = workspace_env(task.repo, ws)
        cmd = ["python", "-s", "-m", "pytest", *targets, f"--junitxml={junit}", "-p", "no:cacheprovider",
               "-o", "python_classes=Test* *Test", "-q"]
        try:
            r = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return VerifyResult(False, True, method, reset_files=reset, error="verification timeout")
        res = VerifyResult(False, True, method, exit_code=r.returncode, reset_files=reset,
                           output_tail=(r.stdout + r.stderr)[-3000:])
        if junit.exists():
            root = ET.parse(junit).getroot()
            suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
            for s in suites:
                tests = int(s.get("tests", 0))
                res.failures += int(s.get("failures", 0))
                res.errors += int(s.get("errors", 0))
                res.skipped += int(s.get("skipped", 0))
                res.passed += tests - int(s.get("failures", 0)) - int(s.get("errors", 0)) - int(s.get("skipped", 0))
        res.resolved = r.returncode == 0 and res.passed > 0 and res.failures == 0 and res.errors == 0
        return res
