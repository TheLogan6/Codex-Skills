***

name: mlops-stg-skill
description: ml-maas / mlops 业务平台交互技能，支持线上 prod（mlops.bytedance.net）和 STG 预发（mlops-stg.bytedance.net）。覆盖基础服务 CronJob 应用目录、方舟开发机 / 堡垒机 VKE 集群登录信息、Nacos 配置中心、配置版本保存、发布单创建与审批发布、模型推理服务（inference service）、服务标签与服务发现标签更新、Splitwise 推理配置创建与服务更新、DCP 配置、CMDB 资产（region / cluster / resource queue / SFCS 预热）、Foundation Model 与 GPU 卡型 / 规格目录、CICD 交付（product / module / delivery / lane delivery / multi-lane delivery / HelmDiff / artifact / change template / release train / delivery event / delivery apply）、泳道应用详情与 Pod 排障（module deploy / K8s 资源 / Pod 日志 / Pod 事件）、事件中心与服务告警、观测中心 TLS 日志。用户提到 mlops、mlops.bytedance.net、mlops-stg、maas、基础服务、CronJob、定时任务应用、方舟开发机、堡垒机、Ark VBH、VKE 集群、登录信息、VkeClusterName、VkeClusterRegion、get\_or\_create\_vbh\_login\_message、方舟推理、inference service、msrv、服务标签、服务发现标签、ModelDiscoveryLabels、support.foundation-model、Nacos 配置、命名空间 / namespace、保存配置、审批人、创建发布单、审批通过、发布配置、发布 / config deployment、批量发布、多泳道发布、泳道管理、泳道应用、泳道交付、泳道发布单、HelmDiff、发布制品、变更模板、发布火车 / release train、交付事件 / delivery event、泳道 Pod、Pod 日志、Pod 事件、Pod 起不来、CrashLoopBackOff、module deploy、ModuleDeployID、Foundation Model、GPU 卡型 / flavor、资源队列 / resource queue、SFCS、Splitwise、推理配置 / inference config、创建配置 / 配置版本、DCP 集群、推理引擎镜像、HPA、Ark service alert、op\_log、TLS token、observability logs 时应使用本技能。
------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# MLOps Skill

使用本技能与 MLOps 业务平台交互：

- `stg`：预发环境，`https://mlops-stg.bytedance.net`

- `prod`：线上环境，`https://mlops.bytedance.net`

CLI 覆盖了录制中出现的所有业务接口，包括基础服务 CronJob 目录和方舟堡垒机登录信息。通用/框架接口（whoami / idc / accessible\_apps / apps/mlops / permissions / actions / devsre\_config）显式排除，不进入 CLI。

## 使用方式

```bash
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py <command> [options]
```

CLI 仅依赖 Python3 原生库。输出为一层 `{"ok", "status", "url", "data"}` JSON 信封；`--pretty` 会 pretty-print。

## 环境选择（线上 / 预发）

默认环境仍是 `stg`（预发），保持历史调用兼容。线上必须显式选择 `prod`：

```bash
# 预发 STG，默认行为
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py list-inference-services \
    --fuzzy-service-name msrv-...

# 线上 prod
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py list-inference-services \
    --env prod --fuzzy-service-name msrv-...
```

批量场景可通过环境变量切换整个会话：

```bash
export MLOPS_ENV=prod
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py list-inference-services ...
```

环境别名：`stg/stage/staging/pre/preprod/pre-release` 都归一为 `stg`；`prod/production/online` 都归一为 `prod`。

写接口只支持 `stg`。基础服务的 `get-or-create-vbh-login-message`，Nacos 的 `update-nacos-config`、`create-nacos-deployment`、`publish-nacos-config`，泳道的 `create-lane-delivery`、`create-multi-lane-deliveries`，推理服务的 `update-inference-service-labels`，以及 Splitwise 的 `create-inference-config`、`preview-update-inference-service`、`update-inference-service` 会在 `prod/online` 下直接拒绝执行。保护逻辑还会校验最终请求主机，避免通过 `--base-url` 或环境变量把 `stg` 写命令指向线上域名。`call-maas-api` 在 prod 下只允许名称以 `Get / List / Describe / Query / Search / Check / Validate / Preview` 开头的明确只读 Action，其他 Action 因可能写入而拒绝执行。调用写命令时必须向用户说明：这是 STG 写操作，执行会产生真实变更；线上环境不支持写接口。

DevSRE 代理路由头由 CLI 按业务 API 路径自动选择：

- `/mlops_xcron/...` → `x-devsre-proxy-consul-psm: data.amltob.ops_xcron`

- `/mlops_cicd/...` → `x-devsre-proxy-consul-psm: data.amltob.ops_cicd`

- `/mlops_cicd_lane/...` → `x-devsre-proxy-consul-psm: data.amltob.ops_cicd_lane`

- `/mlops_deploy/...` → `x-devsre-proxy-consul-psm: data.amltob.ops_deploy`

- `/mlops_eventcenter/...` → `x-devsre-proxy-consul-psm: data.amltob.ops_eventcenter`

- `/mlops_observability/...` → `x-devsre-proxy-consul-psm: data.amltob.ops_observability`

## Region 切换（多分区）

平台默认走 `cn-beijing`。若要查询海外分区（例如新加坡 `ap-southeast-1`），在**任意子命令**上加 `--mlops-region ap-southeast-1`：

```bash
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py \
    list-inference-services --mlops-region ap-southeast-1 --fuzzy-service-name msrv-...
```

CLI 会向请求注入 `X-MLOps-Region: ap-southeast-1` header。**留空 = 走平台默认 cn 分区**，不注入该 header，与旧行为完全一致。

批量场景下可通过环境变量一次性切换整个会话：

```bash
export MLOPS_REGION=ap-southeast-1
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py list-inference-services ...
```

也可以使用环境专属变量：`MLOPS_STG_REGION` / `MLOPS_PROD_REGION`。在 `stg` 下继续兼容旧的 `MLOPS_STG_REGION`。

> 注意：`--mlops-region` 只影响 HTTP header。少数命令还有业务字段级 `--region`（如 `list-inference-hpa-jobs`、`get-tls-sts-token`、`list-service-alerts`），二者含义不同、独立传参。

