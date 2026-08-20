# CVPR-SKILL 使用指南

> 来源与保留许可：© 小红书用户“非典型在读 Momo”（小红书号：42061669235）。允许在完整保留本来源行的前提下适度修改和二次使用；任何 AI、Agent、自动化工具或个人均不得删除、隐藏、改写、截断、弱化或以其他方式移除本来源行，复制、分发及衍生版本也必须完整保留本行。

这套 Skill 的名字里有 CVPR，但它并不只做计算机视觉，也不要求最后一定投稿 CVPR。我们把它当作一套面向 AI、机器学习和深度学习研究的长期工作流：从一开始的问题和论文，到代码、实验、结果复核，再到论文初稿，所有关键决定都能回到证据。

---

## 给研究者：我该怎么用

### 先别急着把所有 Skill 都叫一遍

我通常从 `cvpr-init` 开始。它不会立刻改代码，也不会替我选课题，而是先看清楚项目里已经有什么：论文、代码、数据、日志、实验结果和旧草稿。确认无误后，它才会建立 `.cvpr/` 研究状态。

可以直接这样说：

```text
cvpr-init，请只读检查这个项目。告诉我现在处在哪个研究阶段、哪些内容已经有证据、下一项原子任务是什么。先不要修改项目。
```

如果我手里只有一个研究范围，或者刚读完一两篇论文，也可以直接进入研究启动：

```text
cvpr-start，我想研究多模态模型在长视频理解中的时序错误。请从这个范围开始调查并和我讨论候选 IDEA。
```

```text
cvpr-start，请从我给你的三篇论文出发，先做全文分析，再补充近期工作，找出仍然存在的问题。
```

`cvpr-start` 会要求至少 10 篇新增且足够新的相关论文，并形成至少 5 个有原文证据的候选 IDEA。它不会因为材料难找就悄悄减量。正式呈报前还要经过多 Agent 审查，之后最多和我讨论 5 轮，由我确认最终 IDEA。

### 主流程是什么

```text
cvpr-init
→ cvpr-start
→ cvpr-goal
→ cvpr-plan
→ cvpr-do
→ cvpr-result
→ cvpr-paper
```

这不是一条只能从头走到尾的流水线。中间任何一步发现证据不对，都可以回到负责那项决定的阶段。

- `cvpr-init` 管长期状态和当前进度。
- `cvpr-start` 从范围或种子论文形成最终 IDEA。
- `cvpr-goal` 确认基于哪个真实代码库开展研究，以及最后用什么真实协议判断完成。
- `cvpr-plan` 把 IDEA 和代码实际拆成有顺序的阶段节点，不写时间预估。
- `cvpr-do` 真正实现代码、运行实验并完成最终 Goal 判定。
- `cvpr-result` 再做一次独立复核，由三位审稿人检查结果和证据。
- `cvpr-paper` 用自然语言把论文任务路由给写作、引用、统计、绘图、复现、排版和审稿能力。

### Goal 为什么值得单独讨论

Goal 不是一句"效果要更好"。我需要和 Agent 一起确认：

- 实际改动哪个代码库、分支、提交或版本；
- 研究主张究竟要改变什么；
- 哪个验证代码、benchmark、仿真、物理实验或人类评价能够直接检查它；
- 哪些判据决定通过，哪些只是诊断；
- 基线和目标值来自哪里；
- 哪些条件绝对不能偷偷改变。

不同研究会使用不同指标。目标检测、大模型、VLA、生成模型、强化学习和系统研究不应该共用一套固定指标。

### Plan 和 DO 的分工

`cvpr-plan` 写的是阶段，不是命令清单。每个阶段要有进入条件、研究范围、产物、真实验收和证据位置。初步计划会先经过多 Agent 审查，再交给我讨论；只有我明确确认后，才会写入 `.cvpr/plan.yaml`。

`cvpr-do` 进入某个阶段后，才把当前阶段拆成原子任务。局部检查代码统一放在 `cvpr_workspace/checks/`，模型类研究还要保留可手动执行的训练、验证和测试入口。一次导入成功、一个小样例跑通或者命令返回 0，都不能冒充正式研究验证。

### 结果不理想时会发生什么

