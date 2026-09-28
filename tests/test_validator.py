import zipfile
from pathlib import Path

import pytest

from g4agent.loader import PathTraversalError, SubmissionError, closure, load_agent_tree, load_yaml
from g4agent.validator import validate_dir, validate_zip


def errors_of(root: Path) -> list[str]:
    return validate_dir(root).errors


def test_real_submission_is_valid(submission: Path):
    report = validate_dir(submission, compile_adk=True)
    assert report.ok, report.render()
    assert any("ADK compile OK" in i for i in report.info)


def test_include_resolves_relative_to_including_file(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.yaml").write_text("k: !include y.md\n")
    (tmp_path / "a" / "y.md").write_text("hello")
    assert load_yaml(tmp_path, tmp_path / "a" / "x.yaml").data == {"k": "hello"}


@pytest.mark.parametrize("ref", ["../outside.md", "/etc/passwd"])
def test_include_traversal_rejected(tmp_path: Path, ref: str):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.md").write_text("x")
    (root / "agent.yaml").write_text(f"instruction: !include {ref}\n")
    with pytest.raises(PathTraversalError):
        load_yaml(root, root / "agent.yaml")


def test_include_cycle_rejected(tmp_path: Path):
    (tmp_path / "a.yaml").write_text("x: !include b.yaml\n")
    (tmp_path / "b.yaml").write_text("y: !include a.yaml\n")
    with pytest.raises(SubmissionError, match="cycle"):
        load_yaml(tmp_path, tmp_path / "a.yaml")


def test_symlink_rejected(submission: Path):
    (submission / "prompts" / "link.md").symlink_to(submission / "prompts" / "system.md")
    assert any("symlink" in e for e in errors_of(submission))


def test_missing_placeholder_is_error(submission: Path):
    p = submission / "prompts" / "system.md"
    p.write_text(p.read_text() + "\nUse {repo_name} here.\n")
    assert any("repo_name" in e and "KeyError" in e for e in errors_of(submission))


def test_hints_must_be_optional(submission: Path):
    p = submission / "prompts" / "system.md"
    p.write_text(p.read_text() + "\nHints: {hints}\n")
    assert any("{hints?}" in e for e in errors_of(submission))
    p.write_text(p.read_text().replace("{hints}", "{hints?}"))
    assert errors_of(submission) == []


def test_problem_description_placeholder_ok(submission: Path):
    p = submission / "prompts" / "system.md"
    p.write_text(p.read_text() + "\nIssue: {problem_description}\n")
    assert errors_of(submission) == []


def test_wrong_model(submission: Path):
    p = submission / "agent.yaml"
    p.write_text(p.read_text().replace("gemma-4-31b-it-qat-w4a16-ct", "gemma-4-31b-it"))
    assert any("not allowed" in e for e in errors_of(submission))


def test_unknown_tool(submission: Path):
    p = submission / "agent.yaml"
    p.write_text(p.read_text().replace("  - get_status\n", "  - get_status\n  - web_search\n"))
    assert any("web_search" in e for e in errors_of(submission))


def test_skill_name_must_match_dir(submission: Path):
    md = submission / "skills" / "debugging" / "SKILL.md"
    md.write_text(md.read_text().replace("name: debugging", "name: debug-helper"))
    assert any("must equal directory name" in e for e in errors_of(submission))


def test_shell_script_in_skill_rejected(submission: Path):
    (submission / "skills" / "debugging" / "scripts" / "x.sh").write_text("echo hi\n")
    errs = errors_of(submission)
    assert any("x.sh" in e for e in errs)


def test_hidden_file_rejected(submission: Path):
    (submission / "skills" / ".DS_Store").write_text("")
    assert any(".DS_Store" in e for e in errors_of(submission))


def test_forbidden_generation_field(submission: Path):
    p = submission / "configs" / "sampling.yaml"
    p.write_text(p.read_text() + "safety_settings: []\n")
    assert any("forbidden" in e for e in errors_of(submission))


def test_eval_config_unknown_key(submission: Path):
    (submission / "eval_config.yaml").write_text("evaluation:\n  max_minutes: 3\n")
    assert any("unknown key" in e for e in errors_of(submission))


def test_default_budget_warns(submission: Path):
    (submission / "eval_config.yaml").write_text("evaluation:\n  max_time_minutes: 60\n")
    assert any("EXCEEDS" in w for w in validate_dir(submission).warnings)


def test_missing_adapter(submission: Path):
    p = submission / "agent.yaml"
    p.write_text(p.read_text() + "adapter: main_lora\n")
    assert any("adapter" in e for e in errors_of(submission))


def test_closure_is_minimal(submission: Path):
    (submission / "prompts" / "unused.md").write_text("x")
    tree = load_agent_tree(submission)
    names = {p.relative_to(submission.resolve()).as_posix() for p in closure(tree)}
    assert "prompts/unused.md" not in names
    assert {"agent.yaml", "prompts/system.md", "configs/sampling.yaml", "eval_config.yaml",
            "skills/repo-navigation/scripts/nav.py"} <= names


def test_zip_with_nested_root_rejected(tmp_path: Path, submission: Path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in submission.rglob("*"):
            if p.is_file():
                zf.write(p, "submission/" + p.relative_to(submission).as_posix())
    report = validate_zip(z)
    assert not report.ok and any("not at the archive root" in e for e in report.errors)
