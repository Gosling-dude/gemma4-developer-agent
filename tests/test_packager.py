import hashlib
import zipfile
from pathlib import Path

import pytest

from g4agent.packager import package


@pytest.mark.parametrize("variant", [None, "v0", "v1_baseline", "v1_think", "v1_nograph", "v1_noskills", "v1_oldloc", "v2"])
def test_every_variant_packages(tmp_path: Path, variant):
    out = tmp_path / "s.zip"
    assert package(variant, out, compile_adk=True) == 0
    names = zipfile.ZipFile(out).namelist()
    assert "agent.yaml" in names
    assert not any(n.startswith(("src/", "tests/", "docs/", "variants/")) for n in names)
    assert not any("__pycache__" in n or "/." in n for n in names)


@pytest.mark.parametrize("variant", [None, "v0", "v1_think", "v1_nograph", "v1_noskills", "v1_oldloc", "v2"])
def test_variant_prompts_only_reference_available_tools(tmp_path: Path, variant):
    from g4agent.validator import validate_zip
    out = tmp_path / "s.zip"
    assert package(variant, out, compile_adk=False) == 0
    warns = [w for w in validate_zip(out).warnings if "instruction mentions" in w or "instruction uses skill" in w]
    assert warns == []


def test_package_is_deterministic_and_minimal(tmp_path: Path):
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    assert package(None, a, compile_adk=False) == 0
    assert package(None, b, compile_adk=False) == 0
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
    names = set(zipfile.ZipFile(a).namelist())
    assert "sub_agents/code_analyzer.yaml" not in names          # unreferenced in V1
    assert "prompts/system_v2.md" not in names
    assert "skills/debugging/resources/failure_taxonomy.md" in names  # references/ mirrored
    assert "skills/debugging/references/failure_taxonomy.md" in names