## 关键能力与关键词

### 基础服务 / 方舟堡垒机

| 需求关键词                    | CLI 命令                            | 说明                                                             |
| ------------------------ | --------------------------------- | -------------------------------------------------------------- |
| CronJob / 定时任务应用 / 基础服务  | `list-cronjob-apps`               | 按页列出服务应用，返回 `ID / Name / Owner / Endpoints / ShadowApp`        |
| 方舟开发机 / 堡垒机 / VKE 集群登录信息 | `get-or-create-vbh-login-message` | **仅 STG 写接口**；通过 `VkeClusterRegion + VkeClusterName` 查询或创建登录信息 |
| Region / 集群选择            | `list-regions` → `list-clusters`  | 先取 Region，再按最新接口契约用 `page_number` 分页读取集群                       |

堡垒机命令的结构化调用：

```bash
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py \
    get-or-create-vbh-login-message \
    --vke-cluster-region cn-beijing \
    --vke-cluster-name maas-control-cn-beijing-stg
```

默认 `RequestType=VkeCluster`、`ProductName=ark`。响应摘要必须同时展示 `VkeClusterUnknown`、`VkeClusterVbhUnSupported` 和 `LoginMessage`；不要只看登录文本。该接口包含 `get_or_create` 语义，属于真实 STG 写操作，不自动重试。

### Nacos 配置中心

| 需求关键词                          | CLI 命令                          | 说明                                                                                   |
| ------------------------------ | ------------------------------- | ------------------------------------------------------------------------------------ |
| Nacos 实例 / list nacos instance | `list-nacos-instances`          | 按产品线过滤 Nacos 实例                                                                      |
| Nacos 实例详情                     | `get-nacos-instance`            | 通过 `--instance-id` 拿 Region / Address 等                                              |
| 命名空间 / namespace               | `list-nacos-namespaces`         | 列出实例下命名空间与配置计数                                                                       |
| 配置列表 / list nacos config       | `list-nacos-configs`            | 支持 `--data-id / --group / --namespace-name / --fuzzy-data-id`                        |
| 配置详情 / get nacos config        | `get-nacos-config`              | 返回 OnlineVersion / LastVersion / Tags / DeploymentStatus                             |
| 版本历史 / config history          | `list-nacos-config-versions`    | `--data-id --group --namespace-name` 必填，翻页看历史版本                                      |
| 发布单 / config deployment        | `list-nacos-config-deployments` | 支持 `--status accepted --status reviewing --created-by ...` 与 `--without-instance-id` |
| 批量发布                           | `list-nacos-batch-deployments`  | 按 Region / ProductCode / InstanceID 拉批量发布单                                           |
| 发布单详情 / publish detail         | `get-nacos-deployment`          | 通过 `--id` 拿完整发布记录（包含前后两个版本）                                                          |
| 发布审批人 / reviewers              | `list-nacos-reviewers`          | 通过 `--nacos-config-id` 获取审批人列表与是否允许自审                                                |
| 保存配置版本                         | `update-nacos-config`           | **仅 STG 写接口**；支持完整 payload，或 `--nacos-config-id --content-file --config-type --tag`  |
| 创建配置发布单                        | `create-nacos-deployment`       | **仅 STG 写接口**；传配置 ID、审批人、备注和紧急标记                                                     |
| 审批或发布配置                        | `publish-nacos-config`          | **仅 STG 写接口**；传发布单 ID 与状态，录制值包括 `accepted`、`deploying`                               |

### 推理服务（Inference Service）

| 需求关键词                           | CLI 命令                            | 说明                                                                                         |
| ------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------ |
| 推理服务列表 / list inference / msrv  | `list-inference-services`         | 支持模糊搜索、状态、模型、集群、创建人、混部、灰度和 `--service-ids` 精确过滤                                            |
| 服务详情 / get inference service    | `get-inference-service`           | 通过 `--service-id msrv-...`                                                                 |
| 服务标签 / 服务发现标签 update            | `update-inference-service-labels` | **仅 STG 写接口**；PATCH 完整 `Labels.Values`，支持读取现值后增删标签，以及用 `--foundation-model-label` 生成模型映射标签 |
| 服务事件 / pod events               | `list-inference-service-events`   | 拉 Kubernetes 层事件（BackOff / ImagePull 等）                                                    |
| 服务 Pod 分布                       | `list-inference-service-pods`     | 按 role 分组（r-encoder / r-decoder / ams / worker …）                                          |
| HPA 指标定义                        | `list-inference-hpa-metrics`      | 列出可用 HPA 指标（engine\_utilization / sm\_activity …）                                          |
| HPA 任务                          | `list-inference-hpa-jobs`         | 列出多 region HPA 任务                                                                          |
| DCP GPU 资源统计                    | `get-inference-dcp-gpu-stats`     | 按 `--gpu-types CPU-16XLARGE ...` 汇总队列资源                                                    |
| 更新历史 / update record            | `list-inference-update-records`   | 服务配置版本变更历史                                                                                 |
| 调用底层 openapi / maas\_api\_proxy | `call-maas-api`                   | Action + Version + payload；覆盖 GetInferenceServiceResourceConfig、UpdateInferenceService 等   |

### Splitwise / DCP

| 需求关键词                        | CLI 命令                             | 说明                                                                                                                                                                                                                     |
| ---------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| DCP 联邦控制集群                   | `list-fed-control-clusters`        | KubeAdmiral / fed control 状态                                                                                                                                                                                           |
| DCP 成员集群                     | `list-dcp-member-clusters`         | 通过 `--dcp-control-cluster-id` 过滤                                                                                                                                                                                       |
| 推理配置模板                       | `list-inference-config-templates`  | Splitwise 推理配置模板                                                                                                                                                                                                       |
| 官方推理配置                       | `list-official-inference-configs`  | 按模型 / 版本 / 模板名过滤；编辑页上下文可加 `--context-model-name --context-model-version --service-id --service-type --edit`                                                                                                            |
| 创建推理配置                       | `create-inference-config`          | **仅 STG 写接口**，创建官方推理配置；同名模板会生成新版本                                                                                                                                                                                      |
| 预览服务更新                       | `preview-update-inference-service` | **仅 STG 写接口**，传 `--payload-json` 或 `--payload-file`，返回当前配置与候选配置 diff                                                                                                                                                   |
| 提交服务更新                       | `update-inference-service`         | **仅 STG 写接口**，传 `--payload-json` 或 `--payload-file`，提交 Splitwise 推理服务更新                                                                                                                                                |
| 一键改 Env / Image / EntryPoint | `switch-inference-template-env`    | **仅 STG 写接口**。默认会创建模板新版本并 preview，但不更新 msrv；加 `--apply` 才更新服务。封装：`get` → `GetInferenceServiceResourceConfig` → `ListWholeInferenceConfigsV2` → 修改 Container.Env → `create-inference-config` → `preview` → 可选 `update`。 |

