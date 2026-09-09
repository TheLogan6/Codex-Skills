#!/usr/bin/env python3
"""基于 MLOps 页面录制生成接口分析 HTML 报告。"""

import argparse
import collections
import html
import json
import os
import urllib.parse


BUSINESS_NAMES = {
    "/_sre/openapi/proxy/consul/api/v1/mlops_xcron/apps": "CronJob 应用目录",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/product": "CICD 产品列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/module": "CICD 模块列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/delivery": "产品交付单",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/infrastructure_delivery": "基础设施交付单",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/change_template": "变更模板",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/common/list_reviewers": "Nacos 发布审批人",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_instance": "Nacos 实例列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_instance": "Nacos 实例详情",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_namespace": "Nacos 命名空间列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config": "Nacos 配置列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_config": "Nacos 配置详情",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config_version": "Nacos 配置版本",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config_deployment": "Nacos 发布单列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_deployment": "Nacos 发布单详情",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/update_config": "保存 Nacos 配置新版本",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/create_deployment": "创建 Nacos 发布单",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/publish_config": "审批或发布 Nacos 配置",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_product": "泳道产品列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_product_region_instance": "泳道产品环境",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_lane": "泳道列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_lane": "泳道详情",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module": "泳道可发布组件",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module_deploy": "泳道当前应用",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery": "泳道交付记录",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_delivery": "泳道发布详情",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_artifact_by_delivery": "泳道发布制品",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_module_deploy_by_delivery": "泳道模块部署结果",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_helm_diff_by_delivery": "泳道 HelmDiff",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/create_delivery": "创建泳道发布单",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services": "推理服务详情与列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_events": "推理服务事件",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_pods": "推理服务 Pod 分布",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_hpa_metrics": "HPA 指标定义",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/mr_inference_service_hpa_jobs": "HPA 任务",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/resource_stats/dcp_gpu_types": "DCP GPU 资源统计",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_service_update_records": "推理服务更新记录",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_config_templates": "推理配置模板",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs_official": "官方推理配置",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs": "创建推理配置或新版本",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/preview_update_inference_service": "预览推理服务更新",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_services": "提交推理服务更新",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/maas_api_proxy/": "底层 MaaS OpenAPI 代理",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/fed_control_clusters": "DCP 联邦控制集群",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/dcp_member_clusters": "DCP 成员集群",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/regions": "CMDB Region",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/clusters": "CMDB 集群列表",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/resource_queues": "资源队列",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/sfcs_warmup": "SFCS 预热",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/vbh/get_or_create_vbh_login_message": "查询或创建方舟堡垒机登录信息",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_models": "Foundation Model",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_ark_flavors": "推理规格 Flavor",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/inference_engine_images": "推理引擎镜像",
    "/_sre/openapi/proxy/consul/api/v1/mlops_eventcenter/ark_service_alerts": "服务告警",
    "/_sre/openapi/proxy/consul/api/v1/mlops_eventcenter/events": "事件中心操作日志",
}

EXCLUDED_PATHS = {
    "/_sre/openapi/whoami",
    "/_sre/openapi/idc",
    "/_sre/openapi/accessible_apps",
    "/_sre/openapi/devsre_config",
    "/_sre/openapi/apps/mlops",
    "/_sre/openapi/apps/mlops/actions",
    "/_sre/openapi/apps/mlops/permissions",
}

WRITE_PATHS = {
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/update_config",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/create_deployment",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/publish_config",
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/create_delivery",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/preview_update_inference_service",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_services",
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/vbh/get_or_create_vbh_login_message",
}


def _is_inference_service_labels_path(path):
    prefix = "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/"
    return path.startswith(prefix) and path.endswith("/labels")


def _is_write_path(path):
    return path in WRITE_PATHS or _is_inference_service_labels_path(path)


