"""Run the skill scripts the way run_skill_script does: from a temp cwd, repository at SWE_WORKSPACE."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def run(script: str, args: list[str], ws: Path, tmp_path: Path) -> str:
    env = dict(os.environ, SWE_WORKSPACE=str(ws), PYTHONPATH=str(ws))
    cwd = tmp_path / "skillcwd"
    cwd.mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, str(PROJECT / "skills" / script), *args], cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert len(r.stdout) <= 4600
    return r.stdout


def test_nav_find_ranks_definition_first(repo, tmp_path):
    out = run("repo-navigation/scripts/nav.py", ["find", "clamp", "Scaler"], repo, tmp_path)
    assert "DEFINITIONS" in out and "pkg/mathutil.py:4" in out
    top = out.split("TOP SOURCE FILES")[1].splitlines()[1]
    assert "pkg/mathutil.py" in top
    assert "tests/test_mathutil.py" in out.split("RELATED TEST FILES")[1]


def test_nav_show_and_outline(repo, tmp_path):
    out = run("repo-navigation/scripts/nav.py", ["show", "Scaler.scale"], repo, tmp_path)
    assert "return clamp(value * self.factor, 0, 100)" in out and "|" in out
    out = run("repo-navigation/scripts/nav.py", ["outline", "pkg/mathutil.py"], repo, tmp_path)
    assert "def clamp  [4-10]" in out and "class Scaler" in out


def test_nav_usages_and_bad_command(repo, tmp_path):
    out = run("repo-navigation/scripts/nav.py", ["usages", "clamp"], repo, tmp_path)
    assert "source hits" in out and "TESTS:" in out
    assert "Usage" in run("repo-navigation/scripts/nav.py", ["bogus"], repo, tmp_path)


def test_tests_related_and_run_condensed(repo, tmp_path):
    out = run("test-discovery/scripts/tests.py", ["related", "pkg/mathutil.py", "clamp"], repo, tmp_path)
    assert "tests/test_mathutil.py" in out and "test_clamp_high" in out
    out = run("test-discovery/scripts/tests.py", ["run", "tests/test_mathutil.py"], repo, tmp_path)
    assert out.startswith("exit=1") and "1 failed" in out and "test_clamp_high" in out
    assert "assert 0 == 10" in out
    out = run("test-discovery/scripts/tests.py", ["run"], repo, tmp_path)
    assert "refusing" in out


def test_diagnose_shows_repo_frames(repo, tmp_path):
    script = tmp_path / "repro.py"
    script.write_text("from pkg.mathutil import Scaler\nScaler(None).scale(3)\n")
    out = run("debugging/scripts/diagnose.py", ["run", str(script)], repo, tmp_path)
    assert "exit=1" in out and "TypeError" in out
    assert "pkg/mathutil.py:18 in scale" in out and ">>" in out


def test_review_flags_problems_then_ready(repo, tmp_path):
    (repo / "repro.py").write_text("print(1)\n")
    (repo / "tests" / "conftest.py").write_text("")
    src = repo / "pkg" / "mathutil.py"
    src.write_text(src.read_text().replace("return low  # BUG: should return high", "print('dbg')\n        return high"))
    out = run("debugging/scripts/review.py", [], repo, tmp_path)
    assert "VERDICT: FIX FIRST" in out
    assert "repro.py" in out and "conftest.py" in out and "debug code" in out
    (repo / "repro.py").unlink()
    (repo / "tests" / "conftest.py").unlink()
    src.write_text(src.read_text().replace("print('dbg')\n        ", ""))
    out = run("debugging/scripts/review.py", [], repo, tmp_path)
    assert "VERDICT: READY" in out and "return high" in out


def test_review_empty_diff(repo, tmp_path):
    out = run("debugging/scripts/review.py", [], repo, tmp_path)
    assert "EMPTY" in out and "FIX FIRST" in out


def test_workspace_found_via_pwd_like_official_subprocess_sandbox(repo, tmp_path):
    """Official subprocess sandbox: no /workspace, ADK chdirs to a temp dir; only $PWD points at the repo."""
    env = {k: v for k, v in os.environ.items() if k != "SWE_WORKSPACE"}
    env["PWD"] = str(repo)
    cwd = tmp_path / "adk_tmp"
    cwd.mkdir()
    r = subprocess.run([sys.executable, str(PROJECT / "skills/repo-navigation/scripts/nav.py"), "find", "clamp"],
                       cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    assert "pkg/mathutil.py" in r.stdout, r.stdout


def test_review_flags_whitespace_only_file(repo, tmp_path):
    src = repo / "pkg" / "mathutil.py"
    src.write_text(src.read_text().replace("return low  # BUG: should return high", "return high"))
    init = repo / "pkg" / "__init__.py"
    init.write_text(init.read_text() + "\n\n")
    out = run("debugging/scripts/review.py", [], repo, tmp_path)
    assert "pkg/__init__.py has only whitespace" in out and "FIX FIRST" in out
