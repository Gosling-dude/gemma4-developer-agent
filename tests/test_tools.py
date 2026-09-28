import json
from pathlib import Path

from g4agent.harness.graph import build_from_repo
from g4agent.harness.tools import Budget, LocalHarness, apply_replacement


def make(repo: Path, tmp_path: Path, **budget) -> dict:
    h = LocalHarness(repo, tmp_path / "tmp", Budget(**budget), build_from_repo(repo))
    h.start()
    return h, h.tool_functions()


def test_read_file_slicing_and_prefix(repo, tmp_path):
    _, t = make(repo, tmp_path)
    r = json.loads(t["read_file"]("/workspace/pkg/mathutil.py", 4, 6))
    assert r["status"] == "ok" and r["start_line"] == 4 and r["end_line"] == 6
    assert r["content"].startswith("def clamp")
    assert json.loads(t["read_file"]("../etc/passwd"))["status"] == "error"


def test_read_file_caps_at_150_lines(tmp_path, repo):
    (repo / "big.py").write_text("x = 1\n" * 400)
    _, t = make(repo, tmp_path)
    r = json.loads(t["read_file"]("big.py"))
    assert r["end_line"] == 150 and r["is_truncated"] and r["total_lines"] == 400


def test_edit_file_exact_and_ambiguous(repo, tmp_path):
    _, t = make(repo, tmp_path)
    r = json.loads(t["edit_file"]("pkg/mathutil.py", "return low  # BUG: should return high", "return high"))
    assert r["status"] == "ok" and r["strategy"] == "exact"
    r = json.loads(t["edit_file"]("pkg/mathutil.py", "return low", "return LOW"))
    assert r["status"] == "ok"  # now unique again
    r = json.loads(t["edit_file"]("pkg/mathutil.py", "return", "yield"))
    assert r["status"] == "error" and "matches" in r["error_message"]


def test_edit_file_flexible_reindents():
    text = "def f():\n    if x:\n        return 1\n"
    new, n, strategy = apply_replacement(text, "if x:\n    return 1", "if x:\n    return 2", False)
    assert strategy == "flexible" and n == 1
    assert new == "def f():\n    if x:\n        return 2\n"


def test_edit_file_regex_tier():
    text = "result = compute( a,b )\n"
    new, n, strategy = apply_replacement(text, "compute(a, b)", "compute(b, a)", False)
    assert strategy == "regex" and new == "result = compute(b, a)\n"


def test_run_command_rewrites_paths_and_error_shape(repo, tmp_path):
    _, t = make(repo, tmp_path)
    r = json.loads(t["run_command"]("echo hi > /tmp/x.txt && cat /tmp/x.txt && ls /workspace/pkg"))
    assert r["status"] == "ok" and "hi" in r["stdout"] and "mathutil.py" in r["stdout"]
    assert (tmp_path / "tmp" / "x.txt").exists()
    r = json.loads(t["run_command"]("exit 3"))
    assert r["status"] == "error" and r["details"]["exit_code"] == 3


def test_run_command_timeout(repo, tmp_path):
    _, t = make(repo, tmp_path, command_timeout_seconds=1)
    r = json.loads(t["run_command"]("sleep 5"))
    assert r["error_type"] == "TimeoutExceeded"


def test_submit_patch_includes_untracked_and_is_free(repo, tmp_path):
    h, t = make(repo, tmp_path, tool_calls=20)
    t["write_file"]("pkg/newmod.py", "X = 1\n")
    r = json.loads(t["submit_patch"]())
    assert r["files_changed"] == 1 and h.patch_submitted
    assert "pkg/newmod.py" in h.submitted_patch
    assert h.tool_calls_used == 1


def test_budget_warning_and_exhaustion(repo, tmp_path):
    h, t = make(repo, tmp_path, tool_calls=20)
    for _ in range(9):
        t["get_status"]()  # free
        t["run_command"]("true")
    r = json.loads(t["run_command"]("true"))
    assert "budget_warning" in r
    for _ in range(10):
        t["run_command"]("true")
    assert json.loads(t["run_command"]("true"))["error_type"] == "BudgetExceeded"
    assert json.loads(t["get_status"]())["tool_calls_remaining"] == 0


def test_graph_tools(repo, tmp_path):
    _, t = make(repo, tmp_path)
    r = json.loads(t["get_code_neighbors"]("Scaler.scale"))
    assert r["node"] == "pkg.mathutil.Scaler.scale"
    assert any(n["node"] == "pkg.mathutil.clamp" and n["type"] == "calls" for n in r["neighbors"])
    r = json.loads(t["get_code_subgraph"](["clamp", "Scaler.scale"]))
    assert r["edge_count"] >= 1
    r = json.loads(t["search_similar_code"]("clamp", 3))
    assert r["status"] == "ok" and r["count"] >= 1
    assert json.loads(t["search_similar_code"]("zzz_nothing"))["status"] == "error"
