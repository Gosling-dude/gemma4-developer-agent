| Task | Repo | Runtime s | Tokens | Tool calls | Files inspected | Files edited | Tests run | Patch | Result | Failure |
|---|---|---:|---:|---:|---|---|---:|---|---|---|
| rich_2725 | Textualize/rich | 260.0 | 0 | 78 | 4 | rich/table.py | 0 | 1 file(s), 609 chars | PASS | – |
| rich_2943 | Textualize/rich | 77.3 | 0 | 22 | 3 | rich/style.py | 3 | 1 file(s), 400 chars | PASS | – |
| rich_3043 | Textualize/rich | 256.6 | 0 | 38 | 8 | .pre-commit-config.yaml, rich/_export_format.py | 4 | 2 file(s), 2528 chars | FAIL | wrong_fix (hidden tests fail) |

Resolved 2/3; mean runtime 198.0 s; model gemma-4-31b-it-qat-w4a16-ct.

| Variant | Tasks | Resolved | Mean s | Mean calls | Mean call of 1st edit | No edit | edit_file not found | code-edit ok | Failures | Locations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| root | 3 | 2 | 198.0 | 46.0 | 35.3 | 0 | 0 | 3 | {'wrong_fix (hidden tests fail)': 1} | – |
