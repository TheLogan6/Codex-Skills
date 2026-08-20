# 多 Agent 审查协议

## 调用关系

本协议由 `cvpr-start` 强制执行，编排方法调用通用 `cvpr-someagents` 模式 B。它不改变 `cvpr-someagents` 在其他场景中的通用定位。

## 同一证据包

所有审查 Agent 获得完全相同、带版本号的材料：

- 种子论文分析；
- 新增文献注册表与检索截止日；
- 问题状态矩阵；
- 用户材料分析或缺失声明；
- 全部候选 IDEA 证据卡；
- 用户资源与边界。

角色提示只规定审查角度，不增删事实。

## 五类审查角色

1. 来源真实性与时效性：论文身份、版本、撤稿/更正、近期覆盖和引用定位。
2. 问题证据：问题是否真实存在，支持、反证、条件和证据强度是否匹配。
3. 相关工作与新颖性：最接近方法、重复风险、只换模块或数据的伪创新风险。
4. 方法与实验：机制是否连贯，假设是否可证伪，对照、指标和验收目标是否有效。
5. 可行性与审稿风险：数据、算力、实现、时间、伦理、许可、复现和潜在审稿质疑。

受并发限制时可以分批执行，但五类审查不能省略。

## 单卡审查输出

```yaml
idea_id: I-001
evidence_truth: pass | revise | reject
recency_coverage: pass | revise | reject
problem_validity: pass | revise | reject
novelty_risk: low | medium | high | unknown
falsifiability: pass | revise | reject
feasibility: pass | revise | reject
counterevidence_handled: pass | revise | reject
major_findings: []
required_revisions: []
minority_or_conflicting_views: []
verdict: pass | revise | reject
```

协调者只能去重、归类和裁决，不得删除少数派提出的实质风险。任何 `reject` 或未解决的关键 `revise` 都不能进入正式呈报；候选不足五个时返回检索或问题重构。
