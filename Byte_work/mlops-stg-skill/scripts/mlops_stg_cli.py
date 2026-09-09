#!/usr/bin/env python3
"""ml-maas / mlops 业务平台 CLI。

CLI 只依赖 Python 标准库，便于在最小 Agent 环境中运行。

认证模型
--------
所有业务接口都走当前选择的业务平台 base URL：

    stg  — https://mlops-stg.bytedance.net
    prod — https://mlops.bytedance.net

每个 base URL 下的 DevSRE openapi 路径是：

    <base-url>/_sre/openapi/

请求需要 ByteCloud JWT 和 DevSRE 路由 header：

    X-Jwt-Token: <token from `bytedcli auth get-bytecloud-jwt-token -j`>
    x-devsre-app-alias: mlops
    x-devsre-proxy-consul-psm: selected from the request path

JWT 会按环境缓存 30 分钟，路径为 /tmp/mlops_<env>_skill_auth.json。
测试可以通过显式注入 header JSON 跳过 bytedcli：

    MLOPS_AUTH_JSON       — JSON dict merged verbatim into request headers
    MLOPS_STG_AUTH_JSON   — stg 专用 auth JSON，保留用于兼容旧测试
    MLOPS_PROD_AUTH_JSON  — prod 专用 auth JSON
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_ENV = "stg"
BASE_URL_BY_ENV = {
    "stg": "https://mlops-stg.bytedance.net",
    "prod": "https://mlops.bytedance.net",
}
DEFAULT_BASE_URL = BASE_URL_BY_ENV[DEFAULT_ENV]
FIXED_HEADERS = {
    "x-devsre-app-alias": "mlops",
    "x-devsre-proxy-consul-psm": "data.amltob.ops_deploy",
}

_MLOPS_ENV = DEFAULT_ENV

# 通过 X-MLOps-Region header 选择平台分区。空字符串表示平台默认 cn 分区。
# main() 会从 --mlops-region 或环境专属 region 变量设置该值，_request() 读取。
_MLOPS_REGION = ""
PROXY_API_PREFIX = "/_sre/openapi/proxy/consul/api/v1"
PROXY_PSM_BY_PATH_PREFIX = (
    (PROXY_API_PREFIX + "/mlops_xcron/", "data.amltob.ops_xcron"),
    (PROXY_API_PREFIX + "/mlops_cicd_lane/", "data.amltob.ops_cicd_lane"),
    (PROXY_API_PREFIX + "/mlops_cicd/", "data.amltob.ops_cicd"),
    (PROXY_API_PREFIX + "/mlops_deploy/", "data.amltob.ops_deploy"),
    (PROXY_API_PREFIX + "/mlops_eventcenter/", "data.amltob.ops_eventcenter"),
    (PROXY_API_PREFIX + "/mlops_observability/", "data.amltob.ops_observability"),
)
CACHE_FILE_TEMPLATE = os.path.join(tempfile.gettempdir(), "mlops_%s_skill_auth.json")
CACHE_TTL_SECONDS = 30 * 60


# ---------------------------------------------------------------------------
# Endpoints — human-readable catalog used for coverage verification and docs
# ---------------------------------------------------------------------------
ENDPOINTS = {
    # 工具箱 / 基础服务
    "list-cronjob-apps":                "GET /_sre/openapi/proxy/consul/api/v1/mlops_xcron/apps",
    "get-or-create-vbh-login-message":  "POST /_sre/openapi/proxy/consul/api/v1/mlops_deploy/vbh/get_or_create_vbh_login_message",
    # Nacos configuration center
    "list-nacos-instances":            "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_instance",
    "get-nacos-instance":              "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_instance",
    "list-nacos-namespaces":           "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_namespace",
    "list-nacos-configs":              "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config",
    "get-nacos-config":                "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_config",
    "list-nacos-config-versions":      "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config_version",
    "list-nacos-config-deployments":   "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config_deployment",
    "list-nacos-batch-deployments":    "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_batch_deployment",
    "get-nacos-deployment":            "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_deployment",
    "list-nacos-reviewers":             "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/common/list_reviewers",
    "update-nacos-config":              "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/update_config",
    "create-nacos-deployment":          "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/create_deployment",
    "publish-nacos-config":             "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/publish_config",
    # Delivery / CICD
    "list-products":                   "GET /_sre/openapi/proxy/consul/api/v1/mlops_cicd/product",
    "list-modules":                    "GET /_sre/openapi/proxy/consul/api/v1/mlops_cicd/module",
    "list-deliveries":                 "GET /_sre/openapi/proxy/consul/api/v1/mlops_cicd/delivery",
    "list-infrastructure-deliveries":  "GET /_sre/openapi/proxy/consul/api/v1/mlops_cicd/infrastructure_delivery",
    "list-release-trains":             "GET /_sre/openapi/proxy/consul/api/v1/mlops_cicd/release_train",
    "list-delivery-applies":           "GET /_sre/openapi/proxy/consul/api/v1/mlops_cicd/delivery_apply",
    "list-delivery-events":            "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd/list_delivery_events",
    "list-change-templates":            "GET /_sre/openapi/proxy/consul/api/v1/mlops_cicd/change_template",
    "list-lane-products":               "GET /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_product",
    "list-lane-product-instances":      "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_product_region_instance",
    "list-lanes":                       "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_lane",
    "get-lane":                         "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_lane",
    "list-lane-modules":                "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module",
    "list-lane-module-deploys":         "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module_deploy",
    "get-lane-module-deploy":           "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_module_deploy",
    "get-lane-pod-logs":                "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_pod_logs",
    "get-lane-pod-events":              "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_pod_events",
    "list-lane-deliveries":             "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery",
    "get-lane-delivery":                "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_delivery",
    "list-lane-delivery-artifacts":     "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_artifact_by_delivery",
    "list-lane-delivery-deploys":       "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_module_deploy_by_delivery",
    "list-lane-helm-diffs":             "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_helm_diff_by_delivery",
    "create-lane-delivery":             "POST /_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/create_delivery",
    # Inference services
    "list-inference-services":         "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services",
    "get-inference-service":           "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/{id}",
    "update-inference-service-labels": "PATCH /_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/{id}/labels",
    "list-inference-service-events":   "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_events",
    "list-inference-service-pods":     "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_pods",
    "list-inference-hpa-metrics":      "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_hpa_metrics",
    "list-inference-hpa-jobs":         "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/mr_inference_service_hpa_jobs",
    "get-inference-dcp-gpu-stats":     "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/resource_stats/dcp_gpu_types",
    "call-maas-api":                   "POST /_sre/openapi/proxy/consul/api/v1/mlops_deploy/maas_api_proxy/",
    "list-inference-update-records":   "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_service_update_records",
    # Splitwise / DCP
    "list-fed-control-clusters":       "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/fed_control_clusters",
    "list-dcp-member-clusters":        "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/dcp_member_clusters",
    "list-inference-config-templates": "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_config_templates",
    "list-official-inference-configs": "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs_official",
    "create-inference-config":         "POST /_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs",
    "preview-update-inference-service":  "POST /_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/preview_update_inference_service",
    "update-inference-service":         "POST /_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_services",
    # CMDB
    "list-regions":                    "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/regions",
    "list-clusters":                   "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/clusters",
    "list-resource-queues":            "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/resource_queues",
    "list-sfcs-warmup":                "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/sfcs_warmup",
    # Foundation catalog
    "list-foundation-models":          "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_models",
    "list-foundation-gpu-types":       "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_gpu_types",
    "list-foundation-flavors":         "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_ark_flavors",
    # Ancillary deploy
    "list-inference-engine-images":    "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/inference_engine_images",
    "get-gputype-stat-series":         "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/gputype_stat_series",
    "list-scheduling-priorities":      "GET /_sre/openapi/proxy/consul/api/v1/mlops_deploy/list_scheduling_priority_options",
    # Event center
    "list-service-alerts":             "GET /_sre/openapi/proxy/consul/api/v1/mlops_eventcenter/ark_service_alerts",
    "list-events":                     "GET /_sre/openapi/proxy/consul/api/v1/mlops_eventcenter/events",
    # Observability
    "list-saved-queries":              "POST /_sre/openapi/proxy/consul/api/v1/mlops_observability/list_user_saved_queries",
    "get-tls-sts-token":               "POST /_sre/openapi/proxy/consul/api/v1/mlops_observability/get_tls_sts_token",
}


# ---------------------------------------------------------------------------
# Verify: recording -> CLI coverage classification tables
# ---------------------------------------------------------------------------
COVERED_PATTERNS = [
    # 工具箱 / 基础服务
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_xcron/apps$"), "list-cronjob-apps"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/vbh/get_or_create_vbh_login_message$"), "get-or-create-vbh-login-message"),
    # Nacos
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_instance$"),           "list-nacos-instances"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_instance$"),            "get-nacos-instance"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_namespace$"),          "list-nacos-namespaces"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config$"),             "list-nacos-configs"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_config$"),              "get-nacos-config"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config_version$"),     "list-nacos-config-versions"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config_deployment$"),  "list-nacos-config-deployments"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_batch_deployment$"),   "list-nacos-batch-deployments"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/get_deployment$"),          "get-nacos-deployment"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/common/list_reviewers$"),         "list-nacos-reviewers"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/update_config$"),           "update-nacos-config"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/create_deployment$"),       "create-nacos-deployment"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/publish_config$"),          "publish-nacos-config"),
    # Delivery / CICD
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/product$"),                        "list-products"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/module$"),                         "list-modules"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/delivery$"),                       "list-deliveries"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/infrastructure_delivery$"),        "list-infrastructure-deliveries"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/release_train$"),                  "list-release-trains"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/delivery_apply$"),                 "list-delivery-applies"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/list_delivery_events$"),           "list-delivery-events"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd/change_template$"),                "list-change-templates"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_product$"),              "list-lane-products"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_product_region_instance$"), "list-lane-product-instances"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_lane$"),                  "list-lanes"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_lane$"),                   "get-lane"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module$"),                "list-lane-modules"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module_deploy$"),         "list-lane-module-deploys"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_module_deploy$"),          "get-lane-module-deploy"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_pod_logs$"),               "get-lane-pod-logs"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_pod_events$"),             "get-lane-pod-events"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery$"),             "list-lane-deliveries"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_delivery$"),               "get-lane-delivery"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_artifact_by_delivery$"), "list-lane-delivery-artifacts"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_module_deploy_by_delivery$"), "list-lane-delivery-deploys"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_helm_diff_by_delivery$"), "list-lane-helm-diffs"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/create_delivery$"),            "create-lane-delivery"),
    # Inference services — order matters: subresources before the generic {id}
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/resource_stats/dcp_gpu_types$"), "get-inference-dcp-gpu-stats"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_events$"),      "list-inference-service-events"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_pods$"),        "list-inference-service-pods"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_service_hpa_metrics$"), "list-inference-hpa-metrics"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/mr_inference_service_hpa_jobs$"),        "list-inference-hpa-jobs"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_service_update_records$"), "list-inference-update-records"),
    ("PATCH", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/[^/]+/labels$"), "update-inference-service-labels"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/[^/]+$"),      "get-inference-service"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services$"),            "list-inference-services"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/maas_api_proxy/?$"),                     "call-maas-api"),
    # Splitwise / DCP
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/fed_control_clusters$"),                 "list-fed-control-clusters"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/dcp_member_clusters$"), "list-dcp-member-clusters"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_config_templates$"), "list-inference-config-templates"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs_official$"), "list-official-inference-configs"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs$"), "create-inference-config"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/preview_update_inference_service$"), "preview-update-inference-service"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_services$"), "update-inference-service"),
    # CMDB
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/regions$"),         "list-regions"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/clusters$"),        "list-clusters"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/resource_queues$"), "list-resource-queues"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/sfcs_warmup$"),     "list-sfcs-warmup"),
    # Foundation
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_models$"),    "list-foundation-models"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_gpu_types$"), "list-foundation-gpu-types"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_ark_flavors$"), "list-foundation-flavors"),
    # Ancillary deploy
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/inference_engine_images$"),        "list-inference-engine-images"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/gputype_stat_series$"),            "get-gputype-stat-series"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_deploy/list_scheduling_priority_options$"), "list-scheduling-priorities"),
    # Event center
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_eventcenter/ark_service_alerts$"),        "list-service-alerts"),
    ("GET",  re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_eventcenter/events$"),                    "list-events"),
    # Observability
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_observability/list_user_saved_queries$"), "list-saved-queries"),
    ("POST", re.compile(r"^/_sre/openapi/proxy/consul/api/v1/mlops_observability/get_tls_sts_token$"),       "get-tls-sts-token"),
]

# Generic / framework endpoints the recording contains but the skill deliberately
# does NOT expose in the CLI (whoami / permissions / app metadata / idc).
EXCLUDED_PATTERNS = [
    re.compile(r"^/_sre/openapi/whoami$"),
    re.compile(r"^/_sre/openapi/idc$"),
    re.compile(r"^/_sre/openapi/accessible_apps$"),
    re.compile(r"^/_sre/openapi/devsre_config$"),
    re.compile(r"^/_sre/openapi/apps/mlops$"),
    re.compile(r"^/_sre/openapi/apps/mlops/actions$"),
    re.compile(r"^/_sre/openapi/apps/mlops/permissions$"),
]


# ---------------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------------
class CliError(Exception):
    pass


def _normalize_env(value):
    raw = (value or DEFAULT_ENV).strip().lower()
    aliases = {
        "stg": "stg",
        "stage": "stg",
        "staging": "stg",
        "pre": "stg",
        "preprod": "stg",
        "pre-release": "stg",
        "pre_release": "stg",
        "prod": "prod",
        "production": "prod",
        "online": "prod",
    }
    if raw in aliases:
        return aliases[raw]
    raise CliError("unsupported MLOps env: %s (expected stg or prod)" % value)


def _first_env_value(names):
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return name, value
    return None, None


def resolve_base_url(target_env, explicit_base_url=None):
    if explicit_base_url:
        return explicit_base_url
    target_env = _normalize_env(target_env)
    if target_env == "prod":
        _, value = _first_env_value(("MLOPS_PROD_BASE_URL", "MLOPS_BASE_URL"))
    else:
        _, value = _first_env_value(("MLOPS_STG_BASE_URL", "MLOPS_BASE_URL"))
    return value or BASE_URL_BY_ENV[target_env]


def resolve_region(target_env, explicit_region=None):
    if explicit_region not in (None, ""):
        return explicit_region.strip()
    target_env = _normalize_env(target_env)
    if target_env == "prod":
        _, value = _first_env_value(("MLOPS_PROD_REGION", "MLOPS_REGION"))
    else:
        _, value = _first_env_value(("MLOPS_STG_REGION", "MLOPS_REGION"))
    return (value or "").strip()


def _auth_json_from_env():
    if _MLOPS_ENV == "prod":
        names = ("MLOPS_PROD_AUTH_JSON", "MLOPS_AUTH_JSON", "MLOPS_STG_AUTH_JSON")
    else:
        names = ("MLOPS_STG_AUTH_JSON", "MLOPS_AUTH_JSON")
    return _first_env_value(names)


def _cache_file():
    override = os.environ.get("MLOPS_AUTH_CACHE_FILE")
    if override:
        return override
    return CACHE_FILE_TEMPLATE % _MLOPS_ENV


def _json_loads(value, default=None):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise CliError("invalid JSON: %s" % exc)


def _read_cache(now=None):
    now = now or time.time()
    cache_file = _cache_file()
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if now - float(cached.get("fetched_at", 0)) >= CACHE_TTL_SECONDS:
        return None
    headers = cached.get("headers")
    return headers if isinstance(headers, dict) else None


def _write_cache(headers):
    payload = {"fetched_at": time.time(), "headers": headers}
    cache_file = _cache_file()
    tmp = cache_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, cache_file)


def _fetch_jwt_via_bytedcli():
    """Invoke bytedcli to obtain a fresh ByteCloud JWT token as a plain string."""
    try:
        proc = subprocess.run(
            ["bytedcli", "auth", "get-bytecloud-jwt-token", "-j"],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        raise CliError("bytedcli not found in PATH — install ByteDance internal CLI first")
    except subprocess.TimeoutExpired:
        raise CliError("bytedcli auth get-bytecloud-jwt-token timed out")
    if proc.returncode != 0:
        raise CliError("bytedcli failed: %s" % (proc.stderr or proc.stdout).strip())
    out = proc.stdout.strip()
    # Try JSON first (--json), fall back to plain-token stdout
    try:
        parsed = json.loads(out)
    except json.JSONDecodeError:
        return out
    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, dict):
        for key in ("token", "jwt", "jwt_token", "JwtToken", "data"):
            v = parsed.get(key)
            if isinstance(v, str) and v:
                return v
            if isinstance(v, dict):
                for k2 in ("token", "jwt", "jwt_token"):
                    if isinstance(v.get(k2), str) and v[k2]:
                        return v[k2]
    raise CliError("could not extract JWT from bytedcli output: %s" % out[:200])


def get_auth_headers(force_refresh=False):
    """返回基础认证 header（X-Jwt-Token + 默认 DevSRE 路由 header）。

    优先级：
      1. MLOPS_<ENV>_AUTH_JSON / MLOPS_AUTH_JSON 环境变量
      2. /tmp/mlops_<env>_skill_auth.json 中的缓存 JWT（30 分钟 TTL）
      3. 通过 `bytedcli auth get-bytecloud-jwt-token` 重新获取
    """
    env_auth_name, env_auth = _auth_json_from_env()
    if env_auth:
        data = _json_loads(env_auth, {})
        if not isinstance(data, dict):
            raise CliError("%s must decode to a JSON object" % env_auth_name)
        return {**FIXED_HEADERS, **{str(k): str(v) for k, v in data.items()}}
    if not force_refresh:
        cached = _read_cache()
        if cached:
            return cached
    token = _fetch_jwt_via_bytedcli()
    headers = {"X-Jwt-Token": token, **FIXED_HEADERS}
    _write_cache(headers)
    return headers


def proxy_psm_for_path(path):
    """Return the DevSRE proxy PSM required for a business API path."""
    normalized = path.split("?", 1)[0]
    for prefix, psm in PROXY_PSM_BY_PATH_PREFIX:
        if normalized.startswith(prefix):
            return psm
    return FIXED_HEADERS["x-devsre-proxy-consul-psm"]


def _decode_response(raw, status, url, error=False):
    try:
        data = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        data = raw
    result = {"ok": 200 <= int(status) < 300, "status": int(status), "url": url, "data": data}
    if error:
        result["error"] = data
    return result


def _request(method, base_url, path, params=None, body=None, headers=None, force_auth_refresh=False):
    base_url = base_url.rstrip("/")
    url = base_url + path
    if params:
        items = []
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, list):
                for item in value:
                    if item is not None:
                        items.append((key, item))
            else:
                items.append((key, value))
        query = urllib.parse.urlencode(items, doseq=True)
        if query:
            url += ("&" if "?" in url else "?") + query
    req_headers = {"Accept": "application/json", "Content-Type": "application/json"}
    req_headers.update(get_auth_headers(force_auth_refresh))
    req_headers["x-devsre-proxy-consul-psm"] = proxy_psm_for_path(path)
    if _MLOPS_REGION:
        req_headers["X-MLOps-Region"] = _MLOPS_REGION
    if headers:
        req_headers.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return _decode_response(raw, resp.status, url)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return _decode_response(raw, exc.code, url, error=True)
    except urllib.error.URLError as exc:
        raise CliError("request failed: %s" % exc)


def _resolve_body(args, default_body):
    if getattr(args, "payload_json", None):
        return _json_loads(args.payload_json, {})
    if getattr(args, "payload_file", None):
        with open(args.payload_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return default_body


def _string_bool(flag):
    return "true" if flag else "false"


def _stg_write_hosts():
    hosts = {
        urllib.parse.urlparse(BASE_URL_BY_ENV["stg"]).hostname,
        "127.0.0.1",
        "localhost",
        "::1",
    }
    extra = os.environ.get("MLOPS_STG_WRITE_HOSTS", "")
    hosts.update(item.strip().lower() for item in extra.split(",") if item.strip())
    return hosts


def _require_stg_write(command_name, base_url):
    if _MLOPS_ENV != "stg":
        raise CliError(
            "%s is a write API and is only supported in stg; "
            "prod/online does not support write APIs" % command_name
        )
    host = (urllib.parse.urlparse(base_url or "").hostname or "").lower()
    prod_host = urllib.parse.urlparse(BASE_URL_BY_ENV["prod"]).hostname
    if host == prod_host:
        raise CliError("%s refuses the prod/online host %s" % (command_name, host))
    if host not in _stg_write_hosts():
        raise CliError(
            "%s refuses write host %s; allowed STG hosts: %s"
            % (command_name, host or "<empty>", ", ".join(sorted(_stg_write_hosts())))
        )


def _wrap_write_result(command_name, result):
    notice = ("%s invokes a real STG write API. Prod/online write APIs are intentionally unsupported." %
              command_name)
    if isinstance(result, dict):
        result["write_notice"] = notice
    return result


def _is_read_only_action(action):
    action = action or ""
    return bool(re.match(r"^(Get|List|Describe|Query|Search|Check|Validate|Preview)", action))


def _require_payload_source(args, command_name):
    if not getattr(args, "payload_json", None) and not getattr(args, "payload_file", None):
        raise CliError("%s requires --payload-json or --payload-file" % command_name)


def _is_sensitive_name(value):
    normalized = str(value or "").lower().replace("-", "_")
    words = (
        "password", "passwd", "secret", "token", "cookie",
        "authorization", "credential", "api_key", "access_key",
        "private_key", "redis_pass",
    )
    return (
        any(word in normalized for word in words)
        or normalized.endswith(("_ak", "_sk"))
    )


def _redact_sensitive(value):
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    if not isinstance(value, dict):
        return value
    sensitive_env = _is_sensitive_name(value.get("Name"))
    result = {}
    for key, item in value.items():
        if _is_sensitive_name(key) or (key == "Value" and sensitive_env):
            result[key] = "***REDACTED***"
        else:
            result[key] = _redact_sensitive(item)
    return result


# ---------------------------------------------------------------------------
# 工具箱 / 基础服务
# ---------------------------------------------------------------------------
XCRON_BASE = "/_sre/openapi/proxy/consul/api/v1/mlops_xcron"


def cmd_list_cronjob_apps(args):
    return _request(
        "GET",
        args.base_url,
        XCRON_BASE + "/apps",
        params=_pagination_params(args),
        force_auth_refresh=args.refresh_auth,
    )


def cmd_get_or_create_vbh_login_message(args):
    command = "get-or-create-vbh-login-message"
    _require_stg_write(command, args.base_url)
    if args.payload_json or args.payload_file:
        body = _resolve_body(args, {})
        if not isinstance(body, dict):
            raise CliError("%s payload must be a JSON object" % command)
    else:
        if not args.vke_cluster_region or not args.vke_cluster_name:
            raise CliError(
                "%s requires --vke-cluster-region and --vke-cluster-name "
                "when no raw payload is provided" % command
            )
        body = {
            "VkeClusterRegion": args.vke_cluster_region,
            "RequestType": args.request_type,
            "ProductName": args.product_name,
            "VkeClusterName": args.vke_cluster_name,
        }
    return _wrap_write_result(
        command,
        _request(
            "POST",
            args.base_url,
            DEPLOY_BASE + "/vbh/get_or_create_vbh_login_message",
            body=body,
            force_auth_refresh=args.refresh_auth,
        ),
    )


# ---------------------------------------------------------------------------
# Nacos configuration center
# ---------------------------------------------------------------------------
NACOS_BASE = "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos"


def cmd_list_nacos_instances(args):
    body = {
        "PageNum": args.page_num,
        "PageSize": args.page_size,
        "ProductCode": args.product_code,
        "IsSync": bool(args.is_sync),
    }
    if args.region:
        body["Region"] = args.region
    body = _resolve_body(args, body)
    return _request("POST", args.base_url, NACOS_BASE + "/list_instance", body=body, force_auth_refresh=args.refresh_auth)


def cmd_get_nacos_instance(args):
    body = _resolve_body(args, {"InstanceID": args.instance_id})
    return _request("POST", args.base_url, NACOS_BASE + "/get_instance", body=body, force_auth_refresh=args.refresh_auth)


def cmd_list_nacos_namespaces(args):
    body = _resolve_body(args, {
        "PageNum": args.page_num,
        "PageSize": args.page_size,
        "InstanceID": args.instance_id,
    })
    return _request("POST", args.base_url, NACOS_BASE + "/list_namespace", body=body, force_auth_refresh=args.refresh_auth)


def cmd_list_nacos_configs(args):
    filt = {"InstanceID": args.instance_id}
    if args.namespace_id is not None:
        filt["NamespaceID"] = args.namespace_id
    if args.namespace_name:
        filt["NamespaceName"] = args.namespace_name
    if args.group:
        filt["Group"] = args.group
    if args.data_id:
        filt["DataID"] = args.data_id
    if args.fuzzy_data_id:
        filt["FuzzyDataID"] = args.fuzzy_data_id
    body = _resolve_body(args, {
        "PageNum": args.page_num,
        "PageSize": args.page_size,
        "Filter": filt,
    })
    return _request("POST", args.base_url, NACOS_BASE + "/list_config", body=body, force_auth_refresh=args.refresh_auth)


def cmd_get_nacos_config(args):
    body = _resolve_body(args, {"ID": args.id})
    return _request("POST", args.base_url, NACOS_BASE + "/get_config", body=body, force_auth_refresh=args.refresh_auth)


def cmd_list_nacos_config_versions(args):
    filt = {
        "InstanceID": args.instance_id,
        "DataID": args.data_id,
        "Group": args.group,
        "NamespaceName": args.namespace_name,
    }
    if args.namespace_id is not None:
        filt["NamespaceID"] = args.namespace_id
    body = _resolve_body(args, {
        "Filter": filt,
        "PageNum": args.page_num,
        "PageSize": args.page_size,
    })
    return _request("POST", args.base_url, NACOS_BASE + "/list_config_version", body=body, force_auth_refresh=args.refresh_auth)


def cmd_list_nacos_config_deployments(args):
    filt = {}
    if args.instance_id:
        filt["InstanceID"] = args.instance_id
    if args.created_by:
        filt["CreatedBy"] = args.created_by
    if args.status:
        filt["Status"] = list(args.status)
    if args.data_id:
        filt["DataID"] = args.data_id
    if args.namespace_name:
        filt["NamespaceName"] = args.namespace_name
    body = {
        "PageNum": args.page_num,
        "PageSize": args.page_size,
        "Filter": filt,
    }
    if args.without_instance_id:
        body["WithoutInstanceID"] = True
    body = _resolve_body(args, body)
    return _request("POST", args.base_url, NACOS_BASE + "/list_config_deployment", body=body, force_auth_refresh=args.refresh_auth)


def cmd_list_nacos_batch_deployments(args):
    body = _resolve_body(args, {
        "Pagination": {"PageNum": args.page_num, "PageSize": args.page_size},
        "ProductCode": args.product_code,
        "Region": args.region,
        "Filter": {"InstanceID": args.instance_id} if args.instance_id else {},
    })
    return _request("POST", args.base_url, NACOS_BASE + "/list_batch_deployment", body=body, force_auth_refresh=args.refresh_auth)


def cmd_get_nacos_deployment(args):
    body = _resolve_body(args, {"ID": args.id})
    return _request("POST", args.base_url, NACOS_BASE + "/get_deployment", body=body, force_auth_refresh=args.refresh_auth)


def cmd_list_nacos_reviewers(args):
    body = _resolve_body(args, {
        "NacosConfigID": args.nacos_config_id,
        "type": args.review_type,
    })
    return _request(
        "POST",
        args.base_url,
        CICD_BASE + "/common/list_reviewers",
        body=body,
        force_auth_refresh=args.refresh_auth,
    )


def cmd_update_nacos_config(args):
    _require_stg_write("update-nacos-config", args.base_url)
    if args.payload_json or args.payload_file:
        body = _resolve_body(args, {})
    else:
        if args.nacos_config_id is None or not args.content_file:
            raise CliError(
                "update-nacos-config requires --payload-json/--payload-file "
                "or both --nacos-config-id and --content-file"
            )
        with open(args.content_file, "r", encoding="utf-8") as f:
            content = f.read()
        body = {
            "NacosConfigID": args.nacos_config_id,
            "Description": args.description or "",
            "Tags": list(args.tag or []),
            "NacosConfigVersion": {
                "Content": content,
                "Type": args.config_type,
            },
        }
    return _wrap_write_result(
        "update-nacos-config",
        _request(
            "POST",
            args.base_url,
            NACOS_BASE + "/update_config",
            body=body,
            force_auth_refresh=args.refresh_auth,
        ),
    )


def cmd_create_nacos_deployment(args):
    _require_stg_write("create-nacos-deployment", args.base_url)
    if args.payload_json or args.payload_file:
        body = _resolve_body(args, {})
    else:
        if args.nacos_config_id is None or not args.reviewer:
            raise CliError(
                "create-nacos-deployment requires --payload-json/--payload-file "
                "or --nacos-config-id with at least one --reviewer"
            )
        body = {
            "NacosConfigID": args.nacos_config_id,
            "Reviewer": list(args.reviewer),
            "Comment": args.comment or "",
            "IsUrgent": bool(args.is_urgent),
        }
    return _wrap_write_result(
        "create-nacos-deployment",
        _request(
            "POST",
            args.base_url,
            NACOS_BASE + "/create_deployment",
            body=body,
            force_auth_refresh=args.refresh_auth,
        ),
    )


def cmd_publish_nacos_config(args):
    _require_stg_write("publish-nacos-config", args.base_url)
    if args.payload_json or args.payload_file:
        body = _resolve_body(args, {})
    else:
        if args.deployment_id is None or not args.status:
            raise CliError(
                "publish-nacos-config requires --payload-json/--payload-file "
                "or both --deployment-id and --status"
            )
        body = {
            "NacosDeploymentID": args.deployment_id,
            "Status": args.status,
        }
    return _wrap_write_result(
        "publish-nacos-config",
        _request(
            "POST",
            args.base_url,
            NACOS_BASE + "/publish_config",
            body=body,
            force_auth_refresh=args.refresh_auth,
        ),
    )


# ---------------------------------------------------------------------------
# Delivery / CICD (products, modules, deliveries, release trains, events)
# ---------------------------------------------------------------------------
CICD_BASE = "/_sre/openapi/proxy/consul/api/v1/mlops_cicd"
CICD_LANE_BASE = "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane"


def _pagination_params(args):
    return {"page_num": args.page_num, "page_size": args.page_size}


def cmd_list_products(args):
    return _request("GET", args.base_url, CICD_BASE + "/product", params=_pagination_params(args), force_auth_refresh=args.refresh_auth)


def cmd_list_modules(args):
    params = _pagination_params(args)
    if args.product_id is not None:
        params["product_id"] = args.product_id
    return _request("GET", args.base_url, CICD_BASE + "/module", params=params, force_auth_refresh=args.refresh_auth)


def cmd_list_deliveries(args):
    params = _pagination_params(args)
    if args.status:
        params["status[]"] = list(args.status)
    if args.created_by:
        params["created_by"] = args.created_by
    if args.lc:
        params["_lc"] = args.lc
    return _request("GET", args.base_url, CICD_BASE + "/delivery", params=params, force_auth_refresh=args.refresh_auth)


def cmd_list_infrastructure_deliveries(args):
    params = _pagination_params(args)
    if args.status:
        params["status[]"] = list(args.status)
    if args.created_by:
        params["created_by"] = args.created_by
    return _request("GET", args.base_url, CICD_BASE + "/infrastructure_delivery", params=params, force_auth_refresh=args.refresh_auth)


def cmd_list_release_trains(args):
    params = {"page_size": args.page_size}
    if args.status:
        params["status[]"] = list(args.status)
    if args.lc:
        params["_lc"] = args.lc
    return _request("GET", args.base_url, CICD_BASE + "/release_train", params=params, force_auth_refresh=args.refresh_auth)


def cmd_list_delivery_applies(args):
    params = {"page_size": args.page_size}
    if args.lc:
        params["_lc"] = args.lc
    return _request("GET", args.base_url, CICD_BASE + "/delivery_apply", params=params, force_auth_refresh=args.refresh_auth)


def cmd_list_delivery_events(args):
    body = _resolve_body(args, {
        "PageNum": args.page_num,
        "PageSize": args.page_size,
        "Filter": {
            "StartTime": args.start_time,
            "EndTime": args.end_time,
            "Status": args.status or "",
            "Product": args.product or "",
            "Operator": args.operator or "",
            "Resource": args.resource or "",
            "EventID": args.event_id or "",
            "DeliveryID": args.delivery_id or "",
            "FuzzyKeyword": args.fuzzy_keyword or "",
            "_lc": args.lc or "",
        },
    })
    return _request("POST", args.base_url, CICD_BASE + "/list_delivery_events", body=body, force_auth_refresh=args.refresh_auth)


def cmd_list_change_templates(args):
    params = {"page_size": args.page_size}
    if args.lc:
        params["_lc"] = args.lc
    return _request(
        "GET",
        args.base_url,
        CICD_BASE + "/change_template",
        params=params,
        force_auth_refresh=args.refresh_auth,
    )


def _lane_post(args, endpoint, body):
    return _request(
        "POST",
        args.base_url,
        CICD_LANE_BASE + "/" + endpoint,
        body=body,
        force_auth_refresh=args.refresh_auth,
    )


def cmd_list_lane_products(args):
    return _request(
        "GET",
        args.base_url,
        CICD_LANE_BASE + "/list_product",
        force_auth_refresh=args.refresh_auth,
    )


def cmd_list_lane_product_instances(args):
    body = _resolve_body(args, {"ProductCode": args.product_code})
    return _lane_post(args, "list_product_region_instance", body)


def cmd_list_lanes(args):
    filters = {
        "ProductID": args.product_id,
        "ProductInstanceID": args.product_instance_id,
        "Statuses": list(args.status or []),
        "Name": args.name,
        "CreatedBy": args.created_by,
    }
    filters = {key: value for key, value in filters.items() if value not in (None, "", [])}
    body = _resolve_body(args, {
        "PageNum": args.page_num,
        "PageSize": args.page_size,
        "Filter": filters,
    })
    return _lane_post(args, "list_lane", body)


def cmd_get_lane(args):
    return _lane_post(args, "get_lane", {"ID": args.lane_id})


def cmd_list_lane_modules(args):
    body = _resolve_body(args, {"ProductID": args.product_id})
    return _lane_post(args, "list_module", body)


def cmd_list_lane_module_deploys(args):
    filters = {
        "LaneID": args.lane_id,
        "ModuleID": args.module_id,
        "Statuses": list(args.status or []),
    }
    filters = {key: value for key, value in filters.items() if value not in (None, "", [])}
    body = _resolve_body(args, {
        "PageNum": args.page_num,
        "PageSize": args.page_size,
        "Filter": filters,
    })
    return _lane_post(args, "list_module_deploy", body)


def cmd_get_lane_module_deploy(args):
    return _lane_post(args, "get_module_deploy", {"ModuleDeployID": args.module_deploy_id})


def _lane_pod_target(args):
    """Resolve LaneID / ClusterID / Namespace for a pod command.

    ClusterID and Namespace live on the ModuleDeploy, so --module-deploy-id
    alone is enough; explicit flags win when both are supplied.
    """
    lane_id = args.lane_id
    cluster_id = args.cluster_id
    namespace = args.namespace
    resources = None

    if args.module_deploy_id and not (lane_id and cluster_id and namespace):
        detail = _lane_post(args, "get_module_deploy",
                            {"ModuleDeployID": args.module_deploy_id})
        if not detail.get("ok"):
            return None, detail
        data = detail.get("data") or {}
        deploy = data.get("ModuleDeploy") or {}
        resources = data.get("Resources") or []
        lane_id = lane_id or deploy.get("LaneID")
        cluster_id = cluster_id or deploy.get("ClusterID")
        namespace = namespace or deploy.get("Namespace")

    missing = [name for name, value in (
        ("--lane-id", lane_id),
        ("--cluster-id", cluster_id),
        ("--namespace", namespace),
    ) if not value]
    if missing:
        raise CliError(
            "%s requires %s (or pass --module-deploy-id to resolve them)"
            % (args.command, ", ".join(missing))
        )
    return {
        "LaneID": lane_id,
        "ClusterID": cluster_id,
        "Namespace": namespace,
        "PodName": args.pod_name,
        "_Resources": resources,
    }, None


def cmd_get_lane_pod_events(args):
    if args.payload_json or args.payload_file:
        return _lane_post(args, "get_pod_events", _resolve_body(args, {}))
    target, failure = _lane_pod_target(args)
    if failure is not None:
        return failure
    target.pop("_Resources", None)
    target["Limit"] = args.limit
    return _lane_post(args, "get_pod_events", target)


def cmd_get_lane_pod_logs(args):
    if args.payload_json or args.payload_file:
        return _lane_post(args, "get_pod_logs", _resolve_body(args, {}))
    target, failure = _lane_pod_target(args)
    if failure is not None:
        return failure
    resources = target.pop("_Resources", None)
    target["Limit"] = args.limit

    container = args.container_name
    if not container:
        # The backend defaults to a container literally named "main", which
        # ark workloads do not have -> 500 "container main is not valid".
        # Ask for the pod's own container list instead of guessing.
        container = _lane_pod_default_container(args, target, resources)
    if container:
        target["ContainerName"] = container
    return _lane_post(args, "get_pod_logs", target)


def _lane_pod_default_container(args, target, resources):
    """Pick the business container for a lane pod.

    The backend defaults to a container literally named "main", which ark
    workloads do not have, so GetPodLog 500s unless ContainerName is set.
    Container names are not derivable from the HelmRelease name (observed:
    release "maas-console" runs "maas-console-charts" in its Deployment and
    "maas-console-charts-worker" in its StatefulSet), so read the pod spec
    out of ModuleDeploy.Resources[].Pods[].LiveObject instead of guessing.
    Sidecars are skipped; None means "let the caller surface the error".
    """
    if resources is None:
        if not args.module_deploy_id:
            return None
        detail = _lane_post(args, "get_module_deploy",
                            {"ModuleDeployID": args.module_deploy_id})
        if not detail.get("ok"):
            return None
        resources = (detail.get("data") or {}).get("Resources") or []

    live = None
    for resource in resources:
        for pod in resource.get("Pods") or []:
            if pod.get("Name") == target.get("PodName"):
                live = pod.get("LiveObject")
                break
        if live:
            break
    if not live:
        return None

    names = [name for name in _yaml_pod_container_names(live)
             if name not in LANE_POD_SIDECARS]
    return names[0] if names else None


LANE_POD_SIDECARS = frozenset({"traffic-proxy"})


def _yaml_pod_container_names(live_object):
    """Extract spec.containers[].name from a pod's LiveObject YAML.

    Hand-rolled because the CLI is stdlib-only (no PyYAML). Indentation-aware
    on purpose: a naive `- name:` scan also matches every env var entry.
    """
    lines = live_object.split("\n")
    spec_at = next((i for i, line in enumerate(lines)
                    if line.rstrip() == "spec:"), None)
    if spec_at is None:
        return []

    list_at = None
    list_indent = None
    for i in range(spec_at + 1, len(lines)):
        line = lines[i]
        if line.strip() and not line.startswith(" "):
            break  # left the spec block
        match = re.match(r"^(\s+)containers:\s*$", line)
        if match:
            list_at, list_indent = i, len(match.group(1))
            break
    if list_at is None:
        return []

    names = []
    item_indent = None
    for line in lines[list_at + 1:]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= list_indent and not line.lstrip().startswith("- "):
            break  # next sibling key ends the list
        bullet = re.match(r"^(\s*)-\s", line)
        if bullet and len(bullet.group(1)) == list_indent:
            item_indent = list_indent + 2
            inline = re.match(r"^\s*-\s+name:\s*(\S+)\s*$", line)
            if inline:
                names.append(inline.group(1))
            continue
        if item_indent is not None and indent == item_indent:
            keyed = re.match(r"^\s*name:\s*(\S+)\s*$", line)
            if keyed:
                names.append(keyed.group(1))
    return names


def cmd_list_lane_deliveries(args):
    filters = {
        "LaneID": args.lane_id,
        "Statuses": list(args.status or []),
        "CreatedBy": args.created_by,
    }
    filters = {key: value for key, value in filters.items() if value not in (None, "", [])}
    body = _resolve_body(args, {
        "PageNum": args.page_num,
        "PageSize": args.page_size,
        "Filter": filters,
    })
    return _lane_post(args, "list_delivery", body)


def cmd_get_lane_delivery(args):
    return _lane_post(args, "get_delivery", {"DeliveryID": args.delivery_id})


def cmd_list_lane_delivery_artifacts(args):
    return _lane_post(
        args,
        "list_delivery_artifact_by_delivery",
        {"DeliveryID": args.delivery_id},
    )


def cmd_list_lane_delivery_deploys(args):
    filters = {"Statuses": list(args.status or []), "ModuleID": args.module_id}
    filters = {key: value for key, value in filters.items() if value not in (None, "", [])}
    default = {"DeliveryID": args.delivery_id}
    if filters:
        default["Filter"] = filters
    return _lane_post(
        args,
        "list_delivery_module_deploy_by_delivery",
        _resolve_body(args, default),
    )


def cmd_list_lane_helm_diffs(args):
    return _lane_post(
        args,
        "list_helm_diff_by_delivery",
        {"DeliveryID": args.delivery_id},
    )


def _lane_delivery_modules(args):
    modules = []
    for raw in args.module_json or []:
        module = _json_loads(raw, None)
        if not isinstance(module, dict):
            raise CliError("--module-json must decode to a JSON object")
        modules.append(module)
    if not modules:
        raise CliError("create-lane-delivery requires at least one --module-json")
    return modules


def _create_lane_delivery_body(args):
    if args.payload_json or args.payload_file:
        body = _resolve_body(args, {})
        if not isinstance(body, dict):
            raise CliError("create-lane-delivery payload must be a JSON object")
        return body
    required = {
        "--product-id": args.product_id,
        "--lane-id": args.lane_id,
        "--product-instance-id": args.product_instance_id,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise CliError(
            "create-lane-delivery requires %s when no raw payload is provided"
            % ", ".join(missing)
        )
    return {
        "ProductID": args.product_id,
        "LaneID": args.lane_id,
        "ProductInstanceID": args.product_instance_id,
        "DeployMode": args.deploy_mode,
        "StageAutoNext": not args.manual_stage,
        "Description": args.description,
        "ModulesToDelivery": _lane_delivery_modules(args),
    }


def cmd_create_lane_delivery(args):
    command = "create-lane-delivery"
    _require_stg_write(command, args.base_url)
    body = _create_lane_delivery_body(args)
    return _wrap_write_result(
        command,
        _lane_post(args, "create_delivery", body),
    )


def cmd_create_multi_lane_deliveries(args):
    command = "create-multi-lane-deliveries"
    _require_stg_write(command, args.base_url)
    lane_ids = list(dict.fromkeys(args.lane_id or []))
    if not lane_ids:
        raise CliError("%s requires at least one --lane-id" % command)
    if len(lane_ids) > 10:
        raise CliError(
            "%s accepts at most 10 lanes per run; review the first batch before continuing"
            % command
        )
    modules = _lane_delivery_modules(args)

    lanes = []
    for lane_id in lane_ids:
        detail = _lane_post(args, "get_lane", {"ID": lane_id})
        if not detail.get("ok"):
            return _wrap_write_result(command, detail)
        lane = (detail.get("data") or {}).get("Lane")
        if not isinstance(lane, dict):
            raise CliError("get_lane returned no Lane object for lane %s" % lane_id)
        missing_fields = [
            field for field in ("ID", "ProductID", "ProductInstanceID")
            if lane.get(field) is None
        ]
        if missing_fields:
            raise CliError(
                "get_lane returned incomplete metadata for lane %s: missing %s"
                % (lane_id, ", ".join(missing_fields))
            )
        lanes.append(lane)

    results = []
    for lane in lanes:
        body = {
            "ProductID": lane.get("ProductID"),
            "LaneID": lane.get("ID"),
            "ProductInstanceID": lane.get("ProductInstanceID"),
            "DeployMode": args.deploy_mode,
            "StageAutoNext": not args.manual_stage,
            "Description": args.description,
            "ModulesToDelivery": modules,
        }
        result = _lane_post(args, "create_delivery", body)
        results.append({
            "LaneID": lane.get("ID"),
            "LaneName": lane.get("Name"),
            "Result": result,
        })
        if not result.get("ok"):
            break
    ok = len(results) == len(lanes) and all(item["Result"].get("ok") for item in results)
    status = results[-1]["Result"].get("status", 500) if results else 500
    return _wrap_write_result(command, {
        "ok": ok,
        "status": status,
        "url": args.base_url + CICD_LANE_BASE + "/create_delivery",
        "data": {"Results": results, "RequestedLaneCount": len(lane_ids)},
    })


# ---------------------------------------------------------------------------
# Inference services
# ---------------------------------------------------------------------------
DEPLOY_BASE = "/_sre/openapi/proxy/consul/api/v1/mlops_deploy"


def cmd_list_inference_services(args):
    params = _pagination_params(args)
    optional = {
        "fuzzy_service_name": args.fuzzy_service_name,
        "fuzzy_image_url": args.fuzzy_image_url,
        "model_name": args.model_name,
        "model_version": args.model_version,
        "hybrid": args.hybrid,
        "multi_cluster": args.multi_cluster,
        "is_gray_release": args.is_gray_release,
        "usage": args.usage,
        "resource_queue": args.resource_queue,
        "dcp_resource_queue": args.dcp_resource_queue,
        "cluster_id": args.cluster_id,
        "fuzzy_create_user": args.fuzzy_create_user,
        "engine_arch": args.engine_arch,
        "modality": args.modality,
        "model_type": args.model_type,
        "_lc": args.lc,
    }
    for k, v in optional.items():
        if v is not None and v != "":
            params[k] = v
    if args.statuses:
        params["statuses[]"] = list(args.statuses)
    if args.service_ids:
        params["service_ids[]"] = list(args.service_ids)
    return _request("GET", args.base_url, DEPLOY_BASE + "/model_inferences_services", params=params, force_auth_refresh=args.refresh_auth)


def cmd_get_inference_service(args):
    path = "%s/model_inferences_services/%s" % (DEPLOY_BASE, urllib.parse.quote(args.service_id, safe=""))
    return _request("GET", args.base_url, path, force_auth_refresh=args.refresh_auth)


def cmd_update_inference_service_labels(args):
    command = "update-inference-service-labels"
    _require_stg_write(command, args.base_url)
    has_payload = bool(args.payload_json or args.payload_file)
    has_edits = bool(args.set_label or args.remove_label or args.foundation_model_label)
    if has_payload and has_edits:
        raise CliError(
            "%s accepts either --payload-json/--payload-file or incremental label options, not both"
            % command
        )
    if not has_payload and not has_edits:
        raise CliError(
            "%s requires --payload-json/--payload-file or at least one of "
            "--set-label/--remove-label/--foundation-model-label" % command
        )

    service_id = urllib.parse.quote(args.service_id, safe="")
    path = "%s/model_inferences_services/%s/labels" % (DEPLOY_BASE, service_id)
    if has_payload:
        body = _resolve_body(args, {})
        if not isinstance(body, dict) or not isinstance(body.get("Values"), dict):
            raise CliError("%s payload requires object field Values" % command)
    else:
        detail = _request(
            "GET",
            args.base_url,
            "%s/model_inferences_services/%s" % (DEPLOY_BASE, service_id),
            force_auth_refresh=args.refresh_auth,
        )
        if not detail.get("ok"):
            return detail
        service = (detail.get("data") or {}).get("InferenceService") or {}
        labels = service.get("Labels") or {}
        values = labels.get("Values") if isinstance(labels, dict) else None
        # 兼容部分旧响应直接把标签字典放在 Labels 下的结构。
        if not isinstance(values, dict):
            values = labels if isinstance(labels, dict) else {}
        values = dict(values)
        for spec in args.set_label or []:
            key, value = _parse_kv_pair(spec, "--set-label")
            values[key] = value
        for spec in args.foundation_model_label or []:
            model_name, model_version = _parse_kv_pair(spec, "--foundation-model-label")
            key = "support.foundation-model.ark/%s_%s" % (model_name, model_version)
            values[key] = "true"
        for key in args.remove_label or []:
            values.pop(key, None)
        body = {"Values": values, "BatchToOnline": bool(args.batch_to_online)}

    return _wrap_write_result(
        command,
        _request(
            "PATCH",
            args.base_url,
            path,
            body=body,
            force_auth_refresh=args.refresh_auth,
        ),
    )


def cmd_list_inference_service_events(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/model_inferences_service_events",
                    params={"service_id": args.service_id}, force_auth_refresh=args.refresh_auth)


def cmd_list_inference_service_pods(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/model_inferences_service_pods",
                    params={"service_id": args.service_id}, force_auth_refresh=args.refresh_auth)


def cmd_list_inference_hpa_metrics(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/model_inferences_service_hpa_metrics",
                    force_auth_refresh=args.refresh_auth)


def cmd_list_inference_hpa_jobs(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/mr_inference_service_hpa_jobs",
                    force_auth_refresh=args.refresh_auth)


def cmd_get_inference_dcp_gpu_stats(args):
    params = {}
    if args.gpu_types:
        params["gpu_types[]"] = list(args.gpu_types)
    if args.service_id:
        params["service_id"] = args.service_id
    return _request("GET", args.base_url,
                    DEPLOY_BASE + "/model_inferences_services/resource_stats/dcp_gpu_types",
                    params=params, force_auth_refresh=args.refresh_auth)


def cmd_call_maas_api(args):
    body = _resolve_body(args, _json_loads(args.payload_json, {}) if args.payload_json else {})
    params = {"Action": args.action, "Version": args.version or "2024-01-01"}
    potentially_writes = not _is_read_only_action(args.action)
    if potentially_writes:
        _require_stg_write("call-maas-api Action=%s" % args.action, args.base_url)
    result = _request("POST", args.base_url, DEPLOY_BASE + "/maas_api_proxy/", params=params, body=body,
                      force_auth_refresh=args.refresh_auth)
    if potentially_writes:
        return _wrap_write_result("call-maas-api Action=%s" % args.action, result)
    return result


def cmd_list_inference_update_records(args):
    return _request("GET", args.base_url,
                    DEPLOY_BASE + "/splitwise_models/inference_service_update_records",
                    params={"service_id": args.service_id},
                    force_auth_refresh=args.refresh_auth)


# ---------------------------------------------------------------------------
# Splitwise / DCP
# ---------------------------------------------------------------------------
def cmd_list_fed_control_clusters(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/fed_control_clusters", force_auth_refresh=args.refresh_auth)


def cmd_list_dcp_member_clusters(args):
    params = {}
    if args.dcp_control_cluster_id:
        params["DcpControlClusterId"] = args.dcp_control_cluster_id
    return _request("GET", args.base_url, DEPLOY_BASE + "/splitwise_models/dcp_member_clusters",
                    params=params, force_auth_refresh=args.refresh_auth)


def cmd_list_inference_config_templates(args):
    return _request("GET", args.base_url,
                    DEPLOY_BASE + "/splitwise_models/inference_config_templates",
                    params=_pagination_params(args), force_auth_refresh=args.refresh_auth)


def cmd_list_official_inference_configs(args):
    params = _pagination_params(args)
    for k, v in {
        "model_name": args.model_name,
        "model_version": args.model_version,
        "fuzzy_template_name": args.fuzzy_template_name,
        "modelName": args.context_model_name,
        "modelVersion": args.context_model_version,
        "serviceId": args.service_id,
        "serviceType": args.service_type,
        "_lc": args.lc,
    }.items():
        if v:
            params[k] = v
    if args.edit:
        params["edit"] = "true"
    return _request("GET", args.base_url,
                    DEPLOY_BASE + "/splitwise_models/inference_configs_official",
                    params=params, force_auth_refresh=args.refresh_auth)


def cmd_create_inference_config(args):
    _require_stg_write("create-inference-config", args.base_url)
    _require_payload_source(args, "create-inference-config")
    body = _resolve_body(args, {})
    return _wrap_write_result(
        "create-inference-config",
        _request("POST", args.base_url,
                 DEPLOY_BASE + "/splitwise_models/inference_configs",
                 body=body, force_auth_refresh=args.refresh_auth),
    )


def cmd_preview_update_inference_service(args):
    _require_stg_write("preview-update-inference-service", args.base_url)
    _require_payload_source(args, "preview-update-inference-service")
    body = _resolve_body(args, {})
    return _wrap_write_result(
        "preview-update-inference-service",
        _request("POST", args.base_url,
                 DEPLOY_BASE + "/splitwise_models/preview_update_inference_service",
                 body=body, force_auth_refresh=args.refresh_auth),
    )


def cmd_update_inference_service(args):
    _require_stg_write("update-inference-service", args.base_url)
    _require_payload_source(args, "update-inference-service")
    body = _resolve_body(args, {})
    return _wrap_write_result(
        "update-inference-service",
        _request("POST", args.base_url,
                 DEPLOY_BASE + "/splitwise_models/inference_services",
                 body=body, force_auth_refresh=args.refresh_auth),
    )


# ---------------------------------------------------------------------------
# Shortcut: switch-inference-template-env
#
# Encapsulates the 6-step env-edit flow surfaced in the mock-vlm session:
#   1. get-inference-service     → InferenceConfigV2ID, FoundationModel*, Region
#   2. GetInferenceServiceResourceConfig → WorkerSetResourceInfos/Annotations/AppLabels
#   3. ListWholeInferenceConfigsV2       → full Application (Envs/Image/EntryPoint)
#   4. mutate Application in memory
#   5. create-inference-config           → new fmvicv2-<version>
#   6. preview + (optional) update-inference-service
# ---------------------------------------------------------------------------
def _dict_to_kv_list(obj, path=""):
    """Convert MLOps-returned dict fields (Labels/Taints/Annotations/etc.) to
    [{Key,Value}] list expected by preview/update-inference-service.
    """
    if isinstance(obj, dict):
        return [{"Key": k, "Value": v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}
                for k, v in obj.items()]
    return obj


def _kv_transform_service(svc):
    """In-place: convert the well-known dict → [{Key,Value}] fields on a
    get-inference-service payload so preview/update accept it.
    """
    for k in ["Labels", "Taints", "ModelDiscoveryLabels", "TrafficScheduleAnnotations", "OpsAttrs"]:
        v = svc.get(k)
        if isinstance(v, dict):
            svc[k] = _dict_to_kv_list(v)
    app = svc.get("App") or {}
    for k in ["Labels", "Annotations"]:
        v = app.get(k)
        if isinstance(v, dict):
            app[k] = _dict_to_kv_list(v)
    for ws in app.get("WorkerSets") or []:
        for k in ["Labels", "Annotations"]:
            v = ws.get(k)
            if isinstance(v, dict):
                ws[k] = _dict_to_kv_list(v)


def _parse_kv_pair(spec, flag_name):
    if "=" not in spec:
        raise CliError("%s expects KEY=VALUE, got: %s" % (flag_name, spec))
    k, v = spec.split("=", 1)
    if not k:
        raise CliError("%s empty KEY in: %s" % (flag_name, spec))
    return k, v


def _select_container(app, worker_set, role, container):
    """Locate the target Container object inside Application.WorkerSets[].Roles[].Containers[]."""
    ws_names = [w.get("Name") for w in (app.get("WorkerSets") or [])]
    target_ws = next((w for w in (app.get("WorkerSets") or []) if w.get("Name") == worker_set), None)
    if not target_ws:
        raise CliError("worker-set %r not found; available: %s" % (worker_set, ws_names))
    roles = target_ws.get("Roles") or []
    if role:
        target_role = next((r for r in roles if r.get("Name") == role), None)
        if not target_role:
            raise CliError("role %r not found in worker-set %r; available: %s"
                           % (role, worker_set, [r.get("Name") for r in roles]))
    else:
        if not roles:
            raise CliError("worker-set %r has no Roles" % worker_set)
        target_role = roles[0]
    containers = target_role.get("Containers") or []
    if container:
        target_container = next((c for c in containers if c.get("Name") == container), None)
        if not target_container:
            raise CliError("container %r not found in role %r; available: %s"
                           % (container, target_role.get("Name"), [c.get("Name") for c in containers]))
    else:
        if not containers:
            raise CliError("role %r has no Containers" % target_role.get("Name"))
        target_container = containers[0]
    return target_ws, target_role, target_container


def _apply_env_mutations(container, set_envs, unset_envs, set_image, set_entrypoint):
    """In-place mutate the given Container's Env / Image / EntryPoint."""
    env_list = container.get("Env") or []
    env_by_name = {}
    for i, e in enumerate(env_list):
        env_by_name.setdefault(e.get("Name"), i)
    changes = {"set_env": [], "unset_env": [], "unset_env_missing": [], "set_image": None, "set_entrypoint": None}
    for name in unset_envs or []:
        idx = env_by_name.get(name)
        if idx is None:
            changes["unset_env_missing"].append(name)
            continue
        env_list.pop(idx)
        env_by_name = {e.get("Name"): i for i, e in enumerate(env_list)}
        changes["unset_env"].append(name)
    for name, value in set_envs or []:
        idx = env_by_name.get(name)
        if idx is None:
            env_list.append({"Name": name, "Value": value})
            env_by_name[name] = len(env_list) - 1
            changes["set_env"].append({"Name": name, "Value": value, "op": "add"})
        else:
            old = env_list[idx].get("Value")
            env_list[idx]["Value"] = value
            changes["set_env"].append({"Name": name, "Value": value, "old": old,
                                       "op": "unchanged" if old == value else "update"})
    container["Env"] = env_list
    if set_image is not None:
        changes["set_image"] = {"old": container.get("Image"), "new": set_image}
        container["Image"] = set_image
    if set_entrypoint is not None:
        changes["set_entrypoint"] = {"old": container.get("EntryPoint"), "new": set_entrypoint}
        container["EntryPoint"] = set_entrypoint
    return changes


