"""Apply the pre-registered R019 promotion gate (docs/r019.md section 6) to a trace_mechanics.py report.

Usage: python3 -I scripts/r019_gate.py evaluations/analysis/R019-tool-loop-guard_mechanics.json \
           --candidate r19_root --control r17_control --stored r17_stored

The criteria are coded exactly as written before the run; this script only reads numbers and prints the verdict.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--candidate", default="r19_root")
    ap.add_argument("--control", default="r17_control")
    ap.add_argument("--stored", default="r17_stored")
    a = ap.parse_args(argv)
    rep = json.load(open(a.report))
    S, T = rep["summary"], rep["tasks"]
    cand, ctrl, stored = S[a.candidate], S[a.control], S[a.stored]

    def pair(x, y):
        return rep["paired"].get(f"{x}_vs_{y}") or _flip(rep["paired"][f"{y}_vs_{x}"])

    p_ctrl, p_stored = pair(a.candidate, a.control), pair(a.candidate, a.stored)
    cand_tasks = {t: v[a.candidate] for t, v in T.items() if v.get(a.candidate)}
    invalid = lambda s: s["invalid_path_ops"] + s["budget_rejections"] + s["workspace_scratch_writes"]
    cov = lambda s: eval(s["post_final_edit_check"].replace("/", "/ max(1,") + ")") if s["post_final_edit_check"] else 0.0
    rows = [
        ("1. resolved >= 15/24", cand["resolved"] >= 15, f"{cand['resolved']}/24"),
        ("2. wins - losses >= 3 vs same-run R017 control", p_ctrl["net"] >= 3,
         f"W{len(p_ctrl['wins'])} L{len(p_ctrl['losses'])} T{p_ctrl['ties']} net {p_ctrl['net']:+d} "
         f"(wins {p_ctrl['wins']}, losses {p_ctrl['losses']})"),
        ("3. no material regression vs stored R017: resolved >= 13 and losses <= 2",
         cand["resolved"] >= 13 and len(p_stored["losses"]) <= 2,
         f"resolved {cand['resolved']}; losses vs stored {p_stored['losses']}"),
        ("4. no unhandled tool-contract / sandbox / architecture failures",
         cand["unknown_tool_calls"] == 0 and all(
             (v["status"] in ("SUCCESS", None)) and not (v["error"] and "Traceback" in v["error"]) for v in cand_tasks.values()),
         f"unknown-tool calls {cand['unknown_tool_calls']}; statuses {sorted({str(v['status']) for v in cand_tasks.values()})}; "
         f"errors {sorted({str(v['error'])[:60] for v in cand_tasks.values() if v['error']})}"),
        ("5. no empty-patch submission loop (<= 2 empty submits per task, no 80-turn end)",
         all(v["empty_submits"] <= 2 for v in cand_tasks.values()) and cand["turn_limit_ends"] == 0,
         f"max empty submits in a task {max((v['empty_submits'] for v in cand_tasks.values()), default=0)}; "
         f"turn-limit ends {cand['turn_limit_ends']}; max submits {cand['max_submits_in_a_task']}"),
        ("6. invalid ops <= half of control's and scratch patches <= 2",
         invalid(cand) <= invalid(ctrl) / 2 and cand["scratch_patches"] <= 2,
         f"invalid ops {invalid(cand)} vs control {invalid(ctrl)} (stored R017 {invalid(stored)}); "
         f"scratch patches {cand['scratch_patches']} (control {ctrl['scratch_patches']}, stored {stored['scratch_patches']})"),
        ("7. post-final-edit check coverage >= control's and wrong fixes <= 6",
         cov(cand) >= cov(ctrl) and cand["wrong_fix"] <= 6,
         f"coverage {cand['post_final_edit_check']} vs control {ctrl['post_final_edit_check']}; wrong fixes {cand['wrong_fix']}"),
        ("8. projected full run <= 10.5 h", (cand["projected_full_run_h"] or 99) <= 10.5,
         f"{cand['projected_full_run_h']} h (mean {cand['mean_s']} s/task)"),
    ]
    for name, ok, detail in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    verdict = all(ok for _, ok, _ in rows)
    print("GATE:", "PASS" if verdict else "FAIL")
    return 0 if verdict else 1


def _flip(p: dict) -> dict:
    return {**p, "wins": p["losses"], "losses": p["wins"], "net": -p["net"]}


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
