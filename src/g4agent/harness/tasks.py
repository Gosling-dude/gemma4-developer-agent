"""Task records, workspace preparation and per-repo Python environments.

Two task sources are supported, both in the official `tasks.jsonl` schema (instance_id, repo,
base_commit, problem_statement, hints_text, patch, test_patch, created_at):
1. Official competition data: `<data>/tasks.jsonl` + `<data>/snapshots/<id>.tgz` (+ graphs/, embeddings/).
2. Local cases built by scripts/build_cases.py: `evaluations/cases/tasks.jsonl`. Workspaces are created
   from a cached clone with `git archive <base_commit>`.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
CACHE = PROJECT / "evaluations" / ".cache"


@dataclasses.dataclass
class Task:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    hints_text: str = ""
    patch: str = ""
    test_patch: str = ""
    created_at: str = ""
    extra: dict = dataclasses.field(default_factory=dict)

    @property
    def repo_short(self) -> str:
        return self.repo.split("/")[-1]


def load_tasks(path: Path) -> list[Task]:
    fields = {f.name for f in dataclasses.fields(Task)} - {"extra"}
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            raw = json.loads(line)
            out.append(Task(**{k: raw.get(k, "") or "" for k in fields},
                            extra={k: v for k, v in raw.items() if k not in fields}))
    return out


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def repo_cache(repo: str) -> Path:
    """A full clone of github.com/<repo>, created once (local cases only; needs network)."""
    path = CACHE / "repos" / repo.replace("/", "__")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", f"https://github.com/{repo}.git", str(path)],
                       check=True)
    return path


GIT_EXCLUDES = "__pycache__/\n*.pyc\n.pytest_cache/\n*.egg-info/\nbuild/\ndist/\n.coverage\n"


def prepare_workspace(task: Task, dest: Path, data_dir: Path | None = None) -> Path:
    """Create /workspace for a task: snapshot at base_commit, git excludes, 'baseline' commit."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    snap = data_dir / "snapshots" / f"{task.instance_id}.tgz" if data_dir else None
    if snap and snap.exists():
        with tarfile.open(snap) as tf:
            tf.extractall(dest, filter="data")
        inner = [p for p in dest.iterdir()]
        if len(inner) == 1 and inner[0].is_dir() and not (dest / ".git").exists():
            for p in inner[0].iterdir():
                shutil.move(str(p), dest)
            inner[0].rmdir()
    else:
        cache = repo_cache(task.repo)
        archive = subprocess.run(["git", "archive", task.base_commit], cwd=cache, capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)
    if not (dest / ".git").exists():
        _git(dest, "init", "-q", "-b", "main")
    _git(dest, "config", "user.email", "agent@local")
    _git(dest, "config", "user.name", "agent")
    excl = dest / ".git" / "info" / "exclude"
    excl.parent.mkdir(parents=True, exist_ok=True)
    with excl.open("a") as fh:
        fh.write(GIT_EXCLUDES)
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "baseline", "--allow-empty")
    return dest


# ---------------------------------------------------------------------- python environments

def env_dir(repo: str) -> Path:
    return CACHE / "envs" / repo.replace("/", "__")


def python_env(repo: str) -> dict[str, str]:
    """Environment variables for running a workspace's code/tests with the repo's venv."""
    venv = env_dir(repo)
    env = dict(os.environ)
    if (venv / "bin" / "python").exists():
        env["PATH"] = f"{venv / 'bin'}:{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(venv)
    env.pop("PYTHONHOME", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_PAGER"] = "cat"
    env["PAGER"] = "cat"
    return env


def workspace_env(repo: str, workspace: Path) -> dict[str, str]:
    env = python_env(repo)
    # The workspace package shadows any installed copy (the venv holds only dependencies).
    paths = [str(workspace / "src"), str(workspace)] if (workspace / "src").is_dir() else [str(workspace)]
    env["PYTHONPATH"] = os.pathsep.join(paths)
    env["SWE_WORKSPACE"] = str(workspace)
    return env
