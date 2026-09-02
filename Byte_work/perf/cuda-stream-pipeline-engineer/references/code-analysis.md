# 代码分析：Chunk、Stream、Event、Collective 与 Lifetime

## 1. 从 Serial Reference 开始

先定位实际入口、路径选择与 fallback，再把串行链拆成 stage：

```text
host preparation
→ A: input preparation / dispatch / transfer
→ B: compute
→ C: return / postprocess
→ final consumer
```

对每个 stage 记录：

| Stage | Inputs/Outputs | Stream | Producer/Consumer | GPU resource | Host work | Collective/group | Duration/exposed |
|---|---|---|---|---|---|---|---|
| A | | | | | | | |
| B | | | | | | | |
| C | | | | | | | |

同时搜索：

- 路径选择条件、互斥模式和一次性 engagement log；
- stream 创建位置和生命周期；
- Event 的创建、record、wait；
- `record_stream`、显式引用、buffer pool 和 slot；
- `.item()`、`.tolist()`、`.cpu()`、pageable copy、device-wide synchronize；
- collective 的 group、输入 split、输出 owner 和全 rank 调用次序；
- 最后 consumer 在哪个 stream 上读取。

## 2. 画 Dependency DAG

每条边必须标注原因，不只画先后顺序：

```text
producer data-ready
  └─event→ auxiliary stage reads input
auxiliary stage output-ready
  └─event→ main stage consumes output
main stage output-ready
  └─event→ return stage reads buffer
return completion
  └─event→ final consumer / reuse / function return
```

边的类型：

- RAW：consumer 读取 producer 写入；
- WAR：下一轮写入必须等上一轮读取完成；
- WAW：复用 slot 的两次写入必须定序；
- collective program order：不同 rank 必须一致；
- host dependency：split size、shape、plan 或动态分支需要 CPU 结果；
- allocator lifetime：Python 引用结束不等于异步 stream 已用完。

Event 只解决 stream 间执行依赖。`record_stream` 只延长 caching allocator 对 storage 的使用期。两者不能互相替代。

## 3. 证明 Chunk Axis 合法

对候选轴回答：

1. 每个 chunk 是否能独立构造输入、metadata 和输出 slice？
2. chunk-local index 如何映射 global index？
3. reduction、normalization、quant scale、随机数或状态是否跨 chunk？
4. ragged tail 是否改变 shape、collective 次数或算法？
5. 所有 rank 是否得到一致 chunk program，包含 empty rank？
6. 1 chunk 是否与 serial reference 等价？
7. chunk 改变 GEMM/attention tile、weight locality 或 cache reuse 吗？

常见 split-invariant 形式：

```text
row-local transform: f(concat(chunks)) == concat(f(chunk_i))
independent slices: output[s:e] depends only on input[s:e]
fixed-order reduce: partial chunks can combine only under named order/criterion
```

若量化 scale 跨整 tensor 求 amax，或 normalization 跨 chunk 轴，则不能直接切分。

## 4. Collective Program

对每个 communicator 写出所有 rank 的静态 program：

```text
rank r: A0, A1, C0, A2, C1, ..., C_last
```

检查：

- collective 类型、数量、group 和顺序完全一致；
- 数据相关分支不能导致某 rank 跳过；
- empty payload 也调用合法 collective 或统一走预先约定的 no-op；
- communicator 内操作若本就串行，多建 stream 不会增加网络并发；
- group 是正确 subgroup，不是恰好可运行的更大 group；
- dynamic split 的 host side 信息不会在某 rank形成不同控制流。

集体通信 hang 时，优先检查 program/group/shape，再怀疑 kernel。

## 5. Head、Steady、Tail

单独量化：

```text
head   = first consumer 前无法隐藏的准备与首次通信
steady = 相邻 chunks 之间可重叠区
tail   = last compute 后的 return/drain/final wait
```

理论上限：

```text
overlap saving ≤ min(independent compute window, hideable communication)
pipeline latency ≈ head + steady critical path + tail + new overhead
new overhead = extra launches + events + smaller-kernel loss + host work
```

不能用 `sum(stage duration) - wall time` 之外的猜测声称 overlap；必须看 trace 中时间区间和资源共驻。

## 6. 资源分析

为每个 stage 标注：

- SM/CTA；
- Tensor Core；
- HBM bandwidth；
- L2/cache；
- copy engine；
- NIC/P2P fabric；
- launch/CPU feed。

两个 stage 在不同 stream 上仍可能因以下原因串行：

- compute kernel 占满所有 active CTA slots；
- 两者均 memory-bound；
- collective kernel runnable 得太晚；
- stream priority 不能抢占已驻留 CTA；
- host 未及时提交；
- 隐藏同步阻断；
- communicator 内部强制序列化。

## 7. Lifetime 与内存

列出每个在途 tensor：

| Buffer | Allocate stream | Writer | Readers | Last-use Event | Reuse condition | Bytes |
|---|---|---|---|---|---|---|
| input chunk | | | | | | |
| dispatch payload | | | | | | |
| metadata | | | | | | |
| compute output | | | | | | |
| return payload | | | | | | |

同时记录：

- Python reference lifetime；
- `record_stream` 的每个 consumer；
- slot epoch/parity；
- framework allocated/reserved；
- driver-visible memory；
- collective/internal buffer；
- 多 stream allocator pool。

平均显存不够，必须测最坏 shape 和 hottest rank。

## 8. 输出分析结论

```yaml
engaged:
serial_chain:
dependency_edges:
chunk_axis_and_proof:
collective_program:
head_ms:
steady_ms:
tail_ms:
hideable_window:
resource_conflicts:
hidden_host_sync:
buffer_lifetimes:
theoretical_ceiling:
selected_schedule:
rejected_schedules:
```
