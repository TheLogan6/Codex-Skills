---
name: "gpu-operator-optimization-engineer"
description: "Orchestrates evidence-driven GPU operator optimization. Invoke to baseline a GPU path, route work to a specialist skill, keep seven ledgers, and accept or reject a shared diff."
---

# GPU Operator Optimization Engineer

以可复现基线为起点，维护七本账，按瓶颈机制路由到专门 skill，并用同一套 correctness、性能、资源和 diff 门禁给出 `ship | continue | stop | blocked`。本 skill 是编排与验收层，不重造 profiler，也不替代专门算子 skill。

## 输入契约

```yaml
repository: <repo>
revision: <revision>
target: {files: [], symbols: [], callsite: null}
baseline: {command: null, artifacts: [], environment: {}}
candidate: {command: null, artifacts: [], feature_gate: null}
workload: {shapes: [], dtypes: [], distributions: {}, phases: []}
hardware: {gpu: null, count: null, topology: null, software: {}}
correctness: {reference: null, criterion: exact | bitwise | tolerance | quality | unspecified}
performance: {metric: null, aggregation: slowest-rank | end-to-end | other, repeats: null}
memory_guard: {device_peak_bytes: null, safety_margin_bytes: null}
mutation_policy: read-only | implementation-allowed
```

未知项写 `unknown`。缺 reference、目标调用点、可比命令或目标硬件时，不得把结论升级为 `ship`。

## 唯一工作流

1. 建立复现账和契约账，锁定 revision、命令、环境、shape、dtype、布局、owner、有效区及比较准则。
2. 证明候选路径实际命中；记录 feature gate、fallback 和一次性 engagement 证据。
3. **瓶颈 trace 必须调用同级 `../llm-torch-profiler-analysis`**。直接使用它的统一入口和固定三表：
   - kernel table
   - overlap-opportunity table
   - fuse-pattern table
4. 不复制、不改写、不重新实现 profiler 解析、trace 采集或第四张 profiler 表。需要新 profiler 能力时，路由回该 skill。
5. 根据 [references/skill-routing.md](references/skill-routing.md) 选择一个 primary specialist；跨机制时可增加 secondary，但每个 diff 必须有单一主假设。
6. 按 [references/bottleneck-ledgers.md](references/bottleneck-ledgers.md) 持续更新七本账。每条判断必须指向命令、文件、trace、测试或测量记录。
7. 实现最小候选；保留 reference、feature gate、fallback，不夹带无关重构。
8. 用 `scripts/summarize_diff.py` 只读汇总改动面；用 `scripts/compare_runs.py` 对可比运行做字段化比较。
9. 按 [references/shared-diff-acceptance.md](references/shared-diff-acceptance.md) 验收。任何硬门禁失败都不得以平均性能或单 kernel 提速覆盖。

## 七本账

七本账名称固定，不增删、不合并：

1. `reproduction`：代码、命令、环境、硬件与输入可复现性。
2. `contract`：数学语义、shape/dtype/layout、owner、有效区与 reference。
3. `bottleneck`：固定三表、目标层级 exposed cost、slowest rank 与理论上限。
4. `hypothesis`：单一机制、因果链、预期收益、反证和停止条件。
5. `implementation`：文件/符号、接线、gate、fallback、同步、生命周期和 diff 范围。
6. `validation`：逐级 correctness、负例、最坏 shape、目标层级性能与统计。
7. `resource-risk`：显存、寄存器、shared memory、occupancy、编译、拓扑、可移植性、回滚与结论。

字段、状态和更新规则见 reference。账本是证据索引，不是散文日志。

## 路由规则

- profiler、trace 解析、kernel/overlap/fuse 归因：`llm-torch-profiler-analysis`
- activation 与低比特量化融合：`activation-quant-fusion-engineer`
- NVFP4 dispatch 到 expert-major pack：`nvfp4-dispatch-pack-engineer`
- bounded-key sort-pack 或 indexed gather-reduce：`indexed-pack-reduce-fusion-engineer`
- CUDA stream、Event、chunk、collective overlap：`cuda-stream-pipeline-engineer`
- GPU offload、H2D prefetch、residency：`gpu-offload-prefetch-engineer`
- persistent device schedule、task table、epoch/ring：`persistent-schedule-engineer`

不得因为某个专门 skill 不适用而强行修改其入口条件；回到账本，重写主假设或停止。

## 输出契约

```yaml
scope:
primary_route:
secondary_routes: []
seven_ledgers:
  reproduction:
  contract:
  bottleneck:
  hypothesis:
  implementation:
  validation:
  resource-risk:
profiler_evidence:
  source_skill: llm-torch-profiler-analysis
  kernel_table:
  overlap_opportunity_table:
  fuse_pattern_table:
diff_summary:
acceptance:
  hard_gates:
  result: ship | continue | stop | blocked
remaining_risks:
next_action:
```

## 结论语义

- `ship`：所有硬门禁通过，目标层级收益成立，资源不回退，diff 可审计且 fallback 可用。
- `continue`：机制仍成立，但证据、覆盖或收益不足；必须给出下一条最小实验。
- `stop`：假设被反证、目标层级无收益、correctness/资源失败，或更改不值得保留。
- `blocked`：缺硬件、权限、输入、reference 或可复现环境；列出解除阻塞所需的最小信息。

禁止用“kernel 更快”“测试通过”或“trace 看起来更好”单独得出 `ship`。
