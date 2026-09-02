# 七本账

七本账用于把事实、推断、实现和结论分离。每条记录使用稳定 ID，证据以路径、命令、哈希或报告段落定位；未知事实写 `unknown`，不得留空后靠推测补齐。

## 通用记录格式

```yaml
id: <ledger-prefix>-NNN
status: open | supported | refuted | passed | failed | blocked | superseded
claim: <单一可证伪陈述>
evidence:
  - kind: code | command | trace | test | benchmark | resource | diff
    locator: <path-symbol-command-or-artifact>
    observation: <直接观察>
comparability: <为何可比较，或 unknown>
owner: <role-or-skill>
updated_at: <ISO-8601>
next_check: <最小下一步>
```

`claim` 不得混合多个因果判断。`observation` 只写观察，不把解释伪装成事实。

## 1. reproduction

前缀：`REP`

记录：

- repository、revision、dirty state；
- baseline/candidate 的完整命令、环境变量和 feature flags；
- GPU 型号/数量、拓扑、驱动、CUDA、编译器和关键依赖；
- workload 的 shape、dtype、分布、phase、warmup、迭代和 seed；
- artifact 路径与内容哈希；
- 重复运行的离散度及机器占用条件。

门禁：不能在同一硬件、同一 workload 和等价环境下复现时，性能结论最多为 `blocked` 或 `continue`。

## 2. contract

前缀：`CON`

记录：

- 调用入口、producer/consumer 和实际命中路径；
- 输入输出的逻辑含义、shape、stride、dtype、layout、owner；
- 有效区、padding、sentinel、empty/ragged 行为；
- reduction/quantization/randomness 的顺序与舍入边界；
- 命名 reference 和 correctness criterion；
- collective group/order、stream/Event 和 buffer lifetime（如适用）。

门禁：reference 未命名、有效区不清或 owner 不清时，禁止实现不可逆替换。

## 3. bottleneck

前缀：`BOT`

只接受两类证据：

1. 目标层级的端到端或 block/layer 测量；
2. 同级 `llm-torch-profiler-analysis` 产出的固定三表。

固定三表必须原样保留名称与含义：

- kernel table
- overlap-opportunity table
- fuse-pattern table

账中引用三表的行、阶段和阈值，不复制 profiler 实现，不衍生第四张 profiler 表。另行记录：

- exposed cost，而非仅累计 GPU time；
- prefill/decode 或其他 phase；
- slowest rank 和 rank spread；
- launch、host gap、HBM、compute、copy、NIC/P2P 等资源；
- 理论收益上限和测量误差。

门禁：热点若已被 overlap、未命中目标调用点或上限小于噪声，停止该假设。

## 4. hypothesis

前缀：`HYP`

每个候选只保留一个 primary hypothesis：

```yaml
mechanism: <fusion | layout | overlap | residency | persistent-schedule | other>
cause_chain: <现象 -> 根因 -> 改动 -> 目标层级收益>
predicted_effect:
  metric: <metric>
  lower_bound: <value-or-unknown>
  upper_bound: <value-or-unknown>
disconfirming_evidence: []
stop_conditions: []
route: <specialist-skill>
```

若一个 diff 同时声称 fusion、overlap 和 offload 收益，拆分实验或指定唯一主假设，其余仅作风险项。

## 5. implementation

前缀：`IMP`

记录：

- 修改文件、符号和调用接线；
- reference、feature gate、fallback、engagement log；
- 索引、布局、同步、生命周期和错误处理；
- 生成代码、构建参数、测试与 benchmark 改动；
- 每个改动与 hypothesis 的对应关系；
- `scripts/summarize_diff.py` 的只读摘要。

门禁：未接线、无 fallback、夹带无关重构、修改 benchmark 以偏向 candidate，或 diff 无法映射到主假设时，不得 `ship`。

## 6. validation

前缀：`VAL`

按因果层级记录：

```text
helper/reference
→ 单算子
→ producer/consumer 边界
→ block/layer
→ 多 rank / 多 phase
→ 最坏 shape
→ 目标层级
→ 端到端
```

每层必须有：命名 reference、输入集、比较方式、结果、失败样例。性能记录必须包含 warmup、重复次数、统计量、slowest rank 和离散度。baseline 与 candidate 用 `scripts/compare_runs.py` 检查可比字段。

门禁：较低层通过不能代替较高层；只测 happy path、只报 best run 或只看平均 rank 时最多 `continue`。

## 7. resource-risk

前缀：`RSK`

记录：

- allocated、reserved 和 driver-visible device memory；
- workspace、live range、register、shared memory、occupancy；
- 编译时间、binary/cache 膨胀和 shape specialization；
- stream/allocator pool、graph capture、拓扑、collective deadlock；
- 不支持的 dtype/shape/GPU 和 fallback 行为；
- rollback 方式、默认开关和未决风险；
- 最终 `ship | continue | stop | blocked` 及理由。

门禁：达到显存 guard、最坏 shape 资源失败、回退不可用、风险无 owner 或结论无证据索引时，不得 `ship`。

## 更新顺序

每轮实验按以下顺序更新：

```text
reproduction → contract → bottleneck → hypothesis
→ implementation → validation → resource-risk
```

新证据反驳旧结论时，将旧记录标记为 `superseded` 或 `refuted`，不得删除历史。最终结论至少引用一个 `REP`、一个 `CON`、一个 `BOT`、一个 `HYP`、一个 `IMP`、一个 `VAL` 和一个 `RSK`。
