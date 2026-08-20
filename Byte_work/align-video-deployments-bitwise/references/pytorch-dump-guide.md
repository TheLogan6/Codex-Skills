# PyTorch video-pipeline dump guide

## Contents

1. Instrumentation rules
2. Canonical boundaries
3. First-divergence checklist
4. Repair order

## Instrumentation rules

- Insert hooks at equivalent semantic boundaries, not merely similarly named functions.
- Dump the actual tensors consumed by the next stage after preprocessing, casting, reshaping, sharding, and classifier-free-guidance concatenation.
- Call `torch.cuda.synchronize(device)` before copying an asynchronously produced CUDA tensor.
- Use `tensor.detach().contiguous().cpu()` and write raw tensor bytes plus shape/dtype metadata. Use the bundled `tensor_dump.py` helper.
- Preserve the inference stream, dtype, device placement, and operation order. Avoid `.float()` in the live path; cast only a detached diagnostic copy when calculating statistics.
- Name tensors deterministically. Include the DiT step as a zero-padded integer and avoid object IDs, timestamps, ranks, or absolute deployment paths in filenames.
- On tensor-parallel runs, either dump the same post-gather tensor or dump every shard with stable rank names and compare corresponding ranks. Record the topology.
- Dump masks, timestep/sigma tensors, rotary/position data, guidance inputs, and scheduler state along with obvious hidden states and latents.

## Canonical boundaries

Dump at least these boundaries for an NFE=5 diagnostic:

```text
encoder/input_ids
encoder/attention_mask
encoder/hidden_states
encoder/pooled_output              # when present
dit/initial_noise
dit/initial_latent
dit/step_000/timestep_or_sigma
dit/step_000/latent_before
dit/step_000/conditioning/*
dit/step_000/prediction
dit/step_000/latent_after
...
dit/step_004/*
decode/input_latent
decode/output_frames
```

Dump preprocessing outputs for image, audio, or reference video before their encoder as applicable. Hash the original input file separately.

## First-divergence checklist

| First mismatch | Check first |
| --- | --- |
| Token IDs or masks | tokenizer revision, prompt bytes, truncation, padding side, max length |
| Encoder input | resize/crop/resample, normalization, channel order, mask construction, dtype cast |
| Encoder output | weight/config hashes, attention backend, dtype/autocast, TF32, parallel reductions |
| Initial noise | seed scope, generator device, draw order, shape, batch/CFG duplication |
| Timestep/sigma | scheduler class/config, timestep spacing, offset, dtype/device |
| DiT conditioning | CFG packing order, encoder selection, mask broadcast, positional/rotary inputs |
| First DiT prediction | model weights/config, fused kernels, attention backend, dtype, TP collectives |
| Later DiT step | scheduler update, in-place mutation, cast/rounding, latent scaling |
| Decoder input | latent scaling/shift, temporal padding, frame slicing, dtype |
| Frames only | decoder/VAE version, tiling, precision, output clamp/round/channel order |
| Video file only | FPS time base, codec/pixel format, encoder build/options, metadata/mux order |

For distributed differences, also compare rank-to-device mapping, world size, collective algorithm/environment variables, shard padding, and gather/reduce order. For compiled/fused execution, compare with the same compile and fusion settings first; disabling an optimization on only one side does not establish equivalent deployment settings.

## Repair order

Apply fixes in this order and stop as soon as the earliest mismatch moves downstream:

1. input bytes and preprocessing;
2. model/config/tokenizer identities;
3. explicit generation arguments and scheduler arrays;
4. RNG construction and consumption order;
5. dtype/autocast/TF32/determinism settings;
6. attention/fused kernel choice;
7. tensor/distributed parallel topology and reduction order;
8. decoder and serializer.

Record failed hypotheses and revert them. Do not accumulate speculative changes.