### CMDB & 基础目录

| 需求关键词         | CLI 命令                         | 说明                                                                                                   |
| ------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------- |
| Region 列表     | `list-regions`                 | 支持 `--filter-json '{"ArkControlRegion":"cn-beijing"}'`                                               |
| 集群列表          | `list-clusters`                | `--page-num / --page-size` 会映射为接口的 `page_number / page_size`；含 ClusterID / Region / DCType / Account |
| 资源队列          | `list-resource-queues`         | 本地和 DCP 队列                                                                                           |
| SFCS 预热       | `list-sfcs-warmup`             | 按 `--service-id` 拉 SFCS pin / warmup 状态                                                              |
| Foundation 模型 | `list-foundation-models`       | 全部基础模型元数据                                                                                            |
| GPU / NPU 卡型  | `list-foundation-gpu-types`    | Cap / Alloc / EPAlloc / ClusterStats                                                                 |
| 推理规格 flavor   | `list-foundation-flavors`      | GPU 数 / VCPU / Mem / RdmaType                                                                        |
| 推理引擎镜像        | `list-inference-engine-images` | 按 region + 模糊镜像 URL 过滤                                                                               |
| GPU 时序统计      | `get-gputype-stat-series`      | 卡型分配时序数据                                                                                             |
| 调度优先级         | `list-scheduling-priorities`   | 可选调度优先级枚举                                                                                            |

### CICD / 交付中心

| 需求关键词                     | CLI 命令                                               | 说明                                                                                                                            |
| ------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 产品线 / product             | `list-products`                                      | 全量 MLOps 产品                                                                                                                   |
| 模块 / module               | `list-modules`                                       | `--product-id` 过滤某产品的模块                                                                                                       |
| 交付单 / delivery            | `list-deliveries`                                    | 状态与创建人过滤                                                                                                                      |
| 基建交付 / infra delivery     | `list-infrastructure-deliveries`                     | 基础设施类交付单                                                                                                                      |
| 发布火车 / release train      | `list-release-trains`                                | 版本发布火车列表                                                                                                                      |
| 交付申请 / delivery apply     | `list-delivery-applies`                              | 待审批的交付申请                                                                                                                      |
| 交付事件 / delivery event     | `list-delivery-events`                               | 时间窗内的交付事件流水（Nacos / 服务上线）                                                                                                     |
| 变更模板 / change template    | `list-change-templates`                              | 获取变更场景模板，支持 `--page-size` 与 `--lc`                                                                                            |
| 泳道产品与环境                   | `list-lane-products` / `list-lane-product-instances` | 获取 ProductID、ProductCode 和 ProductInstanceID                                                                                  |
| 泳道列表 / lane               | `list-lanes`                                         | 按产品、环境、状态、名称、创建人筛选泳道                                                                                                          |
| 泳道详情                      | `get-lane`                                           | 通过 `--lane-id` 获取 ProductID、ProductInstanceID 和当前状态                                                                           |
| 泳道组件                      | `list-lane-modules`                                  | 获取支持泳道发布的 ModuleID、仓库和部署类型                                                                                                    |
| 泳道应用                      | `list-lane-module-deploys`                           | 查看泳道中当前组件、命名空间和部署状态；`--module-id` 精确查某个模块是否已部署（依赖检查），`--status` 按状态过滤                                                         |
| 泳道应用详情 / K8s 资源 / Pod 列表  | `get-lane-module-deploy`                             | 通过 `--module-deploy-id` 拿 `Resources[]`（Deployment/Service/ConfigMap…）+ 每个 workload 的 `Pods[]`。**这是拿到 Pod 名字的唯一途径**，Pod 排障的入口 |
| Pod 日志                    | `get-lane-pod-logs`                                  | 传 `--module-deploy-id --pod-name` 即可，lane/cluster/namespace/容器名全自动解析                                                          |
| Pod 事件 / CrashLoopBackOff | `get-lane-pod-events`                                | 同上；看 `Unhealthy` / `BackOff` 等 Warning 事件                                                                                     |
| 泳道交付 / lane delivery      | `list-lane-deliveries`                               | 支持按 `--lane-id`、状态、创建人和分页查询                                                                                                   |
| 泳道发布详情                    | `get-lane-delivery`                                  | 返回 Stage、Status、DeliveryModules 和完成时间                                                                                         |
| 发布制品                      | `list-lane-delivery-artifacts`                       | 查看 Image / Chart 构建状态和 ArtifactURLs                                                                                           |
| HelmDiff                  | `list-lane-helm-diffs`                               | 查看 HelmRenderStatus、进度、资源 diff 或 RenderError                                                                                  |
| 模块部署结果                    | `list-lane-delivery-deploys`                         | 查看目标集群、命名空间和部署状态；`--status Failed` 直接筛出失败模块（诊断入口）                                                                             |
| 创建泳道发布                    | `create-lane-delivery`                               | **仅 STG 写接口**；支持结构化参数或完整 payload                                                                                              |
| 多泳道发布                     | `create-multi-lane-deliveries`                       | **仅 STG 批量写接口**；先读取全部泳道元数据，再逐条创建，每次最多 10 条                                                                                    |

### 事件中心 & 观测中心