REQUIRED_INPUTS = {
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/vbh/get_or_create_vbh_login_message": [
        "VkeClusterRegion", "RequestType", "ProductName", "VkeClusterName",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_instance": [
        "InstanceID",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_namespace": [
        "InstanceID", "PageNum", "PageSize",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config": [
        "PageNum", "PageSize", "Filter.InstanceID",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_config": [
        "ID",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config_version": [
        "PageNum", "PageSize", "Filter.InstanceID", "Filter.DataID",
        "Filter.Group", "Filter.NamespaceName",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_deployment": [
        "ID",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/common/list_reviewers": [
        "NacosConfigID", "type",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/update_config": [
        "NacosConfigID", "NacosConfigVersion.Content", "NacosConfigVersion.Type",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/create_deployment": [
        "NacosConfigID", "Reviewer", "Comment", "IsUrgent",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/publish_config": [
        "NacosDeploymentID", "Status",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery": [
        "PageNum", "PageSize", "Filter.LaneID / Filter.Statuses / Filter.CreatedBy",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_product_region_instance": [
        "ProductCode",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_lane": [
        "PageNum", "PageSize", "Filter.ProductID",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_lane": ["ID"],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module": ["ProductID"],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module_deploy": [
        "PageNum", "PageSize", "Filter.LaneID",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_delivery": ["DeliveryID"],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_artifact_by_delivery": [
        "DeliveryID",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_module_deploy_by_delivery": [
        "DeliveryID",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_helm_diff_by_delivery": [
        "DeliveryID",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/create_delivery": [
        "ProductID", "LaneID", "ProductInstanceID", "DeployMode",
        "StageAutoNext", "ModulesToDelivery",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_events": ["service_id"],
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_pods": ["service_id"],
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_service_update_records": ["service_id"],
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/maas_api_proxy/": ["Action", "Version", "payload 由 Action 决定"],
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs": [
        "FoundationModelName", "FoundationModelVersion", "TemplateName", "Application",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/preview_update_inference_service": [
        "MaasServiceId", "Region", "InferenceConfigVersionV2Id", "WorkerSetResourceInfos",
    ],
    "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_services": [
        "MaasServiceId", "Region", "InferenceConfigVersionV2Id", "WorkerSetResourceInfos",
    ],
}


def _load_events(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("timeline must be a JSON list")
    return data


def _short_json(value, limit=1400):
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, indent=2)
    else:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) > limit:
        text = text[:limit] + "\n..."
    return html.escape(text)


def _parse_json(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _is_sensitive_name(value):
    normalized = str(value or "").lower().replace("-", "_")
    sensitive_words = ("password", "passwd", "secret", "token", "cookie",
                       "authorization", "credential", "api_key", "access_key",
                       "private_key", "redis_pass")
    return any(word in normalized for word in sensitive_words) or normalized.endswith(("_ak", "_sk"))


def _redact(value):
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    sensitive_env = _is_sensitive_name(value.get("Name"))
    for key, item in value.items():
        if (
            _is_sensitive_name(key)
            or str(key).lower() in ("content", "resolvedvalues", "resolved_values")
            or (key == "Value" and sensitive_env)
        ):
            result[key] = "***REDACTED***"
        else:
            result[key] = _redact(item)
    return result


def _response_shape(value):
    value = _parse_json(value)
    if isinstance(value, dict):
        return "object {" + ", ".join(sorted(value.keys())) + "}"
    if isinstance(value, list):
        return "array[%d]" % len(value)
    if value is None:
        return "无响应体"
    return type(value).__name__


def _category(path):
    if "/mlops_xcron/" in path or "/vbh/" in path:
        return "基础服务与堡垒机"
    if "/mlops_cicd/" in path or "/mlops_cicd_lane/" in path:
        return "Nacos 与 CICD"
    if "/cmdb/" in path:
        return "CMDB 与资源"
    if "/foundation_" in path or path.endswith("/inference_engine_images"):
        return "模型与规格目录"
    if "/splitwise_models/" in path or path.endswith("/maas_api_proxy/"):
        return "Splitwise 与服务配置"
    if "model_inferences_service" in path or path.endswith("/fed_control_clusters"):
        return "推理服务运行态"
    if "/mlops_eventcenter/" in path:
        return "事件与告警"
    return "其他业务能力"


def _business_name(path):
    if path in BUSINESS_NAMES:
        return BUSINESS_NAMES[path]
    if _is_inference_service_labels_path(path):
        return "更新推理服务标签"
    prefix = "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/"
    if path.startswith(prefix):
        return "推理服务详情"
    return "通用/框架接口" if path in EXCLUDED_PATHS else "待人工确认"


def _collect(events):
    rows = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "NETWORK_REQUEST" and event.get("action") != "NETWORK_REQUEST":
            continue
        method = (event.get("method") or "").upper()
        raw_url = event.get("url") or ""
        parsed = urllib.parse.urlparse(raw_url)
        if not parsed.path:
            continue
        rows.append({
            "method": method,
            "path": parsed.path,
            "query": parsed.query,
            "status": event.get("status"),
            "page": urllib.parse.urlparse(event.get("page_url") or "").path,
            "page_url": event.get("page_url") or "",
            "payload": event.get("payload"),
            "response": event.get("response"),
        })

    counts = collections.Counter((r["method"], r["path"]) for r in rows)
    pages = collections.Counter(r["page"] for r in rows if r["page"])
    actions = collections.Counter()
    for r in rows:
        if r["path"].endswith("/maas_api_proxy/"):
            qs = urllib.parse.parse_qs(r["query"])
            actions[qs.get("Action", [""])[0]] += 1
    return rows, counts, pages, actions


def _render_table(rows, counts):
    parts = []
    for (method, path), count in sorted(counts.items(), key=lambda item: (item[0][1], item[0][0])):
        sample = next(r for r in rows if r["method"] == method and r["path"] == path)
        business = _business_name(path)
        query_keys = sorted(urllib.parse.parse_qs(sample["query"], keep_blank_values=True).keys())
        statuses = sorted({
            str(row["status"])
            for row in rows
            if row["method"] == method and row["path"] == path
        })
        parts.append(
            "<tr><td><code>{}</code></td><td><code>{}</code></td><td>{}</td>"
            "<td>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(method),
                html.escape(path),
                count,
                html.escape(business),
                html.escape(", ".join(query_keys) or "-"),
                html.escape(", ".join(statuses)),
            )
        )
    return "\n".join(parts)


