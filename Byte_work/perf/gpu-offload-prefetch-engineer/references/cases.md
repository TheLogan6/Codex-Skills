# Offload / Prefetch 案例

以下案例均为匿名通用模式，不携带项目、机器、提交或真实性能数字。

## 成功案例：expert-split 降低 H2D 次数

**现象**

单个 layer 的专家权重无法常驻，原路径对每个 token chunk 重新遍历并加载全部 weight chunks；总线忙且 consumer 经常等待。

**根因**

循环顺序为 `token_chunk → weight_chunk`，同一权重每层搬运次数等于 token chunk 数。scale 另走一条路径，产生额外等待。

**方案**

- 改为 `weight_chunk → relevant token_chunks`；
- 预先构造 routing 到 weight chunk 的索引；
- weight 与 scale 同分片进入 pinned flat pack；
- 双 slot：slot 写入等待上一代 compute-done，consumer 等本代 H2D-done；
- 空 chunk 跳过 compute 但保持状态机一致。

**证据**

- per-unit H2D 计数从每 token chunk 一次降为每层一次；
- weight、scale、downstream output 满足声明的正确性标准；
- trace 显示 copy 与独立计算窗口重叠；
- 最热 rank 的三类显存指标均低于 guard；
- layer 和端到端收益超出噪声。

**结论**

`ship`，前提是循环换序未导致 activation live range 越过 guard。

## 成功案例：部分驻留而非全 pin

**现象**

全 offload 容量安全但存在无法隐藏的短尾；全 resident 超出容量。

**根因**

少数高复用或大对象的 H2D 难以隐藏，其余对象可在前一阶段计算中完成 copy。

**方案**

按 `avoided_exposed_H2D / resident_bytes` 排序，只常驻收益最高的完整协议单元；其余继续双缓冲 streaming。策略进入 cache/store fingerprint。

**证据**

最坏 shape 有安全余量；常驻集合的 H2D 计数为零；streamed 集合次数符合预期；目标层级更快且 feature-off 与 baseline 等价。

**结论**

`ship`，并固定 residency policy 的版本和回退路径。

## 失败案例：增加 stream 触发 allocator cliff

**现象**

两个独立序列被放到不同 stream 后，短 shape 更快，长 shape OOM；静态 tensor 大小之和看似未超预算。

**根因**

跨 stream 安全延长了 activation 生命周期，并引入额外 allocator pool；预取 slot 与通信 slab 在峰值点同时 live。

**方案**

绘制 Event 边界 live-range，采集 allocated/reserved/driver-visible 峰值；减少 prefetch depth、共享 slot 或退回单 stream。

**证据**

新 stream 的峰值超过 guard；OOM 与 driver-visible 峰值一致；删除 stream 后容量恢复。

**结论**

当前 diff `stop`。不能以短 shape 性能为由合入。

## 失败案例：prefetch 后立即 wait

**现象**

代码有 copy stream、Event 和 `non_blocking=True`，但 layer 时间不变。

**根因**

prefetch 在 consumer 前才发起，consumer 立即等待；独立计算窗口为零。新增 Event 只增加 launch/host 开销。

**方案**

将 issue 前移到上一阶段；若数据直到 consumer 前才可知，则取消异步复杂度。

**证据**

timeline 中 H2D 与 compute 无重叠，exposed tail 等于 copy duration；前移后才出现覆盖。

**结论**

无法前移则 `stop`；可前移但尚无高层证据则 `continue`。

## 失败案例：双缓冲 slot 被提前覆盖

**现象**

单层正确，多层或压力测试偶发数值错误；加 device synchronize 后消失。

**根因**

实现只用了 `slot = layer % 2` 和 H2D-done，没有让下一次 copy 等待上一代 compute-done，形成 WAR。`record_stream` 被误当成同步。

**方案**

增加 slot generation 与 compute-done Event；写 slot 前等待最后 consumer，测试中注入 copy/compute 延迟扩大竞态窗口。

**证据**

竞态测试稳定复现旧实现错误；新实现无全局同步且长期复用 exact。

**结论**

旧 diff `stop`；修复并通过压力门禁后重新评估。

## 不适用案例：权重已常驻且 H2D 不在关键路径

**现象**

显存余量充足，profile 中目标层没有 H2D，瓶颈是计算或通信。

**根因**

offload/prefetch 与 observed bottleneck 无关；引入它只会增加 host memory、copy 和状态管理。

**方案**

记录拒绝理由，转向真实 exposed bottleneck。

**证据**

H2D ledger 为零或传输完全隐藏；理论上限接近零。

**结论**

`stop`，不实现 offload。
