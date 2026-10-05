"""Invariants of the V1.2 experiment variants (docs/experiments.md §E)."""

import hashlib
from pathlib import Path

import pytest

from g4agent.packager import PROJECT, package

V11_ZIP_SHA256 = "24b3fab0b3761fc52fc036bee60b3fdaf571ff58c277cd4f058b839454af0f2a"  # tag v1.1-baseline


def test_v1_1_overlay_rebuilds_the_frozen_v11_archive(tmp_path: Path):
    out = tmp_path / "v11.zip"
    assert package("v1_1", out, compile_adk=False) == 0
    assert hashlib.sha256(out.read_bytes()).hexdigest() == V11_ZIP_SHA256
    assert hashlib.sha256((PROJECT / "submission/v1.1/submission.zip").read_bytes()).hexdigest() == V11_ZIP_SHA256


V12_ZIP_SHA256 = "b446da1c591597de3e5d8befc60dace0fd2a042dd14ddab24ee4952ac0f9e9ce"  # tag v1.2-baseline, 0.08


def test_v1_2_overlay_rebuilds_the_submitted_v12_archive(tmp_path: Path):
    out = tmp_path / "v12.zip"
    assert package("v1_2", out, compile_adk=False) == 0
    assert hashlib.sha256(out.read_bytes()).hexdigest() == V12_ZIP_SHA256
    assert hashlib.sha256((PROJECT / "submission/v1.2/submission.zip").read_bytes()).hexdigest() == V12_ZIP_SHA256


@pytest.mark.parametrize("variant", ["v12_analyzer", "v12_reviewer", "v12_both"])
def test_multiagent_variants_are_v12_plus_one_section(variant):
    """V1.2 + specialist, exactly: V1.2's prompt and code-edit skill, whatever the root (V1.3) holds."""
    v12 = PROJECT / "variants/v1_2"
    base = (v12 / "prompts/system.md").read_text().rstrip("\n")
    prompt = (PROJECT / "variants" / variant / "prompts" / f"system_{variant}.md").read_text()
    assert prompt.startswith(base + "\n")
    assert prompt[len(base):].lstrip().startswith("# Specialist")
    for f in ("skills/code-edit/SKILL.md", "skills/code-edit/scripts/edit.py"):
        assert (PROJECT / "variants" / variant / f).read_bytes() == (v12 / f).read_bytes()


def _edit_step(text: str) -> str:
    return text[text.index("5. EDIT."):text.index("6. VERIFY")]


def test_v13_channel_is_v12_with_only_the_edit_step_changed():
    v12 = (PROJECT / "variants/v1_2/prompts/system.md").read_text()
    chan = (PROJECT / "variants/v13_channel/prompts/system.md").read_text()
    root = (PROJECT / "prompts/system.md").read_text()
    assert _edit_step(chan) == _edit_step(root) != _edit_step(v12)
    assert chan.replace(_edit_step(chan), "") == v12.replace(_edit_step(v12), "")
    assert {p.relative_to(PROJECT / "variants/v13_channel").as_posix()
            for p in (PROJECT / "variants/v13_channel").rglob("*") if p.is_file()} == {"prompts/system.md"}


def test_single_change_variants_differ_only_in_eval_config():
    v11 = PROJECT / "variants/v1_1"
    budget = PROJECT / "variants/v11_budget"
    files = lambda d: {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()}
    assert files(v11) == files(budget)
    changed = {f for f in files(v11) if (v11 / f).read_bytes() != (budget / f).read_bytes()}
    assert changed == {"eval_config.yaml"}
    assert (budget / "eval_config.yaml").read_text() == (PROJECT / "eval_config.yaml").read_text()
    assert files(PROJECT / "variants/v12_v11budget") == {"eval_config.yaml"}
    assert (PROJECT / "variants/v12_v11budget/eval_config.yaml").read_text() == (v11 / "eval_config.yaml").read_text()
