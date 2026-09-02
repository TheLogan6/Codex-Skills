# Offload / Prefetch 测试与 Diff 验收

## 1. 正确性门禁

### L0：pack 与 view

- 多 dtype、不同 shape、非连续原 tensor；
- offset 无重叠、对齐与总字节正确；
- host→GPU round-trip exact；
- weights、scales、metadata 同 version；
- empty pack、零长度 entry、尾分片；
- unload 后 view 恢复到合法 host backing。

### L1：单 slot / 双 slot

- 单层同步 reference 对 candidate；
- 两个 slot 连续交替；
- 人工延迟 copy 与 compute，扩大 RAW/WAR 窗口；
- generation/epoch 不接受旧 Event；
- `record_stream` 有/无不改变依赖正确性；
- 不依赖 device-wide synchronize 才正确。

### L2：composition

- offload on/off；
- residency `none / selected / all`；
- weight 与 scale 同步分片；
- token chunk × weight chunk 多种组合；
- zero/empty expert、skew、ragged tail；
- feature-off 回到原 production chain。

### L3：integration

- 多 layer、forward hook 或显式 API 调用；
- context cache 复用；
- phase 从小 shape 切到大 shape，再切回；
- unload/reload；
- 多 rank 中至少覆盖 hottest rank；
- 错误 store fingerprint、非法策略组合必须 fail-fast。

正确性标准必须具名：

```text
candidate <name> 对 reference <name>，
在 <shape/dtype/residency/topology> 下使用
torch.equal / 指定 tolerance / quality gate。
```

不得把改变 quant recipe 或 reduction order 的路径宣称为 bitwise。

## 2. H2D 与 timeline 门禁

为每个逻辑 weight unit 断言：

```text
observed_H2D_count == expected_H2D_count
observed_H2D_bytes == expected_bytes
```

至少提交：

- copy issue、done、consumer-ready、consumer-start；
- exposed tail；
- next-layer/next-chunk prefetch 是否落入预期窗口；
- 总线与 compute 是否资源竞争；
- consumer 是否仅在首个依赖点等待；
- pageable copy、`.item()`、`.tolist()` 等 hidden sync 审计。

代码中出现多 stream 不算 overlap 证据；必须用 timeline。

## 3. 显存门禁

在最坏 shape 和 hottest rank 上同时报告：

| 指标 | baseline | candidate | guard |
|---|---:|---:|---:|
| peak allocated |  |  |  |
| peak reserved |  |  |  |
| driver-visible device memory |  |  |  |
| pinned host bytes |  |  |  |
| staging/resident bytes |  |  |  |

容量判定：

```text
candidate_driver_peak + safety_margin <= usable_device_capacity
```

至少重复运行以覆盖 allocator/cache 稳态。只跑通一次且接近容量上限不能 `ship`。

## 4. 性能 A/B

- baseline/candidate 除单变量 patch 外一致；
- 同 session、交错 paired A/B；
- 固定输入、warmup、迭代、shape、dtype、topology；
- 每 rank 记录，报告 slowest rank；
- 分开报告 H2D、consumer wait、operator、layer/phase、端到端；
- 同时给出理论可隐藏上限与 trace 解释；
- 负收益和噪声内收益都要记录。

优化目标优先级：

```text
容量 guard
→ H2D 次数
→ exposed H2D tail
→ 目标层级 latency/throughput
```

## 5. Diff 清单

执行并检查：

```bash
git diff --name-status <baseline>..<candidate>
git diff --stat <baseline>..<candidate>
git diff --check <baseline>..<candidate>
```

逐文件确认：

- 参数分类、pack/store schema；
- slot 与 Event 状态机；
- prefetch/consumer/offload 接线；
- feature gate、互斥与 fail-fast；
- fallback 与 unload；
- H2D 计数和 engagement log；
- 单元、竞态、集成、最坏 shape 测试；
- benchmark、timeline、显存证据；
- 无无关重构、私有路径和真实实验数据。

硬拒绝项：

- 新 stream 无 lifetime/timeline 证据；
- 只比较最终输出，不测 slot 复用；
- 只看 framework allocated；
- 同一 weight 每层 H2D 次数增加且无高层收益解释；
- weights/scales/metadata 生命周期不一致；
- 容量超过 guard；
- fallback 不可用或非法组合 silent fallback。

## 6. 结论

```text
ship:
  正确性与竞态门禁通过；
  H2D/live-range 机制被计数和 trace 证明；
  最坏 shape/hottest rank 有安全余量；
  目标层级收益超出噪声；
  diff 最小且 fallback 完整。

continue:
  机制成立，但缺少目标拓扑、最坏 shape、长期复用或高层性能证据。

stop:
  正确性失败、slot 竞态、目标层级不提速、H2D 重复、
  显存越过 guard 或稳定性回退。

blocked:
  缺少必要硬件、输入、reference、权限或驱动级显存/trace 能力。
```
