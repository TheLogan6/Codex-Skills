# Persistent Schedule 案例

以下案例采用匿名通用写法。

## 成功案例：one-chunk skew 与 routing-independent prologue

**现象**

普通多 stream pipeline 的 steady state 已重叠，但首个 dispatch、plan host gap 和最后 return 仍暴露。

**根因**

首 payload 实际不依赖 routing，却在 routing 后才发起；每个 chunk 的通信只尝试覆盖自身计算，无法消除 head/tail。

**方案**

- 把与 routing 无关的 payload 预处理和 dispatch(0) 前移；
- 采用 `compute(i)` 覆盖 `return(i-1) | dispatch(i+1)`；
- plan 拆为可提前发布的 Stage 1 和临近消费的 Stage 2；
- 末尾单独 drain return/unpack。

**证据**

timeline 显示首 dispatch 与前置 compute 重叠，steady-state 相邻 chunk 覆盖成立；逐 level exact；slowest-rank layer 收益超出噪声且显存满足 guard。

**结论**

`ship`，并保留普通 pipeline fallback。

## 成功案例：phase transition 动态扩展 plan ring

**现象**

context 在短 phase 建立，后续长 phase 的 chunk 数增加；固定 plan slots 不足。

**根因**

cache key 未包含 chunk 数，且同层所有 Stage 1 metadata 同时 live，旧 ring 深度只覆盖初始 phase。

**方案**

在 phase boundary 调用 `ensure_slots(n_chunks)`：全 rank 一致地同步旧引用、重分配 symmetric slabs、rendezvous pointers、清 flags，再替换 context。

**证据**

negative control 去掉 grow 后稳定触发容量断言；启用 grow 后多 layer、多 epoch 和长短 phase 往返 exact，旧 slab 无引用。

**结论**

`ship`。增长必须在热路径外，不能用 `chunk % old_slots` 规避。

## 成功案例：subgroup PE 映射收敛

**现象**

world 大于调度 subgroup；原实现用 global rank 做 peer address，单组测试正确，多组时错发或等待。

**根因**

owner、transport PE 和 process group 使用了不同 rank 空间。

**方案**

统一以 subgroup-local PE 编码 task 和 slab；启动时验证 group ranks、node locality、switch 边界和 symmetric-memory group。

**证据**

full-group 与多个 subgroup 均通过逐 level gate；错误 group 排列在初始化时 fail-fast。

**结论**

`ship`，但不得把一个拓扑结果外推到未测试拓扑。

## 失败案例：简单取模覆盖 live metadata

**现象**

短层正确，chunk 数增加后 plan 偶发错行或死锁；扩大 slot 数后消失。

**根因**

所有 chunks 的 Stage 1 同时发布，旧 metadata 尚未被 Stage 2 消费；`slot = chunk % n_slots` 提前覆盖。

**方案**

计算同时 live 的 plan 数并增长 ring；slot 与 epoch 共同标识 generation。

**证据**

live-range 图证明重叠；negative control 能复现；修复后 phase transition 压力测试通过。

**结论**

原 diff `stop`。不能用更多 retry 或全局同步掩盖。

## 失败案例：更快 epilogue 破坏整 block

**现象**

standalone epilogue microbenchmark 更快；并入高占用 compute kernel 后 layer 变慢，或少量 sub-tile 错误。

**根因**

新增寄存器/shared memory 降低 occupancy 或破坏 comm CTA 共驻；跨 CTA completion/visibility 未证明。

**方案**

保留 standalone 路径；检查资源、arrival 和逐 tile 正确性。若无法建立跨 CTA 协议则撤回 fusion。

**证据**

resource report 与 timeline 显示关键路径回退；边界 shape 复现局部错误。

**结论**

`stop`。persistent schedule 不为错误 fusion 放宽标准。

## 失败案例：错误 transport/bootstrap 被误判为 kernel bug

**现象**

第一个包含 peer-transport device code 的 kernel 崩溃或超时，即使问题分支看似未执行。

**根因**

peer capability、NIC/IPC path、symmetric heap、import/init 顺序或 subgroup bootstrap 错误。

**方案**

先独立验证 transport 初始化、peer mapping、最小 put/signal 和 heap size，再运行算术 kernel。

**证据**

最小 transport probe 失败；修复启动契约后原 kernel 无代码变化即可运行。

**结论**

诊断阶段 `blocked` 或配置 `stop`，不要先修改 kernel。

## 不适用案例：瓶颈是 compute 或 load skew

**现象**

head/tail 很小，steady-state 被 compute 或 slowest-rank 负载主导；host lane 连续。

**根因**

persistent 调度理论上限接近零，真正问题是 work、placement 或 kernel。

**方案**

拒绝调度重写，转向 work reduction、load balance 或 kernel/layout 优化。

**证据**

timeline 与 per-rank ledger 显示调度空隙不 exposed。

**结论**

`stop`，不实现 persistent。