def _post_preview_with_html500_retry(base_url, path, body, force_auth_refresh,
                                     retries=1, delay=3):
    """仅对不落库的预览请求执行一次 HTML 500 重试。"""
    for attempt in range(retries + 1):
        result = _request("POST", base_url, path, body=body, force_auth_refresh=force_auth_refresh)
        err = result.get("error") or result.get("data")
        html_err = isinstance(err, str) and "invalid character '<'" in err
        if result.get("ok") or not html_err or attempt == retries:
            return result
        time.sleep(delay)
    return result


def cmd_switch_inference_template_env(args):
    """One-shot: mutate `Env / Image / EntryPoint` on one Container of a msrv's
    inference template, bump the template version, and (optionally) apply.

    默认创建模板新版本并预览；传 --apply 后才更新服务。
    """
    if not (
        args.set_env
        or args.unset_env
        or args.set_image is not None
        or args.set_entrypoint is not None
        or args.template_name is not None
    ):
        raise CliError("switch-inference-template-env requires at least one template mutation")
    _require_stg_write("switch-inference-template-env", args.base_url)

    trace = {
        "step": [],
        "service_id": args.service_id,
        "worker_set": args.worker_set,
        "role": args.role,
        "container": args.container,
    }

    def _envelope(ok, data, status=200, error=None):
        env = {"ok": ok, "status": status, "url": None, "data": data}
        if error:
            env["error"] = error
        return env

    # Step 1: get-inference-service
    svc_res = _request("GET", args.base_url, DEPLOY_BASE + "/model_inferences_services/" + args.service_id,
                       force_auth_refresh=args.refresh_auth)
    trace["step"].append({"stage": "get-inference-service", "ok": svc_res.get("ok"), "status": svc_res.get("status")})
    if not svc_res.get("ok"):
        return _envelope(False, {"trace": trace, "detail": svc_res}, status=svc_res.get("status", 500),
                         error="get-inference-service failed")
    svc = svc_res["data"]["InferenceService"]
    current_template_id = svc.get("InferenceConfigV2ID")
    fm = (svc.get("ModelReference") or {}).get("FoundationModel") or {}
    fm_name = fm.get("Name"); fm_version = fm.get("ModelVersion")
    if not (current_template_id and fm_name and fm_version):
        return _envelope(False,
                         {"trace": trace,
                          "svc_head": {"Id": svc.get("Id"),
                                       "InferenceConfigV2ID": current_template_id,
                                       "FoundationModel": fm}},
                         status=500,
                         error="missing InferenceConfigV2ID or ModelReference.FoundationModel.{Name,ModelVersion}")
    trace["current_template"] = current_template_id

    # Step 2: GetInferenceServiceResourceConfig (needed for update payload)
    rc_body = {
        "ResponseMetadata": {"Action": "GetInferenceServiceResourceConfig", "Version": "2024-01-01"},
        "MaasServiceId": args.service_id,
        "FoundationModelName": fm_name,
        "FoundationModelVersion": fm_version,
    }
    rc_res = _request("POST", args.base_url, DEPLOY_BASE + "/maas_api_proxy/",
                      params={"Action": "GetInferenceServiceResourceConfig", "Version": "2024-01-01"},
                      body=rc_body, force_auth_refresh=args.refresh_auth)
    trace["step"].append({"stage": "GetInferenceServiceResourceConfig", "ok": rc_res.get("ok"), "status": rc_res.get("status")})
    if not rc_res.get("ok"):
        return _envelope(False, {"trace": trace, "detail": rc_res}, status=rc_res.get("status", 500),
                         error="GetInferenceServiceResourceConfig failed")
    rc_result = (rc_res["data"] or {}).get("Result") or {}

    # Step 3: ListWholeInferenceConfigsV2 to get the full Application
    tpl_body = {
        "ResponseMetadata": {"Action": "ListWholeInferenceConfigsV2", "Version": "2024-01-01"},
        "Filter": {"Ids": [current_template_id]},
    }
    tpl_res = _request("POST", args.base_url, DEPLOY_BASE + "/maas_api_proxy/",
                       params={"Action": "ListWholeInferenceConfigsV2", "Version": "2024-01-01"},
                       body=tpl_body, force_auth_refresh=args.refresh_auth)
    trace["step"].append({"stage": "ListWholeInferenceConfigsV2", "ok": tpl_res.get("ok"), "status": tpl_res.get("status")})
    if not tpl_res.get("ok"):
        return _envelope(False, {"trace": trace, "detail": tpl_res}, status=tpl_res.get("status", 500),
                         error="ListWholeInferenceConfigsV2 failed")
    tpl_items = ((tpl_res["data"] or {}).get("Result") or {}).get("Items") or []
    if not tpl_items:
        return _envelope(False, {"trace": trace}, status=404,
                         error="template %s not found via ListWholeInferenceConfigsV2" % current_template_id)
    current_template = tpl_items[0]
    app_before = current_template.get("Application") or {}

    # Step 4: mutate a deep copy of Application
    import copy as _copy
    app_after = _copy.deepcopy(app_before)
    set_env_pairs = [_parse_kv_pair(s, "--set-env") for s in (args.set_env or [])]
    unset_env_list = list(args.unset_env or [])
    try:
        _, target_role, target_container = _select_container(
            app_after, args.worker_set, args.role, args.container)
    except CliError as e:
        return _envelope(False, {"trace": trace}, status=400, error=str(e))
    changes = _apply_env_mutations(target_container, set_env_pairs, unset_env_list,
                                   args.set_image, args.set_entrypoint)
    trace["changes"] = _redact_sensitive(changes)
    trace["target"] = {"worker_set": args.worker_set,
                       "role": target_role.get("Name"),
                       "container": target_container.get("Name")}

    # Step 5: create-inference-config (bump version if TemplateName unchanged)
    new_template_name = args.template_name or current_template.get("TemplateName")
    create_body = {
        "FoundationModelName": current_template.get("FoundationModelName") or fm_name,
        "FoundationModelVersion": current_template.get("FoundationModelVersion") or fm_version,
        "TemplateName": new_template_name,
        "Application": app_after,
    }
    create_res = _request(
        "POST",
        args.base_url,
        DEPLOY_BASE + "/splitwise_models/inference_configs",
        body=create_body,
        force_auth_refresh=args.refresh_auth,
    )
    trace["step"].append({"stage": "create-inference-config", "ok": create_res.get("ok"), "status": create_res.get("status")})
    if not create_res.get("ok"):
        return _envelope(False, {"trace": trace, "detail": create_res}, status=create_res.get("status", 500),
                         error="create-inference-config failed")
    new_template_id = (create_res.get("data") or {}).get("Id")
    if not new_template_id:
        return _envelope(False, {"trace": trace, "detail": create_res}, status=500,
                         error="create-inference-config returned no Id")
    trace["new_template"] = new_template_id

    # Step 6a: build update-inference-service payload from get + resource-config
    update_payload = dict(svc)  # shallow copy of InferenceService
    _kv_transform_service(update_payload)
    update_payload["FoundationModelName"] = fm_name
    update_payload["FoundationModelVersion"] = fm_version
    update_payload["InferenceConfigVersionV2Id"] = new_template_id
    update_payload["DeployType"] = svc.get("ServiceType", "Dynamic")
    update_payload["MaasServiceId"] = svc.get("Id")
    update_payload.pop("Usage", None)
    update_payload["WorkerSetResourceInfos"] = rc_result.get("WorkerSetResourceInfos", [])
    update_payload["Annotations"] = rc_result.get("Annotations", [])
    update_payload["AppLabels"] = rc_result.get("AppLabels", [])

    # Step 6b: preview
    preview_res = _post_preview_with_html500_retry(
        args.base_url, DEPLOY_BASE + "/splitwise_models/preview_update_inference_service",
        body=update_payload, force_auth_refresh=args.refresh_auth)
    trace["step"].append({"stage": "preview-update-inference-service", "ok": preview_res.get("ok"), "status": preview_res.get("status")})
    if not preview_res.get("ok"):
        return _envelope(False, {"trace": trace, "detail": preview_res}, status=preview_res.get("status", 500),
                         error="preview-update-inference-service failed")

    data = {"trace": trace, "preview": _redact_sensitive(preview_res.get("data")),
            "applied": False,
            "new_template_id": new_template_id}

    if args.apply:
        apply_res = _request(
            "POST",
            args.base_url,
            DEPLOY_BASE + "/splitwise_models/inference_services",
            body=update_payload,
            force_auth_refresh=args.refresh_auth,
        )
        trace["step"].append({"stage": "update-inference-service", "ok": apply_res.get("ok"), "status": apply_res.get("status")})
        data["applied"] = apply_res.get("ok", False)
        data["apply_status"] = apply_res.get("status")
        data["apply_response"] = _redact_sensitive(apply_res.get("data"))
        if not apply_res.get("ok"):
            return _envelope(False, data, status=apply_res.get("status", 500),
                             error="update-inference-service failed")

    return _wrap_write_result("switch-inference-template-env",
                              _envelope(True, data, status=200))


