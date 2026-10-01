| Task | Repo | Runtime s | Tokens | Tool calls | Files inspected | Files edited | Tests run | Patch | Result | Failure |
|---|---|---:|---:|---:|---|---|---:|---|---|---|
| rich_3006 | Textualize/rich | 326.0 | 0 | 78 | 3 | rich/repr.py | 0 | 1 file(s), 1000 chars | PASS | – |
| rich_3052 | Textualize/rich | 187.7 | 0 | 14 | 3 | – | 1 | empty | FAIL | cap_hit: turns, no patch |
| rich_3061 | Textualize/rich | 317.0 | 0 | 78 | 4 | – | 0 | empty | FAIL | no_patch |
| rich_3063 | Textualize/rich | 333.7 | 0 | 46 | 2 | – | 0 | empty | FAIL | cap_hit: time, no patch |
| rich_3067 | Textualize/rich | 334.7 | 0 | 78 | 5 | rich/highlighter.py | 2 | 1 file(s), 655 chars | PASS | – |
| rich_3105 | Textualize/rich | 91.4 | 0 | 72 | 0 | – | 0 | empty | FAIL | no_patch |
| rich_3180 | Textualize/rich | 332.0 | 0 | 62 | 1 | – | 0 | empty | FAIL | cap_hit: time, no patch |
| rich_3278 | Textualize/rich | 334.9 | 0 | 68 | 3 | rich/ansi.py | 0 | 1 file(s), 352 chars | FAIL | cap_hit: time |

Resolved 2/8; mean runtime 282.2 s; model gemma-4-31b-it-qat-w4a16-ct.

| Variant | Tasks | Resolved | Mean s | Mean calls | Mean call of 1st edit | No edit | edit_file not found | code-edit ok | Failures | Locations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| root | 8 | 2 | 282.2 | 62.0 | 44.3 | 5 | 0 | 4 | {'cap_hit: turns, no patch': 1, 'no_patch': 2, 'cap_hit: time, no patch': 2, 'cap_hit: time': 1} | – |
