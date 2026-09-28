import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project() -> Path:
    return PROJECT


@pytest.fixture
def submission(tmp_path: Path) -> Path:
    """A copy of the real submission sources (root V1) that tests can mutate."""
    dest = tmp_path / "sub"
    dest.mkdir()
    for entry in ("agent.yaml", "eval_config.yaml", "configs", "prompts", "skills", "sub_agents"):
        src = PROJECT / entry
        if src.is_dir():
            shutil.copytree(src, dest / entry, ignore=shutil.ignore_patterns("__pycache__", ".*"))
        else:
            shutil.copy2(src, dest / entry)
    shutil.rmtree(dest / "sub_agents")  # unreferenced by V1
    for p in ("repository_analyzer.md", "patch_reviewer.md", "test_analyzer.md", "debugger.md", "system_v2.md"):
        (dest / "prompts" / p).unlink()
    return dest


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny git repository with a package, a bug, and tests."""
    ws = tmp_path / "workspace"
    (ws / "pkg").mkdir(parents=True)
    (ws / "tests").mkdir()
    (ws / "pkg" / "__init__.py").write_text("from .mathutil import clamp, Scaler\n")
    (ws / "pkg" / "mathutil.py").write_text(textwrap.dedent('''\
        """Math helpers."""


        def clamp(value, low, high):
            """Clamp value into [low, high]."""
            if value < low:
                return low
            if value > high:
                return low  # BUG: should return high
            return value


        class Scaler:
            def __init__(self, factor):
                self.factor = factor

            def scale(self, value):
                return clamp(value * self.factor, 0, 100)
        '''))
    (ws / "tests" / "test_mathutil.py").write_text(textwrap.dedent('''\
        from pkg.mathutil import clamp, Scaler


        def test_clamp_low():
            assert clamp(-5, 0, 10) == 0


        def test_clamp_high():
            assert clamp(50, 0, 10) == 10


        def test_scaler():
            assert Scaler(2).scale(10) == 20
        '''))
    _git(ws, "init", "-q", "-b", "main")
    _git(ws, "config", "user.email", "t@t")
    _git(ws, "config", "user.name", "t")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "baseline")
    return ws
