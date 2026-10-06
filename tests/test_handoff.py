"""Invariants of R012-v13-handoff: one change vs the R009 V1.3 build (121bd79), the read-only localizer stage.

Everything the experiment must not touch is pinned to its 121bd79 bytes, so the comparison with R012-v13-base
(archive 1e344ea7…) isolates the handoff.
"""

import hashlib

import yaml

from g4agent.loader import load_yaml
from g4agent.packager import PROJECT

V13_SHA256 = {  # git show 121bd79:<path> | shasum -a 256
    "skills/code-edit/scripts/edit.py": "13a38363c69cb514356c47a03ebff31bb10e2df63cd438a5602d65b2aead5787",
    "skills/code-edit/SKILL.md": "122c970c0ec7622e09cc16af1b9c53ba2384274cdd9d0b3eaa970dab13e4ab9d",
    "skills/repo-navigation/scripts/nav.py": "e600e8b2a91c947bea405f005cd19b39adc71eedbf8eed547a384ab23db113c2",
    "skills/repo-navigation/SKILL.md": "7d7885bd2ecaa813f8a88bc5c800f4e252d646413dd74236025c1c3cfcb997a6",
    "eval_config.yaml": "48c97a48ac1b85a7db47862f25f5b302e1fffe51ae3a3328470ae8d0d78779d5",
    "configs/sampling.yaml": "332e8adc50a3d6b71f78974c54e251ec1b4c6d7be8df6ec54321b458c06de890",
}
V13_PROMPT_SHA256 = "b2a3fa87a02787a895335110624546a6c976880c388eb7bb3e58fb2ff5a18258"
V13_TOOLS = ["run_command", "read_file", "edit_file", "write_file", "get_status", "submit_patch",
             "get_code_neighbors", "search_similar_code", "get_code_subgraph"]
V13_SKILLS = ["skills/repo-navigation", "skills/test-discovery", "skills/debugging", "skills/code-edit"]
WRITE_TOOLS = {"run_command", "edit_file", "write_file", "submit_patch"}


def _sha(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


def _cfg(rel: str) -> dict:
    return load_yaml(PROJECT, PROJECT / rel).data


def test_untouched_files_are_the_v13_bytes():
    for rel, sha in V13_SHA256.items():
        assert _sha((PROJECT / rel).read_bytes()) == sha, rel


def test_root_is_localizer_then_coder():
    root = yaml.safe_load((PROJECT / "agent.yaml").read_text())
    assert root["agent_class"] == "SequentialAgent"
    assert [s["config_path"] for s in root["sub_agents"]] == ["sub_agents/localizer.yaml", "sub_agents/coder.yaml"]


def test_coder_is_the_v13_agent():
    coder = _cfg("sub_agents/coder.yaml")
    assert coder["tools"] == V13_TOOLS and coder["skills"] == V13_SKILLS
    assert coder["generate_content_config"] == _cfg("configs/sampling.yaml")
    assert coder["include_contents"] == "none" and "output_key" not in coder


def test_localizer_is_read_only_and_short():
    loc = _cfg("sub_agents/localizer.yaml")
    assert not WRITE_TOOLS & set(loc["tools"])
    assert loc["skills"] == ["skills/repo-navigation-readonly"]  # nav.py: find/show/read/usages only (R013)
    assert loc["output_key"] == "repair_plan"
    sampling = loc["generate_content_config"]
    assert sampling["temperature"] == 0.1
    assert {k: v for k, v in sampling.items() if k != "temperature"} == \
           {k: v for k, v in _cfg("configs/sampling.yaml").items() if k != "temperature"}
    prompt = loc["instruction"]
    assert len(prompt) < 2500
    for field in ("FILE:", "SYMBOL:", "CAUSE:", "EDIT:", "CHECK:"):
        assert f"\n{field}" in prompt


def test_coder_prompt_is_v13_plus_issue_and_plan_only():
    """Undo the two R012 insertions and the V1.3 prompt comes back byte for byte."""
    text = (PROJECT / "prompts/system.md").read_text()
    issue = "\n# Issue\n{problem_description}\n\n{hints?}\n"
    start = text.index("2. START FROM THE PLAN.")
    end = text.index("most specific first:\n", start) + len("most specific first:\n")
    v13 = (text.replace(issue, "", 1)[:start - len(issue)]
           + "2. LOCATE (1–3 calls). Use the navigation script with the 2–5 most specific terms, most specific first:\n"
           + text[end:])
    assert _sha(v13.encode()) == V13_PROMPT_SHA256
    assert text.count("{repair_plan?}") == 1 and "Start from {repair_plan?}" in text
