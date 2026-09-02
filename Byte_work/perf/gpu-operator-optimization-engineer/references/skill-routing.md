# Skill 路由

先用事实确定机制，再路由。文件名、kernel 名或用户预设不能单独决定路由。默认选择一个 primary specialist；只有边界明确、验收可拆时才添加 secondary。

## 强制 profiler 路由

任何涉及 trace 采集、解析、kernel 归因、overlap 判断或 fusion pattern 的工作，必须复用同级：

```text
../llm-torch-profiler-analysis
```

使用其 `scripts/analyze_llm_torch_profile.py` 和输出契约。结果固定为：

1. kernel table
2. overlap-opportunity table
3. fuse-pattern table

本 skill 不复制 analyzer，不实现 trace parser，不建立自己的 profiler 表，不改变三表阈值或语义。若已有 trace，直接交给该 skill；若需 live capture，也由该 skill 判断 framework 前提。其结论作为 `bottleneck` 账的证据，而不是替代目标层级 benchmark。

## 决策表

| 直接证据 / 主机制 | Primary skill | 进入前必须证明 | 常见拒绝条件 |
| --- | --- | --- | --- |
| activation 与 quant/dequant 相邻，中间张量只服务单一 consumer | `activation-quant-fusion-engineer` | reference 舍入边界、scale 语义、dtype/layout | 算法或 accumulation order 不可合法保持 |
| NVFP4 dispatch payload 到 expert-major GEMM 输入布局 | `nvfp4-dispatch-pack-engineer` | pair/scatter 索引、local expert 映射、codes/scales 布局 | 路由语义或 group-scale 地址不明 |
| bounded-key sort/count/pack，或 indexed gather/product/segment reduce | `indexed-pack-reduce-fusion-engineer` | key domain、稳定性、destination order、reduction criterion | 通用大 key、无序高冲突或多 consumer |
| exposed communication/copy 可与独立 compute 跨 chunk 共驻 | `cuda-stream-pipeline-engineer` | split invariance、collective order、Event/lifetime、资源互补 | 依赖不可切、compute 饱和、chunk 效率崩溃 |
| HBM 容量或重复 H2D；residency/prefetch 可减少暴露尾部 | `gpu-offload-prefetch-engineer` | live range、H2D 次数、pinned/stream 条件、hottest rank | 传输已隐藏、容量越界或无计算窗口 |
| 普通 fusion/pipeline 后仍由 host/launch/head-tail/arrival 主导 | `persistent-schedule-engineer` | bounded task table、epoch/slot、topology、逐级 reference | 真实瓶颈是 compute/wire bytes/imbalance |

## 路由算法

1. **先定层级**：用户关心 kernel、operator、block/layer 还是 end-to-end；最终验收不得低于目标层级。
2. **再取证**：运行或读取统一 profiler 三表，并记录 exposed cost、phase 和 slowest rank。
3. **写主假设**：用一句可证伪因果链描述“为何慢”和“哪类改动会改善目标指标”。
4. **检查专门入口条件**：命中决策表后，读取对应 skill 的输入、进入和停止条件。
5. **选 primary**：选择直接改变主因的 skill。优化相邻但非主因的步骤不能成为 primary。
6. **控制 secondary**：只在主改动产生明确接口需求时增加；分别维护 reference 和验收，不把两个机制塞进同一 benchmark 结论。
7. **无法路由时停止**：保留 `gpu-operator-optimization-engineer` 做分析，状态为 `continue` 或 `blocked`；不得伪造通用 kernel 专家。

## 常见冲突

### Fusion 与 stream overlap

- 中间张量、launch 或 HBM traffic 是 exposed 主因：优先 fusion。
- 通信/copy 是 exposed 主因，且独立 compute 窗口明确：优先 stream pipeline。
- trace 中 kernel 已被完全覆盖：不要因累计 GPU time 高而优先 fusion。

### Stream pipeline 与 persistent schedule

- 先尝试较低风险的普通 chunk/Stream/Event pipeline。
- 只有其剩余是固定 launch、host sync、head/tail 或 CTA arrival，才进入 persistent。
- 两条路径同时默认开启必须有独立协议与组合验收，否则互斥。

### Offload 与 stream pipeline

- 容量首先不成立：先由 offload skill 建立 residency。
- 容量成立但 H2D 尾部暴露：offload skill 主导 prefetch，stream skill 可审查 Event/lifetime。
- 不得为隐藏 H2D 增加导致显存越界的在途 buffer。

### 专用 pack 与通用 indexed fusion

- NVFP4 codes、per-token/group scales、expert-major consumer 同时存在：走 NVFP4 专用 skill。
- 不依赖 NVFP4 wire/layout 语义的 bounded-key 或 indexed reduce：走通用 indexed skill。

## 路由记录模板

```yaml
target_level:
profiler_source: llm-torch-profiler-analysis
three_table_evidence:
  kernel:
  overlap:
  fuse:
primary_hypothesis:
primary_skill:
entry_conditions:
  - condition:
    evidence:
rejected_routes:
  - skill:
    reason:
secondary_skills: []
acceptance_level:
```