def _render_endpoint_details(rows, counts):
    parts = []
    for (method, path), count in sorted(counts.items(), key=lambda item: (item[0][1], item[0][0])):
        sample = next(r for r in rows if r["method"] == method and r["path"] == path)
        query = urllib.parse.parse_qs(sample["query"], keep_blank_values=True)
        required = REQUIRED_INPUTS.get(path, [])
        if _is_inference_service_labels_path(path):
            required = ["路径参数 service_id", "Values"]
        if "/model_inferences_services/" in path and path.rsplit("/", 1)[-1].startswith("msrv-"):
            required = ["路径参数 service_id"]
        optional = [key for key in sorted(query) if key not in required]
        payload = _redact(_parse_json(sample["payload"]))
        response = _redact(_parse_json(sample["response"]))
        statuses = sorted({
            str(row["status"])
            for row in rows
            if row["method"] == method and row["path"] == path
        })
        scope = "排除：通用/框架接口" if path in EXCLUDED_PATHS else "接入：业务接口"
        write_badge = '<span class="badge write">写操作</span>' if _is_write_path(path) else ""
        parts.append(
            """
<details>
  <summary><code>{method}</code> {business} <span class="badge">{count} 次</span>{write_badge}</summary>
  <div class="detail-grid">
    <div><b>Path</b><code class="path">{path}</code></div>
    <div><b>分类</b>{category} · {scope}</div>
    <div><b>必填入参</b>{required}</div>
    <div><b>可选入参</b>{optional}</div>
    <div><b>返回结构</b>{response_shape}</div>
    <div><b>状态码</b>{status}</div>
  </div>
  <div class="sample-grid">
    <div><b>Query 样例</b><pre>{query}</pre></div>
    <div><b>Payload 样例（已脱敏）</b><pre>{payload}</pre></div>
    <div><b>Response 样例（已脱敏）</b><pre>{response}</pre></div>
  </div>
</details>""".format(
                method=html.escape(method),
                business=html.escape(_business_name(path)),
                count=count,
                write_badge=write_badge,
                path=html.escape(path),
                category=html.escape(_category(path)),
                scope=scope,
                required=html.escape(", ".join(required) or "无"),
                optional=html.escape(", ".join(optional) or "无"),
                response_shape=html.escape(_response_shape(sample["response"])),
                status=html.escape(", ".join(statuses)),
                query=_short_json(query),
                payload=_short_json(payload),
                response=_short_json(response),
            )
        )
    return "\n".join(parts)