# ---------------------------------------------------------------------------
# CMDB
# ---------------------------------------------------------------------------
def cmd_list_regions(args):
    params = {}
    if args.filter_json:
        params["Filter"] = args.filter_json
    return _request("GET", args.base_url, DEPLOY_BASE + "/cmdb/regions",
                    params=params, force_auth_refresh=args.refresh_auth)


def cmd_list_clusters(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/cmdb/clusters",
                    params={"page_number": args.page_num, "page_size": args.page_size},
                    force_auth_refresh=args.refresh_auth)


def cmd_list_resource_queues(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/cmdb/resource_queues",
                    force_auth_refresh=args.refresh_auth)


def cmd_list_sfcs_warmup(args):
    params = {}
    if args.service_id:
        params["service_id"] = args.service_id
    return _request("GET", args.base_url, DEPLOY_BASE + "/cmdb/sfcs_warmup",
                    params=params, force_auth_refresh=args.refresh_auth)


# ---------------------------------------------------------------------------
# Foundation catalog
# ---------------------------------------------------------------------------
def cmd_list_foundation_models(args):
    params = _pagination_params(args)
    if args.lc:
        params["_lc"] = args.lc
    return _request("GET", args.base_url, DEPLOY_BASE + "/foundation_models",
                    params=params, force_auth_refresh=args.refresh_auth)