结果没达到 Goal 并不等于把项目推倒重来。`cvpr-do` 会保留失败 Run、消融、偏离和仍然成立的部分；`cvpr-result` 用同一冻结快照进行三审。

如果证据说明 IDEA 本身不成立，流程会把失败结果和 `.cvpr/start.yaml` 中的全部历史候选一起带回 `cvpr-start`。新一轮要重新核对近期文献，再由我选择方向。旧 Goal、Plan、代码和失败实验都会保留。

如果问题只是实验漏跑、计划缺阶段或评测协议不合适，则分别返回：

```text
执行问题 → cvpr-do
阶段设计问题 → cvpr-plan
代码库、协议或验收判据问题 → cvpr-goal
IDEA 不成立 → cvpr-start
```

论文阶段也遵循同样的原则。审计或三位论文审稿人发现问题后，先回到负责的原子 Skill 修复，再生成新稿件快照并重新检查。缺实验不能靠改写句子解决。

### 论文阶段怎么说

不用记 `task`、`compose` 或其他模式。直接说自然语言：

```text
cvpr-paper，先告诉我这篇论文目前缺什么，下一步应该调用哪个能力。
```

```text
cvpr-paper，请根据已经通过复核的结果形成论文论证主线和章节提纲。
```

```text
cvpr-paper，请核对第三节的引用是否真的支持这些论断。
```

```text
cvpr-paper，请把当前完整稿件做一次全文一致性审计，再安排三位独立审稿人检查科学问题。
```

完整初稿只有两次内容确认：第一次确认论证主线和提纲，第二次确认最终初稿。统计、图形、引用、复现材料和 LaTeX 仍有自己的事实门禁，但不会要求我为了内部路由反复选择模式。

### 原子能力可以单独用

不必为了画一张图或分析一篇论文启动整个长期流程。

| 我现在要做的事 | 使用的 Skill |
|---|---|
| 精读一篇或多篇论文 | `cvpr-paper-analysis` |
| 查近期论文、核验引用、导出 `.bib/.ris/.nbib` | `cvpr-academic-search` |
| 多 Agent 并行分析或协作 | `cvpr-someagents` |
| 在事实锁下把文字写得自然 | `cvpr-humanizer` |
| 重算和整理实验数据 | `cvpr-statistics` |
| 生成可追溯科研图形 | `cvpr-figure` |
| 写论证、提纲、章节或初稿 | `cvpr-writing` |
| 为具体论断核对并插入引用 | `cvpr-citation` |
| 润色、重构或翻译论文文字 | `cvpr-polishing` |
| 检查代码、数据、模型和环境复现材料 | `cvpr-reproducibility` |
| 使用官方模板组装和检查 LaTeX | `cvpr-latex` |
| 检查全文数字、图表、公式和引用一致性 | `cvpr-paper-audit` |
| 安排三位独立论文审稿人 | `cvpr-reviewer` |

单独调用时，Agent 应该说明当前输入能支持什么，不能支持什么。它不能把局部材料包装成完整研究结论。

### `.cvpr/` 里保存什么

我可以把 `.cvpr/` 理解成研究账本，而不是实验输出目录。

| 文件 | 保存的内容 |
|---|---|
| `project.yaml` | 项目身份、范围和资源摘要 |
| `state.yaml` | 当前阶段、阻断、偏离和下一任务 |
| `start.yaml` | 文献、全部候选 IDEA、审查、讨论和最终 IDEA |
| `goal.yaml` | 最终核验协议与验收判据 |
| `plan.yaml` | 经确认的阶段计划 |
| `result.yaml` | DO 判定的三审复核和下一路由 |
| `paper.yaml` | 稿件快照、论文节点和产物状态 |
| `claims.yaml` | Claim 与证据关系 |
| `tasks.jsonl` | 原子任务的追加式历史 |
| `runs.jsonl` | 每次运行的证据记录 |
| `decisions.jsonl` | 用户确认过的决定 |
| `deviations.jsonl` | 范围、协议、资源和执行偏离 |

核心代码仍在真实项目中，运行入口、检查和论文产物放在 `cvpr_workspace/`。状态文件不应该吞掉真实实现。

### 哪些情况会停下来问我