| 需求关键词                    | CLI 命令                | 说明                                                                                     |
| ------------------------ | --------------------- | -------------------------------------------------------------------------------------- |
| 服务告警 / ark service alert | `list-service-alerts` | 按 `--service-ids msrv-...` 拉时间窗内告警与聚合统计                                                |
| 事件流 / op\_log / audit    | `list-events`         | `--sources data.amltob.ops_deploy --modules InferenceService-Ops --resources msrv-...` |
| TLS 保存查询 / saved queries | `list-saved-queries`  | 用户保存的 TLS 查询                                                                           |
| TLS 授权 / STS token       | `get-tls-sts-token`   | 拿 STS token 后可直接读 TLS 日志                                                               |

## 业务资产详情跳转链接拼接

基础页面前缀：

```text
stg  -> https://mlops-stg.bytedance.net
prod -> https://mlops.bytedance.net
```

模板：

| 资产            | 路径模板                                                                                                             |
| ------------- | ---------------------------------------------------------------------------------------------------------------- |
| CronJob 应用目录  | `/toolbox/cronjob?_lc=cn`                                                                                        |
| 方舟堡垒机         | `/toolbox/arkvbh?_lc=cn`                                                                                         |
| Nacos 实例总览    | `/cicd/nacos?_lc=cn&instance_id={instance_id}&product={product}`                                                 |
| Nacos 配置版本历史  | `/cicd/nacos/config_history?product={product}&instance_id={instance_id}&namespace={namespace}&data_id={data_id}` |
| Nacos 发布详情    | `/cicd/nacos/publish_detail?product={product}&instance_id={instance_id}&deployment_id={deployment_id}`           |
| 推理服务列表        | `/maas/inferencesservice?_lc=cn`                                                                                 |
| 推理服务详情        | `/maas/inferencesservice/{service_id}/dcp-detail?_lc=cn`                                                         |
| Splitwise 配置台 | `/maas/serviceops/splitwise/config?_lc=cn`                                                                       |
| 发布火车          | `/cicd/releasetrains?_lc=cn`                                                                                     |
| 交付申请          | `/cicd/deliveryapply?_lc=cn`                                                                                     |
| 交付事件          | `/cicd/stat/deliveryevent?_lc=cn`                                                                                |
| 泳道列表          | `/cicd/lanes?_lc=cn`                                                                                             |
| 泳道详情          | `/cicd/lanes/{lane_id}?_lc=cn`                                                                                   |
| 泳道发布详情        | `/cicd/lanes/{lane_id}/deliveries/{delivery_id}?_lc=cn`                                                          |
| 资源大盘          | `/ark-resource-ops/stat/overview?_lc=cn`                                                                         |
| 观测日志          | `/observability/logs?_lc=cn`                                                                                     |

CLI `build-url` 已封装以上模板：

```bash
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py build-url cronjob
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py build-url arkvbh
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py build-url nacos-list \
    --instance-id nctgj1oqh22vvfr2jqrr0 --product maas
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py build-url inference-detail \
    --service-id msrv-20260112162223-bnskp
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py build-url inference-detail \
    --env prod --service-id msrv-20260112162223-bnskp
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py build-url nacos-history \
    --instance-id nctgj1oqh22vvfr2jqrr0 --namespace ml-maas-api-proxy --data-id lb_config
```

`_lc` 会按目标资源所在 region 自动切换（`--lc` 显式传时以显式为准）：

- 未传 `--mlops-region`（或 region 以 `cn-` 开头）→ `_lc=cn`（国内工作台）

- 传入海外 region（例如 `ap-southeast-1`）→ `_lc=bp`（海外 BP 工作台）

先用 `get-inference-service` 读到 msrv 的 `Region` 字段，再透传给 `build-url --mlops-region` 即可直接生成正确 locale 的详情页链接：

```bash
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py build-url inference-detail \
    --service-id msrv-20260629165948-n6jth --mlops-region ap-southeast-1
# → /maas/inferencesservice/msrv-20260629165948-n6jth/dcp-detail?_lc=bp
```

## 推荐工作流

1. **基础服务与方舟堡垒机登录信息**\
   `list-cronjob-apps --page-size 10` → 查看 `Data[].{ID,Name,Owner,Endpoints}`\
   → `list-regions --filter-json '{"ArkControlRegion":"cn-beijing"}'` 选择 Region\
   → `list-clusters --page-num 1 --page-size 100` 获取 `Clusters[].Base.ClusterName`\
   → 用户明确授权真实 STG 写操作后，执行 `get-or-create-vbh-login-message --vke-cluster-region <region> --vke-cluster-name <name>`\
   → 同时检查 `VkeClusterUnknown / VkeClusterVbhUnSupported / LoginMessage`。接口可能创建登录信息，失败时不得自动重放。\\
2. **Nacos 配置排查**\
   `list-nacos-instances --product-code maas` → 拿到 `InstanceID`\
   → `list-nacos-namespaces --instance-id <id>` → 拿到 `NamespaceName`\
   → `list-nacos-configs --instance-id <id> --namespace-name <ns> --data-id <k>` 或 `--fuzzy-data-id`\
   → 拿到 `NacosConfigs[].ID` → `get-nacos-config --id <id>` 看 Online/Last 版本\
   → `list-nacos-config-versions --instance-id <id> --data-id <k> --group <g> --namespace-name <ns>` 看历史\
   → 发布追溯：`list-nacos-config-deployments --data-id <k>` → `get-nacos-deployment --id <id>`\
   → 保存并发布（仅 STG）：`update-nacos-config` 保存新版本 → `list-nacos-reviewers` 获取审批人\
   → `create-nacos-deployment` 创建发布单 → `publish-nacos-config --status accepted/deploying` 推进审批与发布。三个写命令均不会对失败请求自动重试。\
   \
   **STG 自动化默认**：\\

   - **默认不暂停出 diff**：从 `update-nacos-config` 到 `publish-nacos-config --status deploying` 一路自动跑完，中途不停问 diff / reviewer / 是否 accept。**仅当用户在本次任务前置明确要求"给我看 diff / 先 review / 更新前先确认"时，才在** **`update-nacos-config`** **之前暂停一次给出 unified diff 等 ack**。\\

   - `create-nacos-deployment --reviewer` 默认 `liyang.xavier`。仅当 `list-nacos-reviewers` 返回的 `Reviewers[]` 里没有 `liyang.xavier` 时，才回头让用户从列表中挑一位。\\

   - **忽略** **`list-nacos-reviewers`** **的** **`SelfApproval`** **字段**：stg 后端不真拦 self-approve（同账号连续跑 `create → accepted → deploying` 全 200 且 Online 版本正常刷新），无需换人审批。prod 不支持写接口，本默认仅对 stg 生效。
