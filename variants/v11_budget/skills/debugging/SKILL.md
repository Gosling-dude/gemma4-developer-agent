---
name: debugging
description: Diagnose a failing reproduction or test (runs it and shows source around the innermost repository frames) and review the final patch before submission (untracked files, edits the grader will reset, debug prints, syntax errors, empty diff). Use after every failed run and always right before submit_patch.
---

# Debugging and patch review

| Goal | call |
|---|---|
| Run a repro script and see the innermost repo frames | `run_skill_script(skill_name="debugging", file_path="scripts/diagnose.py", args=["run", "/tmp/repro.py"])` |
| Diagnose any shell command | `args=["cmd", "python", "-c", "import pkg; pkg.f(1)"]` |
| Review the patch before submitting | `run_skill_script(skill_name="debugging", file_path="scripts/review.py", args=[])` |

## Evidence-driven repair loop
1. **Classify** the failure from the output. Is it an ImportError or SyntaxError (your edit broke
   the import), an assertion with a wrong value (logic), the wrong exception type or message (contract
   mismatch with the issue), or a timeout (a loop or blocking I/O)?
2. **Locate:** the innermost repository frame is the default suspect. For a wrong value, trace the value
   back one call at a time (`show` in repo-navigation, or `get_code_neighbors`).
3. **Hypothesize** in one sentence: "X returns Y because Z." If you can't write that sentence, gather
   more evidence before editing.
4. **Change one thing**, then rerun the same command. Don't stack speculative edits.
5. If two consecutive attempts at the same hypothesis fail, revert the edit (`git checkout -- file`)
   and reconsider the location.

See `references/failure_taxonomy.md` for common patterns and their usual fixes.
