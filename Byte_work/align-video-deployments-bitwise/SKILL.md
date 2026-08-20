---
name: align-video-deployments-bitwise
description: Compare and bitwise-align two video-generation deployments from deployment directory A and deployment directory B. Use when Codex must run identical prompts, seeds, NFE, duration/frame count, FPS, resolution, scheduler, guidance, inputs, and dtype across two backends or environments; compare output-video hashes; dump encoder and every DiT step after a mismatch; locate the first divergent tensor; make minimal fixes; and keep scripts, outputs, results, dumps, logs, and modification records strictly separated under each deployment directory. Applies to T2V, I2V, R2V, Codance, vLLM-Omni, and similar inference stacks, including requests mentioning bitwise alignment, hash alignment, tensor dumps, encoder/DiT comparison, or two deployment environments.
---

# Align Video Deployments Bitwise

Align two video-generation deployments without mixing their artifacts or silently weakening the equality criterion.

## Accept inputs

Require only these inputs:

- deployment directory A;
- deployment directory B;
- optional reference command or script.

Resolve both directories with `realpath`. Reject identical or nested paths because they cannot provide clean isolation. Treat a reference command as canonical unless it conflicts with an explicit user setting.

Inspect each deployment's `AGENTS.md`, launch scripts, documentation, model config, and environment metadata before changing anything. Reuse its existing environment and stable code. If the Python environment cannot be discovered reliably, ask whether to use the existing uv/conda environment or create one; do not guess or replace it.

## Preserve directory isolation

Create this layout independently in **each** deployment directory:

```text
<deployment>/bitwise对齐/<run-id>/
├── 配置.json
├── 环境.json
├── 脚本/
├── output/
├── 结果/
├── logs/
├── dumps/
│   ├── encoder/
│   ├── dit/
│   └── decode/
└── 修改记录.md
```

Use the same `<run-id>` on both sides. Run `scripts/prepare_alignment.py` to create the mirrored layout and immutable shared configuration. Put A's commands, outputs, logs, dumps, and results only below A; do the same for B. Never place A artifacts in B, B artifacts in A, or ordinary test output in the source repository. Write the same comparison report to both `结果/` directories.

Do not overwrite an existing run. Resume it only after confirming that its `配置.json` matches the requested settings.

## Build one canonical generation specification

Derive one canonical command from the reference command when supplied. Otherwise select a minimal valid example already supported by both deployments, preferring A's documented demo and translating only environment-specific paths for B.

Record every generation-affecting field in both `配置.json` files:

- task type and all conditioning inputs, with SHA-256 for images, audio, embeddings, or reference video;
- positive and negative prompts as exact UTF-8 strings;
- seed and the RNG device/generator construction;
- NFE/steps, scheduler/sampler and timesteps/sigmas;
- duration, frame count, FPS, width, height, aspect/resize/crop behavior;
- guidance scales, strength, noise augmentation, batch size, and sequence length;
- model and component paths/revisions plus hashes of relevant configs and weights;
- dtype, autocast policy, attention backend, quantization, compile mode, parallelism, and GPU mapping;
- decoding and video serialization parameters, including codec, pixel format, and container flags.

Make the effective values explicit in generated scripts. Do not rely on differing backend defaults. Preserve each environment's activation and launch mechanism; only the semantic generation specification must be identical.

## Phase 1: run the output hash gate

Generate exactly one video in each environment. Capture the command, environment variables, stdout/stderr, package snapshot, GPU/runtime information, model/config hashes, elapsed time, and output path under that deployment's run directory.

Hash the complete video file with SHA-256. Use `scripts/compare_artifacts.py` for the comparison.

- If hashes match, write `结果/最终报告.md` on both sides with the shared hash, commands, configuration path, and `BITWISE_ALIGNED`, then stop. Make no code changes.
- If hashes differ, record both hashes and continue. A decoded-frame hash may help distinguish container metadata from generated pixels, but it does **not** satisfy bitwise alignment unless the user explicitly changes the success criterion.

