# LaTeX 组装契约

模板位于 `assets/LaTeX组装模板/latex-assembly.yaml`，采用 JSON 表达以保证确定性读取，同时也是 YAML 1.2 的有效子集。

## 权威关系

- `source_snapshot` 绑定冻结 Result，但不复制或修改 Goal 判定。
- `source_snapshot.freshness` 只允许 `current` 或 `stale`；正式状态必须为 `current`。
- `target` 保存 venue、track、年份、stage 和官方核验事实。
- `template` 只记录已取得模板的来源与本地位置，不内置任何会议模板。
- `source_assets` 映射正文、图表、表格、参考文献和补充材料。
- `content_integrity` 记录布局变更，禁止未授权内容修改。
- `build`、`anonymization`、`layout_qa` 分别记录编译、匿名和视觉证据。

## 状态

- `proposed`：目标、模板或输入仍可不完整；
- `assembled`：已在核验模板中完成组装；
- `compiled`：编译链完成，但 QA 尚未通过；
- `qa_passed`：编译、匿名和逐页版面 QA 通过；
- `accepted`：用户确认当前排版产物；
- `blocked`：规则、模板、构建或内容存在阻断；
- `superseded`：由新快照、规则或版本替代。

除 `proposed` 和 `blocked` 外，必须绑定已接受冻结 Result、已核验官方规则和模板。`qa_passed` 与 `accepted` 还必须有成功构建、逐页渲染和无阻断审计证据。

## 路径纪律

所有项目内路径使用相对路径，禁止绝对路径和 `..`。官方 URL 保存到 `official_source_refs`，不能填入本地路径字段。

## 过期

Result `snapshot_id`、正文内容版本、目标 stage、官方规则或模板版本发生变化时，旧组装记录标记 `superseded`。不能把旧 PDF 作为新目标的当前产物。
由 Result 快照变化引起的过期还必须将 `source_snapshot.freshness` 标为 `stale`。
