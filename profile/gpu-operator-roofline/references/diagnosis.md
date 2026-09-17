# 从落点到性能判断

## 一张表先说清

| 指标 | 含义 | 不能替代 |
|---|---|---|
| `U_compute = F/(tP)` | 匹配工作口径相对计算峰值 | SM busy、瓶颈证明 |
| `U_bandwidth = Q/(tB)` | 该流量口径相对带宽 | Q 是模型时的真实 HBM 利用率 |
| `r = AI/(P/B)` | 所选模型的屋顶区域 | 某资源已饱和 |
| `U_roof = (F/t)/min(P,B*AI)` | 距离匹配屋顶的比例 | 确定可以达到的百分比 |
| `S_fixed = 1/U_roof` | 固定 F/Q 的理想倍数 | 工程收益承诺 |

同口径时有恒等式 `U_roof = max(U_compute,U_bandwidth)`，可作为计算检查。若不满足，通常是单位/边界/分子不一致。接近屋顶表示经典模型剩余空间小，但换算法/融合/减少 Q 可移动落点和上限。

## 区域与置信度

报告精确 r；`r<1` 为 memory-side，`r>1` 为 compute-side。`0.5≤r≤2` 可标近 ridge，但这是可调整的敏感性提示，不是物理定律。用输入不确定性判断是否跨界比固定阈值更可靠。

真实 bound 需多种一致证据。表中的“接近”应参照同设备可复现的校准分布，不能把一个统一百分比用在所有卡。

| 候选瓶颈 | 支持证据 | 最小验证实验 / 否定信号 |
|---|---|---|
| HBM bandwidth | measured Q/t 接近可达 HBM 带宽，memory-side | 减少实际 Q 后时间相应下降；若 Q 降但时间不动，检查其他资源 |
| L2/SMEM | HBM 未满但该层流量吞吐接近自身上限 | 改 tile/复用/冲突，观察该层 bytes 和 stalls |
| compute pipeline | 匹配 tensor/SIMT 管线高，计算主阶段占时 | 减少工作/更合适指令后改善；单纯减 Q 无收益 |
| memory latency / dependency | 低带宽、load dependency stall、eligible warp 少 | 增加并发/ILP/预取有收益，而减算术无明显收益 |
| registers/SMEM/occupancy | register/SMEM 限并发、spill 或尾波 | tile/warps/stages 改变资源占用并改善时间；occupancy 高本身不证明高效 |
| instruction/SFU/barrier | 非主 MMA 指令密集、SFU 或 barrier/dependency stall | 独立改变解包/epilogue/同步/流水策略 |
| launch/host/sync | timeline 可见 launch gap、短 kernel、GPU 空闲 | graph/批处理/融合改善整个 range，而单 kernel 时间近似不变 |
| group imbalance | expert token skew、空组多、尾 CTA 拖长 | 同总 token 改 group 分布、调度方式，观察 tail |
| communication | 关键路径有 collective/传输、未被计算覆盖 | 改 overlap/分片/算法并检查实际关键路径 |

“大空间”的证据可以是 U_roof 低和可改的具体低效机制；若缺少后一项，只能说“模型显示大 gap，实际收益待验证”。小 kernel 即使相对 gap 大，也可能只能省几微秒，业务价值低。

## 优化空间分三层

1. **固定 F/Q 空间**：`t_min=max(F/P,Q/B)`，可省 `t_old-t_min`；称 conditional headroom。使用 measured Q 时只约束当前流量；若优化减少流量，必须重算。
2. **候选实现空间**：`t_new,min=max(F_new/P_new,Q_new/B_new)`。把具体可减少的中间读写、padding、重复工作落到账本，峰值必须对应新精度。显示保守/乐观场景，注明不是实测。
3. **端到端价值**：若目标占原串行关键路径比例 f、局部获得倍数 s，则 `S_e2e=1/((1-f)+f/s)`。延迟下降比例是 `1-1/S_e2e`，不能把“快 1.25x”写成耗时下降 25%（实际为 20%）。

有重叠/流水/异步 offload 时，f 不能从所有 kernel 时间求和直接得出；重建关键路径或直接端到端复测。算子 2.2x 不等于整模型 2.2x。缺 f 时不猜收益。

## >100% 或落点超屋顶

保留点和原始数值，标记“屋顶/口径/测量待核对”，不裁到 100%，不宣称突破物理极限。检查：

- ms/us/s、GB/GiB、单卡/多卡、FMA=1/2；NFE/迭代范围。
- 峰值 SKU、频率、稀疏模式、精度、输入/累加和管线路径。
- useful/executed/dense-equivalent F 是否混用；专家/head 是否重复计数。
- 暖 L2 的 `Q_once` 被误当 HBM 实测；是否漏/多计读写。
- counters 与 latency 来自不匹配的 launch/cache/replay 状态。
- 校准 benchmark 是否弱于当前访问模式，时钟/并发是否不同。

校准屋顶被超过只说明该参考上限不适用；先查证，再修模型。证据不足时保留无效/未定状态。

## 把原文的 tile 调优提升为方法

从 PTX/SASS/source 识别主指令、tile、warps、pipeline、persistent、数据加载/写回、寄存器和同步；kernel 名只能作为线索，PTX 不保证最终机器码和吞吐。

更大 N tile 可提高复用或指令效率，但也扩大 accumulator，增加寄存器/SMEM，减少并发或增加尾块。cooperative 与 ping-pong、更多 stages、persistent、TMA、async copy 都需受控 sweep 和相同准确性测试。每轮只修改可归因的变量组，记录前后指标；只有计数器/时序随假设变化时才收敛到原因。

硬件平台改变后，用该平台的矩阵指令和资源模型重新评估。H20 上的高 MFU 不能作为 H800 的可达目标；相同峰值利用率也不表示相同性能。

## 报告末尾的实验卡

```text
结论：理论区域 / 当前实测限制 / 置信度
主证据：匹配的 shape、时间、Q、管线或 timeline
候选改动：
机制预测：预期哪个 counter、Q/F、资源使用发生什么变化
收益范围：条件上界 + 绝对 ms + 有依据的目标
正确性门槛：误差、边界、异常值、下游回归
对照配置：相同 seed、环境、cache、计时边界
接受条件 / 否定条件：
```
