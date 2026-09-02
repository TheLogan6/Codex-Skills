# Offload / Prefetch 实现

## 1. 通用数据契约

将一个可搬运单元定义为：

```python
Pack = {
    "unit_id": str,
    "dtype": dtype,
    "host_flat": pinned_contiguous_tensor,
    "entries": [(name, offset, numel, shape, stride)],
    "gpu_view": optional_tensor,
    "version": int,
}
```

要求：

- `host_flat` page-locked、连续、生命周期覆盖所有异步 copy；
- offset 不重叠且总范围等于 pack 大小；
- 参数 view 仅指向当前 owner 的 backing storage；
- 权重、scale 与解释其布局的 metadata 使用同一 version；
- persistent store 需校验 schema、dtype、shape、offset 和 digest。

## 2. 双缓冲协议

```python
slots = [allocate(max_pack_bytes), allocate(max_pack_bytes)]
copy_stream = Stream()
h2d_done = [Event(), Event()]
compute_done = [Event(), Event()]
generation = [-1, -1]

def prefetch(item):
    s = item.index % 2
    with stream(copy_stream):
        if generation[s] >= 0:
            copy_stream.wait_event(compute_done[s])  # 防 WAR
        slots[s].copy_(item.host_flat, non_blocking=True)
        h2d_done[s].record(copy_stream)
        generation[s] = item.index

def consume(item):
    s = item.index % 2
    assert generation[s] == item.index
    current_stream().wait_event(h2d_done[s])         # 防 RAW
    bind_views(item, slots[s])
    run_compute(item)
    compute_done[s].record(current_stream())
```

必要不变量：

```text
write(slot,g+1) happens-after last_read(slot,g)
read(slot,g) happens-after copy_done(slot,g)
```

`record_stream` 只保护 allocator 不提前复用 storage；它不建立 copy/compute 的数据依赖。

## 3. H2D 与 consumer wait

- 发起 copy 的时机应靠近“最早数据可知点”，而不是 consumer 前一行。
- wait 放在“首个真正 consumer”之前，而不是 layer 入口。
- 多 pack 时，在最后一次 copy 后记录单个 aggregate Event，或明确每个 pack 的 Event。
- pageable source 不能假定 `non_blocking=True` 真异步。
- 禁止通过 `torch.cuda.synchronize()` 把竞争条件变成“看似正确”的实现；可保留为 debug/fallback。

## 4. Flat packing 与 view 恢复

```python
cursor = 0
for tensor in logical_unit:
    n = tensor.numel()
    offsets.append((cursor, n, tensor.shape))
    host_flat[cursor:cursor+n].copy_(tensor.reshape(-1))
    cursor += n
assert cursor == host_flat.numel()
```

GPU copy 后按相同 offset 建 view。offload/unload 时：

1. 记录 compute-done；
2. 清除 GPU owner 引用；
3. 恢复 host view；
4. 移除 hooks；
5. 等待仍在使用的 stream；
6. 注销 pinned region；
7. 释放 slot/cache。

不要让参数短暂指向已复用的槽。

## 5. Expert / weight-split streaming

当单个 layer 仍放不下时，把 expert 或 weight 维切成 `[a:b)`：

```text
for weight_chunk in expert_chunks:
    prefetch(weight_chunk)
    for token_chunk in token_chunks_requiring(weight_chunk):
        compute(token_chunk, weight_chunk)
```

关键约束：

- routing 预排序或预建 chunk→pair map，避免每个 chunk 重新全量扫描；
- 主权重、scale、bias、量化 metadata 使用相同 `[a:b)`；
- 每个 weight chunk 每 layer 的目标 H2D 次数为 1；
- 空 expert chunk、skew、尾 chunk 和非整分片必须合法；
- 若换循环顺序导致 activation 峰值越过 guard，退回更小工作集或 hybrid schedule。

## 6. Partial residency

residency policy 采用显式枚举或集合：

```text
none | selected-units | all
```

初始化时把对象划分为 resident 与 streamed 两个互斥集合，并验证全集/交集。拒绝：

- 同一对象同时被“resident”和“streamed”声明；
- store 中缺少因当前策略未导出的对象；
- 仅主权重 resident、scale 仍按不兼容节奏 streaming；
- cache key 不含 residency policy/version。

## 7. Live-range 收缩

安全手段：

- transient 在首个 producer 前 lazy allocate；
- 最后 consumer 后立即释放大 activation；
- 复用前用 Event/epoch/free signal 证明完成；
- phase 结束时显式清理 context；
- buffer shape 按实际上界而非历史最大值；
- 只在容量余量允许时增加预取深度。

双缓冲常驻成本约为：

```text
2 × max_pack_bytes_per_dtype
```

还需加 allocator 对齐、stream pool、通信 slab 与 workspace，不得只算 payload。

## 8. Feature gate 与 fallback

初始化时 fail-fast：

- 无 CUDA；
- host memory 未 pinned 且要求异步；
- 容量估算超过 guard；
- residency 与 split policy 冲突；
- pack schema/store fingerprint 不匹配；
- prefetch depth 大于可证明安全的 slot 数。

fallback 是原始 resident 或同步 offload 路径。高风险路径默认关闭，并打印一次实际策略、slot 数、pinned bytes 与预计常驻 bytes。

## 9. 最小接线顺序

1. 先加入只读 H2D/live-range 计数；
2. 建单层 pack 与 round-trip exact test；
3. 单 slot 同步接线；
4. Event 化，不改变结果；
5. 双缓冲并增加 generation 断言；
6. next-layer/next-chunk prefetch；
7. partial residency；
8. 最坏 shape 与 phase reuse；
9. 配对 A/B；
10. 证据完整后才考虑默认开启。