def _render_capabilities(counts):
    grouped = collections.defaultdict(list)
    for method, path in counts:
        if path in EXCLUDED_PATHS:
            continue
        grouped[_category(path)].append("%s %s" % (method, _business_name(path)))
    return "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(category), len(items), html.escape("；".join(sorted(items)))
        )
        for category, items in sorted(grouped.items())
    )


def _render_page_links(rows):
    counts = collections.Counter(r["page_url"] for r in rows if r["page_url"])
    return "\n".join(
        '<li><a href="{url}">{path}</a><span>{count} 次请求</span></li>'.format(
            url=html.escape(url, quote=True),
            path=html.escape(urllib.parse.urlparse(url).path),
            count=count,
        )
        for url, count in counts.most_common()
    )


def _diagram_profile(counts, pages):
    paths = {path for _method, path in counts}
    page_summary = ", ".join("%s=%s" % (key, value) for key, value in pages.most_common())
    if any(_is_inference_service_labels_path(path) for path in paths):
        return {
            "flow_title": "推理服务标签到服务发现标签的更新链路",
            "flow_nodes": [
                ("打开服务详情", "读取现有 Labels"),
                ("选择模型 Label", "Foundation Model"),
                ("确认标签集合", "保留原有 Values"),
                ("提交标签更新", "PATCH /labels"),
                ("回读服务详情", "检查 Labels"),
                ("验证服务发现", "ModelDiscoveryLabels"),
            ],
            "flow_notes": [
                "页面分布：" + page_summary,
                "关键字段：service_id、Labels.Values、BatchToOnline、ModelDiscoveryLabels",
                "写入事实：PATCH 接收完整 Values；平台根据 support.foundation-model 标签派生服务发现模型名和版本标签。",
            ],
            "asset_nodes": [
                ("Inference Service", "service_id"),
                ("Service Labels", "Labels.Values"),
                ("Foundation Model", "模型名 + 版本"),
                ("Discovery Labels", "模型名 / 版本 / 类型"),
                ("路由候选集", "Ready 服务实例"),
            ],
            "asset_edges": ["读取现值", "选择模型", "平台派生", "参与发现"],
            "coverage_note": (
                "本轮新增接入 1 个写接口：更新推理服务标签。录制中的 PATCH 并不直接写 "
                "ModelDiscoveryLabels，而是写入 support.foundation-model 标签，由平台派生服务发现标签。"
            ),
        }
    if (
        "/_sre/openapi/proxy/consul/api/v1/mlops_xcron/apps" in paths
        or "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/vbh/get_or_create_vbh_login_message" in paths
    ):
        return {
            "flow_title": "基础服务与方舟堡垒机登录链路",
            "flow_nodes": [
                ("打开基础服务", "CronJob 应用目录"),
                ("进入方舟开发机", "加载 Region"),
                ("选择目标 Region", "加载 VKE 集群"),
                ("选择目标集群", "VkeClusterName"),
                ("查询登录信息", "get_or_create_vbh_login_message"),
                ("返回登录结果", "LoginMessage / 支持状态"),
            ],
            "flow_notes": [
                "页面分布：" + page_summary,
                "关键字段：VkeClusterRegion、VkeClusterName、RequestType、ProductName。",
                "写入事实：查询接口具有 get_or_create 语义，仅支持 STG；CLI 不对失败请求自动重试。",
            ],
            "asset_nodes": [
                ("CronJob App", "Name + Owner"),
                ("CMDB Region", "Region ID"),
                ("VKE Cluster", "ClusterName"),
                ("VBH Request", "Region + Cluster"),
                ("Login Result", "LoginMessage + 支持状态"),
            ],
            "asset_edges": ["应用目录", "地域筛选", "集群选择", "查询登录信息"],
            "coverage_note": (
                "本轮新增接入 CronJob 应用目录和方舟堡垒机登录信息接口；"
                "集群列表分页参数按最新录制修正为 page_number。"
            ),
        }
    if any("/mlops_cicd_lane/" in path for path in paths):
        return {
            "flow_title": "多泳道发布与状态观测链路",
            "flow_nodes": [
                ("筛选泳道", "产品 / 环境 / 状态"),
                ("选择组件", "ModuleID + GitRef"),
                ("创建发布单", "每条泳道独立 DeliveryID"),
                ("构建制品", "Image + Chart"),
                ("确认变更", "HelmDiff"),
                ("部署完成", "Deploy → Finish"),
            ],
            "flow_notes": [
                "页面分布：" + page_summary,
                "关键 ID：ProductID、ProductInstanceID、LaneID、ModuleID、DeliveryID。",
                "批量边界：多泳道发布按泳道逐单创建，每批最多 10 条；创建属于 STG 真实写操作。",
            ],
            "asset_nodes": [
                ("Product", "ProductID"),
                ("Region Instance", "ProductInstanceID"),
                ("Lane", "LaneID"),
                ("Module", "ModuleID + GitRef"),
                ("Delivery", "DeliveryID + Stage"),
            ],
            "asset_edges": ["环境归属", "泳道归属", "选择组件", "创建发布"],
            "coverage_note": (
                "本轮接入泳道产品、环境、泳道、组件、当前应用、发布单、制品、"
                "HelmDiff、部署结果和创建发布接口，并补充最多 10 条的多泳道发布编排。"
            ),
        }
    if any(
        "/mlops_cicd/" in path or "/mlops_cicd_lane/" in path
        for path in paths
    ):
        return {
            "flow_title": "Nacos 配置保存与发布链路",
            "flow_nodes": [
                ("筛选配置", "list_config"),
                ("读取并编辑", "get_config"),
                ("保存新版本", "update_config"),
                ("选择审批人", "list_reviewers"),
                ("创建发布单", "create_deployment"),
                ("审批与发布", "publish_config"),
            ],
            "flow_notes": [
                "页面分布：" + page_summary,
                "关键 ID：InstanceID、NacosConfigID、NacosDeploymentID、ChangeTemplateID",
                "写接口限制：保存版本、创建发布单、审批发布仅支持 STG，且不自动重试。",
            ],
            "asset_nodes": [
                ("Nacos Instance", "InstanceID"),
                ("Nacos Config", "ID + DataID"),
                ("Config Version", "Type + Tags"),
                ("Deployment", "ID + Status"),
                ("Reviewer / Template", "审批依赖"),
            ],
            "asset_edges": ["实例归属", "版本保存", "审批发布", "审批依赖"],
            "coverage_note": (
                "本轮新增接入 6 个接口：变更模板、审批人、保存配置、创建发布单、"
                "审批发布和泳道交付记录。"
            ),
        }
    return {
        "flow_title": "推理配置创建到服务更新链路",
        "flow_nodes": [
            ("筛选官方配置", "读取 Application"),
            ("编辑模板", "WorkerSets / Roles"),
            ("确认创建", "inference_configs"),
            ("返回配置 ID", "fmvicv2-..."),
            ("绑定推理服务", "预览资源配置 diff"),
            ("提交更新", "inference_services"),
        ],
        "flow_notes": [
            "页面分布：" + page_summary,
            "关键 ID：MaasServiceId、InferenceConfigVersionV2Id、ResourceQueueId、TemplateName/TemplateVersion",
            "写接口限制：创建配置、预览更新、提交更新仅支持 STG；prod/online 由 CLI 主动拒绝。",
        ],
        "asset_nodes": [
            ("Foundation Model", "Name + ModelVersion"),
            ("Inference Config", "Id + TemplateVersion"),
            ("Inference Service", "MaasServiceId"),
            ("Resource Queue", "GPU / Flavor"),
            ("HPA / KEDA 指标", "WorkerSet 资源参数"),
        ],
        "asset_edges": ["模型归属", "配置绑定", "资源调度", "预览 diff"],
        "coverage_note": (
            "推理配置创建、预览更新、提交更新与 MaaS OpenAPI Action "
            "由对应 CLI 命令统一覆盖。"
        ),
    }


