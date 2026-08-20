# 候选 IDEA 证据卡

每个候选 IDEA 单独填写，禁止把多个松散方向合成一张卡。

```yaml
idea_id: I-001
working_title: ""
research_problem: ""
why_it_matters_under_defined_conditions: ""
core_hypothesis: ""
proposed_change: ""
expected_mechanism: ""
literature_evidence:
  - paper_id: ""
    recency: recent | anchor
    statement_type: paper_fact | author_claim | analyst_inference
    locator: ""
    relevance: ""
counterevidence: []
existing_solutions: []
remaining_gap: ""
novelty_boundary: ""
user_side_evidence: present | absent | conflicting
feasibility:
  data: ""
  compute: ""
  implementation: ""
  time: ""
falsification_test: ""
preliminary_acceptance_targets: []
risks: []
open_questions: []
status: draft | audited | rejected | user_selected
```

## 准入条件

- 至少两篇独立论文明确陈述或实验展示该问题；
- 至少一篇是检索窗口内的近期论文；
- 至少一个证据定位到页、节、表、图、公式或失败案例；
- 已检查反证和当前解决方案；
- 核心假设可被实验推翻；
- 初步资源条件与用户边界不明显冲突；
- “创新”只写成待验证边界，不提前声称首创。

任何一项缺失时保留为线索，不进入对用户呈报的五个正式候选。

## 呈报摘要

面向用户呈报时，每个候选用相同口径说明：

1. 我们观察到的具体问题；
2. 现有文献的直接证据及定位；
3. 最新工作解决到哪里、还剩什么；
4. 我们准备改变什么；
5. 为什么可能有效；
6. 如何快速证伪；
7. 最大的新颖性与资源风险。
