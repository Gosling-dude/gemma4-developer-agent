# LoRA track

**Status: not attempted (by design, as of 2026-09-28).** No adapter ships. No training results exist,
and none are claimed.

## Why not yet
1. The priority order puts LoRA last. A LoRA only pays off once prompt, tools and skills are measured,
   and those measurements need a model endpoint (see the TODO in docs/experiments.md).
2. Training needs a GPU that can hold `gemma-4-31b-it-qat-w4a16-ct` for QLoRA-style training
   (≥ 1× 80 GB, or 2× 48 GB). This machine is an Apple M5 laptop with 16 GB RAM and no CUDA.
3. The data (successful agent trajectories) doesn't exist yet. It comes from running V1 on the
   129 public tasks.

## Plan once the prerequisites exist
| Item | Choice | Rationale |
|---|---|---|
| Data | Trajectories from V1 (or a stronger teacher) on public tasks whose patch **resolves** in Phase 2; one example per assistant turn, trained only on assistant tokens (thought + tool call) | Teaches the tool-call format and the workflow; rejection sampling keeps only verified successes |
| Hold-out | Split by repository (e.g. hold out `httpx`) | The hidden test set uses **private repos**, so random splits overestimate |
| Target modules | q,k,v,o,gate,up,down proj | HARNESS_README sizing table |
| Rank / alpha / dropout | r=16, alpha=32, dropout=0.05 | ~110–220 MB, well within the 3 GiB limit and `max_lora_rank=128` |
| Steps | 1–2 epochs, lr 1e-4 cosine, max seq 16k | Small data; avoid overfitting to 4 repos |
| Format | PEFT `adapter_config.json` + `adapter_model.safetensors` (validator enforces) | Harness requirement |
| Success criterion | Resolution rate on the held-out repo better than V1 by more than the run-to-run noise (measure noise with 3 seeds of V1 first) | Avoids shipping noise |

Base-weight compatibility (INFERRED risk): the adapter has to be trained against the same QAT
checkpoint that vLLM serves. Training on the bf16 `gemma-4-31b-it` and serving on the W4A16 model may shift
behaviour. Validate on the served model.
