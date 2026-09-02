# 验证与 Diff 验收

## 1. 正确性金字塔

```text
L0 kernel
L1 reference-chain composition
L2 单次 operator chain
L3 multi-chunk / stream integration
L4 multi-rank collective 前后
L5 layer / phase transition
L6 end-to-end 或质量
```

纯 layout、pack 和兼容性 fusion 优先要求 `torch.equal`。若改变 reduction order 或算法，必须命名 reference、dtype、shape、tolerance/quality 标准；不能静默降低门禁。

## 2. Sort-pack 测试矩阵

逐项 exact 比较 `packed metadata` 和 `counts`：

- `M=0`、`M=1`、小 M、production-scale M、ragged tail；
- 多种 key-domain/bucket 数；
- top-k 或每 token pair 数的边界；
- uniform、one-bucket、empty-buckets、极端 skew；
- int32 与 int64 输入索引；
- gate/value 的所有支持 dtype；
- bitcast 列逐位一致；
- 稳定顺序：相同 bucket 内 original ordinal 单调；
- 非法 key、domain、overflow 和非支持 constexpr fail-fast；
- candidate on/off 走到预期路径；
- CPU lane 无新增 `.item()`、`.tolist()` 或隐式同步。

建议额外做性质测试：

```text
sum(counts) == M
counts[b] == number_of(key == b)
decode(pack)[stable_position(m)] == original_pair(m)
all output positions written exactly once
```

## 3. Gather-reduce-layout 测试矩阵

- 独立 reference：gather → gate/product → intermediate rounding → ordered segment reduce；
- `M=0`、`R=0`（若 API 允许）、empty segment；
- repeated destination、单 destination、均匀和高度 skew；
- dropped/sentinel source；
- source permutation 与 non-zero owner offset；
- `H` 小值、常用值、non-power-of-two、tile tail；
- gate 为 zero、正负值、极值；
- value/gate/output dtype 组合；
- bitwise 模式逐位比较；
- fast/新数值模式只按预先定义 tolerance 比较，且不得冒充兼容模式；
- collective 前 terminal slab exact；
- collective 后最终 owner output 与 reference 一致；
- multi-chunk split 不改变结果。

## 4. 性能与资源

同一进程交错运行 baseline/candidate，固定输入、warmup、迭代、stream、shape、dtype 和 topology。分别报告：

| 层级 | 指标 |
|---|---|
| microkernel | latency、effective bytes、launch 数 |
| composition | 完整被替换链耗时 |
| operator/block | 调用点端到端耗时 |
| distributed | slowest-rank、arrival skew、collective 前后 |
| layer/e2e | 目标层级延迟与吞吐 |
| resource | registers、shared memory、occupancy、active CTAs |
| memory | workspace、peak allocated/reserved、driver-visible |

理论收益上限：

```text
sort-pack ceiling
  ≤ exposed generic-sort + gather/pack launches + hidden host stall

gather-reduce ceiling
  ≤ exposed intermediate write + read + removed launch/layout pass
```

candidate 若接近 copy ceiling，继续调单 kernel 的优先级应低于消除 materialization。

## 5. Diff 检查

执行并审查：

```bash
git diff --name-status <baseline>..<candidate>
git diff --stat <baseline>..<candidate>
git diff --check <baseline>..<candidate>
git diff <baseline>..<candidate> -- <target-files>
```

逐文件确认：

- wrapper 与 kernel 契约一致；
- 调用点确实接线；
- feature gate、fallback 和 engagement log 齐全；
- reference test 与 candidate 实现独立；
- benchmark 测量完整被替换链，而非漏算清零、offset 或 workspace；
- sort-pack 与 gather-reduce 两条子路径可独立开关、测试和回滚；
- 没有混入无关重构、量化 recipe 或 owner mapping 变化；
- 注释描述的是机制和限制，不写未经验证的收益承诺。

## 6. 硬门禁

### `ship`

- L0–目标使用层级全部通过；
- exact/bitwise 声明明确命名 reference；
- stable order、rounding、reduction order、layout/owner 已证明；
- target operator/block/layer 收益超出噪声；
- slowest rank、资源与 peak memory 无不可接受回退；
- diff 最小且 gate/fallback 完整。

### `continue`

- kernel 和 composition 正确，机制成立；
- 但尚缺真实调用接线、distributed/collective 后门禁、目标层级 A/B 或资源证据。

### `stop`

- metadata 顺序、bitcast、rounding 或 reduction 语义失败；
- 目标层级无收益或更慢；
- workspace、occupancy、显存或稳定性越过 guard；
- 目标段不 exposed，或该模式不适用。

### `blocked`

- 缺少目标硬件、输入、reference、分布式拓扑、权限或质量评测能力。

## 7. 验收报告模板

```yaml
path: metadata | return
baseline_revision: <baseline>
candidate_revision: <candidate>
engagement_evidence:
index_contract:
reference:
correctness:
  kernel:
  composition:
  collective_or_integration:
performance:
  microkernel:
  target_scope:
  slowest_rank:
resources:
  registers:
  shared_memory:
  occupancy:
memory:
  workspace:
  peak_allocated:
  driver_visible:
diff:
  files:
  unrelated_changes:
result: ship | continue | stop | blocked
remaining_risks:
```
