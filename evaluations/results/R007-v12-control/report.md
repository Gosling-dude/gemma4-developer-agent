| Task | Repo | Runtime s | Tokens | Tool calls | Files inspected | Files edited | Tests run | Patch | Result | Failure |
|---|---|---:|---:|---:|---|---|---:|---|---|---|
| rich_3006 | Textualize/rich | 151.3 | 0 | 47 | 5 | rich/repr.py | 2 | 1 file(s), 558 chars | PASS | – |
| rich_3052 | Textualize/rich | 174.1 | 0 | 43 | 4 | rich/prompt.py | 2 | 1 file(s), 2959 chars | FAIL | wrong_fix (hidden tests fail) |
| rich_3061 | Textualize/rich | 335.5 | 0 | 75 | 2 | rich/text.py | 0 | 1 file(s), 990 chars | FAIL | cap_hit: time |
| rich_3063 | Textualize/rich | 230.9 | 0 | 76 | 2 | – | 0 | empty | FAIL | no_patch |
| rich_3067 | Textualize/rich | 245.3 | 0 | 76 | 4 | repro.py | 0 | 1 file(s), 728 chars | FAIL | cap_hit: turns |
| rich_3105 | Textualize/rich | 116.0 | 0 | 79 | 0 | – | 0 | empty | FAIL | no_patch |
| rich_3180 | Textualize/rich | 332.4 | 0 | 72 | 1 | – | 0 | empty | FAIL | cap_hit: time, no patch |
| rich_3278 | Textualize/rich | 332.5 | 0 | 48 | 2 | – | 0 | empty | FAIL | cap_hit: time, no patch |

Resolved 1/8; mean runtime 239.8 s; model gemma-4-31b-it-qat-w4a16-ct.

| Variant | Tasks | Resolved | Mean s | Mean calls | Mean call of 1st edit | No edit | edit_file not found | code-edit ok | Failures | Locations |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| v1_2 | 8 | 1 | 239.8 | 64.5 | 36.0 | 4 | 0 | 0 | {'wrong_fix (hidden tests fail)': 1, 'cap_hit: time': 1, 'no_patch': 2, 'cap_hit: turns': 1, 'cap_hit: time, no patch': 2} | – |