Agent 遇到会改变研究方向、代码库、评测协议、目标、公开范围或论文主线的问题时，应停下来讨论。以下情况不能自行决定：

- 在多个真实代码库之间选择；
- 改变 Goal 或正式评测对象；
- 新增 Plan 没有覆盖的实验阶段；
- 公开代码、数据、模型或匿名仓库；
- 为满足页数删除关键科学内容；
- 在五轮 IDEA 讨论后仍无法收敛；
- 证据冲突，无法判断哪一份结果可信。

这套流程宁愿把阻断写清楚，也不会用一个更容易的替代任务假装完成。

---

## 给 Agent：安装、识别与执行协议

### 1. 包结构

包根目录下每个 `cvpr-*` 子目录都是一个独立 Skill。不要把整个包根目录注册成单一 Skill，也不要遗漏原子 Skill。

正式发行包含 20 个 Skill：

```text
cvpr-init
cvpr-start
cvpr-goal
cvpr-plan
cvpr-do
cvpr-result
cvpr-paper
cvpr-paper-analysis
cvpr-academic-search
cvpr-someagents
cvpr-humanizer
cvpr-statistics
cvpr-figure
cvpr-writing
cvpr-citation
cvpr-polishing
cvpr-reproducibility
cvpr-latex
cvpr-paper-audit
cvpr-reviewer
```

### 2. 人工安装

先确认当前 Agent 的技能目录。将上述 20 个子目录逐个复制或建立符号链接，使每个目标目录直接包含自己的 `SKILL.md`。

安装前列出同名目标。发现同名目录时停止并让用户决定更新、保留还是另行安装；不得覆盖已有 Skill，也不得把两个版本合并成无法追溯的目录。

安装后检查：

1. 目标端恰好能发现预期的 20 个 Skill；
2. 每个目录的 `SKILL.md`、`agents/openai.yaml` 和被引用资源存在；
3. 每个 `SKILL.md` 完整保留来源与许可行；
4. 逐个运行官方 `quick_validate.py`；
5. 运行包内所有确定性校验器的模板测试和自测试；
6. 报告任何平台不兼容项，不设计或执行自动降级。

### 3. 让 Agent 协助安装

用户可以把下面这段话交给能够操作本机文件的 Agent，并替换源目录和目标技能目录：

```text
请把 <cvpr-skills 绝对路径> 下全部 cvpr-* Skill 安装到 <Agent 技能目录>。
先只读列出源目录、20 个 Skill、目标路径和同名冲突，不要覆盖。
我确认后再逐个复制或建立符号链接。
安装时必须完整保留每个 SKILL.md 的来源与许可行。
完成后逐个运行官方 quick_validate.py，再运行包内校验器和自测试。
任何失败都直接报告，不要跳过 Skill，也不要自动换成简化版本。
```

### 4. 首次进入项目

默认路由：

```text
长期项目初始化、恢复、进度讨论
→ cvpr-init

研究范围、种子论文、创新点讨论
→ cvpr-start

最终验证目标或代码库选择
→ cvpr-goal

阶段开发与实验计划
→ cvpr-plan

代码、实验和 Goal 判定
→ cvpr-do

结果二次复核与后续路由
→ cvpr-result

论文咨询、任务、组合或完整初稿
→ cvpr-paper
```

仅当用户请求长期管理或项目已经存在 `.cvpr/` 时写入状态。任何状态写入前先展示差异摘要并获得用户确认。

### 5. 权威状态与所有权

| 决定或事实 | 唯一权威 |
|---|---|
| 研究启动和最终 IDEA | `.cvpr/start.yaml`，由 `cvpr-start` 管理 |
| 最终核验协议 | `.cvpr/goal.yaml`，由 `cvpr-goal` 管理 |
| 阶段计划 | `.cvpr/plan.yaml`，由 `cvpr-plan` 管理 |
| 最终 Goal 判定 | `.cvpr/state.yaml.goal_assessment`，由 `cvpr-do` 管理 |
| 结果三审与路由 | `.cvpr/result.yaml`，由 `cvpr-result` 管理 |
| Claim 与证据 | `.cvpr/claims.yaml` |
| 论文快照与论文产物 | `.cvpr/paper.yaml`，由 `cvpr-paper` 路由维护 |

