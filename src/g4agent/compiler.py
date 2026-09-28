"""Compile a validated submission directory into a google-adk (1.36.1) agent tree.

This is our own stand-in for the harness's closed-source `compile_submission`. It builds real ADK
objects, so schema/type problems show up locally, and the local runner (harness/runner.py) uses it
to execute the exact YAML we ship.

Differences from the real harness (INFERRED, since that compiler isn't public):
- `adapter:` is recorded but ignored, because LoRA routing only exists on the vLLM server.
- Tools come from a caller-supplied factory. By default they are stubs with the documented signatures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.agents.base_agent import BaseAgent
from google.adk.code_executors.base_code_executor import BaseCodeExecutor
from google.adk.skills import load_skill_from_dir
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import types

from .loader import find_root_config, load_yaml, resolve_inside

ToolFactory = Callable[[str], Any]
ModelFactory = Callable[[str, str | None], Any]


def _stub_tools() -> dict[str, Callable[..., str]]:
    """Signature-accurate stand-ins for the 9 harness tools (used for compile checks only)."""

    def run_command(command: str) -> str:
        """Executes a shell command in /bin/bash -c inside /workspace."""
        return "{}"

    def submit_patch() -> str:
        """Stages untracked files and captures git diff HEAD from /workspace as the final patch."""
        return "{}"

    def get_status() -> str:
        """Returns live budget consumption and patch status."""
        return "{}"

    def read_file(filepath: str, start_line: int | None = None, end_line: int | None = None) -> str:
        """Reads a file from /workspace with 1-indexed inclusive line slicing."""
        return "{}"

    def edit_file(filepath: str, old_string: str, new_string: str, allow_multiple: bool = False) -> str:
        """Replaces old_string with new_string in an existing file inside /workspace."""
        return "{}"

    def write_file(filepath: str, content: str) -> str:
        """Creates or overwrites a file at /workspace/<filepath>."""
        return "{}"

    def get_code_neighbors(node: str, edge_type: str | None = None, max_neighbors: int = 50) -> str:
        """Finds incoming and outgoing neighbors of a symbol in the call/dependency graph."""
        return "{}"

    def search_similar_code(query: str, k: int = 10) -> str:
        """Finds top-k graph nodes most similar to the query symbol."""
        return "{}"

    def get_code_subgraph(nodes: list[str]) -> str:
        """Extracts the induced subgraph for a list of symbols."""
        return "{}"

    return {f.__name__: f for f in (run_command, submit_patch, get_status, read_file, edit_file,
                                    write_file, get_code_neighbors, search_similar_code, get_code_subgraph)}


def _default_tool_factory(name: str) -> Any:
    return FunctionTool(_stub_tools()[name])


def _generation_config(cfg: dict | None) -> types.GenerateContentConfig | None:
    if not cfg:
        return None
    cfg = dict(cfg)
    thinking = cfg.pop("thinking_config", None)
    if thinking:
        thinking = dict(thinking)
        if "thinking_level" in thinking:
            thinking["thinking_level"] = str(thinking["thinking_level"]).upper()
        cfg["thinking_config"] = types.ThinkingConfig(**thinking)
    return types.GenerateContentConfig(**cfg)


def compile_submission(
    root: Path,
    *,
    tool_factory: ToolFactory | None = None,
    model_factory: ModelFactory | None = None,
    code_executor: BaseCodeExecutor | None = None,
) -> BaseAgent:
    root = Path(root).resolve()
    tool_factory = tool_factory or _default_tool_factory
    root_cfg = find_root_config(root)

    def build(cfg_path: Path) -> BaseAgent:
        cfg: dict = load_yaml(root, cfg_path).data
        cls = cfg.get("agent_class", "LlmAgent")
        children = []
        for sub in cfg.get("sub_agents") or []:
            children.append(build(resolve_inside(root, cfg_path.parent, sub["config_path"])))
        if cls == "SequentialAgent":
            return SequentialAgent(name=cfg["name"], description=cfg.get("description", ""), sub_agents=children)
        if cls == "ParallelAgent":
            return ParallelAgent(name=cfg["name"], description=cfg.get("description", ""), sub_agents=children)
        if cls == "LoopAgent":
            return LoopAgent(name=cfg["name"], description=cfg.get("description", ""), sub_agents=children,
                             max_iterations=cfg.get("max_iterations", 500))

        tools: list[Any] = []
        for t in cfg.get("tools") or []:
            if isinstance(t, str):
                tools.append(tool_factory(t))
            else:
                at = t["agent_tool"]
                sub_agent = build(resolve_inside(root, cfg_path.parent, at["config_path"]))
                tools.append(AgentTool(agent=sub_agent, skip_summarization=bool(at.get("skip_summarization"))))
        skill_paths = cfg.get("skills") or []
        if skill_paths:
            skills = [load_skill_from_dir(resolve_inside(root, cfg_path.parent, s)) for s in skill_paths]
            tools.append(SkillToolset(skills=skills, code_executor=code_executor))

        model = cfg["model"]
        if model_factory is not None:
            model = model_factory(model, cfg.get("adapter"))
        kwargs: dict[str, Any] = dict(
            name=cfg["name"],
            model=model,
            description=cfg.get("description", ""),
            instruction=cfg.get("instruction", ""),
            tools=tools,
            sub_agents=children,
        )
        if cfg.get("global_instruction"):
            kwargs["global_instruction"] = cfg["global_instruction"]
        gcc = _generation_config(cfg.get("generate_content_config"))
        if gcc is not None:
            kwargs["generate_content_config"] = gcc
        for key in ("output_key", "include_contents", "disallow_transfer_to_parent", "disallow_transfer_to_peers"):
            if cfg.get(key) is not None:
                kwargs[key] = cfg[key]
        return LlmAgent(**kwargs)

    # Cycles are not tracked here; validator.load_agent_tree rejects them first.
    return build(root_cfg)
