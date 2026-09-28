# Submitting

## Build and check
```bash
scripts/setup.sh                 # once
scripts/validate.sh              # unit tests + build + strict validation + ADK compile
scripts/package_submission.sh    # -> submission/submission.zip (re-validated, contents listed)
```
Package a variant instead: `scripts/package_submission.sh --variant v2`.

## What the checks enforce
- Exactly one root config, at the archive root (never nested in a folder).
- Every `!include`, `config_path`, `skills` path and adapter resolves **inside** the root. No absolute
  paths, NUL bytes or symlinks.
- Only `.yaml .yml .md .txt .py .json .safetensors` files; no hidden files, no `__pycache__`.
- Every agent uses `gemma-4-31b-it-qat-w4a16-ct`, and only one base model appears in the submission.
- Tools are the 9 harness tools or `agent_tool` entries. Generation config fields are allowed and in range, with no forbidden fields.
- Skills: `SKILL.md` frontmatter valid, name is kebab-case and equals the directory name, scripts are `.py` and parse.
- Instructions contain no `{placeholder}` that would raise KeyError at runtime (`{hints}` must be `{hints?}`).
- `eval_config.yaml` keys are valid, and the projected worst-case run time fits in 12 h.
- Only files reachable from `agent.yaml` are shipped (plus `eval_config.yaml`).
- The archive is deterministic (fixed timestamps), so identical sources give an identical sha256.

## Uploading (manual, by you)
1. Accept the rules on the competition page (this can't be done on your behalf).
2. Go to Submit Predictions and upload `submission/submission.zip`, or use the CLI with your own credentials:
   `kaggle competitions submit -c gemma-4-developer-agent -f submission/submission.zip -m "V1"`
   (The exact CLI flow for this code-competition format is unverified; the web form is the safe path.)
3. The scoring run takes up to 12 h. Record the public LB score in `docs/experiments.md` with the date.

## Pre-upload checklist
- [ ] `scripts/package_submission.sh` ends with `SUBMISSION READY`
- [ ] `git status` is clean and the commit hash is noted in docs/experiments.md
- [ ] If an adapter was added: real safetensors (not a placeholder), rank ≤ 128, total < 3 GiB
- [ ] `eval_config.yaml` budget is deliberate (see docs/competition_notes.md "Budget analysis")
