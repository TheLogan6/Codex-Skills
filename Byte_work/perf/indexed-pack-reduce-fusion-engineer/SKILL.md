---
name: "indexed-pack-reduce-fusion-engineer"
description: "Implements bounded-key sort-pack and indexed gather-reduce fusion. Invoke for argsort/bincount metadata, gather/unpermute, segment reduction, or collective input layouts."
---

# Indexed Pack/Reduce Fusion Engineer

面向由索引驱动的 metadata pack 与 return reduce 两类 GPU 数据链，完成代码分析、融合实现、逐级验证和 diff 验收。两条子路径可独立优化，不要求同时修改。

## 输入契约

先固定以下事实；未知项写 `unknown`，不得猜测：

```yaml
repository: <repo>
revision: <revision>
target_symbols: []
path: metadata | return | both
shapes:
  rows: <M>
  destinations: <R>
  hidden: <H>
  key_domain: <K>
dtypes:
  values: <dtype>
  gates: <dtype>
  indices: <dtype>
layouts:
  source: <shape-stride-owner>
  destination: <shape-stride-owner>
reference: <callable-or-command>
correctness: exact | bitwise-to-named-reference | tolerance
mutation_policy: read-only | implementation-allowed
```

若缺少 reference、目标调用点或 production shape，只能给出分析与实现草案，结论不得超过 `continue`。

## 先区分两条链

```text
metadata path:
  bounded key → stable order → bucket counts → packed metadata/wire layout

return path:
  indexed source rows → gate/product → destination grouping
  → ordered segment reduction → terminal/collective input layout
```

先读 [references/code-analysis.md](references/code-analysis.md)，画出每个索引的定义域、值域、owner 和排序性质。禁止仅凭变量名推断 `pair_idx`、`scatter_index` 或 destination row 的含义。

## 主工作流

1. **证明路径命中**：定位入口、feature gate、fallback、实际调用类与一次性 engagement 证据。
2. **重建 baseline**：记录 producer/consumer、shape、stride、dtype、owner、materialization、launch 和 host sync。
3. **证明融合适用**：
   - key 值域远小于 pair 数时，评估 histogram/scan/stable scatter；
   - 连续 gather/permutation 只服务一个 consumer 时，合成索引并直写终态布局；
   - reduction 必须有可复现的 destination order 和数值边界。
4. **估算上限**：只计入实际 exposed 的排序 pass、HBM 中间张量、launch 与 host block。
5. **实现最小 candidate**：遵守 [references/implementation.md](references/implementation.md)，保留 reference、fallback 和 feature gate。
6. **运行正反场景**：使用 [references/cases.md](references/cases.md) 检查稳定性、舍入、资源和“不适用”条件。
7. **逐级验收**：按 [references/validation-and-diff.md](references/validation-and-diff.md) 从 kernel 到 collective 后结果与目标层级性能。

## 必守不变量

- stable sort 的稳定性是语义，不是性能选项；同 bucket 内保持原始 pair 顺序。
- `counts` 正确不代表 metadata 正确；必须比较完整 packed rows 和顺序。
- bitcast 是原始位模式搬运，不得替换成数值 cast。
- 合成置换前分别写清 `src(m)` 与 `dst(m)`，并验证 dropped sentinel。
- 删除中间 tensor 后，显式恢复其 dtype rounding；例如先把 product 回落到 value dtype，再按原顺序 FP32 累加。
- segment 输入若依赖有序 destination，candidate 必须证明该有序性或显式构造边界。
- output 预清零、空 segment、重复 destination、ragged tail 和非整 hidden 都是契约的一部分。
- 只优化 send metadata 不得被描述为同时优化 return；两条子路径独立验收。

## 实现选择

### Sort-pack

当 key domain 小且静态时，优先：

```text
per-block histogram
→ bucket totals + exclusive prefix
→ per-block bucket offsets
→ stable scatter directly into packed output
```

如果 key domain 大、动态、稀疏到 histogram workspace 不经济，或稳定顺序无可并行实现，则保留通用排序。

### Gather-reduce-layout

当链路为单一 consumer 且目标 row 已排序时，优先：

```text
source = values[scatter_index[m]]
product = round_to_reference_dtype(source * gate[m])
acc[destination[m]] += fp32(product)
store directly to terminal layout
```

若 source 被多个 consumer 复用、目标无序需要高冲突原子操作、或 reduction order 不能合法改变，则拒绝融合或缩小范围。

## 输出

```yaml
baseline_chain:
index_contract:
exposed_cost:
selected_path: sort-pack | gather-reduce-layout | both | reject
semantic_invariants:
implementation_files:
fallback_and_gate:
validation_evidence:
diff_scope:
result: ship | continue | stop | blocked
remaining_risks:
```

只有 reference 精确门禁、目标调用点接线、目标层级性能、资源与显存均通过时才可 `ship`。正确性失败、目标层级无收益或资源回退时 `stop`；证据尚缺但机制成立时 `continue`；缺硬件、输入、权限或 reference 时 `blocked`。
