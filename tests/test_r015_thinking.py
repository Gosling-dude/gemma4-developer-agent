"""R015: R014 with Gemma thinking turned on (include_thoughts: true) in both stages; nothing else changes.

Evidence (docs/r015_research.md): adk-submission's generation resolver maps include_thoughts: false to
chat_template_kwargs.enable_thinking=false, so V1.1-R014 ran with thinking off. A controlled 129-task ablation
(discussion 746250) resolved 48 with thinking on vs 23 with it off, and every public bundle scoring >= 0.18 runs
thinking on.
"""

import hashlib
import subprocess
import sys
from pathlib import Path

import yaml

from g4agent.compiler import compile_submission
from g4agent.packager import PROJECT
from g4agent.validator import validate_dir

R014_REV = "1ab7c6e77736fb10397b166b5d7c85eaabe9ddb3"
R015_SHA256 = {
    "configs/sampling.yaml": "85f7fa32c1529cd7c17e7a136ca556e45e3cde87d1aa87ee1e9fba43b68ef103",
    "configs/localizer_sampling.yaml": "6e66f8a3a955682ddcfae9f6b5e63bfaba018e3ff929226409b3a5ce491f4169",
}


def _yaml(text: str) -> dict:
    return yaml.safe_load(text)


def _r014(rel: str) -> str:
    return subprocess.run(["git", "show", f"{R014_REV}:{rel}"], cwd=PROJECT, capture_output=True, text=True,
                          check=True).stdout


def test_sampling_files_are_pinned():
    for rel, sha in R015_SHA256.items():
        assert hashlib.sha256((PROJECT / rel).read_bytes()).hexdigest() == sha, rel


def test_only_change_vs_r014_is_thinking_on():
    for rel in R015_SHA256:
        new, old = _yaml((PROJECT / rel).read_text()), _yaml(_r014(rel))
        assert old["thinking_config"] == {"include_thoughts": False}
        assert new["thinking_config"] == {"include_thoughts": True}
        assert {k: v for k, v in new.items() if k != "thinking_config"} == \
            {k: v for k, v in old.items() if k != "thinking_config"}          # T, top_p, top_k, max tokens unchanged


def test_nothing_else_in_the_package_changed(tmp_path: Path):
    """Package R015 and R014: the archives differ only in the two sampling configs."""
    r014_src = tmp_path / "r014"
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(r014_src), R014_REV], cwd=PROJECT, check=True)
    try:
        builds = {}
        for name, src in (("r015", PROJECT), ("r014", r014_src)):
            out = tmp_path / f"{name}_build"
            r = subprocess.run([sys.executable, "-c",
                                f"import sys; sys.path.insert(0, {str(src / 'src')!r});"
                                f"from g4agent.packager import package; from pathlib import Path;"
                                f"raise SystemExit(package(None, Path({str(tmp_path / (name + '.zip'))!r}),"
                                f" compile_adk=False, keep_build=Path({str(out)!r})))"],
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stdout + r.stderr
            builds[name] = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
        assert builds["r015"].keys() == builds["r014"].keys()
        changed = sorted(k for k in builds["r015"] if builds["r015"][k] != builds["r014"][k])
        assert changed == ["configs/localizer_sampling.yaml", "configs/sampling.yaml"], changed
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(r014_src)], cwd=PROJECT, check=False)


def test_compiled_agents_request_thinking(submission: Path):
    """The ADK compile carries include_thoughts=True into both LlmAgents (the harness maps it to enable_thinking)."""
    report = validate_dir(submission, compile_adk=True)
    assert report.ok and not report.warnings, report.render()
    root = compile_submission(submission)
    agents = {a.name: a for a in root.sub_agents}
    for name in ("localizer", "swe_coder"):
        tc = agents[name].generate_content_config.thinking_config
        assert tc is not None and tc.include_thoughts is True, name
