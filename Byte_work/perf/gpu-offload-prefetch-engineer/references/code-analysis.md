# Offload / Prefetch 代码分析

## 1. 从入口建立调用链

从真实 forward 入口而非工具类名开始，沿以下链路追踪：

```text
configuration
→ parameter classification
→ host backing-store construction
→ pinned registration
→ GPU slot allocation
→ prefetch trigger
→ H2D issue
→ consumer wait
→ compute
→ slot release/offload
→ unload/context reuse
```

同时画 baseline 与 candidate；标出新增、删除和移动的操作。搜索 forward pre/post hook、显式 prefetch API、参数 `.data`/view 重绑定、copy stream、Event、`record_stream`、cache 和 phase 切换。

## 2. 对象账本

逐对象填写，不能只列权重：

| 对象 | Shape/dtype | Bytes | Host/GPU owner | 创建 | 首次使用 | 最后使用 | Stream | 可复用条件 |
|---|---|---:|---|---|---|---|---|---|
| weight pack |  |  |  |  |  |  |  |  |
| quant scales/metadata |  |  |  |  |  |  |  |  |
| activation |  |  |  |  |  |  |  |  |
| workspace |  |  |  |  |  |  |  |  |
| communication slab |  |  |  |  |  |  |  |  |
| allocator reserve |  |  |  |  |  |  |  |  |

live range 使用“产生 Event/最后 consumer Event”描述，不以 Python 变量离开作用域代替。

## 3. H2D 账本

为每个逻辑 weight unit 记录：

```text
unit_id
layer / phase / expert-range
weight_bytes + scale_bytes + metadata_bytes
number_of_H2D
copy_stream
issue_timestamp
consumer_wait_timestamp
consumer_start
exposed_tail = max(0, H2D_done - consumer_ready)
```

总传输量：

```text
H2D_total = Σ_unit bytes(unit) × copies(unit)
```

若 token chunk 数为 `T`、weight chunk 数为 `W`：

- `for token in T: for weight in W:` 通常产生 `T×W` 次 weight H2D；
- `for weight in W: load once; for token in T:` 可降至 `W` 次，但会改变 activation live range；
- 选择前必须同时比较 H2D 次数与 activation 峰值。

## 4. 双缓冲状态审计

对每个 slot 建状态机：

```text
FREE
  --H2D starts--> WRITING
  --h2d_done--> READY
  --consumer starts--> READING
  --compute_done--> FREE
```

检查：

- `slot = item % 2` 只决定候选槽，不证明安全；
- WRITING 前必须等待该 slot 上一代的 `compute_done`；
- READING 前必须等待本代 `h2d_done`；
- epoch/item id 防止等待到旧 Event；
- 多 dtype pack 共享 slot 时，其完成条件覆盖全部 copy；
- view 重绑定不能让旧 consumer 看到新 backing buffer。

## 5. 预取窗口

画出：

```text
prefetch_issue ───── H2D ───── h2d_done
          [independent compute window]
consumer_ready ─ wait(if needed) ─ consumer
```

计算：

```text
hideable = min(H2D_duration, independent_window)
exposed_tail = max(0, H2D_duration - independent_window)
```

若 consumer 在发起 copy 后立即 wait，预取没有价值。若 copy 与 compute 竞争同一瓶颈资源，时间重叠也不等于收益。

## 6. 显存与 host memory

同时采集：

- framework allocated peak；
- framework reserved peak；
- 驱动可见 device memory；
- pinned host bytes；
- mmap/shared-storage bytes；
- 每个 stream 的 allocator pool 与 deferred frees；
- hottest rank，而非 rank 0 或平均值。

重点检查新 stream 是否延长 activation/weight 的生命周期，以及 cache 是否跨 phase 保留按最大 shape 分配的 buffer。

## 7. Residency 分析

按单位估算：

```text
benefit(unit) = avoided_exposed_H2D(unit) × reuse_count
cost(unit) = resident_bytes + induced_peak_overlap
```

优先常驻复用高、H2D 难隐藏、单位收益高的对象。weights、scales、zero-point 和布局描述必须一起分类，不能只 pin 主权重。

## 8. 隐藏同步与去项目化诊断

搜索并验证：

- `.item()`、`.tolist()`、Python scalar 写入 device；
- pageable host-to-device copy；
- hook 内 device synchronize；
- non-blocking copy 的 host memory 是否真正 pinned；
- allocator 生命周期是否用 `record_stream` 或显式 owner 管理；
- store 格式和 residency 策略是否有 fingerprint。

最终报告使用 `<repo>`、`<layer>`、`<unit>`、`<shape>`、`<rank>`，不复制项目名、私有开关、机器名、真实日志或提交标识。
