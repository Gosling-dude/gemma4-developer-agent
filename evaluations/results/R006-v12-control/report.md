| Task | Repo | Runtime s | Tokens | Tool calls | Files inspected | Files edited | Tests run | Patch | Result | Failure |
|---|---|---:|---:|---:|---|---|---:|---|---|---|
| rich_2725 | Textualize/rich | 80.1 | 0 | 16 | 3 | rich/table.py | 3 | 1 file(s), 1099 chars | PASS | – |
| rich_2943 | Textualize/rich | 107.0 | 0 | 48 | 3 | rich/style.py | 3 | 1 file(s), 400 chars | PASS | – |
| rich_3043 | Textualize/rich | 200.6 | 0 | 80 | 5 | – | 6 | empty | FAIL | no_patch |

Resolved 2/3; mean runtime 129.2 s; model gemma-4-31b-it-qat-w4a16-ct.

| Variant | Tasks | Resolved | Mean s | Mean calls | Mean call of 1st edit | No edit | edit_file not found | code-edit ok | Failures | Locations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| v1_2 | 3 | 2 | 129.2 | 48.0 | 41.7 | 0 | 1 | 0 | {'no_patch': 1} | – |
