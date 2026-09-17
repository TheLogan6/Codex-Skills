# 操作数和流量：先定义边界，再代入

## 1. 四个容易混淆的量

- `F_useful`：算法有用工作，整数用 OP、浮点用 FLOP，MAC/FMA 按 2 次操作。
- `F_executed`：真实指令工作量，可能包含 padding、masked tile、重计算。
- `Q_model,L`：在明确缓存/复用/融合假设下，对层级 L 的流量估计。
- `Q_measured,L`：该边界实际从 L 读写的计数器字节。

同一图点的横纵坐标使用同一个 F。以有效 F 配实测 Q 可以报告“useful-work / measured-traffic Roofline”，但与原生指令计数的 Roofline 有别。若已知 `e = F_useful/F_executed`，固定实现的 useful compute roof 可进一步收紧至 `e*P`；不要反向把填充工作称成有效吞吐。更多执行工作不代表用户性能更高。

单位：`1 TFLOP/s = 10^12 FLOP/s`，`1 TOP/s = 10^12 OP/s`，`1 GB/s = 10^9 B/s`，`1 GiB/s = 2^30 B/s`。所有 API 和文件边界显式转换。

## 2. GEMM / grouped GEMM

对 `C_e[M_e,N_e] = A_e[M_e,K_e] @ W_e[K_e,N_e]`：

```text
F_main = Σ_e 2*M_e*N_e*K_e
Q_once = Σ_e (sA*M_e*K_e + sW*K_e*N_e + sC*M_e*N_e)
```

`Q_once` 假设每个活动组的 A/W 首次来自该层且各读一次，C 写一次，无共享去重、无旧 C 读、无 metadata。这是一次装载模型，不是任意暖缓存运行的 HBM 最低字节定律。空组若不访问 W，不能把所有配置专家权重都加上；多个组共享 W 时按实际地址/读取策略去重或保留重读，说明原因。

当 N、K 相同：`F = 2*N*K*Σ_e M_e`。若日志中的 M 已经是 dispatch 后全部专家 token 数，不能再乘专家数或 top-k；如果是路由前 token 数，则要从实际 routing 展开并处理容量截断/重复路由。`M_e` 分布与平均值都要保留：相同总 M 的负载不均衡、空组及尾块可以有很不一样的效率。

若 tile 为 `(BM,BN,BK)`，一种实现的粗略 padded 工作估计：

```text
F_tile ≈ Σ_e 2*ceil(M_e/BM)*BM*ceil(N_e/BN)*BN*ceil(K_e/BK)*BK
```

它不是所有指令的精确计数，实际 predication/特殊尾处理可能改变它。检查真实循环和指令。

### W4A8 / mixed precision

- packed INT4 权重的逻辑流量约 `KN/2 bytes`；逐行 padding/pack 对齐时按存储布局逐行向上取整，不能只在总元素数上取整。
- INT8 activation 为 1 B/element，BF16 输出为 2 B/element。
- 若 INT4 先升为 INT8 再执行 INT8 MMA，主计算对标 **INT8 指令峰值**。解包、scale、zero-point、conversion 的负担单独说明。
- 必须记录是每 token/per channel/per group scaling、scale dtype 与数量；kernel 外完成的预处理归入相应边界，不能隐藏为零成本。
- `beta != 0` 增加旧 C 读；split-K 增加 partial accumulator/workspace 读写与 reduction；不同 kernel 融合会改变流量。

Epilogue 按实际工作分别列出，不把 SIMT 浮点 scaling、INT8 MMA 和 SFU 直接合计后除同一个 Tensor Core 峰值。主工作量口径允许省略小 epilogue，但必须说明；epilogue 主导时分阶段建模。

## 3. Attention

令每个 batch/head 的 Q 长度为 Sq、KV 长度 Sk，QK 维度 Dk，V 维度 Dv：

```text
F_QK = 2*B*Hq*Sq*Sk*Dk
F_PV = 2*B*Hq*Sq*Sk*Dv
```

GQA/MQA 中 QK/PV 计算随 **query heads Hq**，KV 存储随 **KV heads Hkv**；共享 KV 的实际跨 head/cache 复用另建模。decode 的 Sq 常为 1，不能搬用 prefill 的强度。

Causal 非 padding 有效 pair 数是 `S*(S+1)/2`（同长自注意力）；实际对角 tile 可能仍执行部分被 mask 的计算。FlashAttention 不把完整 score/prob 矩阵落到 HBM，但 K/V 可能被每个 query tile 重读，不能简单假定各只读一次就称为实测流量。Backward/重算单独推导。

