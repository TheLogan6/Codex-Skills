# 实现：有限值域 Pack 与索引 Reduce 融合

## 1. 先写 reference

candidate 之前保留最直白的 reference chain：

```python
def reference_sort_pack(keys, token_ids, gates, bucket_of, num_buckets):
    bucket = bucket_of(keys)
    order = stable_argsort(bucket)
    counts = bincount(bucket, minlength=num_buckets)
    return pack(keys[order], token_ids[order], gates[order]), counts

def reference_return(values, gates, src_index, dst_index, rows, hidden):
    pair = gather(values, src_index)
    pair = round_to_value_dtype(pair * gates[:, None])
    return ordered_segment_sum(pair, dst_index, rows, hidden)
```

测试中的 reference 必须走独立实现，不能复用 candidate 的 offsets 或地址帮助函数。

## 2. Stable counting sort-pack

### 三阶段骨架

```text
K1 histogram:
  block_counts[block, bucket] = count

K2 scan:
  bucket_base[b] = exclusive_sum(total_count[0:b])
  block_offset[block,b] = bucket_base[b] + sum(previous block counts)
  counts[b] = total_count[b]

K3 stable scatter:
  local_rank = exclusive_prefix(key == b within original block order)
  pos = block_offset[block,b] + local_rank
  packed[pos] = encode(original_pair)
```

稳定性的证明由三层组成：

1. bucket 按固定编号排列；
2. block 按原始 pair 区间排列；
3. block 内位置使用原始 lane 顺序的 exclusive prefix。

### Triton 风格骨架

```python
@triton.jit
def histogram(keys, block_counts, n, K: tl.constexpr, BLOCK: tl.constexpr):
    pid = tl.program_id(0)
    off = pid * BLOCK + tl.arange(0, BLOCK)
    live = off < n
    key = tl.load(keys + off, mask=live, other=0).to(tl.int32)
    for b in tl.static_range(K):
        count = tl.sum(((key == b) & live).to(tl.int32))
        tl.store(block_counts + pid * K + b, count)

@triton.jit
def stable_scatter(keys, payload, offsets, out, n,
                   K: tl.constexpr, BLOCK: tl.constexpr):
    pid = tl.program_id(0)
    off = pid * BLOCK + tl.arange(0, BLOCK)
    live = off < n
    key = tl.load(keys + off, mask=live, other=0)
    for b in tl.static_range(K):
        selected = (key == b) & live
        local = tl.cumsum(selected.to(tl.int32), 0) - selected
        pos = tl.load(offsets + pid * K + b) + local
        store_encoded(out, pos, payload, off, mask=selected)
```

实现约束：

- `K` 若驱动 `tl.arange`、`tl.cumsum` 或 `static_range`，必须声明合法范围并在 wrapper fail-fast；
- 空输入直接返回形状、dtype 正确的空 packed output 和全零 counts；
- key、token 和地址的 int32/int64 范围分别证明，不能为方便全部升为 int64；
- gate 若进入整型 metadata，使用明确 bitcast；接收端必须对称 reinterpret；
- workspace 大小为 `num_blocks × K`，纳入 peak memory；
- tail lane 所有 load/store 都带 mask。

## 3. Gather + ordered segment reduce + terminal layout

### 地址与状态

假设 `dst_index` 已按 destination 非降序排列：

```text
start(q) = lower_bound(dst_index, row_edge[q])
end(q)   = lower_bound(dst_index, row_edge[q+1])
src      = src_index[pos]
dst      = dst_index[pos]
addr_in  = values_base + src * stride_value_row + h
addr_out = out_base + dst * stride_out_row + h
```

kernel 按 destination row space 分块，每个 program：

1. 从 offsets 得到 pair 范围；
2. 顺序扫描 pair；
3. destination 改变时落盘前一 accumulator；
4. 对 `src == invalid` 跳过；
5. 最后落盘剩余 accumulator。

```python
prod = fp32(value) * fp32(gate)
if match_reference:
    prod = fp32(cast_to_value_dtype(prod))
acc = acc + prod
```

此处回落 value dtype 用来复现被删除中间 tensor 的舍入；若 baseline 没有该中间写回，不得机械加入。

### 边界

- `M == 0`：不启动 kernel或返回已初始化输出；
- empty destination：输出保持 reference 的零填充；
- repeated destination：按 reference pair order 顺序累加；
- dropped source：不读 source、不改变 accumulator；
- non-power-of-two `H`：列 mask 覆盖；
- ragged pair range：offsets 和最后一个 segment 均覆盖；
- 非 contiguous 输入：要么使用真实 stride，要么 wrapper 明确拒绝；
- output 若要求预清零，wrapper 负责并计入成本。

### 何时不用原子

当 destination 已排序时，一个 row 应尽量由唯一 program 负责，避免多 CTA 原子导致非确定顺序。若必须多 CTA 合并同一 row：

- exact/bitwise 通常不可保证；
- 需要第二阶段固定顺序 reduction，或把 correctness 改为明确 tolerance；
- 不能静默沿用 bitwise 声明。

## 4. 终态布局直写

不要先生成逻辑 `[R,H]` 再 reshape/scatter。将 owner 和 layout 编入地址：

```text
owner = dst // rows_per_owner
local = dst % rows_per_owner
physical = owner * owner_stride + local * row_stride + column
```

若有 padding 或 tiled layout，明确：

- logical row 到 physical tile；
- tile 内 lane；
- padding 是否必须为零；
- collective flatten 维；
- consumer 的 alignment 要求。

## 5. Host 接线

最小顺序：

1. 新增 candidate wrapper；
2. 保留原 reference chain；
3. 新增默认关闭或风险匹配的 feature gate；
4. 在真实调用点只替换目标子链；
5. 一次性记录 candidate engaged、shape 和模式；
6. 非法 domain/layout/index range fail closed 或回退；
7. 增加独立单测、composition test 和 benchmark；
8. 目标层级通过后再考虑默认开启。

禁止：

- 在 benchmark 中使用 `.tolist()` 打印 device counts，污染 CPU lane；
- candidate 与 reference 共用已排序输出；
- 为追求局部速度改变 gate dtype、reduction order 或 output owner；
- 将 sort-pack 和 gather-reduce 绑成不可独立关闭的一个 gate。

## 6. CUDA/CuTe 对应实现

采用 CUDA/CuTe 时仍遵循相同契约：

- CTA 负责固定 pair 区间或 destination 行区间；
- histogram 的共享内存初始化与 barrier 明确；
- block totals 跨 CTA 时使用独立 scan kernel或可证明的 cooperative protocol；
- producer 写 offsets 后，consumer launch 提供全局完成边界；
- 终态写入满足 consumer alignment；
- 报告 registers/thread、shared memory/CTA、active CTAs/SM；
- 不把单 kernel 的加速直接外推为 layer 收益。
