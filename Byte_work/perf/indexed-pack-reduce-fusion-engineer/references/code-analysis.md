# 代码分析：Sort、Gather、Reduce 与 Layout

## 1. 从调用点向两端追踪

不要先钻进 kernel。先从启用 candidate 的调用点开始，向上找到索引和数据的 producer，向下找到最终 consumer。

```text
entry → gate → baseline/candidate branch → kernel wrapper
      → terminal consumer / collective → observable output
```

逐项记录：

| 对象 | Shape/Dtype/Stride | 值域 | Owner | 排序性质 | Producer | Consumer | Live range |
|---|---|---|---|---|---|---|---|
| key | | | | | | | |
| source index | | | | | | | |
| destination index | | | | | | | |
| gate/weight | | | | | | | |
| values | | | | | | | |
| counts/offsets | | | | | | | |
| packed/terminal output | | | | | | | |

必须用一个具体 pair `m` 手算其身份变化：

```text
logical pair m
→ key(m) / bucket(m)
→ stable position(m)
→ source row src(m)
→ destination row dst(m)
→ output owner and address
```

## 2. Metadata path

将 baseline 展开成原子步骤，不接受“做一次 sort”这种模糊描述：

```text
materialize token ids
→ flatten/upcast keys
→ compute bucket ids
→ stable argsort
→ gather each metadata column
→ bincount
→ cast/bitcast
→ write wire columns
```

分析问题：

1. `n_pairs` 与 key domain `K` 的量级关系是什么？
2. key 是否连续落在 `[0, K)`，是否存在 invalid/sentinel？
3. stable order 是否影响 receiver 的 source grouping、reduction order 或可重放性？
4. `counts` 被 device 还是 host 消费？是否有 `.item()`、`.tolist()`、D2H 或 allocator sync？
5. metadata 列是数值转换还是位模式 reinterpret？
6. consumer 需要 AoS、SoA、按 bucket 连续还是带 padding 的 wire layout？
7. 通用 sort 的 index width、pass 数和 workspace 是否远超问题规模？

建立成本账本：

```text
work: radix/counting passes, comparisons, histogram bins
bytes: key/index temporaries, gathered columns, sort workspace
launch: framework ops + sort internals + pack stores
host: hidden scalar extraction and split-size construction
```

只有这些成本在目标 timeline 中 exposed，才把 sort-pack 作为候选。

## 3. Return path

将链路拆成：

```text
expert/source layout
→ gather or unpermute
→ gate multiply
→ pair matrix materialization
→ destination grouping
→ segment reduction
→ terminal/collective layout
```

分别定义：

- `src(m)`：pair `m` 从哪一行读取，sentinel 如何表示丢弃；
- `dst(m)`：pair `m` 累加到哪一行；
- `ord(m)`：同一 destination 内的累加顺序；
- `owner(dst)`：输出行属于哪个 rank/shard；
- `addr(dst, h)`：终态 layout 的地址公式。

检查 `dst` 是否单调。若接收 metadata 本身按 source 分段且 token id 单调，不代表全局 `dst` 自动有序；必须由代码或测试证明。

数值链必须逐边界写清：

```text
load value dtype
→ gate cast dtype
→ multiply opmath dtype
→ intermediate store dtype/rounding
→ reduction accumulator dtype
→ reduction order
→ output cast dtype
```

“数学等价”不能替代此链。被删除的中间 store 往往同时定义了 rounding boundary。

## 4. Layout 与 owner 反推

从 consumer 反推 producer 应直接写的终态：

```text
logical shape
physical shape and strides
padding/alignment
row owner
tile/block decomposition
collective concatenation dimension
valid rows and zero-fill rule
```

若 collective 接口把 `[P, N, H]` 视为 `[P*N, H]`，要确认 flatten 顺序与 rank owner 一致，而不是仅比较元素总数。

连续置换可合成为：

```text
baseline: tmp[m] = x[src(m)]; out[dst(m)] = tmp[m]
candidate: out[dst(m)] = x[src(m)]
```

合成前检查 `src/dst` 的一对一、多对一、重复、越界与 sentinel 性质。

## 5. 适用性判定

选择 sort-pack 的进入证据：

- key domain 有限且明显小于 pair 数；
- stable order 可由 block 顺序与块内 prefix 保持；
- 可直接输出 counts 和 wire columns；
- baseline 的 sort/workspace/launch/host sync exposed。

选择 gather-reduce-layout 的进入证据：

- 中间 pair matrix 大且只有 reduction consumer；
- source mapping 与 destination row 可直接求出；
- destination 分段边界可构造；
- rounding 与 accumulation order可复现；
- 终态 layout/owner 已知。

拒绝或停止：

- 目标段已被完全遮挡；
- generic sort 不是瓶颈或 key domain 太大；
- 多 consumer 需要中间结果；
- 原链 reduction order 未知且要求 bitwise；
- 融合导致寄存器、共享内存或长循环破坏目标层级性能；
- 只能证明 microkernel 变快，不能证明调用点 engaged。

## 6. 分析产物

分析结束必须输出：

1. baseline 与 candidate 数据流；
2. 索引语义表和一个手算 pair；
3. work/bytes/layout/launch/host-sync 账本；
4. 理论上限；
5. 选中与拒绝方案；
6. 正确性 reference 与允许的比较标准；
7. 最小文件级改动和验证计划。