### Block sparse

若 `n_pair` 已累计所有 batch/head 的实际选中 block pairs，block 大小 `(Bq,Bk)`：

```text
F_main = 2*n_pair*Bq*Bk*(Dk + Dv)
# Dk = Dv = D, Bq = Bk = Bsize 时：4*n_pair*Bsize^2*D
```

不得再次乘 H/B。审计 pair 包括哪些 dense 跨模态区、causal/partial block、top-k 边界和 padding，区分真实算子执行的 pair 与数学非零 pair。mask/索引/offset、softmax、split-K reduction 都有成本。算法 block 稀疏不是硬件 2:4 sparsity。

“AI=256”不是 BSA 的通用常数，必须由自己的 F/Q 推导。实际 Q 取决于 K/V tile 复用、重复加载、split-K workspace、score 是否物化等。

## 4. 其他算子与无法套单 FLOP 屋顶的情形

| 算子 | 工作量起点 | 重点流量/限制 |
|---|---|---|
| 普通卷积 | `2*B*Ho*Wo*Co*(Ci/groups)*Kh*Kw` | winograd/FFT 与直接法执行工作不同，im2col/workspace 与融合 |
| elementwise | 元素数 × 每元素算术操作 | 所有输入读、输出写；广播复用、融合 |
| sum reduction | 每行 `N-1` additions | 多阶段部分和、原子、同步、尾块 |
| softmax/norm | 逐阶段列 reduction、算术、exp/rsqrt | SFU/依赖，不把 exp 按 1 次普通 FLOP 对标 Tensor Core |
| embedding/gather/scatter | 语义工作单位或字节 | index 流量、非合并 transaction、原子冲突、访存延迟 |
| memcpy/transpose | F 可为 0 | 直接比较 bytes/s、Q/B 和延迟，不伪造 log(0) 点 |
| 通信/collective | payload/实际链路字节 | topology/算法步数、链路/注入带宽、overlap；另建通信模型 |

混合指令可报告 `max(F_tensor/P_tensor, F_simt/P_simt, N_sfu/R_sfu, Q/B)` 的松时间下界；这些资源若串行或共享 issue 槽，需更强的阶段/调度模型。未知硬件不猜一条万能 compute roof。

## 5. Bytes 账本与分层分析

每项至少包含名称、shape、存储精度、元素数、读次数、写次数、层级、复用/缓存假设、来源。

```text
logical_bytes = elements * storage_bits / 8
traffic = logical_bytes * (reads + writes)
```

非字节对齐、sector 放大、压缩、padding 不能用这个简式，改用已审计的原始 byte 数。

需要考虑 input、output、旧 output、scale/zero-point、routing index、mask、workspace、中间 tensor、split-K、atomic、spill、layout conversion。融合中真正驻留寄存器/SMEM 的中间值不算 HBM 写回；SMEM 流量另记层级。

缓存热启动可能使 `Q_measured,HBM < Q_once`，不自动判定计数器坏了。逐层计算 `(F/Q_HBM, F/t)`、`(F/Q_L2, F/t)` 等点；每层使用相匹配的带宽屋顶。HBM AI 不能放到 L2 roof 上比较。对分层时间下界取 `max(Q_L/B_L, F/P)`，而不是把不同层级的强度硬放在同一 x 位置。

## 6. 聚合与不确定性

顺序、同设备、同精度/屋顶的可合并调用：`P_agg = ΣF_i/Σt_i`，`AI_agg = ΣF_i/ΣQ_i`。不能算术平均 MFU 或 AI 代替整体指标。不同 shape/rank/stage 先分组，保留慢分位数。

并发 kernel 的时间和可能超过 wall time，按所选 range 的 wall time 和资源界建模；不能把重叠区当成串行总时间。多卡模型 MFU 用全局 useful F /（wall time × 同构单卡峰值 × 卡数）；单 rank 的 F 不乘总卡峰值。异构卡逐卡列，通信另计。

若 Q 只有 `[Qlow,Qhigh]`，AI 范围为 `[F/Qhigh,F/Qlow]`。跨 ridge 时输出“不确定/近 ridge”，不要硬判。时间变化映射到吞吐时注意反向：`P_low=F/t_high`，`P_high=F/t_low`；独立区间不暗示它们有联合概率含义。
