# 验证与 Diff 验收

## 1. 正确性层级

```text
L0 单 stage
L1 A→B→C composition
L2 1 chunk 对 serial
L3 2/multi/ragged chunks
L4 multi-rank collective program
L5 multi-layer / phase transition / context reuse
L6 end-to-end 或质量
```

纯调度替换优先 exact/bitwise 对命名的 serial reference。若 pipeline 同时改变 codec、reduction order 或算法，必须拆成独立变量和门禁。

## 2. 功能测试矩阵

- 1 chunk：强制走 serial 或证明等价；
- 2 chunks：覆盖最小 overlap；
- 多 chunks：覆盖 steady state；
- ragged tail；
- 空输入、空 pair、某 rank 空但其他 rank 非空；
- chunk-local/global index 转换；
- feature on/off；
- debug/calibration hook 兼容或明确 fail-fast；
- deferred return 的最后一块 drain；
- output 在 bias/add/下一层/函数返回前可见；
- 双缓冲 slot 的 RAW/WAR/WAW；
- phase transition 后 chunk 数增大；
- context 重用和重复 invocation；
- 异常 group、非法 chunk 和互斥 scheduler fail closed。

## 3. Collective 顺序门禁

为每个 rank 记录：

```text
(ordinal, communicator-id, op-type, logical-chunk, input-shape, output-shape)
```

验证所有 communicator 成员的 ordinal 序列一致。不要只比较 collective 数量。

负控制：

- 让某 rank 本地数据为空，仍应完成；
- 人为跳过一个 ordinal，测试应快速失败或诊断，不应无限 hang；
- 传入错误 subgroup，capability/topology gate 应拒绝。

## 4. Event 与 Lifetime 门禁

逐边验证：

| Buffer | Producer record | Consumer wait | `record_stream`/ownership | Reuse wait |
|---|---|---|---|---|
| chunk input | | | | |
| staged payload | | | | |
| metadata | | | | |
| return payload | | | | |
| output slice | | | | |

可使用延迟注入、allocator 压力和重复循环暴露竞态：

- 在 producer/consumer 间插入无关 work；
- 强制快速释放 Python 引用；
- 复用相同 slot 多轮；
- 在不同 stream 上制造 allocator churn；
- 运行 sanitizer/同步调试模式仅用于定位，不能作为最终性能配置。

## 5. Trace 验收

timeline 必须同时展示：

- CPU launch lane；
- main/compute stream；
- comm/prefetch stream；
- collective kernels；
-关键 compute kernels；
- Event wait/gap；
- NVTX chunk/stage 标记。

分开报告：

```text
head: first B 前的 exposed A/host
steady: A(i+1)/C(i) 与 B(i) 的 active overlap
tail: last C/drain/final wait
```

回答：

1. communication 是否真的在 compute active 区间执行？
2. overlap 后是否出现新的 host starvation？
3. compute 是否因 chunk 变小而变慢？
4. collective arrival 是否被 compute CTA 阻塞？
5. 最终 wall-time 收益是否接近理论上限？

## 6. Chunk Sweep

同一 session 交错 baseline/candidate，固定输入、拓扑、dtype、其他 feature 和 warmup。每个点记录：

```yaml
chunk_count:
chunk_size:
head_ms:
steady_ms:
tail_ms:
stage_a_ms:
stage_b_ms:
stage_c_ms:
target_scope_ms:
slowest_rank_ms:
peak_allocated:
peak_reserved:
driver_visible:
```

至少包含 1、2、一个中等和一个更细粒度点。不能用单 shape operating point 外推全部 workload。

## 7. 性能与资源门禁

- 报告每 rank，最终以 slowest rank 判断；
- paired A/B，同一进程、同一输入、交错顺序；
- 微阶段、完整 pipeline、layer/step/e2e 分层；
- registers/shared memory/occupancy；
- HBM、Tensor Core、copy engine、NIC/P2P 活跃度；
- framework allocated/reserved 与 driver-visible memory；
- 长时间重复运行，排除 allocator/cache/thermal/session drift；
- 小于噪声的收益不判成功。

## 8. Diff 审查

```bash
git diff --name-status <baseline>..<candidate>
git diff --stat <baseline>..<candidate>
git diff --check <baseline>..<candidate>
git diff <baseline>..<candidate> -- <scheduler-and-tests>
```

逐项确认：

- serial fallback 保留；
- feature gate、互斥与 capability 检查；
- stream 是共享还是 per-instance，生命周期合理；
- Event 的 record/wait 边完整；
- `record_stream` 或显式 ownership 完整；
- collective group/order 有多 rank test；
- chunk policy 有 1-chunk 与 ragged fallback；
- deferred drain 与最终 wait 完整；
- 无 device-wide synchronize 掩盖 bug；
- benchmark 包含 Event、host 和完整 stage 成本；
- 新 stream 有显存证据；
- 没有混入 codec、数学或无关重构；若有则拆 diff。

## 9. 结论

### `ship`

- L0–目标层级正确性通过；
- 全 rank collective program 一致；
- lifetime/slot 证明完整；
- trace 证明 active overlap；
- slowest-rank 目标层级收益超出噪声；
- 最坏 shape 的显存和稳定性通过；
- diff 最小、fallback 可用。

### `continue`

- correctness 和 DAG 成立；
- 但缺真实 topology trace、chunk sweep、目标层级 A/B 或 driver memory 证据。

### `stop`

- split 改变语义；
- collective 顺序可能分叉；
- lifetime/slot 不安全；
- 无真实 overlap或目标层级回退；
- 显存越过 guard；
- fixed overhead 或资源冲突使 pipeline 不适用。

### `blocked`

- 缺目标 GPU/topology、multi-rank 环境、serial reference、输入或 profiler 权限。

## 10. 报告模板

```yaml
baseline_revision: <baseline>
candidate_revision: <candidate>
serial_reference:
chunk_axis:
split_invariance:
collective_program_digest:
event_edges:
lifetime_audit:
correctness:
trace:
  head:
  steady:
  tail:
chunk_sweep:
slowest_rank:
resources:
memory:
diff_files:
result: ship | continue | stop | blocked
remaining_risks:
```