## Phase 2: create the five-step diagnostic run

Create diagnostic scripts inside each run's `脚本/` directory. Force the same canonical specification but set NFE to 5. Keep all other generation-affecting settings equal. Never use the five-step result as the final production proof when the requested NFE differs.

Instrument both pipelines at equivalent semantic boundaries. Read [references/pytorch-dump-guide.md](references/pytorch-dump-guide.md) before editing instrumentation. Copy or import `scripts/tensor_dump.py` into each run's script directory and dump canonical raw bytes plus JSON metadata for:

1. tokenization/text inputs and encoder inputs;
2. every encoder output consumed by DiT, including masks and pooled/hidden states;
3. initial noise/latent and RNG state identifier;
4. for each DiT step `000` through `004`: timestep/sigma, latent before the step, every conditioning tensor passed into DiT, DiT prediction, scheduler output/latent after the step;
5. decoder input and output when all DiT artifacts match but the video does not.

Use stable filenames shared across A and B, such as `step_000__latent_before.bin`. Do not use `torch.save` as the canonical bitwise artifact because archive metadata can differ. Synchronize CUDA before copying tensors and again before measuring timings.

## Phase 3: locate the first divergence

Compare matching dump directories with `scripts/compare_artifacts.py`. Check raw SHA-256 first, then metadata, first differing element/byte, maximum absolute difference, and mean absolute difference when supported.

Trace the earliest mismatch in causal order:

```text
inputs -> encoder -> initial latent -> DiT step 000 -> ... -> step 004 -> decoder -> serializer
```

Do not patch downstream code while an upstream artifact still differs. Classify the first divergence using the checklist in [references/pytorch-dump-guide.md](references/pytorch-dump-guide.md).

## Phase 4: repair minimally and iterate

Change only the side that deviates from the canonical/reference behavior, unless evidence shows the shared specification is wrong. Prefer configuration or launch-script fixes over backend code edits. Reuse existing code and avoid unrelated refactors, generated code, and documentation directories.

Before each change, append a round to both `修改记录.md` files containing:

- timestamp and round number;
- earliest divergent artifact and both hashes;
- evidence and hypothesis;
- exact files/settings changed, with a concise diff summary;
- exact rerun commands;
- post-change hashes and conclusion;
- rollback action when the hypothesis fails.

After each fix, rerun from the earliest affected boundary when safe, then rerun the complete five-step diagnostic. Continue until all diagnostic artifacts match bitwise. Never accept tolerances, cosine similarity, PSNR, or visually identical video as bitwise equality.

## Phase 5: prove the requested configuration

Remove or disable dump hooks without changing numerical execution. Rerun both deployments using the original requested NFE and complete canonical settings. Compare the complete video files again.

Finish only when their SHA-256 hashes match. Write `结果/最终报告.md` to both deployments with:

- `BITWISE_ALIGNED` and the shared video hash;
- exact commands and environment locations;
- canonical settings and input hashes;
- final output paths;
- earliest root cause;
- minimal retained changes and validation evidence.

If permissions, unavailable hardware, nondeterministic kernels, or missing inputs prevent completion, record the exact blocker and last matching boundary. Report `NOT_ALIGNED` rather than claiming success.

## Guardrails

- Treat model weights and input assets as read-only unless the user explicitly authorizes changes.
- Do not terminate unrelated GPU jobs. Resolve GPU ownership before launching.
- Back up or use version control for any source edit. Preserve user changes already present.
- Do not make determinism flags differ across A and B. Record `CUBLAS_WORKSPACE_CONFIG`, TF32, deterministic-algorithm settings, attention backend, and distributed topology explicitly.
- Compare effective scheduler timestep/sigma tensors, not only configuration text.
- Keep separate service PIDs, ports, logs, and output names for A and B.
- Include deployment and test commands in the final report so the run is reproducible.