def cmd_list_foundation_gpu_types(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/foundation_gpu_types",
                    params=_pagination_params(args), force_auth_refresh=args.refresh_auth)


def cmd_list_foundation_flavors(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/foundation_ark_flavors",
                    params=_pagination_params(args), force_auth_refresh=args.refresh_auth)


# ---------------------------------------------------------------------------
# Ancillary deploy endpoints
# ---------------------------------------------------------------------------
def cmd_list_inference_engine_images(args):
    params = _pagination_params(args)
    if args.region:
        params["region"] = args.region
    if args.fuzzy_image_url is not None:
        params["fuzzy_image_url"] = args.fuzzy_image_url
    return _request("GET", args.base_url, DEPLOY_BASE + "/inference_engine_images",
                    params=params, force_auth_refresh=args.refresh_auth)


def cmd_get_gputype_stat_series(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/gputype_stat_series",
                    force_auth_refresh=args.refresh_auth)


def cmd_list_scheduling_priorities(args):
    return _request("GET", args.base_url, DEPLOY_BASE + "/list_scheduling_priority_options",
                    force_auth_refresh=args.refresh_auth)


# ---------------------------------------------------------------------------
# Event center
# ---------------------------------------------------------------------------
EVENT_BASE = "/_sre/openapi/proxy/consul/api/v1/mlops_eventcenter"


