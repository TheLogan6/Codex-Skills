---
name: "persistent-schedule-engineer"
description: "Analyzes and implements persistent device-driven schedules. Invoke for task tables, epochs, ring buffers, device flags, launch overhead, pipeline head/tail, or topology-aware peer transport."
---

# Persistent Schedule Engineer

分析并实现 persistent device-driven schedule：不是简单把一个 kernel 常驻，而是把 plan、dispatch、compute、return、unpack 的依赖、任务表、跨设备完成协议和 buffer 复用编码成可验证的调度系统。

## 输入契约

```yaml
repository: <repo>
revision: <revision>
target: {files: [], symbols: [], commits: []}
baseline: {command: null, schedule: null}
candidate: {command: null, schedule: null}
workload: {shapes: {}, dtype: null, chunks: null, phases: []}
parallelism: {world: null, subgroup: null, rank_mapping: null}
topology: {nodes: null, switch_domains: null, peer_paths: null}
codec: {wire_format: null, reference: null}
correctness: {criterion: bitwise | exact | tolerance | quality | unspecified}
mutation_policy: read-only | implementation-allowed
```

未知项写 `unknown`。不得根据变量名猜 process group、owner 或 transport。

## 进入条件

仅当以下条件都有证据时进入实现：

- 普通 kernel fusion 与 stream pipeline 已分析；
- 剩余 exposed bottleneck 是 head/tail、host sync、固定 launch 或 CTA arrival；
- task 序列可编码为有界 device-side table；
- buffer owner、slot、epoch、复用条件可定义；
- topology 和 peer addressing 可在启动时校验；
- 存在可逐 level 比较的 production reference。

否则记录拒绝理由并 `stop` 或路由到更低风险方案。

## 完成定义

```yaml
baseline_schedule:
exposed_head_tail:
task_protocol:
epoch_and_slot_invariants:
topology_contract:
implementation_scope:
per_level_validation:
performance_and_memory:
diff_result: ship | continue | stop | blocked
remaining_risks:
```

## 工作流

### 1. 重建 baseline schedule

阅读 [references/code-analysis.md](references/code-analysis.md)。从调用入口画出：

```text
plan → dispatch → expand/pack → compute → return → unpack
```

逐 stage 记录 producer/consumer、stream、owner、通信组、host sync、task 粒度、buffer last use、head/steady/tail 和 slowest-rank arrival。

### 2. 判断 persistent 是否解决真实瓶颈

计算普通 pipeline 的剩余：

```text
head = first dispatch + plan + host gaps
steady = max(compute, overlappable transfer) + contention
tail = final return + unpack
```

若瓶颈是算力、wire bytes、负载倾斜或单 kernel 效率，先解决对应问题；不要用 persistent 掩盖。

### 3. 定义协议

阅读 [references/implementation.md](references/implementation.md)，明确：

- one-chunk skew：compute(i) 与 return(i-1)/dispatch(i+1) 的关系；
- routing-independent work 能否安全前移；
- plan stage 1/2 的输入、输出和唯一 host sync；
- task row schema、cursor、任务顺序与 deadlock 约束；
- device flag 的 memory scope、release/acquire、单调 epoch；
- NIC/IPC/peer transport 的 fence、signal、quiet 和 free acknowledgment；
- payload slab parity 与 plan slot depth；
- ring grow 的同步点及 stale slot/ABA 防护；
- topology/capability/import/init gate；
- host fallback 与普通 pipeline 互斥。

### 4. 最小实现

```text
host task-table simulation
→ plan local-mode reference
→ 单设备逐 kernel gate
→ 单 peer transport + flags
→ 单 chunk schedule
→ 多 chunk + slab reuse
→ 多 layer + epoch reuse
→ phase transition + ring grow
→ subgroup / full group
→ target topology
```

高风险路径默认关闭。保留 production reference、feature gate、fallback 和 engagement log。

### 5. 案例与停止条件

阅读 [references/cases.md](references/cases.md)。案例统一使用：

```text
现象 → 根因 → 方案 → 证据 → 结论
```

kernel 独立变快但 layer 不变、错误 topology/bootstrap、ring slot 被覆盖、GEMM/codec reference 不一致都必须作为停止条件处理。

### 6. 逐级验证与 diff

阅读 [references/validation-and-diff.md](references/validation-and-diff.md)，按顺序：

```text
plan
→ task table / strip table
→ expand
→ GEMM
→ activation/quant
→ pre-sum/codec
→ unpack
→ single chunk
→ multi chunk
→ multi layer
→ phase transition
→ full group
→ subgroup
→ target topology
```

所有 level 必须具名 reference。纯 schedule/layout 替换优先 exact；不同 GEMM accumulation order 或不同 codec 不得错误宣称 bitwise。

## 强制原则

- task table 是协议，不是普通优化参数；host 与 device 常量必须单源或静态校验。
- epoch 必须单调并与 slot generation 绑定；只用 parity 无法防 stale completion。
- ring depth 由同时 live 的对象数决定，不能用简单取模掩盖容量不足。
- device flag 必须成对定义 release/acquire scope；payload 完成与 source 可复用是两个不同条件。
- transport 选择由 topology 和 capability 决定，错误配置应 fail-fast。
- stream priority 不会抢占已驻留 CTA；arrival order 必须由 trace 证明。
- persistent 的收益在完整 schedule/layer/slowest rank 上验收，不从 microkernel 外推。
- persistent 与普通 pipeline 同时开启必须明确拒绝，除非组合协议经过独立设计与测试。