3. **推理服务巡检**\
   `list-inference-services --statuses Abnormal --statuses Running --fuzzy-service-name <keyword>` → 拿到 `Id`\
   → `get-inference-service --service-id msrv-...` 看基础配置\
   → `list-inference-service-events / list-inference-service-pods` 看事件与 Pod 分布\
   → `list-service-alerts --service-ids msrv-... --begin-at <ts> --end-at <ts>` 看告警\
   → 需要底层资源配置：`call-maas-api --action GetInferenceServiceResourceConfig --payload-json ...`\
   → 版本历史：`list-inference-update-records --service-id msrv-...`
4. **服务标签与服务发现模型映射更新（仅 STG）**\
   页面录制确认，更新入口是 `PATCH /model_inferences_services/{service_id}/labels`。请求体写入的是服务 `Labels.Values`，不是直接写 `ModelDiscoveryLabels`。平台收到 `support.foundation-model.ark/<模型名>_<版本>=true` 后，会派生服务发现使用的模型名、版本和模型类型标签。\
   \
   推荐使用增量模式。CLI 会先读取当前 `Labels.Values`，保留账号类型、模型类型和场景等已有标签，再提交完整集合：\\

   ```bash
   python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py \
       update-inference-service-labels \
       --service-id msrv-... \
       --mlops-region ap-southeast-1 \
       --foundation-model-label doubao-seed-1-8=251128
   ```

   通用标签可用重复的 `--set-label KEY=VALUE` 添加或覆盖，用 `--remove-label KEY` 删除。需要完全复刻页面 payload 时使用：\\

   ```bash
   python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py \
       update-inference-service-labels \
       --service-id msrv-... \
       --payload-file labels.json
   ```

   原始 payload 至少包含 `{"Values": {...}}`，录制中的 `BatchToOnline` 为 `false`；增量模式默认也为 `false`，仅显式传 `--batch-to-online` 时置为 `true`。这是覆盖完整标签集合的真实写操作，不会自动重试。写入后用 `get-inference-service` 同时检查 `Labels.Values` 和 `ModelDiscoveryLabels`；服务是否进入发现候选集还取决于实例是否 Ready。\\
5. **Splitwise / 官方模板匹配**\
   `list-inference-config-templates` / `list-official-inference-configs --model-name doubao-seed-1-6 --model-version mock`\
   → 拿到 `Configs[].Id`（fmvicv2-...）→ 结合 `call-maas-api` 落到具体服务\
   → 创建配置或同名模板新版本时，人工确认完整 payload 后执行 `create-inference-config --payload-file <payload.json>`。该命令会真实写入 STG。
6. **Splitwise 服务更新 —— 修改 Env / Image / EntryPoint（仅 STG）**\
   `Envs / Image / EntryPoint` 都存在**推理配置模板层**（`InferenceConfig.Application.WorkerSets[].Roles[].Containers[]`），**不在 msrv 实例上**。想改必须生成模板新版本，然后把 msrv 切过去。⚠️ **`update-inference-service`** **单独调用不会写 Envs**（只覆盖资源层），必须先走 `create-inference-config`。\\

   **快速路径**（推荐）：`switch-inference-template-env` 一条命令封装完整 6 步。默认会创建真实模板版本并执行 preview，但不会更新 msrv：\\

   ```bash
   # 创建模板新版本并预览；不会更新 msrv，但不是 dry run
   python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py switch-inference-template-env \
       --service-id msrv-20260722160309-bqrzp \
       --mlops-region ap-southeast-1 \
       --set-env MOCK_VLM=true --unset-env OLD_VAR
   # 检查 preview diff 无误后加 --apply 更新服务
   ... --apply
   ```

   支持 `--worker-set / --role / --container` 精确指定目标（默认 `decode` WS 的第一个 role / container），`--set-image` / `--set-entrypoint` 同时改镜像和入口，`--template-name` 强制新模板名（默认沿用当前 TemplateName 让 Version 自动 +1）。只有无落库副作用的 preview 会对特定 HTML 500 自动重试；创建模板和更新服务不会自动重放。\\

   **展开手动路径**（想控制中间产物 / 排障时用）：\\

   1. `get-inference-service --service-id msrv-...` → 读取 `InferenceConfigV2ID` (fmvicv2-\*)、`ModelReference.FoundationModel.{Name, ModelVersion}`、`Region`。\\
   2. `call-maas-api --action GetInferenceServiceResourceConfig --payload-json '{"MaasServiceId":"msrv-...","FoundationModelName":"...","FoundationModelVersion":"..."}'` → 拿到 `Result.WorkerSetResourceInfos / Annotations / AppLabels`（后续 update payload 必需）。\\
   3. `call-maas-api --action ListWholeInferenceConfigsV2 --payload-json '{"Filter":{"Ids":["fmvicv2-..."]}}'` → 拿**完整** `Application` 结构（含每个 Container 的 `Env / Image / EntryPoint / Ports`）。⚠️ **不要用** **`list-official-inference-configs`**：那个接口会 strip Application 的执行细节，返回空 Envs。\\
   4. 修改 `Application.WorkerSets[<name>].Roles[<r-name>].Containers[<name>].Env[]`（append / 改值 / 删除），拼 `create-inference-config` payload（`TemplateName` 保持不变 → 自动 bump Version），执行 `create-inference-config --payload-file ...` → 返 `{Id: fmvicv2-<新版本>}`。\\
   5. 拼 `update-inference-service` payload（详见"推理模板 Env 编辑 payload 拼接"章节），先 `preview-update-inference-service --payload-file ...` 看 `CurrentServiceResourceInfo` vs `CandidateServiceResourceInfo` 以及 `CurrentInferenceConfig.Application` vs `CandidateInferenceConfig.Application` diff，确认只有目标 Env 变化。\\
   6. `update-inference-service --payload-file ...` 真实 apply → 触发 msrv rolling update → decode pod 重启后 Env 生效。若创建或更新请求返回不确定的 HTTP 500，不要直接重放；先查询配置版本或服务状态确认是否已生效。`prod/online` 不支持写接口。
