---
name: "cuda-stream-pipeline-engineer"
description: "Builds chunked CUDA stream pipelines for compute, communication, and transfer overlap. Invoke for Stream/Event scheduling, collectives, deferred drains, or lifetime bugs."
---

# CUDA Stream Pipeline Engineer

面向通信、计算和搬运的 chunked CUDA pipeline，建立依赖正确、collective 顺序一致、生命周期安全且由 trace 证明有效的 overlap 实现。

## 输入契约

```yaml
repository: <repo>
revision: <revision>
entrypoint: <symbol-or-command>
serial_reference: <symbol-or-command>
stages: []
chunk_axis: <axis-or-unknown>
shapes: {}
dtypes: {}
streams:
  main: <stream>
  auxiliary: []
collectives:
  groups: []
  program_order: []
hardware:
  gpu: <gpu>
  topology: <topology>
correctness: exact | bitwise-to-named-reference | tolerance
mutation_policy: read-only | implementation-allowed
```

未知项必须标记，不得从“代码用了多个 stream”推断已经 overlap。

## 主流程

1. 用 [references/code-analysis.md](references/code-analysis.md) 重建 serial chain 和 dependency DAG。
2. 证明存在 split-invariant 的 chunk 轴；列出跨 chunk 状态和 collective 约束。
3. 将 timeline 分为 head、steady state、tail，量化实际 exposed 时间和理论 overlap 上限。
4. 为每个 stage 标注 SM/Tensor Core、HBM、copy engine、NIC/P2P、host launch 等资源。
5. 固定所有 rank 在每个 communicator 上的 collective program order。
6. 按 [references/implementation.md](references/implementation.md) 实现 main/comm/prefetch stream、Event、ownership 和 deferred drain。
7. sweep chunk count/size，而不是把某个值当算法常数。
8. 用 [references/cases.md](references/cases.md) 主动验证有效、失败和不适用场景。
9. 按 [references/validation-and-diff.md](references/validation-and-diff.md) 验收 split、timeline、slowest rank、资源、显存和 Git diff。

## 三个核心不变量

### 1. 数学与切分不变量

- 每个 chunk 的 logical input/output slice 完整且不重叠；
- chunk-local index 与 global index 的转换明确；
- codec、normalization、reduction 或随机状态若跨行/跨 chunk，不得假定 split-invariant；
- 1 chunk 必须可回退 serial reference。

### 2. Collective 顺序不变量

- 同一 communicator 上所有 rank 发出相同 collective 类型、数量和顺序；
- empty rank 也不能擅自跳过 collective；
- chunk bounds 若不同，仍必须生成等价的全局 program order，否则 fail-fast；
- process group 必须与数据 owner/topology 匹配。

### 3. 跨 Stream 生命周期不变量

- Event 表达执行依赖：producer record，consumer wait；
- `record_stream` 表达 allocator 使用期，不建立执行依赖；
- buffer 复用必须同时防止 RAW、WAR、WAW；
- 函数返回、后续 consumer 或 Python 引用释放前，最后写入必须对目标 stream 可见；
- pinned/pageable host memory 与 non-blocking copy 的条件必须明确。

## 设计目标

典型三阶段：

```text
A: metadata / dispatch / H2D / input collective
B: compute
C: return collective / D2H / postprocess
```

稳态可尝试：

```text
comm:    A0   A1   C0/A2   C1/A3   ...   C_last
main:         B0      B1      B2    ...
```

优先准备下一块输入通常能避免 compute 饥饿，但具体 `A(i+1)` 与 `C(i)` 的次序必须由依赖、collective 顺序和 tail 成本决定。代码结构不等于硬件共驻，最终以 timeline 为准。

## 进入与停止条件

适用：

- serial 链中有显著 exposed communication/transfer；
- 存在独立且 split-invariant 的计算窗口；
- stage 主要资源不同，有共驻可能；
- chunk 后的 compute/collective 仍有足够效率；
- 增加的 live range 在显存 guard 内。

拒绝或停止：

- 单 chunk、极小 workload 或 fixed latency 主导；
- stage 真实依赖无法跨 chunk 解开；
- collective order 依赖数据分支；
- compute 已占满资源，auxiliary kernel 无法共驻；
- chunk 后 GEMM/算子效率损失大于 overlap；
- driver-visible memory、allocator pool 或在途 buffer 越过 guard；
- 只有 event timing，没有 trace 中的 overlap 与目标层级收益。

## 输出

```yaml
serial_chain:
dependency_dag:
chunk_invariance:
collective_program:
event_edges:
buffer_ownership:
head_steady_tail:
resource_map:
chunk_sweep:
trace_evidence:
correctness_gates:
diff_scope:
result: ship | continue | stop | blocked
remaining_risks:
```
