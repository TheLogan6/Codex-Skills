# 实现：Chunked CUDA Stream Pipeline

## 1. Stage 契约

先把每个 stage 写成纯接口：

```text
A(chunk) -> staged_inputs + ready_event
B(staged_inputs) -> return_payload + compute_done
C(return_payload, output_slice) -> done_event | deferred_result
drain(deferred_result) -> output_slice
```

每个输出注明：

- allocation stream；
- writer stream；
- consumer streams；
- last-use；
- owner；
- shape/dtype/layout；
- 能否跨 iteration/phase 复用。

## 2. 基本 Event 方向

```python
main = torch.cuda.current_stream(device)
comm = shared_comm_stream(device)

input_ready = torch.cuda.Event()
input_ready.record(main)                 # main 生产输入

with torch.cuda.stream(comm):
    comm.wait_event(input_ready)         # comm 消费输入
    staged = stage_a(chunk)
    a_ready = torch.cuda.Event()
    a_ready.record(comm)
    staged.payload.record_stream(main)   # allocator lifetime，不是同步

main.wait_event(a_ready)                 # main 消费 A 输出
return_payload = stage_b(staged)
b_done = torch.cuda.Event()
b_done.record(main)
return_payload.record_stream(comm)

with torch.cuda.stream(comm):
    comm.wait_event(b_done)              # comm 消费 B 输出
    stage_c(return_payload, output_slice)
    c_done = torch.cuda.Event()
    c_done.record(comm)

main.wait_event(c_done)                  # 最终 main consumer 可见
```

规则：

- Event 在 producer stream 的最后写入之后 record；
- consumer stream 在第一次读取前 wait；
- 跨 stream tensor 对每个异步 consumer调用 `record_stream`，或用明确的引用+Event pool 管理；
- 不用 `torch.cuda.synchronize()` 修复局部依赖；
- Event 对象本身在其使用结束前保持存活。

## 3. Pipeline 调度

优先让下一块输入准备不阻塞 compute：

```python
staged = enqueue_A(0)
pending = None

for i in range(num_chunks):
    main.wait_event(staged[i].ready)
    ret = B(staged[i])
    b_done = record_on(main)

    if i + 1 < num_chunks:
        staged[i + 1] = enqueue_A(i + 1)

    current = enqueue_C(i, ret, b_done)

    if pending is not None:
        drain_on_main(pending)
    pending = current.deferred

drain_on_main(pending)
wait_for_last_output()
```

若 C 包含 `collective → compute postprocess`，可将 postprocess 延迟一个 chunk：

```text
B(i)
→ C-collective(i) on comm
→ B(i+1)
→ wait C(i), postprocess(i) on main
```

最后一块必须显式 drain，不能依赖函数返回后的偶然同步。

## 4. Collective 约束

- 预先由全局一致参数构造 `bounds` 和 program；
- 所有 rank 即使本地数据为空也执行相同序列；
- 同一 communicator 优先使用 process-wide per-device shared comm stream，除非 trace 证明多 stream 有价值；
- collective input 必须 contiguous/满足 API layout；
- output allocation stream 和后续消费 stream 的 ownership 明确；
- dynamic split size 的 CPU 转换是显式 host block，计入 head/steady 成本；
- feature 组合若替换同一完整 scheduler，启动时 fail-fast，不允许同时开启。

## 5. Chunk Policy

至少 sweep：

```text
1 chunk (serial/fallback)
2 chunks
3–4 chunks
更多 chunks，直到 launch/小 kernel 损失明显
```

选择依据：

- first-ready 时间；
- steady overlap；
- final tail；
- stage 固定开销；
- compute tile/GEMM M 效率；
- weight/cache locality；
- collective payload 效率；
- transient 与 driver-visible memory；
- slowest-rank workload。

推荐将 chunk size 当 workload policy，而非硬编码常数。若 shape 不满足最小粒度、对齐或 group 一致性，回退 1 chunk。

## 6. Buffer 与双缓冲

slot 状态机：

```text
FREE
→ producer owns / WRITING
→ ready_event
→ consumer owns / READING
→ consumed_event
→ FREE
```

复用 slot 前等待 `consumed_event`，防止 WAR。只等待 producer-ready 不能保证上一轮 consumer 已读完。

parity ring 仅在最大同时 live 数已证明时安全。不能简单使用 `slot = chunk % n_slots`；phase 或 shape 墁长可能让旧 slot 仍 live。需要容量 guard、epoch 或动态扩容。

## 7. Host 与 Copy 陷阱

- `.item()`、`.tolist()`、格式化 device scalar 会阻塞 host；
- `tensor.cpu()` 可能隐式同步；
- pageable host memory 的 `non_blocking=True` 不等于真正异步；
- pinned buffer 复用必须等 D2H/H2D 完成；
- Python loop、allocator 与 collective plan 可能饿死 GPU launch lane；
- calibration、dump、debug hook 可能捕获完整 tensor，破坏切分和生命周期，应显式禁用或走兼容路径。

## 8. Stream Priority

高优先级只影响 pending work 的调度倾向，不能抢占已驻留 CTA。若希望 communication CTA 先到：

- 更早 enqueue；
- 减少前序 host gap；
- 检查 compute kernel occupancy；
- 必要时调整 compute grid/resource，而不是只提高 stream priority。

## 9. 接线顺序

1. 保留 serial reference；
2. 实现 1-chunk 等价路径；
3. 加两 chunk 与 ragged tail；
4. 加 Event 和 ownership assertions；
5. 加全 rank collective sequence debug digest；
6. 加 feature gate、互斥检查和 fallback；
7. 加 timeline annotations；
8. sweep chunk 并测 memory；
9. 目标层级通过后再考虑默认开启。

所有异常组合必须 fail closed；不得静默改变 group、切分或 fallback 的数学语义。
