"""g4agent.real_report on a synthetic directory shaped like the Kaggle notebook's output (no real results)."""

import json
from pathlib import Path

from g4agent.real_report import main

PATCH = "diff --git a/rich/text.py b/rich/text.py\n--- a/rich/text.py\n+++ b/rich/text.py\n@@ -1 +1 @@\n-a\n+b\n"


def _call(name, **args):
    return {"function_name": name, "arguments": args, "extra": {"usage": {"prompt_tokens": 100, "completion_tokens": 10}}}


def test_report_from_kaggle_layout(tmp_path: Path):
    root = tmp_path / "g4_results"
    (root / "v1" / "traces").mkdir(parents=True)
    trace = {"steps": [{"tool_calls": [_call("read_file", filepath="/workspace/rich/text.py"),
                                       _call("run_command", command="python -m pytest tests/test_text.py -q"),
                                       _call("edit_file", filepath="rich/text.py")]}]}
    (root / "v1" / "traces" / "a.json").write_text(json.dumps(trace))
    rows = [
        {"variant": "v1", "instance_id": "rich_1", "repo": "Textualize/rich", "resolved": True, "patch": PATCH,
         "patch_chars": len(PATCH), "tool_calls": 3, "llm_calls": 4, "total_tokens": 330, "status": "SUCCESS",
         "duration_s": 100.0, "error": None, "trace": "/kaggle/working/g4_results/v1/traces/a.json"},
        {"variant": "v1", "instance_id": "rich_2", "repo": "Textualize/rich", "resolved": False, "patch": "",
         "patch_chars": 0, "tool_calls": 60, "duration_s": 300.2, "error": "time limit reached", "trace": ""},
        {"variant": "v1", "instance_id": "rich_3", "repo": "Textualize/rich", "resolved": False, "patch": PATCH,
         "patch_chars": len(PATCH), "tool_calls": 20, "duration_s": 150.0, "error": None, "trace": ""},
    ]
    (root / "v1_task_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (root / "summary.json").write_text(json.dumps({"model": "gemma-4-31b-it-qat-w4a16-ct"}))
    assert main([str(tmp_path)]) == 0
    rep = json.loads((tmp_path / "report.json").read_text())
    a, b, c = rep["tasks"]
    assert (rep["resolved"], rep["n"], rep["mean_runtime_s"]) == (1, 3, 183.4)
    assert a["result"] == "PASS" and a["failure_category"] is None and a["trace_found"]
    assert a["files_inspected"] == ["rich/text.py", "tests/test_text.py"] and a["files_edited"] == ["rich/text.py"]
    assert a["tests_run"] == ["python -m pytest tests/test_text.py -q"] and a["prompt_tokens"] == 300
    assert b["failure_category"].startswith("cap_hit") and b["patch_status"] == "empty"
    assert c["failure_category"] == "wrong_fix (hidden tests fail)" and c["tests_run"] is None


REF = ("diff --git a/rich/text.py b/rich/text.py\n--- a/rich/text.py\n+++ b/rich/text.py\n"
       "@@ -10,2 +10,2 @@ class Text:\n     def split(self):\n-        a\n+        b\n")
SAME_FUNC = REF.replace("+        b", "+        c")
OTHER_FUNC = REF.replace("@@ -10,2 +10,2 @@ class Text:\n     def split(self):", "@@ -90,2 +90,2 @@ def render(self):\n     x = 1")
OTHER_FILE = REF.replace("rich/text.py", "rich/console.py")


def test_location_classes_caps_and_pairs(tmp_path: Path):
    root = tmp_path / "g4_results"
    (root / "traces").mkdir(parents=True)
    obs_fail = '{"result": "{\\"status\\": \\"error\\", \\"error_message\\": \\"Failed to replace: old_string not found.\\"}"}'
    trace = {"steps": [
        {"tool_calls": [{**_call("edit_file", filepath="rich/text.py"), "extra": {"timestamp": 100.0}}],
         "observation": {"content": obs_fail}},
        {"tool_calls": [{**_call("run_skill_script", skill_name="code-edit", file_path="scripts/edit.py", args=[]),
                         "extra": {"timestamp": 104.0}}],
         "observation": {"content": '{"stdout": "EDITED rich/text.py (unescaped x1 match)."}'}}]}
    (root / "traces" / "t.json").write_text(json.dumps(trace))
    base = {"repo": "Textualize/rich", "tool_calls": 5, "duration_s": 60.0}
    rows = [
        {**base, "variant": "v12", "instance_id": "t1", "resolved": True, "patch": SAME_FUNC, "error": None,
         "trace": str(root / "traces" / "t.json")},
        {**base, "variant": "v12", "instance_id": "t2", "resolved": False, "patch": OTHER_FUNC,
         "error": "Agent exceeded tool call budget (80 calls)"},
        {**base, "variant": "v11", "instance_id": "t1", "resolved": False, "patch": OTHER_FILE,
         "error": "Sandbox execution error: ContextWindowExceededError"},
        {**base, "variant": "v11", "instance_id": "t2", "resolved": False, "patch": "",
         "error": "Agent exceeded turns budget (80 turns)"},
    ]
    (root / "x_task_results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text("".join(json.dumps({"instance_id": i, "patch": REF}) + "\n" for i in ("t1", "t2")))
    assert main([str(tmp_path), "--tasks", str(tasks), "--cap-minutes", "5.5"]) == 0
    rep = json.loads((tmp_path / "report.json").read_text())
    t = {(x["variant"], x["task_id"]): x for x in rep["tasks"]}
    assert t["v12", "t1"]["location"] == "gold_function"
    assert t["v12", "t1"]["edit_file_not_found"] == 1 and t["v12", "t1"]["code_edit_ok"] == 1
    assert t["v12", "t1"]["first_edit_call"] == 2 and t["v12", "t1"]["first_edit_s"] == 4.0
    assert t["v12", "t2"]["location"] == "gold_file" and t["v12", "t2"]["failure_category"] == "cap_hit: tool calls"
    assert t["v11", "t1"]["location"] == "wrong_file"
    assert t["v11", "t1"]["failure_category"] == "harness_exception (patch discarded)"
    assert t["v11", "t2"]["location"] == "no_patch" and t["v11", "t2"]["failure_category"] == "cap_hit: turns, no patch"
    assert rep["variants"]["v12"]["resolved"] == 1 and rep["variants"]["v12"]["code_edit_ok"] == 1
    (pair,) = rep["paired"]
    assert (pair["a"], pair["b"], pair["tasks"], pair["both"], pair["only_a"], pair["only_b"]) == \
        ("v11", "v12", 2, 0, [], ["t1"])
