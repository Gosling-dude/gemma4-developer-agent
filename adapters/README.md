# adapters/

Optional PEFT LoRA adapters, one directory per adapter:

```
adapters/<name>/adapter_config.json
adapters/<name>/adapter_model.safetensors
```

Reference one with `adapter: <name>` on an `LlmAgent`. The packager ships only adapters that an agent
references, so this README never goes into `submission.zip`. The validator rejects missing or placeholder
weights, pickle formats (`.bin`/`.pt`), `peft_type` other than LORA, and rank > 128.

**Status: no adapter is included.** V1 runs the base `gemma-4-31b-it-qat-w4a16-ct`. See
`experiments/lora/README.md` for why, and for the plan and the conditions under which training is justified.
