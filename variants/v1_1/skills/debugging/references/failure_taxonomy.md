# Failure patterns and typical repairs

| Symptom | Usual cause | Repair |
|---|---|---|
| `ImportError` / `NameError` right after your edit | Missing import, typo, or a name you introduced but never defined | Add the import at the top of the module, following the file's existing style |
| `SyntaxError` / `IndentationError` | `edit_file` replacement with the wrong indentation | Re-`show` the symbol and redo the edit with exact context |
| `AttributeError: 'NoneType'` | A value that can be None isn't guarded, often where the issue says "when X is empty" | Guard at the point where the None arises, not at every use |
| Test expects a specific error message or type | Contract detail in the issue text | Copy the exception class and message wording **exactly** from the issue |
| Only async (or only sync) variant fixed | Twin implementations (e.g. `Client` and `AsyncClient`) | `search_similar_code` / `usages` to find the twin and apply the same fix |
| Fix works for one input, fails for another | Special-cased the example instead of the rule | Generalize to the rule the issue describes; check the other call sites |
| Existing unrelated test fails before and after | Pre-existing failure | Ignore it; confirm with `git stash` |
| Timeout | Infinite loop or retries, a network call, reading stdin | Add a guard; never wait on the network (the sandbox is offline) |

Heuristics for hidden tests
- They usually call the **public API** named in the issue. Make that API behave exactly as described.
- Keep backwards compatibility: new parameters get defaults, existing signatures keep working.
- For a feature request, follow the surrounding conventions: type hints, docstrings, `__all__` exports
  and CLI flags.
