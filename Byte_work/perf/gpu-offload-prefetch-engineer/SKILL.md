---
name: "gpu-offload-prefetch-engineer"
description: "Analyzes and implements GPU offload, H2D prefetch, residency, and buffer reuse. Invoke for HBM limits, repeated weight transfers, double buffering, allocator cliffs, or transfer tails."
---

# GPU Offload & Prefetch Engineer

以“容量先成立、传输次数再最小、最后隐藏暴露尾部”的顺序分析并实现 GPU offload/prefetch。不要从增加 stream 或盲目 pin 权重开始。

## 输入契约

先固定并记录；未知项写 `unknown`，不得猜测：

```yaml
repository: <repo>
revision: <revision>
target: {files: [], symbols: [], commits: []}
baseline: {command: null, residency: null}
candidate: {command: null, residency: null}
workload: {shapes: {}, dtype: null, phases: []}
hardware: {gpu: null, host_memory: null, interconnect: null, numa: null}
correctness: {criterion: bitwise | exact | tolerance | quality | unspecified}
memory_guard: {device_peak_bytes: null, safety_margin_bytes: null}
mutation_policy: read-only | implementation-allowed
```

## 完成定义

输出必须包含：

```yaml
baseline_contract:
live_range_ledger:
h2d_ledger:
exposed_transfer_tail:
selected_residency:
buffer_ownership:
implementation_scope:
validation_gates:
diff_result: ship | continue | stop | blocked
remaining_risks:
```

只有正确性、最坏 shape、最热 rank、目标层级性能、allocated/reserved/driver-visible 显存和 feature-off fallback 全部有证据时，才可判定 `ship`。

## 工作流

### 1. 建立事实基线

从真实调用入口向下追踪权重注册、host backing store、H2D、consumer wait、forward hooks、unload 和 phase/context 复用。证明 feature 实际 engaged，并固定 shape、dtype、rank、拓扑和运行命令。

阅读 [references/code-analysis.md](references/code-analysis.md)，建立：

- weights、scales、activations、workspace、通信 slab 和 allocator pool 的 live-range 表；
- 每份权重在每层、每 phase、每 token chunk 的 H2D 次数；
- producer stream、copy stream、consumer stream 和 Event 边；
- slot 的 owner、写入者、最后消费者和再次写入条件；
- hottest rank 的 allocated、reserved 与驱动可见峰值。

### 2. 先判定是否适用

按以下顺序：

1. 最坏 shape 是否能在显存 guard 内运行；
2. 循环嵌套是否导致同一权重被重复 H2D；
3. 是否存在足够长且资源独立的计算窗口覆盖 H2D；
4. partial residency 是否能以更少 H2D 尾部换取可接受的常驻显存；
5. 新 stream 是否延长 live range 或建立额外 allocator pool。

若传输已完全隐藏、权重复用高且容量充足，或新增 staging buffer 会越过 guard，拒绝 offload/prefetch 改动。

### 3. 设计数据与同步协议

阅读 [references/implementation.md](references/implementation.md)。实现前写清：

- host flat buffer 是否 page-locked，参数到 offset/shape 的映射是否稳定；
- 双缓冲 `slot = logical_item % 2` 是否真的安全；
- copy 前等待上一使用者的 compute-done Event，避免 WAR；
- copy 完成后由 consumer 等 H2D-done Event，避免 RAW；
- tensor/view 在跨 stream 使用时的 allocator ownership；
- weights 与 scales、zero-point、layout metadata 是否同分片、同 epoch；
- unload 后所有参数 view 恢复到合法 backing storage；
- 非法 residency、store、expert-split 组合 fail-fast。

### 4. 最小实现

优先顺序：

```text
reference + instrumentation
→ pinned host packing
→ 单 slot 同步 copy
→ H2D-done consumer wait
→ 双 slot + compute-done 防覆盖
→ next-item prefetch
→ partial residency
→ expert/weight split
→ 默认值评估
```

保留 reference、feature gate、fallback 和一次性 engagement log。不得用 `record_stream` 代替依赖同步；不得用 device-wide synchronize 掩盖错误，除非它是明确记录的保守 fallback。

### 5. 用案例校准决策

阅读 [references/cases.md](references/cases.md)。至少写一条成功、一条失败和一条“不适用/停止”案例，统一采用：

```text
现象 → 根因 → 方案 → 证据 → 结论
```

### 6. 测试与 diff 验收

阅读 [references/validation-and-diff.md](references/validation-and-diff.md)，按层验收：

```text
host pack/view
→ 单层单 slot
→ 双 slot 复用
→ 多层 prefetch
→ 多 token/weight chunk
→ phase transition/context reuse
→ 最坏 shape/最热 rank
→ 目标层级与端到端
```

检查 Git diff 是否同时包含实现、接线、feature gate、fallback、正确性测试、H2D 计数、显存门禁和性能证据。只有 microbenchmark、只看平均 rank、只看 framework allocated 或没有 feature-off 对照时，最多 `continue`。

## 强制原则

- 峰值由 live ranges 的重叠决定，不是静态 tensor 大小求和。
- offload/prefetch 通常减少 exposed H2D tail，不会提高物理总线带宽。
- token chunk 外层包住 weight chunk 往往会把 H2D 次数乘上 token chunk 数。
- pinned memory 只是异步 copy 的前提，不等于 copy 已被隐藏。
- consumer 只等待它真正依赖的 weight；过早等待会消灭 prefetch 窗口。
- 容量以 hottest rank、最坏 shape 和安全余量判定。
- 任何新 stream 都必须提交 timeline 与 live-range 证据。
- 权重、scale 和布局元数据必须作为一个版本化 residency 单元。
