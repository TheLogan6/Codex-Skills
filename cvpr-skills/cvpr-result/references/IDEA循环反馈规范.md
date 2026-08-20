# IDEA 循环反馈规范

## 目的

科研性失败不是清空项目。将失败结果转换为新一轮 IDEA 讨论的实物证据，使循环从已知事实继续。

## 失败证据包

路由 `restart-idea` 时至少保存：

- 原 IDEA ID、研究主张和核心假设；
- 未达到或无法判断的 Goal 判据；
- 关键主实验、baseline 和消融结果；
- 哪些模块有效、无效或存在交互；
- 三位审稿人的独立报告；
- 已排除的解释和仍可能的解释；
- 失败、异常和边界条件；
- 可复用代码、数据、入口、checkpoint 和统计资产；
- 历史候选 IDEA 证据卡引用；
- 上一轮 `.cvpr/start.yaml` 的 `start_id`、版本和文件定位；
- 需要新增检索或补证的问题。

## 返回 `cvpr-start`

重新进入 IDEA 环节时：

1. 校验并读取上一轮 `.cvpr/start.yaml` 的全部候选 IDEA，不只读取最后选中的一个；
2. 用当前结果逐项检查候选的机制兼容性和可复用性；
3. 识别失败现象是否形成新的研究问题；
4. 重新核对近期文献是否已经解决相关方向；
5. 必要时补充候选，但仍遵守 `cvpr-start` 的证据门槛；
6. 把旧候选、新候选和失败证据用同一口径呈报；
7. 由用户重新确认 IDEA。

新一轮创建新的 `.cvpr/start.yaml` 版本或新 `start_id`，填写 `input.failure_evidence_ref`、`input.previous_start_ref`、`input.reused_candidate_refs` 和 `supersedes`，并再次通过 `cvpr-start` 校验器。

不能由 Result 自动选择“最可能成功”的候选，也不能只为了通过原 Goal 而改写 IDEA。

## 历史保留

- 不覆盖失败的 Goal、Plan、Run 和 Result Review；
- 新 IDEA 使用新 ID；
- 新 Goal、Plan 和 Result 通过版本和 `supersedes` 建立关系；
- 新一轮不得把旧运行直接当作新 Goal 证据，除非协议和条件经过重新核对；
- 失败结果可以成为论文负结果或限制证据，但是否进入论文由用户决定。