7. **多泳道发布（仅 STG）**\
   录制确认单条发布请求为 `POST /mlops_cicd_lane/create_delivery`。每条泳道都会产生独立 `DeliveryID`，后续阶段也独立推进。\
   \
   发布前先查询资产：\
   `list-lane-products` → `list-lane-product-instances --product-code maas`\
   → `list-lanes --product-id <id> --status Active`\
   → `get-lane --lane-id <id>` 校验 `ProductID / ProductInstanceID / Status`\
   → `list-lane-modules --product-id <id>` 获取 `ModuleID / DeployType / GitRepo`。\
   \
   单泳道使用 `create-lane-delivery`。多泳道使用 `create-multi-lane-deliveries`，重复传 `--lane-id`，并用 `--module-json` 传同一组组件配置：\\

   ```bash
   python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py \
       create-multi-lane-deliveries \
       --lane-id 33 --lane-id 34 \
       --description "model-proxy 联调" \
       --module-json '{"ModuleID":167,"DeployType":3,"GitRepo":"machinelearning/model-proxy","GitRef":"feat/example","ReleaseCommit":"","ChartGitRef":"master"}'
   ```

   CLI 会先完成所有 `get_lane` 校验，再开始写入；任一创建失败后停止后续泳道。每次最多 10 条，完成首批后必须人工检查结果，再决定是否继续下一批。执行前必须明确告知用户这是 STG 真实批量发布。\
   \
   发布后按阶段观测：`get-lane-delivery` 看主状态；`ArtifactBuild` 阶段查 `list-lane-delivery-artifacts`；`HelmDiff` 阶段查 `list-lane-helm-diffs`；`Deploy` 阶段查 `list-lane-delivery-deploys`。录制中的自动阶段顺序为 `Initialize → Plan → ArtifactBuild → HelmDiff → Deploy → Finish`。即使 `HelmRenderStatus=Success`，也要检查 `ResourceItems[].RenderError`，不能只看顶层状态。\\
8. **泳道 Pod 排障（Deploy 阶段失败 / Pod 起不来）**\
   `Delivery.Status` 说的是"发布流程有没有跑完"，不等于"应用真的活着"。发布单 `Success` 但 Pod `CrashLoopBackOff` 是常见情形，必须下钻到 Pod 层。\
   \
   `list-lane-delivery-deploys --delivery-id <id> --status Failed` 定位失败模块（或 `list-lane-module-deploys --lane-id <id>` 看泳道现状）\
   → 拿到 `ModuleDeployID` → `get-lane-module-deploy --module-deploy-id <id>` 拿 `Resources[]` 与其中的 `Pods[].Name`\
   → `get-lane-pod-events` 看 `Unhealthy` / `BackOff` 等 Warning，`get-lane-pod-logs` 看业务日志：\\

   ```bash
   python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py \
       get-lane-pod-logs --module-deploy-id 1404 \
       --pod-name maas-console-66d8f5b9f5-7mnsj --limit 100
   ```

   只传 `--module-deploy-id` + `--pod-name` 即可，CLI 会自动从 ModuleDeploy 解析 `LaneID / ClusterID / Namespace`，并从 Pod spec 解析业务容器名。\
   \
   **容器名陷阱**：后端默认读名为 `main` 的容器，方舟 workload 没有这个容器，不指定 `ContainerName` 直接 500（`container main is not valid for pod`）。**容器名也不等于 HelmReleaseName** —— 实测 HelmRelease `maas-console` 的 Deployment 里容器叫 `maas-console-charts`，StatefulSet 里叫 `maas-console-charts-worker`，不能按 release 名去猜。CLI 已从 `Resources[].Pods[].LiveObject` 自动解析并跳过 `traffic-proxy` 边车；要看边车日志显式传 `--container-name traffic-proxy`。\
   \
   依赖缺失识别：Pod 日志出现 `connection refused` / `no such host` / `runtime config not loaded` 时，先用 `list-lane-module-deploys --lane-id <id> --module-id <依赖的 ModuleID>` 确认依赖模块是否已部署（已知 `maas-console-new` 依赖 `maas-runtime-config`）。\\
9. **交付事件复盘**\
   `list-delivery-events --start-time <ts> --end-time <ts> --product maas` → 拿到 `DeliveryID`\
   → `get-nacos-deployment --id <deployment_id>` 或 `list-nacos-config-deployments` 反查发布单\
   → `list-release-trains --status Running` 关联版本发布火车
10. **资源和卡型盘点**\
    `list-regions` → `list-clusters` → `list-resource-queues` → `list-foundation-gpu-types` / `list-foundation-flavors`

## 推理模板 Env 编辑 payload 拼接

Env 存在模板层（`InferenceConfig.Application.WorkerSets[].Roles[].Containers[]`）。基于最新一次 UI 追踪（`recorded_timeline0727.json`）沉淀的字段实测规范：

### 模板 Application 层字段（严格 CamelCase 单数）

```jsonc
{
  "Protocol": "http-acc",       // 不是 grpc_default；从 ListWholeInferenceConfigsV2 拿实际值
  "WorkerSets": [{
    "Name": "decode",            // "prefill" / "decode" / "acc" / "encoder" / "ams" / "router"
    "DisablePublishInternalNotReadyEndpoint": true,   // 有些 WS 上会带
    "Roles": [{
      "Name": "r-decode",        // Role 名和 WS 名不完全相同
      "Replicas": 1,
      "Expose": true,
      "FlavorType": "cpu-test",
      "RestartPolicy": "Always",
      "TerminationGracePeriodSeconds": 2,
      "MountTosSFCS": false,
      "Labels": [{"Key":"...","Value":"..."}],
      "Containers": [{
        "Name": "decode",
        "Image": "maas-stg-ap-southeast-1.cr.volces.com/maas/ark-mock-model-service:latest",
        "EntryPoint": "/opt/tiger/ark/mocks/bin/ark-mock-model-service vlm",
        "Env": [{"Name":"MOCK_VLM","Value":"true"}],   // ← 单数 Env，不是 Envs
        "Ports": [{"ListenPort":"62000","Type":"RPC"}],
        "ServiceDiscoveryPath": "/etc/config/discovery/"
      }]
    }]
  }]
}
```

