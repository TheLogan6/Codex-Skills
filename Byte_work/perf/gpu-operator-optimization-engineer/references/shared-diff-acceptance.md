# Shared Diff 验收

此门禁适用于所有由本 skill 编排的 GPU 优化 diff。专门 skill 可以增加更严格门禁，但不得降低这些要求。

## 0. 冻结可比性

baseline 与 candidate 必须固定：

- repository 基线和 candidate revision；
- 硬件、GPU 数、拓扑、driver/CUDA 和关键依赖；
- workload、shape、dtype、phase、seed、batch/concurrency；
- warmup、测量次数、同步边界和统计方式；
- correctness reference 与有效区；
- metric 定义和目标层级。

若 candidate 必须改变输入、算法或输出 criterion，作为新实验处理，不宣称同一 A/B。可用 `scripts/compare_runs.py` 检查结构化 run record。

## 1. Diff 范围门禁

用 `scripts/summarize_diff.py` 只读检查：

- 修改文件、增删行、二进制文件和目录分布；
- source、test、benchmark、build/config、generated/vendor/docs 分类；
- 是否包含接线、gate、fallback、测试；
- 是否混入无关重构、格式化、生成物或 benchmark 偏置。

每个 production 改动必须映射到一个 `HYP` 记录。测试和 benchmark 可支持 hypothesis，但不得改变 baseline 语义来制造收益。

## 2. 路径命中门禁

必须有至少一种直接证据：

- 一次性 engagement log；
- counter/marker；
- trace 中可定位的路径变化；
- feature-on/off 的行为差异；
- 调试断言或定向测试。

配置存在、代码可导入或 kernel 编译成功不等于路径命中。

## 3. Correctness 硬门禁

按专门 skill 的 reference 和 criterion 验收：

- exact/bitwise 必须比较完整有效输出；bitcast/packed code 比较原始位模式；
- tolerance 必须声明 `atol/rtol`、dtype、误差统计和理由；
- reduction、quantization、随机、collective 的顺序变化必须显式批准；
- 覆盖 empty、tail、ragged、padding/sentinel、非整 tile、极端路由及最坏 shape；
- feature-off 必须回到命名 reference；
- 多 rank 路径检查 slowest rank、collective order 和无 hang。

任一未解释 correctness diff：`stop`。缺 reference 或缺目标输入：`blocked`。

## 4. Profiler 证据门禁

trace 只能来自同级 `llm-torch-profiler-analysis` 工作流，报告固定三表：

1. kernel table
2. overlap-opportunity table
3. fuse-pattern table

验收记录需给出 trace/profile 路径、framework、phase、单 trace 或 mapping/formal 模式。不得以自制 profiler 表替代，也不得只截取支持候选的行。

三表用于解释机制，不单独决定上线。kernel 变快但原本被 overlap、或 fuse pattern 消失但目标层级不变，均不能通过性能门禁。

## 5. 性能硬门禁

至少同时报告：

- 目标 metric 的 baseline/candidate；
- warmup、repeats、统计量和离散度；
- end-to-end 或目标 block/layer；
- 多 rank 的 slowest-rank 结果及 spread；
- 与理论上限是否一致；
- 同 session 交错 A/B，或解释无法交错的原因。

默认拒绝：

- 只报 best run；
- 只报单 kernel，目标却是 layer/end-to-end；
- candidate 首次编译成本未隔离；
- benchmark 同时更改 workload；
- 收益不超过噪声；
- 平均 rank 变快但 slowest rank 无收益。

明确阈值由任务输入或项目策略提供；未提供时只陈述测量与置信度，不自造上线阈值。

## 6. 资源与稳定性硬门禁

对 baseline/candidate 比较：

- allocated、reserved、driver-visible 峰值和安全余量；
- workspace、live range、stream allocator pool；
- register、shared memory、occupancy 或 spill（适用时）；
- 编译时间、缓存/binary 大小、首次与稳态延迟；
- 长跑、重复 phase、graph capture、并发和错误恢复；
- 最坏 shape、最热 rank、目标 GPU/拓扑；
- fallback、关闭开关和回滚。

触达 memory guard、发生 hang/race、资源 cliff 未解释、只在非目标硬件有效或 fallback 失效时，不得 `ship`。

## 7. 代码质量与可审计性

要求：

- 最小、聚焦、可回滚；
- 常量和协议单源，host/device 一致；
- 错误配置 fail-fast，不静默走错误快路；
- 测试命名 reference 和 criterion；
- 不提交 trace、dump、构建产物、缓存或机器路径；
- 不泄露凭证、内部地址或一次性数据；
- 注释解释不变量和“为什么”，不复述代码。

## 决策矩阵

| 结果 | 条件 |
| --- | --- |
| `ship` | 可比性、命中、correctness、目标层级性能、资源稳定性和 diff 审计全部通过 |
| `continue` | 无硬失败，机制仍成立，但覆盖、统计或收益证据不足；有明确下一实验 |
| `stop` | correctness 失败、主假设被反证、目标层级无收益、资源回退或 diff 不值得保留 |
| `blocked` | 缺权限、硬件、输入、reference、可运行环境或关键 artifact |

## 验收清单

```yaml
comparability: pass | fail | blocked
diff_scope: pass | fail
engagement: pass | fail | blocked
correctness:
  criterion:
  levels: []
  result: pass | fail | blocked
profiler:
  source_skill: llm-torch-profiler-analysis
  kernel_table: <locator>
  overlap_opportunity_table: <locator>
  fuse_pattern_table: <locator>
performance:
  target_level:
  metric:
  repeats:
  baseline:
  candidate:
  slowest_rank:
  dispersion:
  result: pass | fail | inconclusive
resources:
  memory:
  kernel_resources:
  compile:
  stability:
  result: pass | fail | blocked
fallback: pass | fail
result: ship | continue | stop | blocked
evidence_ids: [REP-..., CON-..., BOT-..., HYP-..., IMP-..., VAL-..., RSK-...]
next_action:
```
