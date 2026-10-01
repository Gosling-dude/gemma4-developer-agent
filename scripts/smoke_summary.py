"""Per-task smoke summary for an instrumented real-eval run (R005/R006 and later).

Usage: python scripts/smoke_summary.py evaluations/results/<EXP>
Prints, per task: server probe before/after, first model response time, tokens, first tool call,
first successful edit (call index), total tool calls, patch size, resolved, timeout.
"""

import json
import sys
from pathlib import Path


def first_edit(steps):
    n = 0
    for s in steps:
        obs = str((s.get("observation") or {}).get("content") or "")
        for tc in s.get("tool_calls") or []:
            n += 1
            name, args = tc.get("function_name"), tc.get("arguments") or {}
            if name == "edit_file" and '"status": "ok"' in obs.replace('\\"', '"'):
                return n, "edit_file"
            if name == "run_skill_script" and args.get("skill_name") == "code-edit" and "EDITED " in obs \
                    and "NOT EDITED" not in obs:
                return n, "code-edit " + str((args.get("args") or [""])[0])
    return None, None


def main(d: Path) -> int:
    res = d / "g4_results"
    for f in sorted(res.glob("*_task_results.jsonl")):
        if f.name.startswith("gold"):
            continue
        print(f"== {f.name}")
        for line in f.read_text().splitlines():
            r = json.loads(line)
            tp = res / r["variant"] / "traces" / f"trace_{r['instance_id']}.json"
            steps = json.loads(tp.read_text()).get("steps", []) if tp.exists() else []
            calls = [tc for s in steps for tc in (s.get("tool_calls") or [])]
            fm = json.loads(tp.read_text()).get("final_metrics", {}) if tp.exists() else {}
            fe, how = first_edit(steps)
            pb, pa = r.get("probe_before") or {}, r.get("probe_after") or {}
            print(json.dumps({
                "task": r["instance_id"],
                "probe_before": f"{pb.get('ok')} {pb.get('s')}s", "probe_after": f"{pa.get('ok')} {pa.get('s')}s",
                "model_request_answered": bool(fm.get("total_prompt_tokens")),
                "first_response_s": r.get("first_response_s"),
                "tokens": fm.get("total_tokens"), "first_tool": calls[0]["function_name"] if calls else None,
                "first_edit_call": fe, "first_edit_via": how, "tool_calls": len(calls),
                "patch_chars": r.get("patch_chars"), "resolved": r.get("resolved"),
                "timeout": "timeout" in (r.get("error") or ""), "duration_s": r.get("duration_s")}))
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
