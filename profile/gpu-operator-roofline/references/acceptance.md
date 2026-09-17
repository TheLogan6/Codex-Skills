# 验收与行为自审

## 可执行回归

运行 `python3 -m unittest discover -s scripts -p 'test_*.py' -v`。测试验证实际公式和处理行为：源案例数值、group/head 不重复计数、INT4 字节、规格/校准分离、误差方向、超屋顶不裁剪、零工作/零流量、错误维度/时间、跨路径/层级拒绝。

用两个 examples 各生成一次完整图/报告，检查 `plot_qa.json` 并打开彩色及灰度 PNG，核对数值、图例、标签和误差棒。矢量文件应真实存在、可解析，PNG >=300 DPI。程序通过后仍要看图。

## 五个现实请求

1. **“只有 H800 的 W4A8 group_gemm 日志，MFU=13%，解释瓶颈。”** 应核对总 M/专家、INT8 MMA 峰值与 INT4 bytes；报告低 effective compute utilization，不能直接判断 HBM 饱和；Byte 不明时先有模型/采集计划。
2. **“低 MFU 的向量加法是否还有 100x 空间？”** 应考虑 matched memory roof。高带宽利用率时固定工作空间小，不能以 compute peak / achieved 承诺 100x。
3. **“换成 AMD 卡，继续沿用 H800 的带宽和 WGMMA 参数。”** 应替换精确 SKU 与实测持续峰值、使用 MFMA/ROCm 证据；保留通用计算模型，拒绝跨卡混用峰值。
4. **“memory-side 且带宽只有 15%，是不是带宽瓶颈？”** 应说未证明 bandwidth saturation，排查延迟、并行度、依赖、资源和缓存口径，设计一个最小扰动实验。
5. **“复制算子没有 FLOPs，还是画 Tensor Core MFU。”** 应报告 byte/s 和 Q/B；不能伪造非零工作数让点出现在 log 坐标上。

## 交付前逐项核对

- 数字能从输入/账本重算，原始日志、图片描述、假设、重建与本次测量分开。
- 单 GPU / rank 与全局 F、时间、峰值未混；shape/time/dtype/cache 的边界一致。
- 精度和稀疏模式与实际指令匹配；工作 numerator/byte denominator 各自标明依据。
- Bytes 中输入、输出、scale、索引、workspace、额外写回/重读已列或解释排除。
- “memory-side / compute-side”与“实际 bandwidth/compute bound”分开。
- 图标明层级、单位和 roof，实际点不被不适用的 BF16/INT8 横线评价。
- 没有把 effective modeled bandwidth 称为 profiler-measured HBM。
- gap 是条件上界，提供绝对时间与关键路径影响；缺关键路径比例就不给虚构 E2E 收益。
- 优化方案可被实验否定，正确性不只看 cosine similarity。
- 无 GPU 时只完成离线复算/成图，不报告硬件实验已完成。

## 自动匹配检查

名称 `gpu-operator-roofline` 使用小写连字符，description 同时覆盖中英文任务表述。技能需被目标客户端发现/加载，自动调用才能生效；仅写入任意仓库目录不等于已安装。正向测试请求：

- “这个 grouped GEMM MFU 只有 13%，还有多少优化空间？”
- “H800 上这段 kernel 是 compute-bound 还是 memory-bound？”
- “根据日志算 AI 和 HBM 利用率，画 roofline。”
- “换成另一张卡或改变 tile，算子的性能瓶颈会怎么变？”

普通散点图、GPU 型号价格查询、无性能分析诉求的 kernel 功能开发不应仅因关键词触发。description 有助于匹配但不保证所有客户端检索排序。
