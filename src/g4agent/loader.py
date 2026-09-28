"""Sandboxed loading of a submission directory.

Mirrors the documented behaviour of the harness's `adk-submission` compiler:
- `!include <rel>` resolves relative to the directory of the file containing the tag;
  `.md`/`.txt` become strings and `.yaml`/`.yml` are parsed recursively (depth <= 10, cycles rejected).
- Absolute paths, NUL bytes, symlinks, and anything resolving outside the submission root are rejected.

`load_agent_tree` also follows `sub_agents[*].config_path` and `tools[*].agent_tool.config_path`,
so callers get every agent config plus the exact set of files the submission reaches. The
packager ships only that set.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from . import rules


class SubmissionError(Exception):
    """Raised when a submission cannot be loaded at all."""


class PathTraversalError(SubmissionError):
    pass


def resolve_inside(root: Path, base_dir: Path, rel: str) -> Path:
    """Resolve `rel` against `base_dir`, requiring the result to stay inside `root`."""
    if not isinstance(rel, str) or not rel.strip():
        raise SubmissionError(f"empty or non-string path reference: {rel!r}")
    if "\x00" in rel:
        raise PathTraversalError(f"NUL byte in path: {rel!r}")
    if PurePosixPath(rel).is_absolute() or rel.startswith("\\") or (len(rel) > 1 and rel[1] == ":"):
        raise PathTraversalError(f"absolute path not allowed: {rel!r}")
    candidate = base_dir / rel
    # Reject symlinks on every component inside the root, not just the final target.
    probe = root
    for part in candidate.relative_to(root).parts if _is_relative(candidate, root) else ():
        probe = probe / part
        if probe.is_symlink():
            raise PathTraversalError(f"symlink not allowed: {rel!r}")
    resolved = candidate.resolve()
    if not _is_relative(resolved, root.resolve()):
        raise PathTraversalError(f"path escapes submission root: {rel!r}")
    return resolved


def _is_relative(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclasses.dataclass
class _Include:
    rel: str


def _include_constructor(loader: yaml.SafeLoader, node: yaml.Node) -> _Include:
    return _Include(loader.construct_scalar(node))


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!include", _include_constructor)


@dataclasses.dataclass
class LoadedYaml:
    data: Any
    files: set[Path]
    warnings: list[str]


def load_yaml(root: Path, path: Path, *, _depth: int = 0, _stack: tuple[Path, ...] = ()) -> LoadedYaml:
    """Load a YAML file and expand `!include` tags. Returns the data plus every file touched."""
    root = root.resolve()
    path = path.resolve()
    if path in _stack:
        chain = " -> ".join(str(p.relative_to(root)) for p in (*_stack, path))
        raise SubmissionError(f"!include cycle: {chain}")
    if _depth > rules.MAX_INCLUDE_DEPTH:
        raise SubmissionError(f"!include depth exceeds {rules.MAX_INCLUDE_DEPTH} at {path}")
    if not path.is_file():
        raise SubmissionError(f"missing file: {path.relative_to(root) if _is_relative(path, root) else path}")
    if path.stat().st_size > rules.MAX_YAML_SIZE_BYTES:
        raise SubmissionError(f"YAML file too large: {path}")
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader)
    except yaml.YAMLError as exc:
        raise SubmissionError(f"invalid YAML in {path.relative_to(root)}: {exc}") from exc

    files: set[Path] = {path}
    warnings: list[str] = []

    def expand(node: Any) -> Any:
        if isinstance(node, _Include):
            if ".." in PurePosixPath(node.rel).parts:
                warnings.append(
                    f"{path.relative_to(root)}: '!include {node.rel}' uses '..'. Allowed while it stays "
                    "inside the root, but HARNESS_README lists '..' as blocked; avoid it where possible."
                )
            target = resolve_inside(root, path.parent, node.rel)
            suffix = target.suffix.lower()
            if suffix in (".md", ".txt"):
                if not target.is_file():
                    raise SubmissionError(f"{path.relative_to(root)}: !include target missing: {node.rel}")
                files.add(target)
                return target.read_text(encoding="utf-8")
            if suffix in (".yaml", ".yml"):
                sub = load_yaml(root, target, _depth=_depth + 1, _stack=(*_stack, path))
                files.update(sub.files)
                warnings.extend(sub.warnings)
                return sub.data
            raise SubmissionError(f"{path.relative_to(root)}: !include of unsupported type: {node.rel}")
        if isinstance(node, dict):
            return {k: expand(v) for k, v in node.items()}
        if isinstance(node, list):
            return [expand(v) for v in node]
        return node

    return LoadedYaml(expand(raw), files, warnings)


def find_root_config(root: Path) -> Path:
    found = [root / n for n in rules.ROOT_CONFIG_NAMES if (root / n).is_file()]
    if not found:
        raise SubmissionError(f"no root config found (expected one of {', '.join(rules.ROOT_CONFIG_NAMES)})")
    if len(found) > 1:
        raise SubmissionError(f"multiple root configs: {[p.name for p in found]}")
    return found[0]


@dataclasses.dataclass
class AgentNode:
    """One agent config in the compiled tree."""

    path: Path          # YAML file the agent was declared in
    config: dict        # fully !include-expanded config
    depth: int
    via: str            # "root", "sub_agent" or "agent_tool"


@dataclasses.dataclass
class AgentTree:
    root_dir: Path
    root_config: Path
    agents: list[AgentNode]
    files: set[Path]            # every file reachable from the root config
    skill_dirs: set[Path]
    adapter_dirs: set[Path]
    warnings: list[str]


def iter_child_refs(config: dict) -> list[tuple[str, str]]:
    """(kind, config_path) pairs for the sub-agents and agent tools declared in a config."""
    refs: list[tuple[str, str]] = []
    for sub in config.get("sub_agents") or []:
        if isinstance(sub, dict) and "config_path" in sub:
            refs.append(("sub_agent", sub["config_path"]))
    for tool in config.get("tools") or []:
        if isinstance(tool, dict) and isinstance(tool.get("agent_tool"), dict):
            cp = tool["agent_tool"].get("config_path")
            if cp:
                refs.append(("agent_tool", cp))
    return refs


def load_agent_tree(root_dir: Path) -> AgentTree:
    root_dir = root_dir.resolve()
    root_cfg = find_root_config(root_dir)
    agents: list[AgentNode] = []
    files: set[Path] = set()
    skill_dirs: set[Path] = set()
    adapter_dirs: set[Path] = set()
    warnings: list[str] = []
    seen: set[Path] = set()

    def visit(cfg_path: Path, depth: int, via: str) -> None:
        if depth > rules.MAX_SUB_AGENT_DEPTH:
            raise SubmissionError(f"sub-agent depth exceeds {rules.MAX_SUB_AGENT_DEPTH}")
        if cfg_path in seen:
            # The same YAML referenced twice would compile to duplicate agent names.
            raise SubmissionError(f"agent config referenced more than once: {cfg_path.relative_to(root_dir)}")
        seen.add(cfg_path)
        loaded = load_yaml(root_dir, cfg_path)
        files.update(loaded.files)
        warnings.extend(loaded.warnings)
        if not isinstance(loaded.data, dict):
            raise SubmissionError(f"{cfg_path.relative_to(root_dir)}: agent config must be a mapping")
        agents.append(AgentNode(cfg_path, loaded.data, depth, via))
        for skill in loaded.data.get("skills") or []:
            if isinstance(skill, str):
                skill_dirs.add(resolve_inside(root_dir, cfg_path.parent, skill))
        adapter = loaded.data.get("adapter")
        if isinstance(adapter, str) and adapter:
            adapter_dirs.add(resolve_inside(root_dir, root_dir / "adapters", adapter))
        for kind, rel in iter_child_refs(loaded.data):
            visit(resolve_inside(root_dir, cfg_path.parent, rel), depth + 1, kind)

    visit(root_cfg, 0, "root")
    return AgentTree(root_dir, root_cfg, agents, files, skill_dirs, adapter_dirs, warnings)


def closure(tree: AgentTree) -> set[Path]:
    """Every file that belongs in the packaged submission."""
    out = set(tree.files)
    for d in (*tree.skill_dirs, *tree.adapter_dirs):
        if d.is_dir():
            out.update(p for p in d.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                       and not p.name.startswith("."))
    eval_cfg = tree.root_dir / "eval_config.yaml"
    if eval_cfg.is_file():
        out.add(eval_cfg.resolve())
    return out
