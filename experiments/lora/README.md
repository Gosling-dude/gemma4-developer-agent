# LoRA track

## Decision (2026-09-28): **LoRA is currently not justified.**

Reasons, strongest first:
1. **Adapters currently have no effect on the scorer, or fail it.** The patched vLLM 0.19.1 in the official
   wheelhouse registers every Gemma 4 decoder layer twice, and activating an adapter resets its weights to zero,
   so outputs are identical to the base model (discussion 743508, with a repro; the host replied "I will address").
   The official `sample_submission`, which ships two adapters, failed when submitted as-is (743213). Until the
   host confirms a fix, any adapter costs 0–3 GiB of upload for no effect, or risks a failed submission.
2. **No real-Gemma baseline exists yet**, so there's nothing to measure an adapter against and no trajectories to train on.
3. **No training hardware here** (Apple M5, 16 GB, no CUDA). QLoRA on a 31B model needs roughly ≥ 48–80 GB of GPU memory.

No adapter is shipped and no training was run; no training results are claimed.

## Revisit when all of these hold
- The host confirms that adapters load and affect outputs (e.g. the logprob-difference repro in 743508 passes).
- A real V1.x baseline exists on ≥ 30 official public tasks, with run-to-run noise measured over 3 seeds.
- ≥ 100 successful trajectories (Phase-2 resolved) are available from V1.x runs.

## Plan at that point
| Item | Choice | Rationale |
|---|---|---|
| Data | Assistant turns of **resolved** V1.x trajectories on public tasks; loss on assistant tokens only | Rejection sampling teaches tool-call format and workflow |
| Split | Hold out by repository | The hidden set comes from private repos |
| Base weights | The **served** checkpoint (`gemma-4-31b-it-qat-w4a16-ct`) or a verified-compatible bf16 base | The adapter must match what vLLM serves |
| Targets / rank | q,k,v,o,gate,up,down; r=16, alpha=32, dropout 0.05 | ~110–220 MB (HARNESS_README table); rank ≤ 128 |
| Format | PEFT `adapter_config.json` + `adapter_model.safetensors` (validator enforces) | Harness rule |
| Ship only if | Held-out resolution beats V1.x by more than the seed noise | Avoid shipping noise |
