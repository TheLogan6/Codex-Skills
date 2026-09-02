# 正反案例：Indexed Pack/Reduce Fusion

每个案例按“现象 → 根因 → 方案 → 证据 → 结论”记录。数字只来自当前被测 workload，不作为跨项目承诺。

## 正案例 A：小值域稳定排序直接打包

**现象**：metadata 前处理由 token-id 物化、宽索引转换、通用稳定排序、计数、四次 gather 和多列写入组成；trace 中有多次短 kernel 与意外 CPU stall。

**根因**：pair 数远大于 destination bucket 数。通用 radix sort 解决了比实际需要更大的 key 问题，计数 API 还隐式读取 device 标量。

**方案**：以 block histogram、全局 exclusive prefix、stable scatter 三阶段替换整条链，并直接写 receiver 所需的 packed rows 与 counts。

**证据**：

- 对多个 bucket 数、index dtype、gate dtype，完整 metadata 与 counts 均等于独立 reference；
- uniform、单 bucket、空 bucket、空输入和 ragged tail 均通过；
- 同 bucket 内原始 pair 次序未改变；
- CPU lane 不再出现 candidate 新增的标量同步；
- 目标 stage 与上层调用均出现超出噪声的收益。

**结论**：满足 `ship` 的候选。若只有 microbenchmark，仍为 `continue`。

## 正案例 B：Gather、Gate、Segment Sum 直写终态

**现象**：大 `[pairs, hidden]` 中间矩阵由 gather+gate 写入 HBM，随后 segment kernel再次读取；该矩阵只有一个 consumer。

**根因**：producer 已有 source row，reducer 已有排序后的 destination row，通用 pair matrix 并非语义必需。

**方案**：按 destination segment 顺序读取 expert/source row，乘 gate，在 reference 指定的 dtype 边界舍入，FP32 顺序累加并直接写 terminal/collective layout。

**证据**：

- fused output 对命名的 gather→segment reference 逐位相等；
- dropped source、empty segment、重复 destination、skew 和非整 hidden 通过；
- collective 前 layout exact，collective 后输出仍 exact；
- 删除的 HBM pass 在 profiler 中消失；
- target operator/block 速度提升且 occupancy、peak memory 未回退。

**结论**：可 `ship`。

## 反案例 A：Counts 对了，稳定顺序错了

**现象**：每个 bucket 的 counts 与 reference 相等，但接收端结果偶发漂移。

**根因**：candidate 使用原子计数抢占位置，同 bucket 内 pair 顺序由 CTA 到达决定。下游 reduction 按接收顺序累加，因此稳定性属于数值语义。

**方案**：改为 block 原序 + 块内 exclusive prefix + block 前缀，或保留稳定通用排序。

**证据**：对同一输入重复运行，metadata 行顺序变化；完整 packed rows 与 reference 不等。

**结论**：`stop`，不得因 counts 正确而合入。

## 反案例 B：融合后省内存但不 bitwise

**现象**：fused gather-reduce 与 baseline 数值接近，但 `torch.equal` 失败。

**根因**：baseline 先把 `value * gate` 写回低精度 pair matrix，再由 reducer 转 FP32；candidate 在 FP32 中保留 product 并直接累加，删除了舍入边界。

**方案**：若目标是兼容替换，在 accumulator 前显式 cast 到 reference value dtype 再回到 FP32。若有意改变算法，则改用独立数值/质量门禁并声明新语义。

**证据**：逐 pair 比较显示第一处分歧正好出现在 product store；恢复舍入后 exact gate 通过。

**结论**：未恢复语义前 `stop`；不能把“close”描述为 bitwise。

## 反案例 C：Standalone 快，整层更慢

**现象**：融合 kernel 的事件计时下降，但 block/layer latency 上升。

**根因**：长 segment loop 或更大 `BLOCK_D` 增加寄存器和占用，延迟了相邻 collective；或者原中间链本已被其他工作遮挡。

**方案**：检查寄存器、shared memory、active CTAs/SM 与 timeline co-residency；缩小 tile、拆回 standalone，或只融合 layout 不融合 reduction。

**证据**：trace 中 candidate kernel 更短，但通信开始更晚或关键路径未缩短。

**结论**：当前 diff `stop`。保留负结果与机制，不继续无依据调参。

## 不适用案例 A：Key domain 不小

**现象**：希望把任意 64-bit 稀疏 key 的全排序替换成 dense histogram。

**根因**：key domain 接近或大于 pair 数，workspace 与扫描成本失去优势；还可能无法静态展开。

**方案**：保留 radix sort，或先做可证明无碰撞的 key compression；不要为了使用 counting sort 改变排序语义。

**证据**：理论 workspace、scan work 或编译规模已超过 baseline，目标 timeline 中 sort 也非 exposed。

**结论**：`stop`，该模式不适用。

## 不适用案例 B：中间结果有多个 consumer

**现象**：pair matrix 同时被 reduction、debug dump 和另一个算法分支读取。

**根因**：直写 terminal layout 会删除共享中间语义；复制计算可能抵消收益。

**方案**：先确认额外 consumer 是否只在 debug 模式；可将 debug 与 optimized path 互斥。若是 production consumer，则缩小融合范围或保留 materialization。

**证据**：consumer 搜索与运行时 instrumentation 证明多读者存在。

**结论**：在 ownership 未重构前 `continue` 或 `stop`，不得直接删除。

## 审查用追问

- stable 是明确契约还是恰好观察到？
- bitcast 与 cast 是否被混淆？
- `src/dst/owner` 是否有一个可手算例子？
- 空 bucket、空 segment 与 dropped row 如何处理？
- output 是否需预清零，成本是否算入 benchmark？
- reference 是否真正独立？
- candidate 改变了哪一个 rounding 或 reduction boundary？
- microkernel 收益是否出现在 slowest-rank 目标层级？