def cmd_list_service_alerts(args):
    params = {
        "controll_region": args.control_region,
        "show_list": _string_bool(args.show_list),
        "begin_at": args.begin_at,
        "end_at": args.end_at,
    }
    if args.service_ids:
        params["service_ids[]"] = list(args.service_ids)
    return _request("GET", args.base_url, EVENT_BASE + "/ark_service_alerts",
                    params=params, force_auth_refresh=args.refresh_auth)


def cmd_list_events(args):
    params = {
        "type": args.event_type,
        "page_num": args.page_num,
        "page_size": args.page_size,
        "begin_at": args.begin_at,
        "end_at": args.end_at,
    }
    if args.sources:
        params["sources[]"] = list(args.sources)
    if args.modules:
        params["modules[]"] = list(args.modules)
    if args.resources:
        params["resources[]"] = list(args.resources)
    return _request("GET", args.base_url, EVENT_BASE + "/events",
                    params=params, force_auth_refresh=args.refresh_auth)


# ---------------------------------------------------------------------------
# Observability (TLS logs)
# ---------------------------------------------------------------------------
OBS_BASE = "/_sre/openapi/proxy/consul/api/v1/mlops_observability"


def cmd_list_saved_queries(args):
    body = _resolve_body(args, {})
    return _request("POST", args.base_url, OBS_BASE + "/list_user_saved_queries",
                    body=body, force_auth_refresh=args.refresh_auth)


