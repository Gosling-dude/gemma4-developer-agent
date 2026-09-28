"""Competition constants, taken from HARNESS_README.md and the Overview page.

See docs/competition_notes.md for the provenance of each value.
"""

from __future__ import annotations

ALLOWED_MODEL_NAMES = frozenset({"gemma-4-31b-it-qat-w4a16-ct"})
MODEL_PROVIDER_PREFIXES = ("openai/", "google/", "hosted_vllm/", "custom/")

ROOT_CONFIG_NAMES = ("agent.yaml", "agent.yml", "root_agent.yaml", "root_agent.yml")

HARNESS_TOOLS = frozenset({
    "run_command",
    "submit_patch",
    "get_status",
    "read_file",
    "edit_file",
    "write_file",
    "get_code_neighbors",
    "search_similar_code",
    "get_code_subgraph",
})

AGENT_CLASSES = frozenset({"LlmAgent", "SequentialAgent", "ParallelAgent", "LoopAgent"})

LLM_AGENT_KEYS = frozenset({
    "agent_class", "name", "model", "adapter", "description", "instruction",
    "global_instruction", "tools", "skills", "sub_agents", "output_key",
    "include_contents", "disallow_transfer_to_parent", "disallow_transfer_to_peers",
    "generate_content_config",
})
WORKFLOW_AGENT_KEYS = frozenset({"agent_class", "name", "description", "sub_agents", "max_iterations"})

GENERATION_ALLOWED_FIELDS = frozenset({
    "temperature", "top_p", "top_k", "max_output_tokens", "presence_penalty",
    "frequency_penalty", "stop_sequences", "response_mime_type", "seed", "thinking_config",
})
GENERATION_FORBIDDEN_FIELDS = frozenset({
    "tools", "system_instruction", "http_options", "safety_settings", "response_schema",
})
THINKING_CONFIG_FIELDS = frozenset({"thinking_budget", "thinking_level", "include_thoughts"})
THINKING_LEVELS = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH", "NONE"})
MAX_MODEL_LEN = 32_768

EVAL_CONFIG_KEYS = frozenset({"timeout_seconds", "max_tool_calls", "max_time_minutes", "max_turns"})

ALLOWED_EXTENSIONS = frozenset({".yaml", ".yml", ".md", ".txt", ".py", ".json", ".safetensors"})

MAX_TOTAL_SIZE_BYTES = 3 * 1024**3
MAX_FILE_COUNT = 10_000
MAX_YAML_SIZE_BYTES = 50 * 1024**2
MAX_SKILL_SIZE_BYTES = 50 * 1024**2
MAX_INSTRUCTION_CHARS = 1_000_000
MAX_TOTAL_INSTRUCTION_CHARS = 10_000_000
MAX_AGENTS = 500
MAX_SUB_AGENT_DEPTH = 50
MAX_INCLUDE_DEPTH = 10
MAX_LOOP_ITERATIONS = 500

# Session-state keys the harness populates (HARNESS_README §5.1). `hints` is absent when the
# task has no hints, so it must be referenced as `{hints?}`.
HARNESS_STATE_KEYS = frozenset({"problem_description"})
HARNESS_OPTIONAL_STATE_KEYS = frozenset({"hints"})

# Skill frontmatter rules (google-adk 1.36.1 skills/models.py and skills/_utils.py).
SKILL_FRONTMATTER_KEYS = frozenset({
    "name", "description", "license", "allowed-tools", "allowed_tools", "metadata", "compatibility",
})
SKILL_DESCRIPTION_MAX = 1024
SKILL_NAME_MAX = 64

# Whole-run budget (Overview: 12 h for all tasks, including sandbox setup).
RUN_BUDGET_HOURS = 12.0
EXPECTED_TEST_TASKS = 120
ASSUMED_SETUP_MINUTES_PER_TASK = 0.75  # INFERRED; not documented.
HARNESS_DEFAULT_TIME_MINUTES = 60.0
