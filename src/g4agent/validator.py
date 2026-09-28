"""Strict validation of a submission directory or submission.zip.

Every check corresponds to a documented harness rule (see docs/competition_notes.md) or to a
failure mode we confirmed in google-adk 1.36.1 source. Errors make the submission invalid or
crash it at runtime. Warnings are risky but legal.

Usage:
    python -m g4agent.validator <dir-or-zip> [--compile] [--json]
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from . import rules
from .loader import AgentTree, SubmissionError, load_agent_tree, load_yaml

_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Same pattern google.adk.utils.instructions_utils.inject_session_state uses.
_PLACEHOLDER = re.compile(r"{+[^{}]*}+")


@dataclasses.dataclass
class Report:
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
    info: list[str] = dataclasses.field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def render(self) -> str:
        lines = []
        for m in self.info:
            lines.append(f"  info  {m}")
        for m in self.warnings:
            lines.append(f"  WARN  {m}")
        for m in self.errors:
            lines.append(f"  ERROR {m}")
        lines.append(f"RESULT: {'VALID' if self.ok else 'INVALID'} "
                     f"({len(self.errors)} errors, {len(self.warnings)} warnings)")
        return "\n".join(lines)


# --------------------------------------------------------------------------- tree / files

def check_files(root: Path, report: Report, *, strict_tree: bool) -> None:
    """File-level checks on the directory that will be zipped."""
    total = 0
    count = 0
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            report.error(f"symlink not allowed: {rel}")
            continue
        if not p.is_file():
            continue
        count += 1
        total += p.stat().st_size
        if not strict_tree:
            continue
        if any(part.startswith(".") for part in PurePosixPath(rel).parts):
            report.error(f"hidden file not allowed in submission: {rel}")
        elif "__pycache__" in rel:
            report.error(f"bytecode cache in submission: {rel}")
        elif p.suffix.lower() not in rules.ALLOWED_EXTENSIONS:
            report.error(f"disallowed file extension: {rel} (allowed: {sorted(rules.ALLOWED_EXTENSIONS)})")
    if count > rules.MAX_FILE_COUNT:
        report.error(f"too many files: {count} > {rules.MAX_FILE_COUNT}")
    if total >= rules.MAX_TOTAL_SIZE_BYTES:
        report.error(f"unpacked size {total} bytes >= 3 GiB limit")
    report.info.append(f"{count} files, {total / 1024:.1f} KiB unpacked")


# --------------------------------------------------------------------------- agents

def _placeholders(text: str) -> list[str]:
    return _PLACEHOLDER.findall(text or "")


def check_instruction(where: str, text: Any, state_keys: set[str], report: Report) -> None:
    if text is None:
        return
    if not isinstance(text, str):
        report.error(f"{where}: instruction must be a string")
        return
    if len(text) > rules.MAX_INSTRUCTION_CHARS:
        report.error(f"{where}: instruction exceeds {rules.MAX_INSTRUCTION_CHARS} chars")
    for match in _placeholders(text):
        var = match.lstrip("{").rstrip("}").strip()
        optional = var.endswith("?")
        name = var.removesuffix("?")
        if name.startswith("artifact."):
            report.error(f"{where}: artifact placeholder {match!r} needs an artifact service; not supported")
            continue
        if not _IDENT.match(name):
            # ADK leaves non-identifier braces untouched; harmless but confusing for the model.
            report.warn(f"{where}: literal braces {match!r} in instruction (left as-is by ADK)")
            continue
        if optional:
            continue
        if name in rules.HARNESS_OPTIONAL_STATE_KEYS:
            report.error(f"{where}: {match!r} raises KeyError on tasks without hints; use '{{{name}?}}'")
        elif name not in state_keys:
            report.error(f"{where}: placeholder {match!r} is not in session state -> KeyError at runtime")


def check_generation_config(where: str, cfg: Any, report: Report) -> None:
    if cfg is None:
        return
    if not isinstance(cfg, dict):
        report.error(f"{where}: generate_content_config must be a mapping")
        return
    for key in cfg:
        if key in rules.GENERATION_FORBIDDEN_FIELDS:
            report.error(f"{where}: generate_content_config.{key} is forbidden")
        elif key not in rules.GENERATION_ALLOWED_FIELDS:
            report.error(f"{where}: unknown generate_content_config field {key!r}")
    mot = cfg.get("max_output_tokens")
    if mot is not None and not (isinstance(mot, int) and 1 <= mot <= rules.MAX_MODEL_LEN):
        report.error(f"{where}: max_output_tokens must be an int in 1..{rules.MAX_MODEL_LEN}")
    t = cfg.get("temperature")
    if t is not None and (not isinstance(t, (int, float)) or t < 0):
        report.error(f"{where}: temperature must be >= 0")
    tp = cfg.get("top_p")
    if tp is not None and (not isinstance(tp, (int, float)) or not 0 <= tp <= 1):
        report.error(f"{where}: top_p must be in [0, 1]")
    tk = cfg.get("top_k")
    if tk is not None and (not isinstance(tk, int) or tk < 1):
        report.error(f"{where}: top_k must be an int >= 1")
    tc = cfg.get("thinking_config")
    if tc is not None:
        if not isinstance(tc, dict):
            report.error(f"{where}: thinking_config must be a mapping")
            return
        for key in tc:
            if key not in rules.THINKING_CONFIG_FIELDS:
                report.error(f"{where}: unknown thinking_config field {key!r}")
        tb = tc.get("thinking_budget")
        if tb is not None and not (isinstance(tb, int) and 0 <= tb <= rules.MAX_MODEL_LEN):
            report.error(f"{where}: thinking_budget must be an int in 0..{rules.MAX_MODEL_LEN}")
        lvl = tc.get("thinking_level")
        if lvl is not None:
            if str(lvl).upper() not in rules.THINKING_LEVELS:
                report.error(f"{where}: invalid thinking_level {lvl!r}")
            report.warn(f"{where}: thinking_level maps to reasoning_effort on vLLM; HARNESS_README "
                        "recommends thinking_budget + include_thoughts instead")
        if isinstance(mot, int) and isinstance(tb, int) and tb >= mot:
            report.warn(f"{where}: thinking_budget ({tb}) >= max_output_tokens ({mot}); tool calls may be cut off")


def check_agents(tree: AgentTree, report: Report) -> None:
    root = tree.root_dir
    names: dict[str, str] = {}
    models: set[str] = set()
    state_keys = set(rules.HARNESS_STATE_KEYS)
    for node in tree.agents:
        ok = node.config.get("output_key")
        if isinstance(ok, str):
            state_keys.add(ok)
    total_instr = 0

    if len(tree.agents) > rules.MAX_AGENTS:
        report.error(f"too many agents: {len(tree.agents)}")

    for node in tree.agents:
        cfg = node.config
        where = node.path.relative_to(root).as_posix()
        cls = cfg.get("agent_class", "LlmAgent")
        if cls not in rules.AGENT_CLASSES:
            report.error(f"{where}: unsupported agent_class {cls!r}")
            continue
        allowed_keys = rules.LLM_AGENT_KEYS if cls == "LlmAgent" else rules.WORKFLOW_AGENT_KEYS
        for key in cfg:
            if key not in allowed_keys:
                report.error(f"{where}: unknown/unsupported key {key!r} for {cls}")

        name = cfg.get("name")
        if not isinstance(name, str) or not _IDENT.match(name):
            report.error(f"{where}: 'name' must be a valid identifier, got {name!r}")
        elif name in names:
            report.error(f"{where}: duplicate agent name {name!r} (also in {names[name]})")
        else:
            names[name] = where
        if name == "user":
            report.error(f"{where}: agent name 'user' is reserved by ADK")

        if cls == "LoopAgent":
            mi = cfg.get("max_iterations", 500)
            if not isinstance(mi, int) or not 1 <= mi <= rules.MAX_LOOP_ITERATIONS:
                report.error(f"{where}: max_iterations must be 1..{rules.MAX_LOOP_ITERATIONS}")
        if cls != "LlmAgent":
            if not cfg.get("sub_agents"):
                report.error(f"{where}: {cls} needs sub_agents")
            continue

        model = cfg.get("model")
        if not isinstance(model, str) or not model:
            report.error(f"{where}: LlmAgent requires 'model'")
        else:
            norm = model
            for prefix in rules.MODEL_PROVIDER_PREFIXES:
                norm = norm.removeprefix(prefix)
            models.add(norm)
            if norm not in rules.ALLOWED_MODEL_NAMES:
                report.error(f"{where}: model {model!r} not allowed (only {sorted(rules.ALLOWED_MODEL_NAMES)})")

        instr = cfg.get("instruction")
        check_instruction(where, instr, state_keys, report)
        check_instruction(f"{where} (global_instruction)", cfg.get("global_instruction"), state_keys, report)
        total_instr += len(instr or "") if isinstance(instr, str) else 0
        if node.via != "root" and not cfg.get("description"):
            report.warn(f"{where}: sub-agent without description; the parent cannot tell when to use it")
        desc = cfg.get("description")
        if desc is not None and (not isinstance(desc, str) or len(desc) > rules.MAX_INSTRUCTION_CHARS):
            report.error(f"{where}: description must be a string <= 1M chars")

        ic = cfg.get("include_contents")
        if ic is not None and ic not in ("default", "none"):
            report.error(f"{where}: include_contents must be 'default' or 'none'")

        check_generation_config(where, cfg.get("generate_content_config"), report)

        tools = cfg.get("tools") or []
        if not isinstance(tools, list):
            report.error(f"{where}: tools must be a list")
            tools = []
        tool_names = []
        for t in tools:
            if isinstance(t, str):
                if t not in rules.HARNESS_TOOLS:
                    report.error(f"{where}: tool {t!r} is not provided by the harness")
                elif t in tool_names:
                    report.error(f"{where}: tool {t!r} listed twice")
                tool_names.append(t)
            elif isinstance(t, dict) and set(t) == {"agent_tool"} and isinstance(t["agent_tool"], dict):
                extra = set(t["agent_tool"]) - {"config_path", "skip_summarization"}
                if extra:
                    report.error(f"{where}: unsupported agent_tool keys {sorted(extra)}")
                if "config_path" not in t["agent_tool"]:
                    report.error(f"{where}: agent_tool requires config_path (inline agents are not validated here)")
            elif isinstance(t, dict) and "name" in t and "agent_tool" not in t:
                report.warn(f"{where}: inline agent tool dict is not checked by this validator")
            else:
                report.error(f"{where}: unsupported tool entry {t!r}")

        if isinstance(instr, str):
            for t in sorted(rules.HARNESS_TOOLS):
                if re.search(rf"\b{t}\b", instr) and t not in tool_names:
                    report.warn(f"{where}: instruction mentions tool {t!r} but the agent does not have it")
            if "run_skill_script" in instr and not cfg.get("skills"):
                report.warn(f"{where}: instruction mentions run_skill_script but the agent declares no skills")
            for sk in re.findall(r'skill_name="([a-z0-9-]+)"', instr):
                if not any(str(x).rstrip("/").endswith("/" + sk) or str(x) == sk for x in cfg.get("skills") or []):
                    report.warn(f"{where}: instruction uses skill {sk!r} which this agent does not declare")

        if node.via == "root":
            if "submit_patch" not in tool_names:
                report.warn(f"{where}: root agent lacks submit_patch (harness falls back to git diff)")
            if "edit_file" not in tool_names and "write_file" not in tool_names and "run_command" not in tool_names:
                report.error(f"{where}: root agent has no way to modify files")
        elif node.via == "agent_tool" and "submit_patch" in tool_names:
            report.warn(f"{where}: agent_tool with submit_patch can end the session from inside a sub-call")

        for s in cfg.get("skills") or []:
            if not isinstance(s, str):
                report.error(f"{where}: skills entries must be relative paths")
        for sub in cfg.get("sub_agents") or []:
            if not (isinstance(sub, dict) and "config_path" in sub):
                report.error(f"{where}: sub_agents entries must be {{config_path: ...}}")

        adapter = cfg.get("adapter")
        if adapter is not None:
            check_adapter(root, where, adapter, report)

    if len(models) > 1:
        report.error(f"multiple base models declared: {sorted(models)} (single-model rule)")
    if total_instr > rules.MAX_TOTAL_INSTRUCTION_CHARS:
        report.error("total instruction size exceeds 10M chars")
    report.info.append(f"{len(tree.agents)} agent(s): {', '.join(sorted(names))}")


def check_adapter(root: Path, where: str, adapter: Any, report: Report) -> None:
    if not isinstance(adapter, str) or not _IDENT.match(adapter.replace("-", "_")):
        report.error(f"{where}: invalid adapter name {adapter!r}")
        return
    adir = root / "adapters" / adapter
    if not adir.is_dir():
        report.error(f"{where}: adapter {adapter!r} not found at adapters/{adapter}/")
        return
    cfg = adir / "adapter_config.json"
    weights = adir / "adapter_model.safetensors"
    if not cfg.is_file():
        report.error(f"adapters/{adapter}: missing adapter_config.json")
    if not weights.is_file() or weights.stat().st_size < 1024:
        report.error(f"adapters/{adapter}: missing or placeholder adapter_model.safetensors")
    for p in adir.rglob("*"):
        if p.is_file() and p.suffix in (".bin", ".pt", ".pth", ".pkl"):
            report.error(f"adapters/{adapter}: pickle-based weights not allowed: {p.name}")
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text())
            r = int(data.get("r", 0))
            if r > 128:
                report.error(f"adapters/{adapter}: rank {r} > max_lora_rank 128")
            if data.get("peft_type", "LORA") != "LORA":
                report.error(f"adapters/{adapter}: peft_type must be LORA")
        except (ValueError, TypeError) as exc:
            report.error(f"adapters/{adapter}: bad adapter_config.json: {exc}")


# --------------------------------------------------------------------------- skills

def check_skill(root: Path, skill_dir: Path, report: Report) -> None:
    rel = skill_dir.relative_to(root).as_posix()
    if not skill_dir.is_dir():
        report.error(f"skill directory missing: {rel}")
        return
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        report.error(f"{rel}: SKILL.md missing")
        return
    text = md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        report.error(f"{rel}/SKILL.md: must start with YAML frontmatter '---'")
        return
    parts = text.split("---", 2)
    if len(parts) < 3:
        report.error(f"{rel}/SKILL.md: frontmatter not closed with '---'")
        return
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        report.error(f"{rel}/SKILL.md: invalid frontmatter YAML: {exc}")
        return
    if not isinstance(fm, dict):
        report.error(f"{rel}/SKILL.md: frontmatter must be a mapping")
        return
    for key in fm:
        if key not in rules.SKILL_FRONTMATTER_KEYS:
            report.error(f"{rel}/SKILL.md: unsupported frontmatter key {key!r}")
    name = fm.get("name")
    if not isinstance(name, str) or not _KEBAB.match(name) or len(name) > rules.SKILL_NAME_MAX:
        report.error(f"{rel}/SKILL.md: name must be kebab-case <= 64 chars, got {name!r}")
    if name != skill_dir.name:
        report.error(f"{rel}/SKILL.md: name {name!r} must equal directory name {skill_dir.name!r} (ADK)")
    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        report.error(f"{rel}/SKILL.md: description required")
    elif len(desc) > rules.SKILL_DESCRIPTION_MAX:
        report.error(f"{rel}/SKILL.md: description > {rules.SKILL_DESCRIPTION_MAX} chars")
    size = 0
    for p in skill_dir.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        size += p.stat().st_size
        sub = p.relative_to(skill_dir).as_posix()
        top = sub.split("/", 1)[0]
        if sub != "SKILL.md" and top not in ("scripts", "references", "assets", "resources"):
            report.warn(f"{rel}/{sub}: outside scripts/references/assets/resources; ADK will not load it")
        if top == "scripts" and p.suffix != ".py":
            report.error(f"{rel}/{sub}: skill scripts must be .py (.sh is not an allowed extension)")
        if p.suffix == ".py":
            check_script(f"{rel}/{sub}", p, report)
    if size > rules.MAX_SKILL_SIZE_BYTES:
        report.error(f"{rel}: skill larger than 50 MiB")


_NETWORK_MODULES = {"socket", "requests", "urllib.request", "http.client", "httpx", "aiohttp"}


def check_script(where: str, path: Path, report: Report) -> None:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        report.error(f"{where}: syntax error: {exc}")
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [node.module or ""]
        else:
            continue
        for m in mods:
            if m in _NETWORK_MODULES:
                report.warn(f"{where}: imports {m}; the sandbox has no network")
    if "/workspace" not in src and "SWE_WORKSPACE" not in src:
        report.warn(f"{where}: script never references /workspace; run_skill_script runs in a temp dir")


# --------------------------------------------------------------------------- eval config

def check_eval_config(root: Path, report: Report) -> None:
    path = root / "eval_config.yaml"
    if not path.is_file():
        report.warn("no eval_config.yaml: harness defaults (60 min/task) exceed the 12 h run budget "
                    "if tasks run sequentially")
        return
    try:
        data = load_yaml(root, path).data
    except SubmissionError as exc:
        report.error(f"eval_config.yaml: {exc}")
        return
    if not isinstance(data, dict) or not isinstance(data.get("evaluation"), dict):
        report.error("eval_config.yaml: must contain an 'evaluation:' mapping")
        return
    ev = data["evaluation"]
    for key, val in ev.items():
        if key not in rules.EVAL_CONFIG_KEYS:
            report.error(f"eval_config.yaml: unknown key evaluation.{key}")
        elif not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
            report.error(f"eval_config.yaml: evaluation.{key} must be a positive number")
    minutes = ev.get("max_time_minutes", rules.HARNESS_DEFAULT_TIME_MINUTES)
    if isinstance(minutes, (int, float)):
        projected = rules.EXPECTED_TEST_TASKS * (minutes + rules.ASSUMED_SETUP_MINUTES_PER_TASK) / 60
        msg = (f"worst-case sequential run: {rules.EXPECTED_TEST_TASKS} tasks x "
               f"({minutes} + ~{rules.ASSUMED_SETUP_MINUTES_PER_TASK} setup) min = {projected:.1f} h "
               f"of {rules.RUN_BUDGET_HOURS:.0f} h")
        if projected > rules.RUN_BUDGET_HOURS:
            report.warn(msg + " -> EXCEEDS the run budget if tasks run sequentially")
        else:
            report.info.append(msg)
    ts = ev.get("timeout_seconds")
    if isinstance(ts, (int, float)) and ts < 300:
        report.warn(f"eval_config.yaml: timeout_seconds={ts} < 300 also caps the hidden-test pytest run in grading "
                    "(swegemma harness/verification.py); slow test files would fail correct patches")


# --------------------------------------------------------------------------- optional ADK compile

def check_compile(root: Path, report: Report) -> None:
    try:
        from .compiler import compile_submission
    except ImportError as exc:  # pragma: no cover - depends on optional deps
        report.warn(f"ADK compile check skipped: {exc}")
        return
    try:
        agent = compile_submission(root)
        report.info.append(f"ADK compile OK: root agent {agent.name!r} "
                           f"({type(agent).__name__}, {len(getattr(agent, 'tools', []) or [])} tool entries)")
    except Exception as exc:  # noqa: BLE001 - we report whatever ADK raises
        report.error(f"ADK compile failed: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- entry points

def validate_dir(root: Path, *, strict_tree: bool = True, compile_adk: bool = False) -> Report:
    report = Report()
    root = root.resolve()
    check_files(root, report, strict_tree=strict_tree)
    try:
        tree = load_agent_tree(root)
    except SubmissionError as exc:
        report.error(str(exc))
        return report
    for w in tree.warnings:
        report.warn(w)
    check_agents(tree, report)
    for skill_dir in sorted(tree.skill_dirs):
        check_skill(root, skill_dir, report)
    check_eval_config(root, report)
    if strict_tree:
        from .loader import closure
        reachable = closure(tree)
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.resolve() not in reachable:
                report.warn(f"unreferenced file shipped: {p.relative_to(root).as_posix()}")
    if compile_adk and report.ok:
        check_compile(root, report)
    return report


def validate_zip(zip_path: Path, *, compile_adk: bool = False) -> Report:
    report = Report()
    if not zip_path.is_file():
        report.error(f"archive not found: {zip_path}")
        return report
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        bad = zf.testzip()
        if bad:
            report.error(f"corrupt archive member: {bad}")
        for n in names:
            pp = PurePosixPath(n)
            if pp.is_absolute() or ".." in pp.parts or "\\" in n:
                report.error(f"unsafe archive member path: {n}")
        for info in zf.infolist():
            # Unix mode 0o120000 marks a symlink.
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                report.error(f"symlink inside archive: {info.filename}")
        roots = [n for n in names if n in rules.ROOT_CONFIG_NAMES]
        if not roots:
            nested = [n for n in names if PurePosixPath(n).name in rules.ROOT_CONFIG_NAMES]
            hint = f" (found nested: {nested}; zip the *contents* of the folder)" if nested else ""
            report.error("agent.yaml is not at the archive root" + hint)
        if report.errors:
            return report
        with tempfile.TemporaryDirectory() as td:
            zf.extractall(td)
            inner = validate_dir(Path(td), strict_tree=True, compile_adk=compile_adk)
    report.errors += inner.errors
    report.warnings += inner.warnings
    report.info += inner.info
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path, help="submission directory or submission.zip")
    ap.add_argument("--compile", action="store_true", help="also build the agent tree with google-adk")
    ap.add_argument("--source", action="store_true",
                    help="target is the project source tree (skip file-extension checks on unrelated files)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.target.suffix == ".zip":
        report = validate_zip(args.target, compile_adk=args.compile)
    else:
        report = validate_dir(args.target, strict_tree=not args.source, compile_adk=args.compile)
    if args.json:
        print(json.dumps(dataclasses.asdict(report), indent=2))
    else:
        print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