def build_report(timeline_path):
    events = _load_events(timeline_path)
    rows, counts, pages, actions = _collect(events)
    business_count = sum(v for (m, p), v in counts.items() if p not in EXCLUDED_PATHS)
    excluded_count = sum(v for (m, p), v in counts.items() if p in EXCLUDED_PATHS)
    write_count = sum(v for (m, p), v in counts.items() if _is_write_path(p))
    action_rows = "\n".join(
        "<tr><td><code>{}</code></td><td>{}</td></tr>".format(html.escape(k), v)
        for k, v in actions.most_common()
    )
    endpoint_rows = _render_table(rows, counts)
    endpoint_details = _render_endpoint_details(rows, counts)
    diagram = _diagram_profile(counts, pages)
    flow_nodes = diagram["flow_nodes"]
    asset_nodes = diagram["asset_nodes"]
    return REPORT_TEMPLATE.format(
        timeline=html.escape(timeline_path),
        total=len(rows),
        business_count=business_count,
        excluded_count=excluded_count,
        write_count=write_count,
        pages=html.escape(", ".join("%s=%s" % (k, v) for k, v in pages.most_common())),
        action_rows=action_rows,
        endpoint_rows=endpoint_rows,
        endpoint_details=endpoint_details,
        capability_rows=_render_capabilities(counts),
        page_links=_render_page_links(rows),
        flow_title=html.escape(diagram["flow_title"]),
        flow_1a=html.escape(flow_nodes[0][0]),
        flow_1b=html.escape(flow_nodes[0][1]),
        flow_2a=html.escape(flow_nodes[1][0]),
        flow_2b=html.escape(flow_nodes[1][1]),
        flow_3a=html.escape(flow_nodes[2][0]),
        flow_3b=html.escape(flow_nodes[2][1]),
        flow_4a=html.escape(flow_nodes[3][0]),
        flow_4b=html.escape(flow_nodes[3][1]),
        flow_5a=html.escape(flow_nodes[4][0]),
        flow_5b=html.escape(flow_nodes[4][1]),
        flow_6a=html.escape(flow_nodes[5][0]),
        flow_6b=html.escape(flow_nodes[5][1]),
        flow_note_1=html.escape(diagram["flow_notes"][0]),
        flow_note_2=html.escape(diagram["flow_notes"][1]),
        flow_note_3=html.escape(diagram["flow_notes"][2]),
        asset_1a=html.escape(asset_nodes[0][0]),
        asset_1b=html.escape(asset_nodes[0][1]),
        asset_2a=html.escape(asset_nodes[1][0]),
        asset_2b=html.escape(asset_nodes[1][1]),
        asset_3a=html.escape(asset_nodes[2][0]),
        asset_3b=html.escape(asset_nodes[2][1]),
        asset_4a=html.escape(asset_nodes[3][0]),
        asset_4b=html.escape(asset_nodes[3][1]),
        asset_5a=html.escape(asset_nodes[4][0]),
        asset_5b=html.escape(asset_nodes[4][1]),
        edge_1=html.escape(diagram["asset_edges"][0]),
        edge_2=html.escape(diagram["asset_edges"][1]),
        edge_3=html.escape(diagram["asset_edges"][2]),
        edge_4=html.escape(diagram["asset_edges"][3]),
        coverage_note=html.escape(diagram["coverage_note"]),
    )


REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>MLOps 录制接口分析报告</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #F8FAFC; color: #1E293B;
    font-family: -apple-system, system-ui, 'PingFang SC', sans-serif; }}
  main {{ width: 1180px; margin: 0 auto; padding: 28px 0 48px; }}
  h1 {{ margin: 0 0 8px; font-size: 24px; color: #0F172A; }}
  h2 {{ margin: 28px 0 12px; font-size: 18px; color: #0F172A; }}
  p {{ line-height: 1.7; color: #475569; }}
  code, pre {{ font-family: 'JetBrains Mono', 'SF Mono', monospace; }}
  .card {{ background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px;
    padding: 20px; margin-top: 16px; }}
  .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .metric {{ background: #F5F3FF; border: 1px solid #C4B5FD; border-radius: 10px; padding: 14px; }}
  .metric b {{ display: block; font-size: 22px; color: #5B21B6; margin-bottom: 4px; }}
  .metric span {{ color: #64748B; font-size: 13px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid #E2E8F0; padding: 10px 8px; vertical-align: top; }}
  th {{ text-align: left; background: #F8FAFC; color: #334155; }}
  tr:hover td {{ background: #FAFAFF; }}
  .note {{ border-left: 4px solid #8B5CF6; background: #F5F3FF; padding: 12px 14px; border-radius: 8px; }}
  .warn {{ border-left: 4px solid #F59E0B; background: #FFFBEB; padding: 12px 14px; border-radius: 8px; }}
  details {{ border: 1px solid #E2E8F0; border-radius: 10px; margin: 10px 0; background: #FFFFFF; }}
  summary {{ cursor: pointer; padding: 13px 16px; font-weight: 600; }}
  .badge {{ display: inline-block; margin-left: 8px; padding: 2px 8px; border-radius: 999px;
    background: #F1F5F9; color: #64748B; font-size: 11px; }}
  .badge.write {{ background: #FFFBEB; color: #92400E; }}
  .detail-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px 24px;
    border-top: 1px solid #E2E8F0; padding: 14px 16px; font-size: 13px; }}
  .detail-grid b, .sample-grid b {{ display: block; color: #475569; margin-bottom: 6px; }}
  .path {{ display: block; margin-top: 4px; overflow-wrap: anywhere; }}
  .sample-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; padding: 0 16px 16px; }}
  pre {{ margin: 0; padding: 10px; max-height: 260px; overflow: auto; white-space: pre-wrap;
    background: #F8FAFC; border-radius: 8px; font-size: 11px; }}
  .nav-list {{ list-style: none; padding: 0; margin: 0; }}
  .nav-list li {{ display: flex; justify-content: space-between; gap: 16px; padding: 9px 0;
    border-bottom: 1px solid #F1F5F9; }}
  .nav-list a {{ color: #5B21B6; overflow-wrap: anywhere; }}
  .nav-list span {{ color: #94A3B8; white-space: nowrap; }}
  svg {{ display: block; width: 100%; height: auto; }}
</style>
</head>
<body>
<main>
  <h1>MLOps 录制接口分析报告</h1>
  <p>录制文件：<code>{timeline}</code></p>
  <section class="grid">
    <div class="metric"><b>{total}</b><span>网络请求总数</span></div>
    <div class="metric"><b>{business_count}</b><span>业务接口请求</span></div>
    <div class="metric"><b>{excluded_count}</b><span>排除的通用接口</span></div>
    <div class="metric"><b>{write_count}</b><span>写接口请求</span></div>
  </section>

  <section class="card">
    <h2>业务平台能力盘点</h2>
    <table><thead><tr><th>能力域</th><th>接口数</th><th>操作面</th></tr></thead><tbody>
      {capability_rows}
    </tbody></table>
  </section>

  <section class="card">
    <h2>业务流概览</h2>
    <svg viewBox="0 0 1120 260" role="img" aria-label="{flow_title}">
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#94A3B8"/>
        </marker>
      </defs>
      <rect x="12" y="16" width="1096" height="226" rx="12" fill="#FFFFFF" stroke="#E2E8F0"/>
      <text x="32" y="44" font-size="16" font-weight="700" fill="#0F172A">{flow_title}</text>
      <g font-size="13" fill="#1E293B">
        <rect x="32" y="86" width="150" height="58" rx="8" fill="#EFF6FF" stroke="#93C5FD"/>
        <text x="55" y="111">{flow_1a}</text><text x="48" y="130">{flow_1b}</text>
        <rect x="216" y="86" width="150" height="58" rx="8" fill="#F5F3FF" stroke="#C4B5FD"/>
        <text x="247" y="111">{flow_2a}</text><text x="229" y="130">{flow_2b}</text>
        <rect x="400" y="86" width="150" height="58" rx="8" fill="#FFFBEB" stroke="#FCD34D"/>
        <text x="428" y="111">{flow_3a}</text><text x="415" y="130">{flow_3b}</text>
        <rect x="584" y="86" width="150" height="58" rx="8" fill="#ECFDF5" stroke="#6EE7B7"/>
        <text x="615" y="111">{flow_4a}</text><text x="606" y="130">{flow_4b}</text>
        <rect x="768" y="86" width="150" height="58" rx="8" fill="#EFF6FF" stroke="#93C5FD"/>
        <text x="797" y="111">{flow_5a}</text><text x="784" y="130">{flow_5b}</text>
        <rect x="952" y="86" width="136" height="58" rx="8" fill="#ECFDF5" stroke="#6EE7B7"/>
        <text x="984" y="111">{flow_6a}</text><text x="966" y="130">{flow_6b}</text>
      </g>
      <g stroke="#94A3B8" stroke-width="1.5" marker-end="url(#arrow)">
        <line x1="182" y1="115" x2="216" y2="115"/><line x1="366" y1="115" x2="400" y2="115"/>
        <line x1="550" y1="115" x2="584" y2="115"/><line x1="734" y1="115" x2="768" y2="115"/>
        <line x1="918" y1="115" x2="952" y2="115"/>
      </g>
      <g fill="#64748B" font-size="12">
        <text x="48" y="178">{flow_note_1}</text>
        <text x="48" y="202">{flow_note_2}</text>
        <text x="48" y="226">{flow_note_3}</text>
      </g>
    </svg>
  </section>

  <section class="card">
    <h2>关键资产关系与接口级联</h2>
    <svg viewBox="0 0 1120 260" role="img" aria-label="MLOps 关键资产业务关系">
      <defs>
        <marker id="asset-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#94A3B8"/>
        </marker>
      </defs>
      <g stroke="#94A3B8" stroke-width="1.5" marker-end="url(#asset-arrow)">
        <line x1="226" y1="104" x2="326" y2="104"/><line x1="530" y1="104" x2="630" y2="104"/>
        <line x1="834" y1="104" x2="934" y2="104"/>
        <path d="M732 142 L732 198 L530 198" fill="none"/>
      </g>
      <g font-size="13" fill="#1E293B">
        <rect x="24" y="72" width="202" height="64" rx="8" fill="#EFF6FF" stroke="#93C5FD"/>
        <text x="58" y="98">{asset_1a}</text><text x="45" y="118">{asset_1b}</text>
        <rect x="326" y="72" width="204" height="64" rx="8" fill="#F5F3FF" stroke="#C4B5FD"/>
        <text x="365" y="98">{asset_2a}</text><text x="350" y="118">{asset_2b}</text>
        <rect x="630" y="72" width="204" height="64" rx="8" fill="#ECFDF5" stroke="#6EE7B7"/>
        <text x="672" y="98">{asset_3a}</text><text x="683" y="118">{asset_3b}</text>
        <rect x="934" y="72" width="162" height="64" rx="8" fill="#FFFBEB" stroke="#FCD34D"/>
        <text x="962" y="98">{asset_4a}</text><text x="966" y="118">{asset_4b}</text>
        <rect x="326" y="170" width="204" height="56" rx="8" fill="#F8FAFC" stroke="#CBD5E1" stroke-dasharray="6 3"/>
        <text x="365" y="192">{asset_5a}</text><text x="356" y="211">{asset_5b}</text>
      </g>
      <g fill="#64748B" font-size="11">
        <text x="248" y="94">{edge_1}</text><text x="552" y="94">{edge_2}</text><text x="856" y="94">{edge_3}</text>
        <text x="544" y="188">{edge_4}</text>
      </g>
    </svg>
  </section>

  <section class="card">
    <h2>MaaS OpenAPI Action 统计</h2>
    <table><thead><tr><th>Action</th><th>次数</th></tr></thead><tbody>
      {action_rows}
    </tbody></table>
  </section>

  <section class="card">
    <h2>接口覆盖与接入决策</h2>
    <p class="note">{coverage_note}</p>
    <p class="warn">写接口不提供 prod/online 能力。调用写命令时需要说明这是 STG 写操作，且执行会产生真实变更。</p>
    <table><thead><tr><th>方法</th><th>路径</th><th>次数</th><th>业务含义</th><th>Query 参数</th><th>状态</th></tr></thead><tbody>
      {endpoint_rows}
    </tbody></table>
  </section>

  <section class="card">
    <h2>资源导航 URL</h2>
    <ul class="nav-list">
      {page_links}
    </ul>
  </section>

  <section class="card">
    <h2>接口详情</h2>
    <p>每项默认折叠。样例仅来自本轮录制，敏感字段已替换为 <code>***REDACTED***</code>。</p>
    {endpoint_details}
  </section>
</main>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Build MLOps API analysis report from timeline JSON")
    parser.add_argument("timeline_file")
    parser.add_argument("-o", "--output",
                        help="Output HTML path. Default: api_analysis_v1.html beside timeline file")
    args = parser.parse_args()
    out = args.output or os.path.join(os.path.dirname(os.path.abspath(args.timeline_file)), "api_analysis_v1.html")
    report = build_report(args.timeline_file)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(out)


if __name__ == "__main__":
    main()