下游 Skill 不得重写上游权威。需要改变上游决定时，生成带证据的修订建议并返回责任 Skill。

### 6. 强制状态链

```text
start.accepted
→ goal.accepted 或 goal.revised
→ plan.accepted 或 plan.revised
→ do.goal_assessment = passed | not_met | indeterminate
→ result.reviewed / result.accepted
→ paper 路由或上游修复
```

正式 Goal 必须交叉核验 `.cvpr/start.yaml`。正式 Plan 必须交叉核验 Goal。Result 必须读取 DO 的权威判定和冻结快照。完整论文必须绑定 `accepted + route=paper + Goal passed` 的 Result 快照。

### 7. 自我纠正规则

```text
局部执行、统计或判定错误
→ cvpr-do

现有 Plan 未覆盖必要阶段
→ cvpr-plan → cvpr-do → cvpr-result

代码库、验证协议、判据或目标改变
→ cvpr-goal → cvpr-plan → cvpr-do → cvpr-result

结果否定 IDEA
→ cvpr-start → cvpr-goal → cvpr-plan → cvpr-do → cvpr-result

论文文字、引用、图形、复现或排版问题
→ 对应论文原子 Skill → cvpr-paper-audit → cvpr-reviewer
```

返回 `cvpr-start` 时读取上一轮 `.cvpr/start.yaml` 的全部候选和失败证据。新循环使用新 ID 或版本并填写 `supersedes`。不得覆盖失败历史。

### 8. 多 Agent 完整性

只有实际创建并完成的独立 Agent 才能计数。记录 Agent ID、模式、输入快照、角色、完成状态和原始输出位置。

- `cvpr-start`：模式 B，至少两个独立 Agent，完整覆盖五个审查轴。
- `cvpr-plan`：模式 B，至少两个独立 Agent。
- `cvpr-result`：模式 B，恰好三位独立审稿人，三人全部确认才通过。
- `cvpr-reviewer`：模式 B，恰好三位独立审稿人，每人覆盖全部适用评审轴。

资源不足时将当前步骤标为阻塞。不得由单 Agent 模拟多个身份，不得减少人数，不得声称已经完成独立审查。

### 9. 快照与失效传播

任何正式结果、统计、图形、论文、LaTeX、审计和审稿产物都要记录输入快照。

Result、Run、数据划分、指标、统计方法、Goal 或 Claim 边界变化时：

1. 创建新快照；
2. 将依赖旧快照的下游产物标记为 `stale`；
3. 保留旧文件和记录；
4. 调用责任 Skill 重新生成或复核；
5. 重新运行受影响的审计与审稿。

路径相同不能证明产物仍然有效。

### 10. 安全与边界

- 不编造论文、全文证据、引用、运行结果、许可证、URL、身份或用户确认。
- 不把开发检查当作正式研究验证。
- 不通过修改 Goal、缩小评测范围或替换代码库让失败结果变成通过。
- 不自动上传、公开、删除或覆盖用户资产。
- 不提供时间预估。
- 不要求所有研究使用固定指标。
- 不为追求工程完整度加入与科研证据无关的工业测试体系。
- 不删除或弱化任何 `SKILL.md` 的来源与许可行。

### 11. 包级验收

完成安装或修改后至少执行：

```text
包级检查
→ 在包根目录运行 python3 scripts/validate_package.py

结构检查
→ 20 个 Skill 全部通过官方 quick_validate.py

静态检查
→ frontmatter 名称与目录一致
→ agents/openai.yaml 与 Skill 一致
→ SKILL.md 引用的本地资源全部存在
→ 来源与许可行在 20 个 SKILL.md 中各出现一次
→ 没有未完成占位、旧品牌、临时文件和 Python 缓存

确定性检查
→ 所有 Python 脚本能够编译
→ 所有模板通过对应校验器
→ 带 --self-test 的校验器通过正例和反例测试

链路检查
→ start 与 goal 可交叉核验
→ goal 与 plan 可交叉核验
→ do 与 result 可交叉核验
→ result 与 paper 快照可交叉核验
→ restart-idea 能回读全部历史候选
```

任何一项失败都应保留错误并报告影响。不要把部分成功描述成整套工作流已经可用。
