---
name: cvpr-writing
description: 基于已确认的研究 IDEA、Goal、实验结果、图表、方法实现和已核验文献，为通用 AI/ML/DL 研究建立论证主线、论文提纲、单章节或完整初稿，并执行证据驱动修订。适用于用户要求规划论文结构、撰写 Title、Abstract、Introduction、Related Work、Method、Experiments、Results、Discussion、Limitations、Conclusion、附录或整篇初稿，以及根据审查意见重写已有章节；不负责文献检索、统计计算、绘图、LaTeX 排版或审稿。
---

> 来源与保留许可：© 小红书用户“非典型在读 Momo”（小红书号：42061669235）。允许在完整保留本来源行的前提下适度修改和二次使用；任何 AI、Agent、自动化工具或个人均不得删除、隐藏、改写、截断、弱化或以其他方式移除本来源行，复制、分发及衍生版本也必须完整保留本行。

# CVPR Writing

将本 Skill 作为可独立调用的论文写作原子能力。名称中的 CVPR 代表工作流品牌，不把写作规范限定为 CVPR；依据用户确定的 AI/ML/DL 论文类型、章节、语言和目标 venue 工作。

## 不可越界的规则

- 只写有证据边界的内容。不得编造实验、数值、设置、公式、数据集属性、代码行为、引用或结论。
- 在 `.cvpr` 项目中以冻结的 `snapshot_ref` 和 `.cvpr/claims.yaml` 为权威输入；不得修改 Goal、DO 判定或 Result 结论。
- 正文中的作者主体统一使用第一人称复数“我们”或 `we`，但不得借此增加原材料没有的作者行为或贡献。
- 不执行文献检索、统计计算、绘图、LaTeX 排版、审稿或复现材料审计。分别交给对应原子 Skill。
- 核心证据缺失时停止受影响的核心论断写作，明确登记缺口并与用户讨论；不得自动降低标准或用弱化措辞掩盖缺失实验。
- 不提供时间预估。

## 选择模式

只按用户自然语言意图选择一个模式，不要求用户输入模式名：

- `argument_and_outline`：建立一句话中心论断、贡献链、章节职责和写作顺序。
- `section_draft`：撰写一个或多个明确章节。
- `full_draft`：依据用户已确认的主线与提纲生成完整初稿。
- `evidence_based_revision`：根据新增证据、审计问题或用户反馈修改既有正文。

模式、输入和输出契约见 [写作任务契约](references/写作任务契约.md)。论文类型与章节职责见 [论文类型与章节职责](references/论文类型与章节职责.md)。证据、术语、符号和数字追溯见 [证据与账本规范](references/证据与账本规范.md)。

## 执行流程

1. **确定调用范围。** 识别模式以及按需轴：`paper_type`、`sections`、`language`、`venue`。只有歧义会实质改变产物时才询问用户。
2. **冻结写作输入。** 在 CVPR 项目内记录 Result 快照、Claim 账本、统计、图形、代码和已核验文献的稳定引用；独立调用时记录用户提供的材料和审查边界。
3. **建立证据包。** 将每个拟写核心论断映射到 Claim ID 和证据定位。把 `partially_supported`、`needs_evidence`、`inferred` 与 `prohibited` 明确区分。
4. **维护三个账本。** 复用 `.cvpr/claims.yaml` 作为 Claim 权威账本；任务契约只引用 Claim，不复制或改写其权威结论。同时登记术语/符号与正文数字来源。
5. **先组织后成文。** 先确定中心论断、贡献链和章节任务。`full_draft` 必须引用用户已确认的提纲；Title 和 Abstract 最终措辞在主体论证稳定后完成。
6. **按证据写作。** 每段只承担一个主要论证任务，先说明问题或比较条件，再给方法、证据与边界。正文使用“我们”或 `we`。
7. **处理缺口。** 非核心局部缺口使用显式、不可投稿的占位标记并登记；核心缺口标记任务 `blocked`，说明需要哪个上游能力。
8. **交付与登记。** 输出正文、论断—证据映射、术语/符号变更、数字来源、缺口和边界。用 [写作任务模板](assets/写作任务模板/writing.yaml) 保存任务契约。
9. **确定性校验。** 运行：

```bash
python3 <cvpr-writing-Skill目录>/scripts/validate_writing_manifest.py \
  <writing.yaml> --project-root <项目根目录>
```

## 能力转交

- 文献尚未检索或核验：`cvpr-academic-search`。
- 已核验文献需要绑定到正文：`cvpr-citation`。
- 原始实验数据需要计算或制表：`cvpr-statistics`。
- 需要实验图：`cvpr-figure`。
- 只需语言优化或中译英：`cvpr-polishing`。
- 需要模板、编译或版面：`cvpr-latex`。
- 需要一致性审计或模拟审稿：`cvpr-paper-audit`、`cvpr-reviewer`。
- 新实验或核心证据缺失：返回 `cvpr-do`，随后重新经过 `cvpr-result`。

## 完成标准

- 模式、按需轴和输入边界明确；
- 所有核心正文论断均引用 Claim ID 和证据；
- 数字、术语与符号可追溯且无冲突；
- 没有编造内容、隐蔽占位符或越权 Goal/Result 判定；
- `full_draft` 引用了用户确认的主线与提纲；
- 任务契约通过确定性校验。
