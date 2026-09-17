# 来源与适用范围

方法与工具资料检索于 2026-09-15；执行采集时仍优先当前已安装版本的帮助和定义。

- [Williams / Waterman / Patterson：Roofline 原始论文](https://digicoll.lib.berkeley.edu/record/136692/files/EECS-2008-134.pdf)：计算吞吐、带宽与 operational intensity 的上限模型。这里使用其基础关系；瓶颈验证与任务收益要补实际实验。
- [NVIDIA Nsight Compute Profiling Guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html#roofline-charts)：Roofline 构成、section 类型、cache/replay 等采集语义。counter/section 随架构和版本变化，以当前工具为准。
- [NVIDIA PTX ISA：Asynchronous Warpgroup Level Matrix Instructions](https://docs.nvidia.com/cuda/parallel-thread-execution/#asynchronous-warpgroup-level-matrix-instructions)：核查 WGMMA 的数据类型、合法 shape 和架构要求。dense s8/u8 的 k32 family 支持 m64n256k32；不要把浮点 k16 路径直接套给 INT8。
- [AMD ROCm Compute Profiler：Profile mode](https://rocm.docs.amd.com/projects/rocprofiler-compute/en/develop/how-to/profile/mode.html)：AMD 的采集和 Roofline 入口；develop 文档不保证与机器安装版一致。
- [AMD HIP：Understanding GPU performance](https://rocmdocs.amd.com/projects/HIP/en/latest/understand/performance_optimization.html)：AMD 平台 compute/memory 层次与性能观测的基本术语。
- [Hierarchical Roofline Performance Analysis for Deep Learning Applications](https://arxiv.org/abs/2009.05257)：分层 Roofline、不同精度和 Tensor Core 数据采集方法。
- [Time-Based Roofline for Deep Learning Performance Analysis](https://arxiv.org/abs/2009.04598)：把吞吐与实际耗时、launch 开销和 Tensor Core 使用结合分析。
- [用户提供的 H800 案例](https://bytedance.larkoffice.com/wiki/EhKqwQ5SVinoIRkbeADcCtTwnbI)：只作案例证据，详见 source_case.md 的读取范围与复算假设；不作为跨卡型规格数据库。

本技能没有内置通用 GPU 峰值表。厂商常有 SXM/PCIe/NVL、不同显存、分区、时钟、dense/sparse 等差别；运行时逐目标查证并写进输入来源，避免维护失真的固定常量。