def cmd_get_tls_sts_token(args):
    body = _resolve_body(args, {
        "StsRole": args.sts_role,
        "AccountID": args.account_id,
        "Region": args.region,
    })
    return _request("POST", args.base_url, OBS_BASE + "/get_tls_sts_token",
                    body=body, force_auth_refresh=args.refresh_auth)


# ---------------------------------------------------------------------------
# Verify subcommand: timeline coverage
# ---------------------------------------------------------------------------
def _classify(method, path):
    method_up = (method or "").upper()
    for m, rx, label in COVERED_PATTERNS:
        if m == method_up and rx.match(path):
            return "covered", label
    for rx in EXCLUDED_PATTERNS:
        if rx.match(path):
            return "excluded_by_user_scope", None
    return "missing", None


def cmd_verify_timeline_coverage(args):
    with open(args.timeline_file, "r", encoding="utf-8") as f:
        events = json.load(f)
    if not isinstance(events, list):
        raise CliError("timeline file must be a JSON list of events")

    covered = {}
    excluded = {}
    missing = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "NETWORK_REQUEST" and event.get("action") != "NETWORK_REQUEST":
            continue
        method = (event.get("method") or "").upper()
        raw_url = event.get("url") or ""
        try:
            parsed = urllib.parse.urlparse(raw_url)
        except ValueError:
            continue
        bucket, label = _classify(method, parsed.path)
        key = (method, parsed.path)
        if bucket == "covered":
            entry = covered.setdefault(key, {"label": label, "count": 0})
            entry["count"] += 1
        elif bucket == "excluded_by_user_scope":
            excluded[key] = excluded.get(key, 0) + 1
        else:
            missing[key] = missing.get(key, 0) + 1

    def _to_list(mapping, with_label):
        out = []
        for (m, p), v in sorted(mapping.items()):
            if with_label:
                out.append({"method": m, "path": p, "count": v["count"], "label": v["label"]})
            else:
                out.append({"method": m, "path": p, "count": v})
        return out

    covered_list = _to_list(covered, True)
    excluded_list = _to_list(excluded, False)
    missing_list = _to_list(missing, False)
    total = (sum(x["count"] for x in covered_list)
             + sum(x["count"] for x in excluded_list)
             + sum(x["count"] for x in missing_list))
    data = {
        "covered": covered_list,
        "excluded_by_user_scope": excluded_list,
        "missing": missing_list,
        "covered_count": sum(x["count"] for x in covered_list),
        "excluded_count": sum(x["count"] for x in excluded_list),
        "missing_count": sum(x["count"] for x in missing_list),
        "total": total,
    }
    ok = data["missing_count"] == 0
    return {"ok": ok, "status": 200, "url": args.timeline_file, "data": data}


# ---------------------------------------------------------------------------
# build-url: web page detail URLs
# ---------------------------------------------------------------------------
DEFAULT_WEB_BASE_URL = DEFAULT_BASE_URL

URL_TEMPLATES = {
    "cronjob":          "/toolbox/cronjob?_lc={lc}",
    "arkvbh":           "/toolbox/arkvbh?_lc={lc}",
    "nacos-list":       "/cicd/nacos?_lc={lc}&instance_id={instance_id}&product={product}",
    "nacos-history":    "/cicd/nacos/config_history?product={product}&instance_id={instance_id}&namespace={namespace}&data_id={data_id}",
    "nacos-publish":    "/cicd/nacos/publish_detail?product={product}&instance_id={instance_id}&deployment_id={deployment_id}",
    "inference":        "/maas/inferencesservice?_lc={lc}",
    "inference-detail": "/maas/inferencesservice/{service_id}/dcp-detail?_lc={lc}",
    "splitwise":        "/maas/serviceops/splitwise/config?_lc={lc}",
    "release-trains":   "/cicd/releasetrains?_lc={lc}",
    "delivery-apply":   "/cicd/deliveryapply?_lc={lc}",
    "delivery-events":  "/cicd/stat/deliveryevent?_lc={lc}",
    "lanes":            "/cicd/lanes?_lc={lc}",
    "lane-detail":      "/cicd/lanes/{lane_id}?_lc={lc}",
    "lane-delivery":    "/cicd/lanes/{lane_id}/deliveries/{delivery_id}?_lc={lc}",
    "resource-stats":   "/ark-resource-ops/stat/overview?_lc={lc}",
    "observability":    "/observability/logs?_lc={lc}",
}


def _derive_lc(explicit_lc, region):
    if explicit_lc:
        return explicit_lc
    region = (region or "").strip()
    if region and not region.startswith("cn-"):
        return "bp"
    return "cn"


def cmd_build_url(args):
    template = URL_TEMPLATES.get(args.asset_type)
    if not template:
        raise CliError("unsupported asset type: %s" % args.asset_type)
    region = (getattr(args, "mlops_region", "") or "").strip()
    fields = {
        "lc": _derive_lc(args.lc, region),
        "product": args.product or "maas",
        "instance_id": args.instance_id or "",
        "namespace": args.namespace or "",
        "data_id": args.data_id or "",
        "deployment_id": args.deployment_id or "",
        "lane_id": args.lane_id or "",
        "delivery_id": args.delivery_id or "",
        "service_id": args.service_id or "",
    }
    try:
        path = template.format(**fields)
    except KeyError as exc:
        raise CliError("missing template field: %s" % exc)
    web_base_url = args.web_base_url.rstrip("/")
    url = web_base_url + path
    data = {
        "url": url,
        "path": path,
        "asset_type": args.asset_type,
        "env": args.env,
        "base_url": web_base_url,
    }
    return {"ok": True, "status": 200, "url": url, "data": data}


# ---------------------------------------------------------------------------
# argparse plumbing
# ---------------------------------------------------------------------------
def _add_common(parser):
    parser.add_argument("--env", default=os.environ.get("MLOPS_ENV", DEFAULT_ENV),
                        help="Target MLOps environment: stg (pre-release) or prod (online). Default: stg.")
    parser.add_argument("--base-url", default=None,
                        help="Override business platform base URL. Defaults by --env: stg=%s, prod=%s"
                             % (BASE_URL_BY_ENV["stg"], BASE_URL_BY_ENV["prod"]))
    parser.add_argument("--refresh-auth", action="store_true",
                        help="Ignore cached JWT and fetch a fresh one via bytedcli")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--mlops-region", default=None,
                        help="X-MLOps-Region header value (default empty = platform default cn-beijing). "
                             "Use e.g. 'ap-southeast-1' to query the Singapore region. "
                             "Env fallback: MLOPS_<ENV>_REGION or MLOPS_REGION; "
                             "stg also supports legacy MLOPS_STG_REGION.")


def _add_pagination(parser, default_size=100):
    parser.add_argument("--page-num", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=default_size)