**血泪陷阱**：

| 陷阱                                                            | 表现                                                               | 解药                                                                |
| ------------------------------------------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------------- |
| 用 `Envs`（复数）                                                  | `binding: expr_path=... cause=missing required parameter` 或字段被忽略 | Container 层字段就叫 `Env`                                             |
| 用 `Entrypoint`（一个词）                                           | 500 + HTML 错误页                                                   | 是 `EntryPoint` CamelCase 两个词                                      |
| 用 `list-official-inference-configs` 拿 template                | `Application.WorkerSets[*].{Envs, Image, Entrypoint}` 全部为空       | 换 `call-maas-api ListWholeInferenceConfigsV2`                     |
| 直接改 msrv `App.WorkerSets[].Envs` 后 `update-inference-service` | 返 200 但字段没落库                                                     | Env 属于 template 层，必须 `create-inference-config` 生成新版本，再 update 切过去 |
| `Protocol` 拍脑袋填 `grpc_default`                                | 服务启动异常或 Preview diff 有非预期变化                                      | 从 ListWholeInferenceConfigsV2 原样透传当前值（如 `http-acc`）               |

### create-inference-config 必填字段

```jsonc
{
  "FoundationModelName": "seed-1-8",
  "FoundationModelVersion": "seedance-omni-pe-260128",
  "TemplateName": "seedance-2.0-pe",   // 保持不变 → 自动 bump Version；改名 → 新 Template
  "Application": { /* 见上 */ }
}
```

返回 `{"Id": "fmvicv2-<新版本>"}`。

### update-inference-service 必填字段（从 `get-inference-service` 派生）

从 `InferenceService.get` 响应基础上做以下变换后 POST：

| 操作                                                 | 来源                                                                                                                                                     |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `InferenceConfigVersionV2Id = <新 fmvicv2>`         | `create-inference-config` 返回                                                                                                                           |
| `MaasServiceId = InferenceService.Id`              | 必填，与 `ServiceId` 独立                                                                                                                                    |
| `FoundationModelName / FoundationModelVersion`     | `ModelReference.FoundationModel.{Name, ModelVersion}` 顶层扁平化                                                                                            |
| `DeployType = InferenceService.ServiceType`        | 常见值 `Dynamic`                                                                                                                                          |
| `WorkerSetResourceInfos / Annotations / AppLabels` | `call-maas-api GetInferenceServiceResourceConfig → Result.*` 直接透传                                                                                      |
| dict → `[{Key, Value}]` list 转换                    | `Labels / Taints / ModelDiscoveryLabels / TrafficScheduleAnnotations / OpsAttrs`，以及 `App.Labels / App.Annotations`、每个 `WorkerSet.Labels / Annotations` |
| **删掉** `Usage` 字段                                  | `Usage: Common` 会被服务端拒 `InvalidParameter.Usage`，直接 pop 掉                                                                                               |

写接口有时会返 500 + `invalid character '<'` HTML 错误（透传自上游 500 页面）。创建配置和更新服务是非幂等操作，CLI 不会自动重试；应先查询状态，确认未生效后再决定是否重新执行。

- `list-nacos-instances → NacosInstances[].InstanceID` → 供给 `get-nacos-instance / list-nacos-namespaces / list-nacos-configs / list-nacos-batch-deployments`

- `list-nacos-configs → NacosConfigs[].ID` → `get-nacos-config`；`.DataID + .Group + .NamespaceName + .InstanceID` → `list-nacos-config-versions`

- `list-nacos-config-deployments → NacosConfigDeployments[].ID` → `get-nacos-deployment`

- `get-nacos-config → NacosConfig.ID` → `update-nacos-config / list-nacos-reviewers / create-nacos-deployment`

- `update-nacos-config` 保存新版本 → `list-nacos-reviewers → Reviewers[]` 作为 `create-nacos-deployment.Reviewer`

- `create-nacos-deployment → ID` → `publish-nacos-config.NacosDeploymentID`

- `list-inference-services → InferenceServices[].Id` → `get-inference-service / list-inference-service-events / list-inference-service-pods / list-inference-update-records / list-sfcs-warmup / list-service-alerts`（服务 ID 也直接进 URL 模板 `inference-detail`）

- `get-inference-service → InferenceService.Labels.Values` → `update-inference-service-labels` 增量合并后 PATCH 完整标签集合

- `update-inference-service-labels` 写入 `support.foundation-model.ark/<模型名>_<版本>=true` → 平台派生 `InferenceService.ModelDiscoveryLabels`；需回读详情验证

- `list-official-inference-configs → Configs[].Id` 与 `FoundationModelName + FoundationModelVersion` → `call-maas-api` payload

- `list-official-inference-configs → Configs[].Application` **仅返回结构骨架**（WorkerSets 名字 / Roles 名字），Envs / Image / EntryPoint / Ports **被 strip**；要拿完整 Application 必须用 `call-maas-api Action=ListWholeInferenceConfigsV2` 传 `{"Filter":{"Ids":["fmvicv2-..."]}}`

- `call-maas-api ListWholeInferenceConfigsV2 → Result.Items[].Application` → 修改 `WorkerSets[].Roles[].Containers[].Env` 后进入 `create-inference-config`；返回 `Id` 作为新配置版本 ID

- `call-maas-api Action=GetInferenceServiceResourceConfig → Result.ResourceQueueId / WorkerSetResourceInfos / Annotations / AppLabels` → `preview-update-inference-service / update-inference-service` 的 payload

- `preview-update-inference-service → CurrentServiceResourceInfo / CandidateServiceResourceInfo` → 人工确认 diff 后再调用 `update-inference-service`

