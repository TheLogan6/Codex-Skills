# Persistent Schedule 代码分析

## 1. 先区分 persistent kernel 与 persistent schedule

- persistent kernel：一个 kernel 内循环处理多个工作单元。
- persistent schedule：plan、通信、compute、return、unpack、buffer 复用和跨设备完成条件共同组成 device-driven 协议。

若只找到长驻 GEMM 或 atomic tile cursor，不足以宣称完整 persistent schedule。

## 2. 从入口重建双调用链

同时画 baseline 与 candidate：

```text
configuration/capability gate
→ context construction/cache
→ topology/group creation
→ chunk policy
→ pre-work/prologue
→ plan stage 1
→ plan stage 2
→ task-table build/upload
→ persistent launch
→ compute
→ return/unpack
→ epilogue
→ context reuse/grow/destroy
```

查找 host runner、plan、kernel、transport bootstrap、模型接线和 schedule test。变量名不可信，必须确认 communicator 覆盖的实际 rank 集。

## 3. Stage 账本

| Stage | 输入/输出 | Owner | Stream | Host work | Device work | Sync | Exposed? |
|---|---|---|---|---|---|---|---|
| plan |  |  |  |  |  |  |  |
| dispatch |  |  |  |  |  |  |  |
| expand/pack |  |  |  |  |  |  |  |
| compute |  |  |  |  |  |  |  |
| return |  |  |  |  |  |  |  |
| unpack |  |  |  |  |  |  |  |

标出 head、steady、tail，以及每个 rank 的 arrival。最慢 kernel 不一定是 exposed critical path。

## 4. Task table 逆向

为每种 task type 记录：

| Type | 读 | 写 | Peer | 完成信号 | 前置条件 | Source reuse 条件 |
|---|---|---|---|---|---|---|
| send/put |  |  |  |  |  |  |
| local copy |  |  |  |  |  |  |
| wait-arrival |  |  |  |  |  |  |
| wait-free |  |  |  |  |  |  |
| fence/signal |  |  |  |  |  |  |
| quiet |  |  |  |  |  |  |

核对 host 编码常量与 device 解码常量；检查 task row 字宽、字段语义、index width、最大任务数、空任务和 cursor 越界。

任务顺序必须避免：

- 所有 CTA 先抽到等待任务而 producer task 无 CTA 可执行；
- signal 早于 payload visibility；
- source slab 在 nonblocking put 本地完成前复用；
- 同一 communicator/rank 的程序顺序不一致。

## 5. Epoch 与 device flags

对每个 flag 写清：

```text
address = kind × kind_stride + slot × slot_stride + source × source_stride + slice
value = monotonic_epoch
writer = <rank/task>
reader = <rank/task>
store = release at <scope>
load = acquire at <scope>
```

审计：

- epoch 是否在所有参与 rank 上按相同逻辑推进；
- 比较是 `==` 还是 `>=`，是否会错过已前进的 epoch；
- flag 是否与 payload 共用正确 memory scope；
- parity slot 是否同时携带 generation；
- wraparound 是否在可运行寿命内安全；
- context reuse 是否保留旧 flag。

## 6. Ring 与 live range

区分两类 ring：

1. payload slab：常可用 parity 双缓冲，但必须有 arrival 与 free acknowledgment；
2. plan/meta slot：若所有 chunks 的 stage 1 同时产生、stage 2 逐个消费，则同层每个 chunk 都同时 live，深度至少为 chunk 数。

为每个 slot 记录：

```text
allocate/write → publish(epoch) → acquire/read → last consumer → free/grow
```

`slot = chunk % n_slots` 只有在 last consumer 已完成时才合法。phase/context cache key 必须包含影响 slot 数和 slab stride 的维度，或提供同步 grow。

## 7. Topology 与 peer mapping

逐层确认：

- world、node-local ranks、subgroup、peer index；
- rank 到 device、switch domain、NIC/IPC capability 的映射；
- owner mapping 是否按 subgroup rank 而非 global rank；
- group 是否 node-local；
- subgroup 起点/排列是否满足 peer 分类假设；
- on-switch、off-switch、自身三类路径；
- transport 初始化和 import 顺序；
- symmetric allocation 大小及所有 PE 一致性。

bootstrap/transport 报错可能在第一个含相关 device code 的 kernel 处暴露；先检查初始化日志、capability 和 peer path，再怀疑算术 kernel。

## 8. Reference 与数值协议

逐 level 固定：

- plan row order；
- pair/source accumulation order；
- GEMM tile/block 参数；
- activation/quant rounding；
- codec wire format、group size、scale dtype；
- unpack/reduction order。

不同 GEMM `BLOCK_K` 或 codec 是不同数值协议；即使数学等价，也不能默认 bitwise。

## 9. Host sync 与 arrival

搜索：

- Python scalar 写入 device tensor；
- `.item()`/`.tolist()`；
- pageable H2D；
- pinned D2H 的 Event wait；
- task table 每 chunk 重建；
- host launch feed gap；
- comm CTA 相对 full-occupancy compute CTA 的 runnable 时间。

stream priority 只影响 pending work；用 timeline 证明 comm CTA 是否在 compute 占满资源前到达。
