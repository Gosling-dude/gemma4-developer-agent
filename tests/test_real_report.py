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
