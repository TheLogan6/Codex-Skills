# 采集与峰值校准

## 机器事实表

从用户给定目标环境取事实；没有 GPU 访问时完成离线建模并交付待执行命令，不能称已经实测。保存 hostname/device UUID 或匿名稳定 ID、SKU/板型、device count/rank、MIG/partition、显存类型与容量、SM/CU 数、驱动、runtime、编译器、profiler、代码 hash、功耗限制、GPU/显存时钟、温度、并发任务、ECC（适用时）。共享机上的锁频、功耗调整、counter 权限或系统重配需要已有授权。

NVIDIA 的只读发现示例（先确认本机工具存在）：

```bash
nvidia-smi -L
nvidia-smi -q
ncu --version
ncu --list-sections
ncu --query-metrics
nsys --version
```

`nvidia-smi` 的 GPU utilization 不是 MFU；它不能直接给出所需精度的 Tensor Core 峰值。AMD 使用机器已安装的 `amd-smi`/`rocm-smi`，先看 `--help`。Intel/其他加速器使用对应 profiler/device API；沿用 F/Q/t 的接口，不套 NVIDIA counter 或指令名。

## 峰值的三类来源

1. **规格**：厂商精确 SKU 的数据表。记录 dense/sparse、输入/累加精度、Tensor/SIMT、工作频率、每卡/每 package 等条件及来源日期。括号或脚注的 sparsity 加倍不能直接用于 dense 工作；缺失精度不从邻近卡猜。
2. **持续校准**：同设备状态下的大型、正确、稳定的匹配指令 microbenchmark，以及大于缓存、匹配读写比的内存 benchmark。保存完整代码/命令和数据。取可复现的稳定区间，不取偶然最高单样本。
3. **shape 专属参考**：相同 shape、布局、精度和计算语义的库实现。它是实现对照，不是物理 roof；不要用它替换高峰值来掩盖原实现不足。

带宽 benchmark 的 numerator 必须与工作负载 Q 一致：copy N bytes 通常是 N 读 + N 写；厂商工具可能只报告单向大小，确认后才能比较。工作集适当大于相关 cache，同时避免 OOM/分页。报告冷/热 cache 和读写比。无 HBM 的设备用实际层级名称。

## 稳定计时

从已有 harness 起步，保存输入 seed/分布、layout、shape、计时边界与 correctness tolerance。

- 先 warmup 到编译、autotune、分配、lazy init 完成。默认可从 20 次预热、50 次测量起步，按 kernel 时长/稳定性调整，不强制相同次数适用于所有任务。
- 使用设备 event 测 kernel/range；正确同步终点。多 stream 必须在终点 join 所有依赖。CPU wall time 则明确包含 host dispatch/同步/launch。
- 独立重复、保存原样本。报告 n、median、p10/p90、min/max；单样本仅是个例。极短 kernel 可批量计时，但注明 batch 内 cache 状态，并检查与实际应用一致。
- 预分配输出，随机/固定数据按真实分布。warm cache、cold cache、应用自然 cache 分开。每次复用很小数据得到的是 cache-resident 测试，不能称为 HBM benchmark。
- 检查温度、时钟、功耗、共租干扰和 throttling。A/B 交错测试有助于减少系统漂移；不要因追求最好结果而删慢样本。
- 正确性先过，再计时；不把 profiler replay 时间当生产延迟。

需要编写 PyTorch harness 时，单流模式可用 `torch.cuda.Event(enable_timing=True)` 记录前后事件、`end.synchronize()`、`start.elapsed_time(end)`，但必须注明它测量的是两事件间 GPU timeline。不得只用 Python `time.time()` 包异步调用。

## NVIDIA 采集顺序

先通过 timeline 选 representative kernel/rank/iteration，再选择少量 NCU metrics，避免整模型无限 replay。

```bash
# 查看安装版本的语法与可用 section；下列 kernel pattern/program 是占位参数
nsys profile --help
ncu --help
ncu --list-sections
ncu --query-metrics

# 示例：只采目标 kernel 的一个 launch，具体过滤语法以当前 --help 为准
ncu --kernel-name 'regex:TARGET_KERNEL' --launch-count 1 \
  --section SpeedOfLight --section MemoryWorkloadAnalysis \
  --section Occupancy -o operator-profile ./benchmark
```

选择可用的 Tensor/Hierarchical Roofline section 时核对其实际覆盖的指令类型；默认 FP32/FP64 chart 不一定统计 INT8/FP8 Tensor Core。`dram__bytes_read.sum`、`dram__bytes_write.sum`、`gpu__time_duration.sum` 等是常见查询候选，必须由当前架构/版本确认，记录单位。不要把百分比 peak-sustained counter 当 bytes。counter 若是 sector，必须按文档规定的该 transaction 单位换算。

同时保存匹配的 device/rank/launch ID、时间、DRAM read/write、L2 traffic、tensor/math pipe、寄存器/SMEM/occupancy、spill、stall/eligible warp 和 kernel launch 配置。NOP/predication、稀疏计数是否是 dense-equivalent 需逐 metric 核验。

NCU replay 可改变缓存状态和耗时。官方文档说明默认每轮 replay 清缓存；分析应用预热缓存时可评估 `--replay-mode application --cache-control none`，并让程序重建相同缓存和输入状态。无 profiler 计时与 counter 数据只有在 workload、clock/cache 和执行条件可比时才能组合，并标为 paired runs。否则画 profiler-native 落点并另列实际延迟，不能偷换。

如果 GPU counter 权限不足，保留建模结果和待采集项。不要自动改内核参数或要求广泛权限。

## AMD 与其他平台

AMD 先执行 `rocprof-compute --help`、`rocprof-compute profile --help` 并确认卡型与版本支持；使用内置 Roofline/calibration 与 kernel 过滤导出计数器。`rocprofv3`、`rocprof-compute`、旧版 `rocprof` 并非参数兼容。wavefront、MFMA、LDS 等按对应架构解释，不叫 CUDA warp/WGMMA。

其他平台用厂商 profiler + 层级带宽基准 + 实际指令路径基准，输出相同的标准化输入。缺少特定 operation counter 时使用经审计的工作量模型，明确是 modeled F + measured Q。方法适用性不等于所有卡都拥有相同观测能力。

## 一个可复核的采集记录

```text
workload_id / code_hash / input_hash_or_seed:
device / rank / partition / driver / runtime:
instruction_path / dtype / accumulation / sparsity:
shape / layout / active_expert_histogram / block_pair_definition:
timed_scope / streams / cache_policy / warmup / repeats:
latency_samples_ms / measurement_source:
profiler_version / command / report_path / launch_id:
counter_names / units / read_bytes / write_bytes / cache_state:
spec_roof_source / calibration_command_and_result:
```
