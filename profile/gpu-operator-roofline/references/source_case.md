# 从 Seedance2.5 H800 group_gemm 案例蒸馏

来源：[Seedance2.5 H800 profile](https://bytedance.larkoffice.com/wiki/EhKqwQ5SVinoIRkbeADcCtTwnbI)，本会话通过用户授权 CLI 读取，document revision 2189。正文可见；图像有自动描述，内嵌表格未读取，原图下载因 `docs:document.media:download` scope 缺失未完成。因此下列是正文记录与明确假设下的复算，**不是原始 profiler 文件重新测量或原图像素复刻**。本技能不依赖该文档可访问。

## 原文给出的证据

- SP4、H800、30s+30s 场景，group_gemm 平均 MFU 约 12.96%；优化后 28.87%。
- 原文 profile/屋顶图描述使用 INT8 peak 1979 TOP/s，HBM 3.35 TB/s。
- 图描述给出总 M=234400、N=4096、K=1536、800 experts、实际约 256 TOP/s、AI≈615。
- 另一条具体调用日志是 `M_total=409600, N=4096, K=1536, experts=800, F≈5.154e12, t=21.855ms`。**这不是图中的相同 M**，不要把二者拼成一个“实测点”。
- 原文根据 binary 中的 PTX 分析到 small-N tile、INT8 WGMMA、persistent/warp specialization/TMA 等，再用 CuTe DSL 实现和 tile/pipeline 实验验证。H20 microbenchmark 与 H800 集成结果分开。
- 端到端 DP2SP4 延迟正文记录 356s → 283s，下降约 20.5%；与算子利用率变化不是同一指标。

上述峰值在此仅作为**原文假设**保留，不建立任意 H800 SKU 的自动查表默认值；新机器必须核实。

## 可重算的图描述示例

采用一个 **toy 均匀 group 分布**，仅用于复现总工作/一次流量计算：800 组，每组平均 M=293（总 M=234400），N=4096，K=1536。实际 routing 分布原文未给，不能声称均匀。

假设所有 800 组活动，activation 为 INT8，weight 是 packed INT4，输出 BF16，输入/权重各读一次、输出写一次，暂忽略 scale、padding、额外流量：

```text
F = 2*234400*4096*1536 = 2,949,434,572,800 OP
Q_A = 234400*1536 = 360,038,400 B
Q_W = 800*4096*1536/2 = 2,516,582,400 B
Q_C = 234400*4096*2 = 1,920,204,800 B
Q_once = 4,796,825,600 B
AI ≈ 614.872 OP/B
ridge = 1979e12/3.35e12 ≈ 590.746 OP/B
r ≈ 1.041 → 在原文假设下，靠近拐点的 compute-side
```

256 TOP/s 对应推导时间 `F/(256e12)≈11.52123 ms`，**这是从图描述吞吐反推的示例时间，不是原始计时样本**。

```text
U_compute ≈ 12.936%
Q_once/t ≈ 0.4163 TB/s  # modeled effective bandwidth，不是实测 HBM
U_roof ≈ 12.936%
S_fixed ≈ 7.73x         # 条件理想上限，不是可承诺优化倍数
```

图中的“≈615”与上述账本相容，但相容不证明原作者确实采用同样 metadata/cache 口径。该点极接近 ridge，只要流量增加约 4.1% 就可能换边；必须补实测流量与可达峰值才能做强结论。

配套 `examples/source_reconstruction.json` 同时包含此建模复原点和 M=409600 的单条原日志点，各自标清来源，不把聚合的 28.87% 伪造成同 shape 的优化后计时。

## 应保留的方法，及应修正的泛化

1. 先由实际分组 shape 推导 F，再用时延验证日志 MFU；从自己的张量/metadata 账本推 Q。
2. gap 大提示值得查实现，但不能从一次装载 Q 算出的低带宽断言实际 HBM 未饱和。结合 profiler counter。
3. W4A8 的主 MMA 如果是 s8×s8→s32，算力分母必须匹配 INT8。原文提到扩大 N 后使用 `m64n256k16`；官方 PTX 对 dense s8/u8 WGMMA 列的是 k32 shapes（如 `m64n256k32`）。不把 k16 指令建议复制到整数路径。
4. “tile N 小导致低效”是该例的可验证假设，不是所有小 N 指令都无法发挥硬件性能的定律。检查寄存器、占用率、尾块、调度和指令吞吐，再 sweep。
5. 原文 20 个输入的高余弦相似度、单 case 重跑和全量效果测试是不同层次证据；通用版本补绝对/相对误差、极端值和边界验证。
6. INT8 用 TOP/s；图中的 BF16 roof 如保留只能当旁注对照，不能用来评价同一个 INT8 point。跨精度用独立 panel。

## BSA 辅助校验

原文给 `AI=256`、FP8 peak 1979 TFLOP/s、HBM 3.35 TB/s，故其 modeled memory roof 为 `857.6 TFLOP/s`。约 241.6 TFLOP/s 对应 roof 利用率约 28.2%，不是仅以 1979 分母得出的约 12.2%。但 AI=256 的 Bytes 推导及实际流量在此未核验，不能据此声称该算子已经 memory-bandwidth-bound。
