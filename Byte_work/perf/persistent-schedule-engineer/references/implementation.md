# Persistent Schedule 实现

## 1. One-chunk skew

通用目标：

```text
prologue: dispatch(0)
chunk i main: compute(i)
chunk i comm: return(i-1) | dispatch(i+1)
chunk i finish: unpack(i-1)
epilogue: return(n-1) | unpack(n-1)
```

只有当这些依赖成立才可使用：

- dispatch(i+1) 的 payload 在 compute(i) 前已知；
- return(i-1) 的 producer 在对应 comm launch 前完成；
- compute(i) 不读写被相邻 transfer 复用的 slab；
- 各 rank 的 chunk sequence 一致。

若 payload 与 routing 无关，可在 router/selector 前生成并提前 dispatch(0)；metadata 仍需等待 routing。

## 2. Plan 两阶段

建议拆分：

```text
Stage 1:
  local histogram/count
  peer count/meta publish
  release flag
  compact host-needed summary async D2H

Stage 2:
  acquire peer meta
  build receiver columns
  build row offsets / strip tasks
```

Stage 1 可对后续 chunks 提前执行；Stage 2 在该 chunk 即将消费时执行。若 host 必须知道动态 grid，压缩为一个 pinned D2H，并在 Event 后读取，不要散落多个 `.item()`。

## 3. Task table

固定宽度 schema：

```text
[type, parity, peer, slice, begin, end, aux0, aux1]
```

host/device 共享版本号与静态断言。任务队列通常按：

```text
WAIT_FREE
→ long-latency remote puts
→ local/IPC copies
→ WAIT_IN
→ QUIET
```

排序需保证 producer task 不会被全部 CTA 的阻塞 wait 饿死。cursor 用单个 CTA-uniform atomic 领取；避免把带内部 barrier 的 uniform primitive 放进 lane-divergent 分支。

## 4. Device flag 与内存序

发布 payload：

```text
all payload stores
→ CTA barrier (若多线程共同写)
→ release store/signal at system-appropriate scope
```

消费 payload：

```text
acquire load/wait until flag >= epoch
→ read payload
```

source 可复用不是 arrival：

```text
destination consumes payload
→ free acknowledgment(epoch)
→ source waits free before overwriting slot
```

非阻塞远程 put 还需区分：

- remote visibility：fence + signal；
- local source completion：quiet 或等价机制。

## 5. Epoch、parity 与 ABA

```python
epoch += 1
parity = logical_chunk & 1
need_free = last_fill_epoch[kind][parity]
launch.params = {epoch, need_free}
last_fill_epoch[kind][parity] = epoch
```

flag 比较使用协议允许的 `>= epoch`，以容忍 reader 到达较晚；epoch 必须单调。parity 决定地址，epoch 区分 generation。不能只清零 flag 并依赖时序。

## 6. Ring depth 与动态增长

若同层 `N` 个 plan Stage 1 全部提前发布，则：

```text
required_plan_slots >= N
```

增长流程：

1. 所有参与 rank 对新 `N` 达成一致；
2. 同步确保旧 kernel 不再引用旧 slabs；
3. collective/symmetric reallocate；
4. rendezvous 新 peer pointers；
5. 清零 flags；
6. 原子替换 context；
7. 更新 cache 中的容量。

这是少数可接受的 phase-boundary device sync；必须在热路径外并有测试。payload parity ring 与 plan ring 不要混为一个深度。

## 7. Topology-aware transport

启动时构造：

```text
rank → subgroup PE → node → switch domain → supported peer path
```

对每个 peer 选择经过验证的 path：

- self/local copy；
- on-domain peer copy；
- off-domain remote transport；
- 不支持则 fallback 或 fail-fast。

检查：

- subgroup 必须与 owner mapping 一致；
- symmetric memory group 与 PE 编号一致；
- group 排列满足 switch 分类；
- heap/slab size 覆盖最坏 `ep × chunk_cap × row_bytes × ring_depth`；
- import/init 顺序、allocator 模式和 capability 兼容。

不得把某机器的 transport 环境变量硬编码进通用实现。

## 8. Compute 与 strip table

grouped compute 常以：

```text
strip_count[e] = ceil(rows[e] / BLOCK_M)
task = prefix(strip_count) + local_strip
```

chunk policy 同时服务 overlap 与 weight locality。优先使常见 expert rows 接近 strip quantum，避免同一 weight tile 因边界产生额外 strip。

若要求 exact/bitwise，reference 必须固定同一 GEMM tile、accumulation order 和 codec。autotune 在进程间可能选不同 config，应在 gate 中 pin。

## 9. Host 调度骨架

```python
ctx.ensure_slots(num_chunks)
prologue_event = launch_dispatch0_early()
chunks = plan_stage1_all()

for i, cur in enumerate(chunks):
    cur.finish_stage2()
    if i == 0:
        main.wait_event(prologue_event)
    launch_expand(cur)
    launch_comm(prev=i-1, nxt=i+1)  # side stream
    launch_compute(cur)
    launch_return_pack(cur)
    join_comm_if_needed()
    if i > 0:
        unpack(i-1)

launch_final_return()
unpack(last)
```

main/comm/plan stream 之间只用必要 Event；跨 rank 用 device flags。task tables 可按 shape key 缓存，但 params 中 epoch/need-free 每 launch 更新，避免 Python scalar pageable copy，使用 fill kernel 或 pinned staging。

## 10. Gate、互斥与 fallback

初始化即拒绝：

- codec/reference 不匹配；
- persistent 与普通 pipeline 同开；
- subgroup/topology/peer path 不满足；
- heap 或 slot 容量不足；
- kernel capability、依赖包、初始化顺序错误；
- task table 超最大行数；
- chunk sequence 跨 rank 不一致。

fallback 为原 production schedule，不得半初始化后继续。打印一次实际 group、peer 分类、ring depth、chunk cap、codec 和 implementation class。
