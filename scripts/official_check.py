"""Validate and compile a submission with the OFFICIAL harness libraries (adk-submission / swegemma).

Runs in the isolated venv created by scripts/setup_official_harness.sh (the wheels come from the
organizers' public dataset `metric/gemma-4-developer-agent-wheelhouse`). It uses the same calls the
scorer's agent_runner makes: validate_directory, discover_adapters, discover_declared_models,
compile_submission, with swegemma's limits, generation constraints, tool set and model registry.
It does NOT start a model server; compiling needs none.

Usage: evaluations/.cache/official_venv/bin/python scripts/official_check.py <submission dir or .zip>
"""

from __future__ import annotations

import sys
import tempfile
import types
import zipfile
from pathlib import Path

ALLOWED_MODELS = {"gemma-4-31b-it-qat-w4a16-ct"}


def check(sub: Path) -> int:
    from adk_submission import compile_submission
    from adk_submission.discovery import discover_adapters, discover_declared_models, validate_directory
    from adk_eval_core.sandbox.base import AdkSandboxCodeExecutor
    from swegemma.config import build_submission_limits
    from swegemma.models.registry import resolve_swegemma_adapter, setup_gemma_model_registry
    from swegemma.tools import create_tools

    limits, gen = build_submission_limits()
    validate_directory(sub, limits)
    print("official validate_directory: OK")

    models = discover_declared_models(sub)
    names = {str(m).split("/", 1)[-1] if str(m).startswith(("openai/", "hosted_vllm/", "custom/", "google/")) else str(m)
             for m in (models if isinstance(models, (set, list, tuple)) else [models])}
    print(f"declared models: {sorted(names)}")
    if len(names) != 1 or not names <= ALLOWED_MODELS:
        print("ERROR: must declare exactly one model: gemma-4-31b-it-qat-w4a16-ct")
        return 1

    manifest = discover_adapters(sub, limits) if _takes_limits(discover_adapters) else discover_adapters(sub)
    print(f"adapters: {getattr(manifest, 'names', None) or getattr(manifest, 'adapters', None) or 'none'}")

    registry = setup_gemma_model_registry(api_base="http://127.0.0.1:9/v1", adapter_manifest=manifest)
    ctx = types.SimpleNamespace()  # tools are bound lazily; compiling only needs their signatures
    tools = create_tools(ctx)
    executor = AdkSandboxCodeExecutor(sandbox=None, timeout_seconds=120)
    agent = compile_submission(
        submission_dir=sub, tool_registry=tools, model_registry=registry, code_executor=executor,
        script_timeout=120, limits=limits, generation_constraints=gen, adapter_manifest=manifest,
        adapter_resolver_fn=lambda base, info: resolve_swegemma_adapter(base, info, registry),
    )
    print(f"official compile_submission: OK -> root {type(agent).__name__} {agent.name!r}")
    tool_names = []
    for t in getattr(agent, "tools", []) or []:
        tool_names.append(getattr(t, "name", None) or getattr(t, "__name__", None) or type(t).__name__)
    print(f"root tools: {tool_names}")
    for sub_agent in getattr(agent, "sub_agents", []) or []:
        print(f"sub-agent: {sub_agent.name}")
    gcc = getattr(agent, "generate_content_config", None)
    if gcc is not None:
        print(f"generate_content_config: {gcc.model_dump(exclude_none=True)}")
    return 0


def _takes_limits(fn) -> bool:
    import inspect
    return len(inspect.signature(fn).parameters) > 1


def main(argv: list[str]) -> int:
    target = Path(argv[0]).resolve()
    if target.suffix == ".zip":
        with tempfile.TemporaryDirectory() as td:
            zipfile.ZipFile(target).extractall(td)
            return check(Path(td))
    return check(target)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
