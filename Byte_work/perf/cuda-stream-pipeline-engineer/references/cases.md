# 正反案例：CUDA Stream Pipeline

每个案例采用“现象 → 根因 → 方案 → 证据 → 结论”。

## 正案例 A：Dispatch / Compute / Return 三阶段流水

**现象**：串行路径中 input collective、compute、return collective 顺序相加，网络和 Tensor Core 分时闲置。

**根因**：整批数据是唯一依赖单元；相邻数据块实际上独立，但没有可流水粒度。

**方案**：沿 split-invariant row 轴切 chunk；comm stream 运行 A/C，main stream 运行 B。先发 `A(i+1)`，再在 `B(i)` 完成后发 `C(i)`，通过 Event 建立 RAW 边。

**证据**：

- 1 chunk 与 serial reference exact；
- 多 chunk、ragged tail、empty rank 通过；
- 全 rank collective program digest 一致；
- trace 中 `A(i+1)` 与 `B(i)`、`C(i)` 与后继 compute 实际重叠；
- slowest-rank layer 延迟下降；
- peak allocated/reserved/driver memory 在 guard 内。

**结论**：可 `ship`。

## 正案例 B：Deferred Drain 隐藏返回后处理

**现象**：return collective 后还有 destination-local decode/reduce，若立即在 main stream 等待会截断下一块 compute。

**根因**：postprocess 只依赖当前块 collective 输出，不是下一块 compute 的前置条件。

**方案**：comm stream 完成 return 后记录 Event；先排 `B(i+1)`，再在 main stream wait 并 drain `i`。最后一块显式 drain。

**证据**：

- source accumulation order 与 serial reference 固定一致；
- output slice 在最终 consumer 前完成；
- trace 显示 return 获得完整 compute 窗口；
- 没有跨块覆盖、悬空引用或尾块遗漏。

**结论**：机制与目标层级收益都成立时 `ship`。

## 正案例 C：共享 Comm Stream

**现象**：每层都创建 auxiliary stream，trace lane 膨胀且 driver memory 增加，但同 communicator 上 collective 仍串行。

**根因**：stream 数量增加没有创造新的 communicator 并行，只增加 Event、allocator ownership 和调度复杂度。

**方案**：使用 process-wide per-device shared comm stream，保持全局 collective 顺序。

**证据**：collective program 不变，timeline 更易追踪，stream 数和 driver memory 降低，性能不回退。

**结论**：可作为最小生命周期修复合入。

## 反案例 A：有 Event，但没有 Overlap

**现象**：代码中存在两条 stream 和正确 Event，事件计时也都正常，目标延迟却没有改善。

**根因**：高占用 compute kernel 填满 CTA slots，communication kernel 虽已 enqueue 但无法驻留；或两者竞争 HBM。

**方案**：查看 kernel arrival 与 active 区间、occupancy、HBM 和通信 CTA。尝试更早发通信、缩短/拆分 compute、降低资源占用；若仍无共驻则回到 serial。

**证据**：trace 中 lanes 重叠排队但 GPU active 区间不重叠，collective 实际起点在 compute 结束后。

**结论**：当前优化 `stop`。Event 正确只证明依赖正确，不证明性能。

## 反案例 B：Chunk 更小反而更慢

**现象**：增加 chunk 数后 first-ready 更早，但层延迟上升。

**根因**：collective/launch/Event 固定成本增加，compute 的 M 变小，tile 利用率和 weight locality 下降，head/tail 占比提高。

**方案**：sweep 而不是单向缩小；把 chunk policy 与 compute tile quantum、payload 下限和显存约束联动。

**证据**：trace 显示更多 launch gap、小 GEMM 效率下降，新增 overhead 大于隐藏时间。

**结论**：该 chunk 点 `stop`；可能保留更大的 operating point。

## 反案例 C：多 Stream 引发显存 Cliff

**现象**：framework allocated 变化不大，但长 shape 出现 OOM 或 driver-used 大幅上升。

**根因**：多个在途 chunk 延长 live range，collective/internal buffers、Event 和 per-stream allocator pool 未体现在单一 allocated 指标中。

**方案**：画 live-range，减少在途深度、共享 stream、复用 slot，测 allocated/reserved/driver-visible 与 hottest rank。

**证据**：将 pipeline depth 降低或共享 stream 后 driver memory 回落且 OOM 消失。

**结论**：超过 guard 的版本 `stop`，即使短 shape 更快。

## 反案例 D：Collective 顺序分叉

**现象**：单卡正确，多 rank 偶发 hang；某些 rank 本地 chunk 为空。

**根因**：空 rank 跳过了 collective，或依据本地数据动态选择 A/C 顺序，同 communicator 上 program 不一致。

**方案**：由全局一致配置生成 program；空 payload 仍参加；运行前交换/比较 sequence digest。

**证据**：各 rank trace 或日志显示首个不同 collective ordinal。

**结论**：`stop`，这是 correctness/deadlock 问题，不是性能抖动。

## 不适用案例：无独立窗口

**现象**：希望把 producer 和唯一 consumer 放到不同 stream。

**根因**：consumer 需要 producer 的完整输出，切分轴又会改变 normalization/reduction domain；不存在独立 work。

**方案**：考虑 kernel fusion、算法分块重写或减少 bytes，而不是加 stream。

**证据**：DAG 中每个 candidate overlap 边都有 RAW 依赖，理论隐藏窗口为零。

**结论**：`stop`，pipeline 不适用。

## 审查用追问

- 具体隐藏了哪一段，理论上限是多少？
- chunk 是否对量化、归一化、reduction 和随机状态不变？
- 每个 communicator 的完整 ordinal 序列是什么？
- Event 的 producer/consumer 方向是否正确？
- `record_stream` 覆盖了哪些 storage，是否被误当同步？
- 最后一块何时 drain？
- slot 何时可复用，谁发 consumed Event？
- CPU launch lane 是否被 scalar D2H 阻塞？
- trace 中是实际 active overlap，还是仅不同 lane 排队？
- slowest rank 和 driver-visible memory 是否通过？
