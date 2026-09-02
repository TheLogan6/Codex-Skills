# Persistent Schedule 测试与 Diff 验收

## 1. 逐级正确性金字塔

每一级都固定 reference、shape、dtype、topology、GEMM config 和 codec。

### L0：host 逻辑

- chunk policy：1 chunk、2 chunk、多 chunk、ragged、tail；
- task table 每种 task type、空 peer 类、最大任务数；
- on/off-domain peer 分类与 subgroup rank；
- required slab/heap bytes；
- strip quantum、strip count；
- illegal config fail-fast。

### L1：plan

- histogram/count、prefix、destination row；
- source-major/expert-major 稳定顺序；
- gate bitcast 与 pair metadata；
- empty expert、empty rank、skew、tail；
- local simulation 对 reference；
- Stage 1/2 与 pinned D2H；
- slot capacity 和 epoch flag。

### L2：单 kernel / composition

逐项比较：

```text
expand/pack
GEMM
activation + quant
pre-sum / codec payload
unpack / fixed-order reduction
```

若 reference 要求 bitwise，使用 `torch.equal`；GEMM tile 和 codec 必须相同。改变 accumulation order 时改用明确 tolerance/quality gate，且不能继续写“bitwise”。

### L3：单 chunk schedule

- prologue dispatch；
- plan publish/acquire；
- task cursor；
- IPC/remote put；
- arrival flag；
- free acknowledgment；
- quiet/local completion；
- epilogue drain；
- 无 host barrier 的路径。

### L4：多 chunk / 多 layer

- parity slab 复用；
- epoch 单调、旧 flag 不误满足新 generation；
- task table cache + per-launch params；
- empty routed chunk；
- 多层复用后每 level exact；
- 注入延迟改变 arrival 顺序；
- watchdog 检测死锁。

### L5：phase transition

- 后 phase chunk 数增加，触发 ring grow；
- 后 phase chunk 数减少；
- grow 后旧 slab 无引用；
- context cache 复用；
- negative control：禁用 grow 应复现容量不足或断言，而非静默覆盖。

### L6：distributed topology

- full group；
- subgroup，且 world 是 subgroup 的倍数；
- 多个 subgroup 并行；
- 目标 switch/NIC/IPC 拓扑；
- 错误 group 起点、跨 node、不支持 peer path 均 fail-fast；
- 所有 rank 的 chunk/task/collective program order 一致。

## 2. Device memory-order 测试

为每类 flag 提交：

- writer/reader 与 address 公式；
- release/acquire scope；
- payload store 在 signal 前；
- destination consume 后才发 free；
- source overwrite 前等待 free；
- nonblocking put 在 source 复用前 quiet；
- `>= epoch` 的 late-reader 测试；
- 多 generation、parity wrap 和长循环压力测试。

测试可通过人工延迟 producer/consumer、反转 peer 快慢、缩短 compute 窗口来扩大竞态。

## 3. Negative controls

至少包含：

- 去掉 ring grow；
- 使用不足 slot；
- stale epoch 或错误 parity；
- host/device task type 不一致；
- 省略 release/acquire 或 free acknowledgment；
- 错误 topology；
- heap/slab 容量不足；
- codec/reference 不匹配；
- GEMM config 未 pin；
- persistent 与普通 pipeline 同开；
- feature off 回 production。

negative control 应确定性失败、被断言拒绝或产生预期 mismatch，不能依赖偶发崩溃。

## 4. 性能与资源

配对 A/B：

- 同 tree 除单变量 patch外一致；
- 同 session、交错运行；
- 固定输入、warmup、layer window、chunk policy；
- 每 rank 记录，报告 slowest rank；
- 分开报告 plan、head、steady、tail、block、layer、step、端到端；
- trace 证明 dispatch(0)、相邻 chunk transfer 和 tail；
- CPU lane 无意外同步；
- comm CTA arrival 与 compute CTA 共驻；
- register、shared memory、occupancy；
- allocated、reserved、driver-visible peak 与 transport heap。

性能模型：

```text
head_candidate ≈ max(early_dispatch, pre-work + plan0)
steady_candidate ≈ max(compute_i, return_{i-1} + dispatch_{i+1}) + contention
tail_candidate = final_return + unpack
```

隐藏一段后必须重新确认新的 long pole。

## 5. Diff 验收

检查：

```bash
git diff --name-status <baseline>..<candidate>
git diff --stat <baseline>..<candidate>
git diff --check <baseline>..<candidate>
```

必须闭合的文件类别：

- feature/capability/topology gate；
- host runner 与 context lifecycle；
- plan 与 task table；
- device kernel/transport primitives；
- model/operator wiring；
- host logic test；
- per-level kernel test；
- distributed schedule test；
- phase/ring/topology negative controls；
- benchmark、trace、memory evidence；
- fallback。

硬拒绝：

- 只有 kernel，没有 runner/plan/wiring/schedule gate；
- 只有单 GPU，却宣称 distributed 完成；
- 只看平均 rank；
- 未命名 reference 却宣称 bitwise；
- task schema、epoch、ring 或 topology 仅靠注释；
- transport 错误 silent fallback；
- layer 不提速，或显存/稳定性回退；
- 混入无关重构。

## 6. 结论

```text
ship:
  全部逐级门禁、negative controls 和 feature-off 通过；
  target topology 已验证；
  slowest-rank 目标层级收益超出噪声；
  显存、transport heap、稳定性满足 guard；
  diff 最小且 fallback 完整。

continue:
  协议与局部门禁成立，但缺目标拓扑、多层/phase、trace 或高层性能证据。

stop:
  任一级正确性失败、死锁、stale slot、错误 topology、
  目标层级无收益或资源/显存/稳定性回退。

blocked:
  缺少目标硬件、peer transport、权限、production reference 或质量评测能力。
```
