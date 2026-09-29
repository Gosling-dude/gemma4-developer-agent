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


@pytest.mark.parametrize("variant", ["v12_analyzer", "v12_reviewer", "v12_both"])
def test_multiagent_prompts_are_root_prompt_plus_one_section(variant):
    root = (PROJECT / "prompts/system.md").read_text().rstrip("\n")
    prompt = (PROJECT / "variants" / variant / "prompts" / f"system_{variant}.md").read_text()
    assert prompt.startswith(root + "\n")
    assert prompt[len(root):].lstrip().startswith("# Specialist")


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