def build_parser():
    p = argparse.ArgumentParser(description="ml-maas / mlops business CLI (stg/prod)")
    sub = p.add_subparsers(dest="command", required=True)

    # ---------------- 工具箱 / 基础服务 ----------------
    sp = sub.add_parser("list-cronjob-apps", help="List CronJob service applications")
    _add_common(sp); _add_pagination(sp, default_size=10)
    sp.set_defaults(func=cmd_list_cronjob_apps)

    sp = sub.add_parser(
        "get-or-create-vbh-login-message",
        help="STG-only write API: get or create Ark VBH login information for a VKE cluster",
    )
    _add_common(sp)
    sp.add_argument("--vke-cluster-region")
    sp.add_argument("--vke-cluster-name")
    sp.add_argument("--request-type", default="VkeCluster")
    sp.add_argument("--product-name", default="ark")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_get_or_create_vbh_login_message)

    # ---------------- Nacos ----------------
    sp = sub.add_parser("list-nacos-instances", help="List Nacos instances")
    _add_common(sp); _add_pagination(sp)
    sp.add_argument("--product-code", default="maas")
    sp.add_argument("--region")
    sp.add_argument("--is-sync", action="store_true")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_nacos_instances)

    sp = sub.add_parser("get-nacos-instance", help="Get Nacos instance detail")
    _add_common(sp)
    sp.add_argument("--instance-id", required=True)
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_get_nacos_instance)

    sp = sub.add_parser("list-nacos-namespaces", help="List Nacos namespaces of an instance")
    _add_common(sp); _add_pagination(sp, default_size=1000)
    sp.add_argument("--instance-id", required=True)
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_nacos_namespaces)

    sp = sub.add_parser("list-nacos-configs", help="List Nacos configs in an instance")
    _add_common(sp); _add_pagination(sp, default_size=10)
    sp.add_argument("--instance-id", required=True)
    sp.add_argument("--namespace-id"); sp.add_argument("--namespace-name")
    sp.add_argument("--group"); sp.add_argument("--data-id"); sp.add_argument("--fuzzy-data-id")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_nacos_configs)

    sp = sub.add_parser("get-nacos-config", help="Get Nacos config detail (with latest & online version)")
    _add_common(sp)
    sp.add_argument("--id", type=int, required=True)
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_get_nacos_config)

    sp = sub.add_parser("list-nacos-config-versions", help="List version history for a Nacos config")
    _add_common(sp); _add_pagination(sp, default_size=10)
    sp.add_argument("--instance-id", required=True)
    sp.add_argument("--data-id", required=True)
    sp.add_argument("--group", required=True)
    sp.add_argument("--namespace-name", required=True)
    sp.add_argument("--namespace-id")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_nacos_config_versions)

    sp = sub.add_parser("list-nacos-config-deployments", help="List Nacos config deployments (a.k.a. publish tickets)")
    _add_common(sp); _add_pagination(sp)
    sp.add_argument("--instance-id"); sp.add_argument("--created-by")
    sp.add_argument("--status", action="append", help="Status filter, repeatable (e.g. accepted, reviewing)")
    sp.add_argument("--data-id"); sp.add_argument("--namespace-name")
    sp.add_argument("--without-instance-id", action="store_true",
                    help="Set WithoutInstanceID=true — matches personal deployments across instances")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_nacos_config_deployments)

    sp = sub.add_parser("list-nacos-batch-deployments", help="List batch (multi-instance) Nacos deployments")
    _add_common(sp); _add_pagination(sp, default_size=10)
    sp.add_argument("--product-code", default="maas")
    sp.add_argument("--region", default="cn-beijing")
    sp.add_argument("--instance-id")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_nacos_batch_deployments)

    sp = sub.add_parser("get-nacos-deployment", help="Get a Nacos deployment detail (publish record)")
    _add_common(sp)
    sp.add_argument("--id", type=int, required=True)
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_get_nacos_deployment)

    sp = sub.add_parser("list-nacos-reviewers", help="List reviewers for a Nacos config")
    _add_common(sp)
    sp.add_argument("--nacos-config-id", type=int, required=True)
    sp.add_argument("--review-type", default="nacos")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_nacos_reviewers)

    sp = sub.add_parser(
        "update-nacos-config",
        help="STG-only write API: save a new Nacos config version",
    )
    _add_common(sp)
    sp.add_argument("--nacos-config-id", type=int)
    sp.add_argument("--content-file")
    sp.add_argument("--config-type", default="yaml")
    sp.add_argument("--description", default="")
    sp.add_argument("--tag", action="append")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_update_nacos_config)

    sp = sub.add_parser(
        "create-nacos-deployment",
        help="STG-only write API: create a Nacos publish ticket",
    )
    _add_common(sp)
    sp.add_argument("--nacos-config-id", type=int)
    sp.add_argument("--reviewer", action="append")
    sp.add_argument("--comment", default="")
    sp.add_argument("--is-urgent", action="store_true")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_create_nacos_deployment)

    sp = sub.add_parser(
        "publish-nacos-config",
        help="STG-only write API: advance or publish a Nacos deployment",
    )
    _add_common(sp)
    sp.add_argument("--deployment-id", type=int)
    sp.add_argument("--status", help="Recorded values include accepted and deploying")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_publish_nacos_config)

    # ---------------- Delivery / CICD ----------------
    sp = sub.add_parser("list-products", help="List MLOps CICD products")
    _add_common(sp); _add_pagination(sp)
    sp.set_defaults(func=cmd_list_products)

    sp = sub.add_parser("list-modules", help="List CICD modules of a product")
    _add_common(sp); _add_pagination(sp, default_size=1000)
    sp.add_argument("--product-id", type=int)
    sp.set_defaults(func=cmd_list_modules)

    sp = sub.add_parser("list-deliveries", help="List product delivery tickets")
    _add_common(sp); _add_pagination(sp)
    sp.add_argument("--status", action="append")
    sp.add_argument("--created-by")
    sp.add_argument("--lc")
    sp.set_defaults(func=cmd_list_deliveries)

    sp = sub.add_parser("list-infrastructure-deliveries", help="List infrastructure delivery tickets")
    _add_common(sp); _add_pagination(sp)
    sp.add_argument("--status", action="append")
    sp.add_argument("--created-by")
    sp.set_defaults(func=cmd_list_infrastructure_deliveries)

    sp = sub.add_parser("list-release-trains", help="List release trains")
    _add_common(sp)
    sp.add_argument("--page-size", type=int, default=20)
    sp.add_argument("--status", action="append")
    sp.add_argument("--lc", default="cn")
    sp.set_defaults(func=cmd_list_release_trains)

    sp = sub.add_parser("list-delivery-applies", help="List delivery apply records")
    _add_common(sp)
    sp.add_argument("--page-size", type=int, default=10)
    sp.add_argument("--lc", default="cn")
    sp.set_defaults(func=cmd_list_delivery_applies)

    sp = sub.add_parser("list-delivery-events", help="List delivery events in a time window")
    _add_common(sp); _add_pagination(sp, default_size=20)
    sp.add_argument("--start-time", type=int, default=0)
    sp.add_argument("--end-time", type=int, default=0)
    sp.add_argument("--status"); sp.add_argument("--product", default="maas")
    sp.add_argument("--operator"); sp.add_argument("--resource"); sp.add_argument("--event-id")
    sp.add_argument("--delivery-id"); sp.add_argument("--fuzzy-keyword"); sp.add_argument("--lc", default="cn")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_delivery_events)

    sp = sub.add_parser("list-change-templates", help="List CICD change templates")
    _add_common(sp)
    sp.add_argument("--page-size", type=int, default=10000)
    sp.add_argument("--lc", default="cn")
    sp.set_defaults(func=cmd_list_change_templates)

    sp = sub.add_parser("list-lane-products", help="List products available to lane delivery")
    _add_common(sp)
    sp.set_defaults(func=cmd_list_lane_products)

    sp = sub.add_parser(
        "list-lane-product-instances",
        help="List region/environment instances of a lane product",
    )
    _add_common(sp)
    sp.add_argument("--product-code", default="maas")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_lane_product_instances)

    sp = sub.add_parser("list-lanes", help="List lanes with product, environment and owner filters")
    _add_common(sp); _add_pagination(sp, default_size=20)
    sp.add_argument("--product-id", type=int)
    sp.add_argument("--product-instance-id", type=int)
    sp.add_argument("--status", action="append")
    sp.add_argument("--name")
    sp.add_argument("--created-by")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_lanes)

    sp = sub.add_parser("get-lane", help="Get one lane by ID")
    _add_common(sp)
    sp.add_argument("--lane-id", type=int, required=True)
    sp.set_defaults(func=cmd_get_lane)

    sp = sub.add_parser("list-lane-modules", help="List modules that support lane delivery")
    _add_common(sp)
    sp.add_argument("--product-id", type=int, required=True)
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_lane_modules)

    sp = sub.add_parser("list-lane-module-deploys", help="List current module deployments in a lane")
    _add_common(sp); _add_pagination(sp, default_size=20)
    sp.add_argument("--lane-id", type=int, required=True)
    sp.add_argument("--module-id", type=int,
                    help="Filter to one module (dependency checks, e.g. is maas-runtime-config present)")
    sp.add_argument("--status", action="append",
                    help="ModuleDeploy status filter, repeatable (Succeeded, Failed, ...)")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_lane_module_deploys)

    sp = sub.add_parser(
        "get-lane-module-deploy",
        help="Get one lane module deployment with its K8s resources and pods",
    )
    _add_common(sp)
    sp.add_argument("--module-deploy-id", type=int, required=True)
    sp.set_defaults(func=cmd_get_lane_module_deploy)

    sp = sub.add_parser("get-lane-pod-events", help="Get Kubernetes events of one lane pod")
    _add_common(sp)
    sp.add_argument("--pod-name", help="Pod name from get-lane-module-deploy")
    sp.add_argument("--module-deploy-id", type=int,
                    help="Resolve lane/cluster/namespace from this ModuleDeploy")
    sp.add_argument("--lane-id", type=int)
    sp.add_argument("--cluster-id")
    sp.add_argument("--namespace")
    sp.add_argument("--limit", type=int, default=60, help="Max events (backend cap 60)")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_get_lane_pod_events)

    sp = sub.add_parser("get-lane-pod-logs", help="Get container logs of one lane pod")
    _add_common(sp)
    sp.add_argument("--pod-name", help="Pod name from get-lane-module-deploy")
    sp.add_argument("--module-deploy-id", type=int,
                    help="Resolve lane/cluster/namespace and container name from this ModuleDeploy")
    sp.add_argument("--lane-id", type=int)
    sp.add_argument("--cluster-id")
    sp.add_argument("--namespace")
    sp.add_argument("--container-name",
                    help="Container to read. Auto-resolved from the pod spec when "
                         "--module-deploy-id is given; the backend default 'main' does not exist "
                         "on ark workloads and returns 500")
    sp.add_argument("--limit", type=int, default=100, help="Max log lines (backend cap 500)")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_get_lane_pod_logs)

    sp = sub.add_parser("list-lane-deliveries", help="List lane delivery records")
    _add_common(sp); _add_pagination(sp, default_size=100)
    sp.add_argument("--lane-id", type=int)
    sp.add_argument("--status", action="append")
    sp.add_argument("--created-by")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_lane_deliveries)

    sp = sub.add_parser("get-lane-delivery", help="Get one lane delivery and its current stage")
    _add_common(sp)
    sp.add_argument("--delivery-id", type=int, required=True)
    sp.set_defaults(func=cmd_get_lane_delivery)

    sp = sub.add_parser("list-lane-delivery-artifacts", help="List image/chart artifacts of a lane delivery")
    _add_common(sp)
    sp.add_argument("--delivery-id", type=int, required=True)
    sp.set_defaults(func=cmd_list_lane_delivery_artifacts)

    sp = sub.add_parser("list-lane-delivery-deploys", help="List cluster deployments of a lane delivery")
    _add_common(sp)
    sp.add_argument("--delivery-id", type=int, required=True)
    sp.add_argument("--status", action="append",
                    help="Deploy status filter, repeatable (Failed, Succeeded, Pending, ...)")
    sp.add_argument("--module-id", type=int)
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_lane_delivery_deploys)

    sp = sub.add_parser("list-lane-helm-diffs", help="Get Helm render progress and diff of a lane delivery")
    _add_common(sp)
    sp.add_argument("--delivery-id", type=int, required=True)
    sp.set_defaults(func=cmd_list_lane_helm_diffs)

    sp = sub.add_parser(
        "create-lane-delivery",
        help="STG-only write API: create one lane delivery",
    )
    _add_common(sp)
    sp.add_argument("--product-id", type=int)
    sp.add_argument("--lane-id", type=int)
    sp.add_argument("--product-instance-id", type=int)
    sp.add_argument("--deploy-mode", default="ALL")
    sp.add_argument("--manual-stage", action="store_true",
                    help="set StageAutoNext=false; recording default is automatic progression")
    sp.add_argument("--description", default="")
    sp.add_argument("--module-json", action="append", metavar="JSON",
                    help="one ModulesToDelivery object; repeatable")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_create_lane_delivery)

    sp = sub.add_parser(
        "create-multi-lane-deliveries",
        help="STG-only batch write: create the same delivery in up to 10 lanes",
    )
    _add_common(sp)
    sp.add_argument("--lane-id", type=int, action="append", required=True)
    sp.add_argument("--deploy-mode", default="ALL")
    sp.add_argument("--manual-stage", action="store_true")
    sp.add_argument("--description", default="")
    sp.add_argument("--module-json", action="append", required=True, metavar="JSON",
                    help="one ModulesToDelivery object; repeatable")
    sp.set_defaults(func=cmd_create_multi_lane_deliveries)

    # ---------------- Inference services ----------------
    sp = sub.add_parser("list-inference-services", help="List model inference services")
    _add_common(sp); _add_pagination(sp, default_size=10)
    sp.add_argument("--fuzzy-service-name", default="")
    sp.add_argument("--fuzzy-image-url", default="")
    sp.add_argument("--model-name", default="")
    sp.add_argument("--model-version", default="")
    sp.add_argument("--hybrid"); sp.add_argument("--multi-cluster")
    sp.add_argument("--is-gray-release"); sp.add_argument("--usage")
    sp.add_argument("--resource-queue"); sp.add_argument("--dcp-resource-queue")
    sp.add_argument("--cluster-id"); sp.add_argument("--fuzzy-create-user")
    sp.add_argument("--engine-arch"); sp.add_argument("--modality"); sp.add_argument("--model-type")
    sp.add_argument("--statuses", action="append",
                    help="Statuses filter, repeatable (Running, Abnormal, Scheduling, Closed, ...)")
    sp.add_argument("--service-ids", action="append",
                    help="Service ID filter, repeatable (msrv-...)")
    sp.add_argument("--lc")
    sp.set_defaults(func=cmd_list_inference_services)

    sp = sub.add_parser("get-inference-service", help="Get an inference service by id")
    _add_common(sp)
    sp.add_argument("--service-id", required=True)
    sp.set_defaults(func=cmd_get_inference_service)

    sp = sub.add_parser(
        "update-inference-service-labels",
        help="STG-only write API: replace or incrementally update inference service Labels.Values. "
             "A support.foundation-model label is converted by the platform into ModelDiscoveryLabels.",
    )
    _add_common(sp)
    sp.add_argument("--service-id", required=True)
    sp.add_argument("--payload-json")
    sp.add_argument("--payload-file")
    sp.add_argument(
        "--set-label",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="upsert one service label; repeatable and merged with current Labels.Values",
    )
    sp.add_argument(
        "--remove-label",
        action="append",
        default=[],
        metavar="KEY",
        help="remove one service label; repeatable",
    )
    sp.add_argument(
        "--foundation-model-label",
        action="append",
        default=[],
        metavar="MODEL_NAME=MODEL_VERSION",
        help="add support.foundation-model.ark/<name>_<version>=true; repeatable",
    )
    sp.add_argument(
        "--batch-to-online",
        action="store_true",
        help="set BatchToOnline=true; default false as observed in the recording",
    )
    sp.set_defaults(func=cmd_update_inference_service_labels)

    sp = sub.add_parser("list-inference-service-events", help="List Kubernetes/Pod events for an inference service")
    _add_common(sp)
    sp.add_argument("--service-id", required=True)
    sp.set_defaults(func=cmd_list_inference_service_events)

    sp = sub.add_parser("list-inference-service-pods", help="List pods of an inference service by role")
    _add_common(sp)
    sp.add_argument("--service-id", required=True)
    sp.set_defaults(func=cmd_list_inference_service_pods)

    sp = sub.add_parser("list-inference-hpa-metrics", help="List supported HPA metric definitions")
    _add_common(sp)
    sp.set_defaults(func=cmd_list_inference_hpa_metrics)

    sp = sub.add_parser("list-inference-hpa-jobs", help="List active multi-region HPA jobs")
    _add_common(sp)
    sp.set_defaults(func=cmd_list_inference_hpa_jobs)

    sp = sub.add_parser("get-inference-dcp-gpu-stats", help="DCP GPU resource stats for inference services")
    _add_common(sp)
    sp.add_argument("--gpu-types", action="append",
                    help="GPU type key, repeatable (e.g. CPU-16XLARGE, NVIDIA-L20)")
    sp.add_argument("--service-id")
    sp.set_defaults(func=cmd_get_inference_dcp_gpu_stats)

    sp = sub.add_parser("call-maas-api",
                        help="Invoke the maas_api_proxy openapi (Action+Version). "
                             "Payload comes from --payload-json/--payload-file.")
    _add_common(sp)
    sp.add_argument("--action", required=True,
                    help="e.g. GetInferenceServiceResourceConfig, UpdateInferenceService")
    sp.add_argument("--version", default="2024-01-01")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_call_maas_api)

    sp = sub.add_parser("list-inference-update-records", help="List inference service update history")
    _add_common(sp)
    sp.add_argument("--service-id", required=True)
    sp.set_defaults(func=cmd_list_inference_update_records)

    # ---------------- Splitwise / DCP ----------------
    sp = sub.add_parser("list-fed-control-clusters", help="List DCP fed-control clusters")
    _add_common(sp)
    sp.set_defaults(func=cmd_list_fed_control_clusters)

    sp = sub.add_parser("list-dcp-member-clusters", help="List DCP member clusters")
    _add_common(sp)
    sp.add_argument("--dcp-control-cluster-id")
    sp.set_defaults(func=cmd_list_dcp_member_clusters)

    sp = sub.add_parser("list-inference-config-templates", help="List inference config templates")
    _add_common(sp); _add_pagination(sp, default_size=200)
    sp.set_defaults(func=cmd_list_inference_config_templates)

    sp = sub.add_parser("list-official-inference-configs", help="List official Splitwise inference configs")
    _add_common(sp); _add_pagination(sp, default_size=10)
    sp.add_argument("--model-name"); sp.add_argument("--model-version")
    sp.add_argument("--fuzzy-template-name"); sp.add_argument("--lc", default="cn")
    sp.add_argument("--context-model-name", help="UI context query param modelName from Splitwise edit page")
    sp.add_argument("--context-model-version", help="UI context query param modelVersion from Splitwise edit page")
    sp.add_argument("--service-id", help="UI context query param serviceId from Splitwise edit page")
    sp.add_argument("--service-type", help="UI context query param serviceType, e.g. online")
    sp.add_argument("--edit", action="store_true", help="Set edit=true, matching the Splitwise edit page query")
    sp.set_defaults(func=cmd_list_official_inference_configs)

    sp = sub.add_parser(
        "create-inference-config",
        help="STG-only write API: create an official Splitwise inference config or a new version. "
             "Prod/online write APIs are not supported.",
    )
    _add_common(sp)
    sp.add_argument("--payload-json")
    sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_create_inference_config)

    sp = sub.add_parser(
        "preview-update-inference-service",
        help="STG-only write API: preview an inference service update diff before committing it. "
             "Prod/online write APIs are not supported.",
    )
    _add_common(sp)
    sp.add_argument("--payload-json")
    sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_preview_update_inference_service)

    sp = sub.add_parser(
        "update-inference-service",
        help="STG-only write API: commit an inference service update. "
             "Prod/online write APIs are not supported.",
    )
    _add_common(sp)
    sp.add_argument("--payload-json")
    sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_update_inference_service)

    sp = sub.add_parser(
        "switch-inference-template-env",
        help="STG-only shortcut: mutate Env/Image/EntryPoint on one Container "
             "of a msrv's inference template, create a new template version, "
             "preview diff, and optionally apply it to the service.",
    )
    _add_common(sp)
    sp.add_argument("--service-id", required=True, help="msrv-* service id")
    sp.add_argument("--worker-set", default="decode",
                    help="target WorkerSet name (default: decode)")
    sp.add_argument("--role", default=None,
                    help="target Role name inside the WorkerSet (default: first role)")
    sp.add_argument("--container", default=None,
                    help="target Container name inside the Role (default: first container)")
    sp.add_argument("--set-env", action="append", default=[],
                    metavar="KEY=VALUE",
                    help="upsert an env var; repeatable (e.g. --set-env MOCK_VLM=true)")
    sp.add_argument("--unset-env", action="append", default=[], metavar="KEY",
                    help="remove an env var by name; repeatable")
    sp.add_argument("--set-image", default=None, help="replace Container.Image")
    sp.add_argument("--set-entrypoint", default=None, help="replace Container.EntryPoint")
    sp.add_argument("--template-name", default=None,
                    help="override TemplateName for the created config (default: keep current "
                         "TemplateName → auto-bumps Version)")
    sp.add_argument("--apply", action="store_true",
                    help="actually POST update-inference-service after preview; "
                         "default creates a template version and previews without updating msrv")
    sp.set_defaults(func=cmd_switch_inference_template_env)

    # ---------------- CMDB ----------------
    sp = sub.add_parser("list-regions", help="List CMDB regions")
    _add_common(sp)
    sp.add_argument("--filter-json",
                    help='JSON literal for the Filter query param (e.g. \'{"ArkControlRegion":"cn-beijing"}\')')
    sp.set_defaults(func=cmd_list_regions)

    sp = sub.add_parser("list-clusters", help="List CMDB clusters")
    _add_common(sp); _add_pagination(sp, default_size=200)
    sp.set_defaults(func=cmd_list_clusters)

    sp = sub.add_parser("list-resource-queues", help="List CMDB resource queues (both local and DCP)")
    _add_common(sp)
    sp.set_defaults(func=cmd_list_resource_queues)

    sp = sub.add_parser("list-sfcs-warmup", help="List SFCS warmup status for a service")
    _add_common(sp)
    sp.add_argument("--service-id")
    sp.set_defaults(func=cmd_list_sfcs_warmup)

    # ---------------- Foundation ----------------
    sp = sub.add_parser("list-foundation-models", help="List foundation model catalog")
    _add_common(sp); _add_pagination(sp, default_size=1000)
    sp.add_argument("--lc")
    sp.set_defaults(func=cmd_list_foundation_models)

    sp = sub.add_parser("list-foundation-gpu-types", help="List available foundation GPU/NPU types")
    _add_common(sp); _add_pagination(sp, default_size=1000)
    sp.set_defaults(func=cmd_list_foundation_gpu_types)

    sp = sub.add_parser("list-foundation-flavors", help="List Ark inference flavor specs")
    _add_common(sp); _add_pagination(sp, default_size=200)
    sp.set_defaults(func=cmd_list_foundation_flavors)

    # ---------------- Ancillary deploy ----------------
    sp = sub.add_parser("list-inference-engine-images", help="List published inference engine images")
    _add_common(sp); _add_pagination(sp, default_size=200)
    sp.add_argument("--region", default="cn-beijing")
    sp.add_argument("--fuzzy-image-url", default="")
    sp.set_defaults(func=cmd_list_inference_engine_images)

    sp = sub.add_parser("get-gputype-stat-series", help="Read GPU type stat time series")
    _add_common(sp)
    sp.set_defaults(func=cmd_get_gputype_stat_series)

    sp = sub.add_parser("list-scheduling-priorities", help="List scheduling priority values")
    _add_common(sp)
    sp.set_defaults(func=cmd_list_scheduling_priorities)

    # ---------------- Event center ----------------
    sp = sub.add_parser("list-service-alerts", help="List Ark inference service alerts (windowed)")
    _add_common(sp)
    sp.add_argument("--control-region", default="cn-beijing")
    sp.add_argument("--service-ids", action="append",
                    help="Inference service id filter, repeatable (msrv-...)")
    sp.add_argument("--show-list", action="store_true", default=True)
    sp.add_argument("--begin-at", type=int, required=True, help="Unix seconds")
    sp.add_argument("--end-at", type=int, required=True, help="Unix seconds")
    sp.set_defaults(func=cmd_list_service_alerts)

    sp = sub.add_parser("list-events", help="List event center audit / op_log events")
    _add_common(sp); _add_pagination(sp, default_size=50)
    sp.add_argument("--event-type", default="op_log", help="Event type: op_log, alarm, ...")
    sp.add_argument("--sources", action="append",
                    help="Repeatable event source (e.g. data.amltob.ops_deploy)")
    sp.add_argument("--modules", action="append",
                    help="Repeatable module filter (e.g. InferenceService-Ops)")
    sp.add_argument("--resources", action="append", help="Repeatable resource id filter")
    sp.add_argument("--begin-at", type=int, required=True)
    sp.add_argument("--end-at", type=int, required=True)
    sp.set_defaults(func=cmd_list_events)

    # ---------------- Observability ----------------
    sp = sub.add_parser("list-saved-queries", help="List user-saved TLS log queries")
    _add_common(sp)
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_list_saved_queries)

    sp = sub.add_parser("get-tls-sts-token", help="Get TLS STS token for the log region")
    _add_common(sp)
    sp.add_argument("--sts-role", default="StsRoleForTLSRead")
    sp.add_argument("--account-id", type=int, default=2100339946)
    sp.add_argument("--region", default="cn-beijing")
    sp.add_argument("--payload-json"); sp.add_argument("--payload-file")
    sp.set_defaults(func=cmd_get_tls_sts_token)

    # ---------------- verify subtree ----------------
    verify = sub.add_parser("verify", help="Verify skill coverage (offline)")
    verify_sub = verify.add_subparsers(dest="verify_command", required=True)
    vp = verify_sub.add_parser("timeline-coverage",
                               help="Classify recorded network requests against CLI coverage")
    vp.add_argument("timeline_file", help="Path to recorded timeline JSON")
    vp.add_argument("--pretty", action="store_true")
    vp.set_defaults(func=cmd_verify_timeline_coverage)

    # ---------------- build-url ----------------
    sp = sub.add_parser("build-url", help="Build a business platform detail URL")
    sp.add_argument("asset_type", choices=sorted(URL_TEMPLATES.keys()),
                    help="Which page template to build")
    sp.add_argument("--instance-id"); sp.add_argument("--namespace"); sp.add_argument("--data-id")
    sp.add_argument("--deployment-id"); sp.add_argument("--service-id")
    sp.add_argument("--lane-id"); sp.add_argument("--delivery-id")
    sp.add_argument("--product", default="maas")
    sp.add_argument("--env", default=os.environ.get("MLOPS_ENV", DEFAULT_ENV),
                    help="Target MLOps environment: stg (pre-release) or prod (online). Default: stg.")
    sp.add_argument("--lc", default=None,
                    help="Locale query param. If omitted, derived from --mlops-region: "
                         "cn-* → cn, other non-empty regions → bp, empty → cn.")
    sp.add_argument("--mlops-region", default=None,
                    help="Region the target resource lives in (e.g. 'cn-beijing', 'ap-southeast-1'). "
                         "Only used to auto-derive --lc when --lc is not set. "
                         "Env fallback: MLOPS_<ENV>_REGION or MLOPS_REGION; "
                         "stg also supports legacy MLOPS_STG_REGION.")
    sp.add_argument("--web-base-url", default=None,
                    help="Override page base URL. Defaults by --env: stg=%s, prod=%s"
                         % (BASE_URL_BY_ENV["stg"], BASE_URL_BY_ENV["prod"]))
    sp.add_argument("--pretty", action="store_true")
    sp.set_defaults(func=cmd_build_url)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    global _MLOPS_ENV, _MLOPS_REGION
    try:
        _MLOPS_ENV = _normalize_env(getattr(args, "env", DEFAULT_ENV))
        args.env = _MLOPS_ENV
        if hasattr(args, "base_url"):
            args.base_url = resolve_base_url(_MLOPS_ENV, args.base_url)
        if hasattr(args, "web_base_url"):
            args.web_base_url = resolve_base_url(_MLOPS_ENV, args.web_base_url)
        if hasattr(args, "mlops_region"):
            args.mlops_region = resolve_region(_MLOPS_ENV, args.mlops_region)
        _MLOPS_REGION = (getattr(args, "mlops_region", "") or "").strip()
        result = args.func(args)
        indent = 2 if getattr(args, "pretty", False) else None
        sort = bool(getattr(args, "pretty", False))
        print(json.dumps(result, ensure_ascii=False, indent=indent, sort_keys=sort))
        return 0 if result.get("ok") else 2
    except CliError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