- `list-products → Products[].ID` → `list-modules?product_id=`；`list-release-trains → ReleaseTrains[].ChangeTemplateID` 关联审批

- `list-lane-products → Products[].ID/Code` → `list-lane-product-instances.ProductCode` 与 `list-lanes.Filter.ProductID`

- `list-lanes → Lanes[].ID` → `get-lane / list-lane-module-deploys / list-lane-deliveries`

- `list-lane-module-deploys → ModuleDeploys[].ID` → `get-lane-module-deploy`；`.ModuleID` 也可反向作为 `list-lane-module-deploys --module-id` 的依赖检查入参

- `get-lane-module-deploy → Resources[].Pods[].Name` → `get-lane-pod-logs / get-lane-pod-events` 的 `--pod-name`；同一响应的 `ModuleDeploy.{LaneID,ClusterID,Namespace}` 与 `Pods[].LiveObject` 里的容器名由 CLI 自动透传，无需手工拼

- `list-lane-delivery-deploys → DeliveryModuleDeploys[].ModuleDeployID` → `get-lane-module-deploy`（Deploy 阶段失败下钻到 Pod 的必经一跳）

- `get-lane → Lane.{ID,ProductID,ProductInstanceID}` → `create-lane-delivery`

- `list-lane-modules → Modules[].{ID,ImageGitRepo,SupportDeployType}` → `create-lane-delivery.ModulesToDelivery[]`

- `create-lane-delivery → ID` → `get-lane-delivery / list-lane-delivery-artifacts / list-lane-helm-diffs / list-lane-delivery-deploys`

- `list-delivery-events → DeliveryEvents[].DeliveryID` → 反查 `get-nacos-deployment` 或 `list-nacos-config-deployments`

- `list-fed-control-clusters → FedControlClusters[].Id` → `list-dcp-member-clusters --dcp-control-cluster-id`

## 输出处理建议

- 列表类命令优先只显示 `Id / Name / Status / CreatedBy / Region` 与总数；需要看细节再展开。

- CronJob 应用目录优先摘要 `ID / Name / Description / Owner / Endpoints[].{Stage,IDCName,SchedCount}`；堡垒机结果必须同时摘要两个支持状态字段和 `LoginMessage`。

- 遇到写接口（`create-lane-delivery`、`create-multi-lane-deliveries`、`update-inference-service-labels`、`create-inference-config`、`preview-update-inference-service`、`update-inference-service` 或 `call-maas-api` 非明确只读 Action）：**在明确用户授权后再执行**，并说明 `prod/online` 不支持写接口。

- `get-or-create-vbh-login-message` 也属于真实 STG 写操作；名称中的 `get` 不代表纯只读，必须先获得明确授权。

- Nacos 的保存配置、创建发布单、审批发布也属于真实写操作；不得对模糊失败自动重试。

- 失败请求原样保留 `status / url / error`，不做二次解释。

## 接口分析报告

最新录制分析报告位于：

```text
/Users/neverth/gitlab/ark_all/api_analysis_v1.html
```

后续如需重新基于录制生成报告，可在确认允许写入报告文件后运行：

```bash
python3 .agents/skills/mlops-stg-skill/scripts/build_api_analysis_report.py \
    "/Users/neverth/gitlab/ark_all/recorded_timeline (3).json"
```

## 覆盖验证

对录制的 timeline 文件运行离线校验：

```
python3 .agents/skills/mlops-stg-skill/scripts/mlops_stg_cli.py verify timeline-coverage <timeline.json> --pretty
```

输出：

- `covered` — (method, path) → 命中的 CLI 命令 + 出现次数

- `excluded_by_user_scope` — 用户显式排除的通用/框架接口

- `missing` — 未覆盖且不属于排除范围的请求，`missing_count = 0` 表示已全覆盖

## 排除范围（不进入 CLI 的通用接口）

- `/_sre/openapi/whoami`

- `/_sre/openapi/idc`

- `/_sre/openapi/accessible_apps`

- `/_sre/openapi/devsre_config`

- `/_sre/openapi/apps/mlops`

- `/_sre/openapi/apps/mlops/actions`

- `/_sre/openapi/apps/mlops/permissions`

## 测试

CLI 自带离线单元测试，覆盖读接口入参、URL、路径优先级、写接口安全保护和覆盖率校验。写接口的真实请求用例默认跳过；设置 `MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1` 后也只会请求测试文件启动的本地 mock server，不会访问 MLOps STG：

```
python3 .agents/skills/mlops-stg-skill/tests/test_cli.py -v
```

测试内部启动一个 stdlib http.server 作为 mock，测试数据固化在测试文件中，不依赖任何录制文件。

## 环境变量（面向 CI / 测试）

- `MLOPS_ENV` — 目标环境，`stg` 或 `prod`；默认 `stg`

- `MLOPS_BASE_URL` — 覆盖当前环境的业务平台 base URL

- `MLOPS_STG_BASE_URL` — 覆盖预发 base URL（默认 `https://mlops-stg.bytedance.net`）

- `MLOPS_PROD_BASE_URL` — 覆盖线上 base URL（默认 `https://mlops.bytedance.net`）

- `MLOPS_AUTH_JSON` — 直接注入请求 header 的 JSON dict（供离线测试跳过任何鉴权流程）

- `MLOPS_STG_AUTH_JSON` — 预发专用 header JSON，兼容旧测试配置

- `MLOPS_PROD_AUTH_JSON` — 线上专用 header JSON

- `MLOPS_REGION` — 当前环境的会话级 `X-MLOps-Region` 默认值，等价于每条命令都带 `--mlops-region`

- `MLOPS_STG_REGION` / `MLOPS_PROD_REGION` — 环境专属 region 默认值；留空 = 平台默认 cn 分区

- `MLOPS_AUTH_CACHE_FILE` — 覆盖 JWT 缓存文件路径；默认按环境隔离为 `/tmp/mlops_stg_skill_auth.json` 或 `/tmp/mlops_prod_skill_auth.json`

- `MLOPS_STG_WRITE_HOSTS` — 额外允许执行 STG 写操作的主机名白名单，逗号分隔；默认仅允许官方 STG 域名与本地回环地址

