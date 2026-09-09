"""mlops-stg-skill CLI 的离线单元测试。

测试会启动 stdlib http.server 模拟 mlops 业务平台，再用下面的环境变量
以子进程方式调用 CLI：

    MLOPS_STG_BASE_URL=http://127.0.0.1:<port>
    MLOPS_STG_AUTH_JSON={"X-Jwt-Token":"unit-test"}

断言会确认 CLI：
  1. 输出顶层 JSON 信封，且 ok=True、data 非空。
  2. 发出目标接口期望的请求（method / path / query / body）。
  3. 从 mock 响应中取到语义字段。

CLI stdout 会回显到测试日志，方便人工查看每条命令返回的 JSON。

运行：python3 tests/test_cli.py -v
"""
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "mlops_stg_cli.py"
REPORT_BUILDER = ROOT / "scripts" / "build_api_analysis_report.py"
WRITE_TESTS_ENABLED = os.environ.get("MLOPS_STG_SKILL_ENABLE_WRITE_TESTS") == "1"


# ---------------------------------------------------------------------------
# Static fixture data — sourced from real recording shapes but kept here so the
# tests do not depend on any external file.
# ---------------------------------------------------------------------------
NACOS_INSTANCE = {
    "ID": 1,
    "InstanceID": "nctgj1oqh22vvfr2jqrr0",
    "Name": "ark-stg-nacos-cn-beijing",
    "Region": "cn-beijing",
    "ProductCode": "maas",
    "RouterSign": "nacos-cn-beijing",
    "PrivateAddress": "10.0.0.86",
}
NACOS_INSTANCES = [NACOS_INSTANCE, {
    "ID": 2, "InstanceID": "nctgkorh3mbxx", "Name": "ark-stg-nacos-utf8mb4-cn-beijing",
    "Region": "cn-beijing", "ProductCode": "maas",
}]
NACOS_NAMESPACES = [
    {"NamespaceID": "", "NamespaceName": "public", "ConfigCount": 7, "Type": 0, "Quota": 200},
    {"NamespaceID": "e08b9355-0745-46de-ae93-f7130a2c0c79",
     "NamespaceName": "ml-maas-api-proxy",
     "NamespaceDesc": "推理链路model-proxy使用的运行时配置", "ConfigCount": 40, "Type": 2, "Quota": 200},
]
NACOS_CONFIG_ROW = {
    "ID": 21, "NamespaceName": "ml-maas-api-proxy",
    "NamespaceID": "e08b9355-0745-46de-ae93-f7130a2c0c79",
    "DataID": "lb_config", "Group": "ml-maas-api-proxy",
    "CreatedBy": "qiuli.garden",
}
NACOS_CONFIG_DETAIL = {
    **NACOS_CONFIG_ROW,
    "OnlineVersion": {"ID": 9130, "Version": 154, "IsRelease": True, "PublishedBy": "liyang.112",
                      "Content": "P2C_LB_CONFIG:\n  ALLOW_ALL: true\n  N: 3\n"},
    "LastVersion":   {"ID": 9130, "Version": 154, "IsRelease": True, "PublishedBy": "liyang.112",
                      "Content": "P2C_LB_CONFIG:\n  ALLOW_ALL: true\n  N: 3\n"},
    "NacosInstance": NACOS_INSTANCE, "Tags": ["p2c", "lb"],
}
NACOS_CONFIG_VERSION = {
    "ID": 9130, "NacosConfigID": 21, "Version": 154, "CreatedBy": "liyang.112",
    "Content": "P2C_LB_CONFIG:\n  ALLOW_ALL: true\n", "MD5": "abcdef1234",
    "IsRelease": True, "PublishedAt": "2026-07-06 21:02:48",
}
NACOS_DEPLOYMENT = {
    "ID": 8833, "CreatedBy": "liyang.112", "Status": "success",
    "NacosConfig": NACOS_CONFIG_ROW,
    "NacosConfigVersion": NACOS_CONFIG_VERSION,
    "Reviewer": ["daizhiyang.jesper"], "Comment": "灰度上线",
    "ChangeTicketID": 3370,
}
NACOS_REVIEWERS = ["wulei.wl", "xiaxiangning", "zhangyanpei"]
CHANGE_TEMPLATES = [
    {"ID": 3368, "Name": "Nacos 配置变更", "Description": "Nacos 配置发布"},
]
LANE_DELIVERIES = [
    {"ID": 110, "LaneID": 33, "Stage": "Finish", "Status": "Success",
     "CreatedBy": "liyang.112"},
]
LANE_PRODUCTS = [{"ID": 5, "Name": "maas", "Code": "maas"}]
LANE_INSTANCES = [
    {"ID": 24, "ProductID": 5, "Region": "cn-beijing-stg", "Level": "STG"},
    {"ID": 26, "ProductID": 5, "Region": "ap-southeast-1-stg", "Level": "STG"},
]
LANES = [
    {"ID": 33, "Name": "lane-diffa", "ProductID": 5, "ProductInstanceID": 24,
     "Status": "Active", "CreatedBy": "liyang.112"},
    {"ID": 34, "Name": "lane-diffb", "ProductID": 5, "ProductInstanceID": 24,
     "Status": "Active", "CreatedBy": "liyang.112"},
]
LANE_MODULES = [
    {"ID": 167, "Name": "ark-model-proxy", "ProductID": 5,
     "ImageGitRepo": "machinelearning/model-proxy", "SupportLane": True},
]
LANE_MODULE_DEPLOYS = [
    {"ID": 99, "LaneID": 33, "ModuleID": 167, "Status": "Succeeded",
     "Namespace": "lane-diffa"},
]
# Pod spec shaped like the real LiveObject: the business container is NOT
# named after the HelmRelease, and a traffic-proxy sidecar comes first.
LANE_POD_LIVE_OBJECT = """metadata:
  name: ark-model-proxy-66d8f5b9f5-7mnsj
  namespace: lane-diffa
spec:
  containers:
  - args:
    - proxy
    env:
    - name: META_PSM
      value: ark-model-proxy
    - name: TRAFFIC_PROXY_EGRESS_ADDRESS
      value: unix:/traffic-proxy/uds.sock
    image: registry/traffic-proxy:latest
    name: traffic-proxy
  - env:
    - name: CONF_ENV
      value: stg
    image: registry/ark-model-proxy:test
    name: ark-model-proxy-charts
  volumes:
  - name: kube-api-access-sd5lf
"""
LANE_MODULE_DEPLOY_DETAIL = {
    "ModuleDeploy": {
        "ID": 99, "LaneID": 33, "ModuleID": 167, "Status": "Succeeded",
        "Namespace": "lane-diffa", "ClusterID": "cckj929cfa0r3001mac8g",
        "HelmReleaseName": "ark-model-proxy",
        "ClusterName": "maas-control-cn-beijing-stg",
    },
    "Resources": [
        {"Kind": "ConfigMap", "Name": "ark-model-proxy-config",
         "Namespace": "lane-diffa", "Status": "Ready", "Pods": []},
        {"Kind": "Deployment", "Name": "ark-model-proxy",
         "Namespace": "lane-diffa", "Status": "Ready",
         "Pods": [{"Kind": "Pod", "Name": "ark-model-proxy-66d8f5b9f5-7mnsj",
                   "Namespace": "lane-diffa", "Status": "Ready",
                   "LiveObject": LANE_POD_LIVE_OBJECT}]},
    ],
}
LANE_POD_EVENTS = [
    {"Type": "Warning", "Reason": "Unhealthy", "Count": 8,
     "ObjectName": "ark-model-proxy-66d8f5b9f5-7mnsj",
     "Message": "Readiness probe failed: connection refused"},
]
LANE_ARTIFACTS = [
    {"ID": 177, "DeliveryID": 110, "ArtifactType": "Image", "Status": "Success",
     "ArtifactURLs": ["registry/ark-model-proxy:test"]},
]
LANE_DELIVERY_DEPLOYS = [
    {"ID": 116, "DeliveryID": 110, "ModuleID": 167, "Status": "Succeeded"},
]
LANE_HELM_DIFF = {
    "HelmRenderStatus": "Success",
    "HelmRenderProgress": "100%",
    "ResourceItems": [{"HelmReleaseName": "ark-model-proxy", "ModuleID": 167}],
}
INFERENCE_SERVICE = {
    "Id": "msrv-20260112162223-bnskp",
    "ServiceName": "press-mock-wxd",
    "Status": "Running", "Replicas": 259,
    "CardName": "Doubao-1.6",
    "ModelReference": {"FoundationModel": {"Name": "doubao-seed-1-6", "ModelVersion": "mock"}},
    "Protocol": "grpc_default", "ServiceType": "Dynamic",
    "InferenceConfigV2ID": "fmvicv2-20260722144857-ddnrs",
    "Labels": {"app": "press-mock-wxd"},
    "App": {
        "WorkerSets": [
            {"Name": "decode",
             "Image": "cr.example/maas/ark-mock-model-service:latest",
             "Entrypoint": "ark-mock-model-service vlm",
             "Envs": [{"Name": "MOCK_EP", "Value": "doubao-seed-1-6-250615"}]},
        ],
        "Labels": {},
    },
}
INFERENCE_SERVICE_2 = {**INFERENCE_SERVICE, "Id": "msrv-20260611213334-r2mbj",
                       "ServiceName": "duplex-sfcs-test", "Replicas": 6}
INFERENCE_LABEL_SERVICE = {
    **INFERENCE_SERVICE,
    "Id": "msrv-label-test",
    "ServiceName": "自动化勿动-label-test",
    "Labels": {
        "Values": {
            "support.account-type.ark/internal": "true",
            "support.foundation-model.ark/legacy_001": "true",
        },
    },
}
# Full template fixture returned by ListWholeInferenceConfigsV2. Container-level
# Env (singular) + EntryPoint (CamelCase) mirror the real MLOps schema.
WHOLE_INFERENCE_CONFIG = {
    "Id": "fmvicv2-20260722144857-ddnrs",
    "TemplateName": "seedance-2.0-pe",
    "Version": 2,
    "FoundationModelName": "doubao-seed-1-6",
    "FoundationModelVersion": "mock",
    "Application": {
        "Protocol": "http-acc",
        "WorkerSets": [
            {"Name": "decode",
             "Roles": [{"Name": "r-decode",
                        "Containers": [{"Name": "decode",
                                        "Image": "cr.example/maas/ark-mock-model-service:latest",
                                        "EntryPoint": "ark-mock-model-service vlm",
                                        "Env": [{"Name": "MOCK_EP",
                                                 "Value": "doubao-seed-1-6-250615"}]}]}]}
        ],
    },
}
PODS_ROLES = [
    {"Role": "r-encoder", "StatusStats": [{"Key": "Running", "Value": 20}],
     "Pods": [{"ObjectMeta": {"Name": "msrv-x-encoder-r-0", "Namespace": "ark-service",
                              "UID": "abc-1", "CreationTimestamp": 1781178890}}]},
    {"Role": "r-decoder", "StatusStats": [{"Key": "Running", "Value": 20}],
     "Pods": [{"ObjectMeta": {"Name": "msrv-x-decoder-r-0", "Namespace": "ark-service",
                              "UID": "abc-2", "CreationTimestamp": 1781178890}}]},
]
SERVICE_EVENTS = [
    {"UID": "670bfb20-2178-4ddb-ad71-49d0aa3be378",
     "StartTimestamp": 1782387587, "LastTimestamp": 1783343690,
     "Type": "Normal", "ObjectKind": "Pod", "ObjectName": "msrv-encoder-worker-0",
     "Reason": "BackOff", "Message": "Back-off pulling image", "Count": 12},
]
HPA_METRICS = [
    {"DisplayName": "engine_utilization", "FullName": "engine_utilization",
     "Type": "Percent", "Max": 100, "Min": 0},
    {"DisplayName": "engine_activity", "FullName": "maas_engine_activity",
     "Type": "Percent", "Max": 100, "Min": 0},
]
UPDATE_RECORDS = [
    {"Id": "6a2aa1f8fe857ce68103d667",
     "Request": {"FoundationModelName": "doubao-seed-1-6",
                 "FoundationModelVersion": "mock",
                 "InferenceConfigVersionV2Id": "fmvicv2-20260604172451-k88dl"}}
]
FOUNDATION_MODELS = [
    {"Name": "doubao-seed-audio-1-0", "DisplayName": "doubao-seed-audio-1-0",
     "Creator": "xuliyang.young", "ArkRegion": "cn-beijing", "CreatedAt": 1783343256},
    {"Name": "doubao-seed-1-6", "DisplayName": "doubao-seed-1-6",
     "Creator": "system", "ArkRegion": "cn-beijing", "CreatedAt": 1783343256},
]
FOUNDATION_GPU_TYPES = [
    {"ArkRegion": "cn-beijing", "Name": "NVIDIA-L20", "Cap": 454, "Alloc": 50},
    {"ArkRegion": "cn-beijing", "Name": "NVIDIA-H20-SXM5-96GB", "Cap": 300, "Alloc": 246},
]
FOUNDATION_FLAVORS = [
    {"Name": "910-HWC-16-TEST", "GPUSpecName": "NPU-A2-HWC-16", "GPUType": "NPU-A2-HWC",
     "GPUNum": 16, "VCPU": 240, "Memory": 2304, "ArkRegion": "cn-beijing"}
]
CLUSTERS = [
    {"Base": {"ClusterID": "cd77sv9bmsgqn3050u1b0",
              "ClusterName": "maas-stg-cn-3rd-y1-cn-neimenggu-1-gpu-cluster-01",
              "Region": "cn-3rd-y1-cn-neimenggu-1", "DCType": "3th",
              "AccountID": "2100339946", "AccountName": "ml-platform-stg"}}
]
RESOURCE_QUEUES = {
    "LocalQueues": [{"Id": "rq-20260205203457-h4pb7", "Name": "for-test",
                     "ClusterId": "cd4ndsphsd1p2tcel8a6g",
                     "ClusterName": "maas-gpu-cluster-03",
                     "PayloadType": "ep", "Region": "cn-beijing"}],
    "DcpQueues": [],
}
SFCS_WARMUP = [
    {"ModelTosBucket": "maas-efs-base-model-2100466578-seed-cn-beijing-multiaz",
     "ModelTosPath": "/maas_models/official/Doubao/doubao1.5-vision-pro-thinking-250428-final",
     "SfcsRegion": "cn-beijing", "SfcsInstanceName": "ark-stg-cn-beijing-default",
     "PinStatus": "Pinned", "WarmupStatus": "Success",
     "LatestWarmupTime": "2026-07-01 10:00:00"}
]
REGIONS = [{"ID": "cn-beijing", "Name": "cn-beijing"},
           {"ID": "cn-shanghai", "Name": "cn-shanghai"}]
CRONJOB_APPS = [
    {
        "ID": 4,
        "Name": "data.amltob.ops_cicd",
        "Description": "cicd 定时任务，元数据检查",
        "Owner": "qiuli.garden,daizhiyang.jesper,songruiguo",
        "Endpoints": [
            {
                "Host": "2605:340:cd50:f09:bff0:b15f:691d:d426",
                "Stage": "canary",
                "Timestamp": 1786680531,
                "SchedCount": 0,
                "IDCName": "boe",
            },
        ],
        "AllowIDC": "",
        "ShadowApp": "",
    },
]
VBH_LOGIN_RESPONSE = {
    "VkeClusterUnknown": False,
    "VkeClusterVbhUnSupported": False,
    "LoginMessage": "",
}
PRODUCTS = [{"ID": 5, "Name": "maas", "Description": "", "Owner": "daizhiyang.jesper",
             "Code": "maas", "ModuleCount": 308},
            {"ID": 16, "Name": "managed_agents", "Description": "agent",
             "Code": "managed_agents", "ModuleCount": 20, "Owner": "zouyang.233"}]
MODULES = [{"ID": 487, "Name": "ark-account-level-runtime-config",
            "ArgoCDAppName": "ark-account-level-runtime-config", "ProductID": 5}]
RELEASE_TRAINS = [{"ID": 238, "Name": "ARK release/20260630 版本发布",
                   "ChangeTemplateID": 3370, "CreatedBy": "daizhiyang.jesper"}]
DELIVERY_APPLIES = [{"ID": 13, "CreatedBy": "daizhiyang.jesper",
                     "Product": {"ID": 5, "Name": "maas"}}]
DELIVERY_EVENTS = [{"EventID": "5ded6d9a-6744-40be-9e47-6f0873836c4e",
                    "Timestamp": 1783344027294, "Status": "succeed",
                    "Operator": "liangbingxue", "Region": "cn-beijing",
                    "Product": "maas", "DeliveryID": 8836, "Module": "nacos",
                    "Result": "success"}]
INFRA_DELIVERIES = []
DELIVERIES = []
CONFIG_TEMPLATES = [{"Id": "6a21658933ee3dc33b0524a4", "Name": "seed-template",
                     "Application": {"Protocol": "http-acg"}}]
OFFICIAL_INFERENCE_CONFIGS = [
    {"Id": "fmvicv2-20260604172451-k88dl",
     "FoundationModelName": "doubao-seed-1-6",
     "FoundationModelVersion": "mock",
     "TemplateName": "seed-1-6-mock-press", "Version": 19,
     "Description": "压测模式-0604", "Status": "Active",
     "Application": {"Protocol": "http-acg"}, "Creator": "seedbot"},
]
CREATED_INFERENCE_CONFIG = {"Id": "fmvicv2-20260727230124-5n9xh"}
FED_CLUSTERS = [{"Id": "fcccq6it4l0k8ch8r53g6i0", "Name": "maas-dcp-stg",
                 "KubeAdmiralVersion": "v1.26.10-dcp-1.14.0",
                 "Status": {"Phase": "Running"}, "MemberClusters": []}]
ENGINE_IMAGES = [{"ID": "6a4ba9724eb77c857880e626",
                  "PushTime": 1783343159, "Region": "cn-beijing",
                  "RepoName": "vegrid-dev", "Tag": "1.0.0.1638.th27_cu128.71bb941",
                  "ImageURL": "maas-seed-cn-beijing.cr.volces.com/ml_maas_inference/vegrid-dev:1.0.0.1638.th27_cu128.71bb941"}]
GPU_STAT_SERIES = [{"ArkRegion": "cn-beijing", "Timestamp": 1783094700,
                    "GPUType": "所有卡型", "Cap": 2232, "Alloc": 377}]
SCHED_PRIORITIES = ["", "2", "3", "4", "7", "9", "10", "12"]
DELIVERY_APPLY_LIST = [{"ID": 13, "CreatedBy": "daizhiyang.jesper", "Product": {"ID": 5, "Name": "maas"}}]
SERVICE_ALERTS_RESP = {
    "Alerts": [],
    "Stat": {
        "LevelStats": [{"Label": "07-06 15:18(5m)", "Values": []}],
        "ModelStats": [], "KindStats": [], "SvcStats": [],
    }
}
EVENTS_RESP = {"Pagination": {"PageNum": 1, "PageSize": 50, "Total": 250},
               "Events": [{"Type": "op_log", "ID": "5bd6f4eb-33eb-4573-8559-e3298051eee7",
                           "Source": "data.amltob.ops_deploy",
                           "Module": "InferenceService-Ops", "Action": "update",
                           "Resource": "msrv-20260611213334-r2mbj",
                           "Timestamp": 1783344004511, "Message": "updated"}]}
SAVED_QUERIES_RESP = {"Items": []}
TLS_TOKEN_RESP = {"Token": "UGZJa0ZEUmY4eDRQelk2VEhjZ1NORmVGTzc4OEhBYlJuRFczbjkzMmQwST0=",
                  "DefaultProjectID": "5876cf33-2db4-4aa9-a0e6-44813c3fab85",
                  "DefaultTopicID": ""}
MAAS_API_RESULT = {
    "ResponseMetadata": {"Action": "GetInferenceServiceResourceConfig",
                         "Region": "cn-beijing",
                         "RequestId": "20260706211821DA689D357382936C6D5A",
                         "Service": "ark_stg", "Version": "2024-01-01"},
    "Result": {"Annotations": [{"Key": "grofed.volcengine.com/cluster-selector", "Value": "{}"}],
               "AppLabels": [], "FoundationModelName": "doubao-seed-1-6",
               "FoundationModelVersion": "mock",
               "MaasServiceId": "msrv-20260112162223-bnskp",
               "WorkerSetResourceInfos": [{"Name": "worker-0"}]}
}
DCP_MEMBER_CLUSTERS = {"MemberClusters": []}
DCP_GPU_STATS = {"Stats": [], "Ticks": [{"GPUType": "CPU-16XLARGE",
                                          "RQCap": 0, "RQAlloc": 0,
                                          "SubQCap": 0, "SubQAlloc": 0,
                                          "SubQueues": []}]}


# Route table: (method, path) -> callable(handler, parsed, qs, body) -> response
# The mock handler dispatches through this table plus a small set of dynamic
# regex routes for /model_inferences_services/{id}.
class Handler(http.server.BaseHTTPRequestHandler):
    last_requests = []

    # --- transport helpers -------------------------------------------------
    def log_message(self, *_):
        return

    def _send(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}

    def _capture(self, method, parsed, body=None):
        Handler.last_requests.append({
            "method": method, "path": parsed.path,
            "query": parsed.query, "raw_path": self.path,
            "body": body,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        })

    # --- routing -----------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        self._capture("GET", parsed)
        return self._route_get(parsed, qs)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        body = self._body()
        self._capture("POST", parsed, body=body)
        return self._route_post(parsed, body)

    def do_PATCH(self):
        parsed = urllib.parse.urlparse(self.path)
        body = self._body()
        self._capture("PATCH", parsed, body=body)
        return self._route_patch(parsed, body)

    # ---- GET routes -------------------------------------------------------
    def _route_get(self, parsed, qs):
        base = "/_sre/openapi/proxy/consul/api/v1"
        deploy = base + "/mlops_deploy"
        cicd = base + "/mlops_cicd"
        event = base + "/mlops_eventcenter"
        xcron = base + "/mlops_xcron"
        p = parsed.path

        # ---- 基础服务 CronJob ----
        if p == xcron + "/apps":
            return self._send({
                "Pagination": {
                    "PageNum": int(qs.get("page_num", ["1"])[0]),
                    "PageSize": int(qs.get("page_size", ["10"])[0]),
                    "Total": len(CRONJOB_APPS),
                },
                "Data": CRONJOB_APPS,
            })

        # ---- CICD tickets ----
        if p == cicd + "/product":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 100, "Total": len(PRODUCTS)},
                               "Products": PRODUCTS})
        if p == cicd + "/module":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 1000, "Total": len(MODULES)},
                               "Modules": MODULES, "_echo_product_id": qs.get("product_id", [""])[0]})
        if p == cicd + "/delivery":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 100, "Total": 0},
                               "Deliveries": DELIVERIES})
        if p == cicd + "/infrastructure_delivery":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 100, "Total": 0},
                               "InfrastructureDeploys": INFRA_DELIVERIES})
        if p == cicd + "/release_train":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 20, "Total": 1},
                               "ReleaseTrains": RELEASE_TRAINS})
        if p == cicd + "/delivery_apply":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 10, "Total": 1},
                               "DeliveryApplies": DELIVERY_APPLY_LIST})
        if p == cicd + "/change_template":
            return self._send({
                "Pagination": {"PageNum": 1, "PageSize": 10, "Total": 1},
                "ChangeTemplates": CHANGE_TEMPLATES,
            })
        if p == base + "/mlops_cicd_lane/list_product":
            return self._send({"TotalCount": len(LANE_PRODUCTS), "Products": LANE_PRODUCTS})

        # ---- Inference (specific paths first) ----
        if p == deploy + "/model_inferences_services/resource_stats/dcp_gpu_types":
            return self._send(DCP_GPU_STATS)
        if p == deploy + "/model_inferences_service_events":
            return self._send({"Events": SERVICE_EVENTS,
                               "_echo_service_id": qs.get("service_id", [""])[0]})
        if p == deploy + "/model_inferences_service_pods":
            return self._send({"Pods": PODS_ROLES,
                               "_echo_service_id": qs.get("service_id", [""])[0]})
        if p == deploy + "/model_inferences_service_hpa_metrics":
            return self._send({"Metrics": HPA_METRICS})
        if p == deploy + "/mr_inference_service_hpa_jobs":
            return self._send({"Jobs": []})
        if p == deploy + "/splitwise_models/inference_service_update_records":
            return self._send({"Pagination": {"PageNum": 0, "PageSize": 0, "Total": 1},
                               "Records": UPDATE_RECORDS,
                               "_echo_service_id": qs.get("service_id", [""])[0]})
        if p.startswith(deploy + "/model_inferences_services/"):
            svc_id = p.rsplit("/", 1)[-1]
            fixture = {"msrv-20260112162223-bnskp": INFERENCE_SERVICE,
                       "msrv-20260611213334-r2mbj": INFERENCE_SERVICE_2,
                       "msrv-label-test": INFERENCE_LABEL_SERVICE}.get(svc_id, INFERENCE_SERVICE)
            return self._send({"InferenceService": {**fixture, "Id": svc_id}})
        if p == deploy + "/model_inferences_services":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 10, "Total": 292},
                               "InferenceServices": [INFERENCE_SERVICE, INFERENCE_SERVICE_2],
                               "_echo_statuses": qs.get("statuses[]", []),
                               "_echo_model_name": qs.get("model_name", [""])[0]})

        # ---- Splitwise / DCP ----
        if p == deploy + "/fed_control_clusters":
            return self._send({"FedControlClusters": FED_CLUSTERS})
        if p == deploy + "/splitwise_models/dcp_member_clusters":
            return self._send({**DCP_MEMBER_CLUSTERS,
                               "_echo_dcp_id": qs.get("DcpControlClusterId", [""])[0]})
        if p == deploy + "/splitwise_models/inference_config_templates":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 200, "Total": 1},
                               "Configs": CONFIG_TEMPLATES})
        if p == deploy + "/splitwise_models/inference_configs_official":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 10, "Total": 1},
                               "Configs": OFFICIAL_INFERENCE_CONFIGS})

        # ---- CMDB ----
        if p == deploy + "/cmdb/regions":
            return self._send({"Regions": REGIONS,
                               "_echo_filter": qs.get("Filter", [""])[0]})
        if p == deploy + "/cmdb/clusters":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 200, "Total": len(CLUSTERS)},
                               "Clusters": CLUSTERS})
        if p == deploy + "/cmdb/resource_queues":
            return self._send(RESOURCE_QUEUES)
        if p == deploy + "/cmdb/sfcs_warmup":
            return self._send({"Items": SFCS_WARMUP,
                               "_echo_service_id": qs.get("service_id", [""])[0]})

        # ---- Foundation ----
        if p == deploy + "/foundation_models":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 1000, "Total": 222},
                               "FoundationModels": FOUNDATION_MODELS})
        if p == deploy + "/foundation_gpu_types":
            return self._send({"FoundationGPUTypes": FOUNDATION_GPU_TYPES})
        if p == deploy + "/foundation_ark_flavors":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 200, "Total": 187},
                               "Flavors": FOUNDATION_FLAVORS})

        # ---- Ancillary ----
        if p == deploy + "/inference_engine_images":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 200, "Total": 20100},
                               "Images": ENGINE_IMAGES})
        if p == deploy + "/gputype_stat_series":
            return self._send({"Series": GPU_STAT_SERIES})
        if p == deploy + "/list_scheduling_priority_options":
            return self._send({"SchedulingPriorities": SCHED_PRIORITIES})

        # ---- Event center ----
        if p == event + "/ark_service_alerts":
            return self._send({**SERVICE_ALERTS_RESP,
                               "_echo_service_ids": qs.get("service_ids[]", [])})
        if p == event + "/events":
            return self._send({**EVENTS_RESP,
                               "_echo_sources": qs.get("sources[]", []),
                               "_echo_modules": qs.get("modules[]", []),
                               "_echo_resources": qs.get("resources[]", [])})

        return self._send({"message": "not found", "path": p}, status=404)

    # ---- POST routes ------------------------------------------------------
    def _route_post(self, parsed, body):
        base = "/_sre/openapi/proxy/consul/api/v1"
        cicd = base + "/mlops_cicd"
        cicd_lane = base + "/mlops_cicd_lane"
        deploy = base + "/mlops_deploy"
        obs = base + "/mlops_observability"
        p = parsed.path
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

        # ---- Nacos ----
        if p == cicd + "/nacos/list_instance":
            return self._send({"Pagination": {"PageNum": body.get("PageNum", 1),
                                              "PageSize": body.get("PageSize", 100),
                                              "Total": len(NACOS_INSTANCES)},
                               "NacosInstances": NACOS_INSTANCES,
                               "_echo": body})
        if p == cicd + "/nacos/get_instance":
            return self._send({"NacosInstance": {**NACOS_INSTANCE,
                                                 "InstanceID": body.get("InstanceID")}})
        if p == cicd + "/nacos/list_namespace":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 1000, "Total": len(NACOS_NAMESPACES)},
                               "Namespaces": NACOS_NAMESPACES,
                               "_echo_instance_id": body.get("InstanceID")})
        if p == cicd + "/nacos/list_config":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 10, "Total": 1},
                               "NacosConfigs": [NACOS_CONFIG_ROW],
                               "_echo_filter": body.get("Filter", {})})
        if p == cicd + "/nacos/get_config":
            return self._send({"NacosConfig": {**NACOS_CONFIG_DETAIL,
                                               "ID": body.get("ID")}})
        if p == cicd + "/nacos/list_config_version":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 10, "Total": 154},
                               "NacosConfigVersions": [NACOS_CONFIG_VERSION],
                               "_echo_filter": body.get("Filter", {})})
        if p == cicd + "/nacos/list_config_deployment":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 100, "Total": 1},
                               "NacosConfigDeployments": [NACOS_DEPLOYMENT],
                               "_echo": body})
        if p == cicd + "/nacos/list_batch_deployment":
            return self._send({"Pagination": {"PageNum": 1, "PageSize": 10, "Total": 0},
                               "_echo": body})
        if p == cicd + "/nacos/get_deployment":
            return self._send({"NacosConfigDeployment": {**NACOS_DEPLOYMENT,
                                                         "ID": body.get("ID")}})
        if p == cicd + "/common/list_reviewers":
            return self._send({
                "Reviewers": NACOS_REVIEWERS,
                "SelfApproval": False,
            })
        if p == cicd + "/nacos/update_config":
            return self._send({"Result": True})
        if p == cicd + "/nacos/create_deployment":
            return self._send({"ID": 10066})
        if p == cicd + "/nacos/publish_config":
            return self._send({"Result": True})
        if p == cicd_lane + "/list_product_region_instance":
            return self._send({
                "TotalCount": len(LANE_INSTANCES),
                "ProductRegionInstances": LANE_INSTANCES,
                "_echo_product_code": body.get("ProductCode"),
            })
        if p == cicd_lane + "/list_lane":
            return self._send({
                "Pagination": {"PageNum": 1, "PageSize": 20, "Total": len(LANES)},
                "Lanes": LANES,
                "_echo_filter": body.get("Filter", {}),
            })
        if p == cicd_lane + "/get_lane":
            lane_id = body.get("ID")
            lane = next((item for item in LANES if item["ID"] == lane_id), None)
            return self._send({"Lane": lane})
        if p == cicd_lane + "/list_module":
            return self._send({
                "TotalCount": len(LANE_MODULES),
                "Modules": LANE_MODULES,
                "_echo_product_id": body.get("ProductID"),
            })
        if p == cicd_lane + "/list_module_deploy":
            deploys = LANE_MODULE_DEPLOYS
            deploy_filter = body.get("Filter") or {}
            if deploy_filter.get("ModuleID") is not None:
                deploys = [item for item in deploys
                           if item["ModuleID"] == deploy_filter["ModuleID"]]
            if deploy_filter.get("Statuses"):
                deploys = [item for item in deploys
                           if item["Status"] in deploy_filter["Statuses"]]
            return self._send({
                "Pagination": {"PageNum": 1, "PageSize": 20, "Total": len(deploys)},
                "ModuleDeploys": deploys,
                "_echo_filter": deploy_filter,
            })
        if p == cicd_lane + "/get_module_deploy":
            return self._send(LANE_MODULE_DEPLOY_DETAIL)
        if p == cicd_lane + "/get_pod_events":
            return self._send({"Events": LANE_POD_EVENTS,
                               "_echo_request": body})
        if p == cicd_lane + "/get_pod_logs":
            container = body.get("ContainerName") or "main"
            if container not in ("ark-model-proxy-charts", "traffic-proxy"):
                # Mirrors the real backend: it defaults to a container named
                # "main", which ark workloads do not have.
                return self._send(
                    "stream pod logs (%s/%s/%s): container %s is not valid for pod %s"
                    % (body.get("Namespace"), body.get("PodName"), container,
                       container, body.get("PodName")),
                    status=500,
                )
            return self._send({"LogContent": "log line from %s\n" % container,
                               "_echo_request": body})
        if p == cicd_lane + "/list_delivery":
            return self._send({
                "Pagination": {"PageNum": 1, "PageSize": 100, "Total": 1},
                "Deliveries": LANE_DELIVERIES,
            })
        if p == cicd_lane + "/get_delivery":
            return self._send({"Delivery": {**LANE_DELIVERIES[0],
                                             "ID": body.get("DeliveryID")}})
        if p == cicd_lane + "/list_delivery_artifact_by_delivery":
            return self._send({
                "TotalCount": len(LANE_ARTIFACTS),
                "DeliveryArtifacts": LANE_ARTIFACTS,
            })
        if p == cicd_lane + "/list_delivery_module_deploy_by_delivery":
            return self._send({
                "TotalCount": len(LANE_DELIVERY_DEPLOYS),
                "DeliveryModuleDeploys": LANE_DELIVERY_DEPLOYS,
            })
        if p == cicd_lane + "/list_helm_diff_by_delivery":
            return self._send(LANE_HELM_DIFF)
        if p == cicd_lane + "/create_delivery":
            return self._send({"ID": 1000 + int(body.get("LaneID", 0))})

        # ---- Delivery events (POST) ----
        if p == cicd + "/list_delivery_events":
            return self._send({"Pagination": {"PageNum": body.get("PageNum", 1),
                                              "PageSize": body.get("PageSize", 20),
                                              "Total": 220},
                               "DeliveryEvents": DELIVERY_EVENTS,
                               "_echo_filter": body.get("Filter", {})})

        # ---- Inference maas_api_proxy ----
        if p == deploy + "/maas_api_proxy/" or p == deploy + "/maas_api_proxy":
            action = qs.get("Action", [""])[0]
            if action == "ListWholeInferenceConfigsV2":
                filt = (body.get("Filter") or {}).get("Ids") or []
                items = [WHOLE_INFERENCE_CONFIG] if filt else []
                return self._send({
                    "ResponseMetadata": {"Action": action, "Version": "2024-01-01",
                                         "Service": "ark_stg", "Region": "cn-beijing",
                                         "RequestId": "test-req-id"},
                    "Result": {"Items": items, "_echo_filter_ids": filt},
                })
            return self._send({**MAAS_API_RESULT,
                               "_echo_action": action,
                               "_echo_version": qs.get("Version", [""])[0],
                               "_echo_body": body})
        if p == deploy + "/splitwise_models/inference_configs":
            return self._send({**CREATED_INFERENCE_CONFIG, "_echo_body": body})
        if p == deploy + "/splitwise_models/preview_update_inference_service":
            return self._send({"CurrentServiceResourceInfo": {},
                               "CandidateServiceResourceInfo": body})
        if p == deploy + "/splitwise_models/inference_services":
            return self._send({"MaasServiceId": body.get("MaasServiceId"),
                               "Updated": True})
        if p == deploy + "/vbh/get_or_create_vbh_login_message":
            return self._send({**VBH_LOGIN_RESPONSE, "_echo": body})

        # ---- Observability ----
        if p == obs + "/list_user_saved_queries":
            return self._send(SAVED_QUERIES_RESP)
        if p == obs + "/get_tls_sts_token":
            return self._send({**TLS_TOKEN_RESP, "_echo": body})

        return self._send({"message": "not found", "path": p}, status=404)

    def _route_patch(self, parsed, body):
        base = "/_sre/openapi/proxy/consul/api/v1/mlops_deploy"
        if (
            parsed.path.startswith(base + "/model_inferences_services/")
            and parsed.path.endswith("/labels")
        ):
            return self._send({
                "Updated": True,
                "Values": body.get("Values"),
                "BatchToOnline": body.get("BatchToOnline"),
            })
        return self._send({"message": "not found", "path": parsed.path}, status=404)


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------
class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)

    def setUp(self):
        Handler.last_requests = []

    def run_cli(self, *args, expect_ok=True, extra_env=None):
        env = os.environ.copy()
        env["MLOPS_STG_BASE_URL"] = self.base_url
        env["MLOPS_STG_AUTH_JSON"] = json.dumps({"X-Jwt-Token": "unit-test"})
        env.pop("MLOPS_ENV", None)
        env.pop("MLOPS_REGION", None)
        env.pop("MLOPS_STG_REGION", None)
        env.pop("MLOPS_PROD_REGION", None)
        env.pop("MLOPS_BASE_URL", None)
        env.pop("MLOPS_PROD_BASE_URL", None)
        if extra_env:
            for key, value in extra_env.items():
                if value is None:
                    env.pop(key, None)
                else:
                    env[key] = value
        proc = subprocess.run(
            [sys.executable, str(CLI), *args],
            env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        print("\nCOMMAND:", " ".join(args))
        print("STDOUT :", proc.stdout)
        if proc.stderr:
            print("STDERR :", proc.stderr)
        if expect_ok:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        if expect_ok:
            self.assertTrue(data.get("ok"), data)
        self.assertIn("data", data)
        self.assertIsNotNone(data["data"])
        return data

    def run_cli_error(self, *args, extra_env=None):
        env = os.environ.copy()
        env["MLOPS_STG_BASE_URL"] = self.base_url
        env["MLOPS_STG_AUTH_JSON"] = json.dumps({"X-Jwt-Token": "unit-test"})
        env.pop("MLOPS_ENV", None)
        env.pop("MLOPS_REGION", None)
        env.pop("MLOPS_STG_REGION", None)
        env.pop("MLOPS_PROD_REGION", None)
        env.pop("MLOPS_BASE_URL", None)
        env.pop("MLOPS_PROD_BASE_URL", None)
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            [sys.executable, str(CLI), *args],
            env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        print("\nCOMMAND:", " ".join(args))
        print("STDOUT :", proc.stdout)
        print("STDERR :", proc.stderr)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(proc.stdout.strip())
        return json.loads(proc.stderr)

    def _last(self, method, path):
        matches = [r for r in Handler.last_requests
                   if r["method"] == method and r["path"] == path]
        self.assertTrue(matches, "expected %s %s to be captured" % (method, path))
        return matches[-1]

    # ------------------------------------------------------------------
    # Auth and routing headers actually reach the request
    # ------------------------------------------------------------------
    def test_auth_headers_present_on_deploy_request(self):
        self.run_cli("list-foundation-gpu-types")
        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_gpu_types")
        # X-Jwt-Token comes from MLOPS_STG_AUTH_JSON overriding the bytedcli
        # flow. The fixed DevSRE routing headers must be added by the CLI.
        self.assertEqual(req["headers"].get("x-jwt-token"), "unit-test")
        self.assertEqual(req["headers"].get("x-devsre-app-alias"), "mlops")
        self.assertEqual(req["headers"].get("x-devsre-proxy-consul-psm"),
                         "data.amltob.ops_deploy")

    def test_cicd_requests_use_cicd_proxy_psm(self):
        self.run_cli("list-nacos-instances", "--product-code", "maas")
        req = self._last("POST",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_instance")
        self.assertEqual(req["headers"].get("x-jwt-token"), "unit-test")
        self.assertEqual(req["headers"].get("x-devsre-app-alias"), "mlops")
        self.assertEqual(req["headers"].get("x-devsre-proxy-consul-psm"),
                         "data.amltob.ops_cicd")

    def test_eventcenter_requests_use_eventcenter_proxy_psm(self):
        self.run_cli(
            "list-events",
            "--begin-at", "1780752066", "--end-at", "1783344066",
            "--page-size", "1",
        )
        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_eventcenter/events")
        self.assertEqual(req["headers"].get("x-jwt-token"), "unit-test")
        self.assertEqual(req["headers"].get("x-devsre-app-alias"), "mlops")
        self.assertEqual(req["headers"].get("x-devsre-proxy-consul-psm"),
                         "data.amltob.ops_eventcenter")

    def test_observability_requests_use_observability_proxy_psm(self):
        self.run_cli("list-saved-queries")
        req = self._last("POST",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_observability/list_user_saved_queries")
        self.assertEqual(req["headers"].get("x-jwt-token"), "unit-test")
        self.assertEqual(req["headers"].get("x-devsre-app-alias"), "mlops")
        self.assertEqual(req["headers"].get("x-devsre-proxy-consul-psm"),
                         "data.amltob.ops_observability")

    def test_xcron_requests_use_xcron_proxy_psm(self):
        result = self.run_cli("list-cronjob-apps", "--page-size", "10")
        self.assertEqual(result["data"]["Data"][0]["Name"], "data.amltob.ops_cicd")
        req = self._last(
            "GET",
            "/_sre/openapi/proxy/consul/api/v1/mlops_xcron/apps",
        )
        self.assertEqual(
            req["headers"].get("x-devsre-proxy-consul-psm"),
            "data.amltob.ops_xcron",
        )

    def test_prod_env_uses_prod_base_url_override(self):
        result = self.run_cli(
            "list-foundation-gpu-types", "--env", "prod",
            extra_env={"MLOPS_PROD_BASE_URL": self.base_url},
        )
        self.assertTrue(result["url"].startswith(self.base_url + "/_sre/openapi/"))
        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_gpu_types")
        self.assertEqual(req["headers"].get("x-jwt-token"), "unit-test")

    def test_prod_env_from_env_var_uses_prod_base_url_override(self):
        result = self.run_cli(
            "list-foundation-gpu-types",
            extra_env={"MLOPS_ENV": "prod", "MLOPS_PROD_BASE_URL": self.base_url},
        )
        self.assertTrue(result["url"].startswith(self.base_url + "/_sre/openapi/"))

    # ------------------------------------------------------------------
    # X-MLOps-Region multi-region support
    # ------------------------------------------------------------------
    def test_region_header_absent_by_default(self):
        # Without --mlops-region and without MLOPS_STG_REGION env, the CLI
        # must NOT send the X-MLOps-Region header — that keeps the old
        # cn-beijing-only behavior for callers who haven't opted in.
        self.run_cli("list-foundation-gpu-types")
        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_gpu_types")
        self.assertNotIn("x-mlops-region", req["headers"])

    def test_region_flag_sets_header(self):
        self.run_cli("list-foundation-gpu-types", "--mlops-region", "ap-southeast-1")
        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_gpu_types")
        self.assertEqual(req["headers"].get("x-mlops-region"), "ap-southeast-1")

    def test_region_env_var_sets_header_on_cicd_path(self):
        # Env-var fallback works on any command regardless of DevSRE proxy PSM.
        self.run_cli(
            "list-nacos-instances", "--product-code", "maas",
            extra_env={"MLOPS_STG_REGION": "ap-southeast-1"},
        )
        req = self._last("POST",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_instance")
        self.assertEqual(req["headers"].get("x-mlops-region"), "ap-southeast-1")
        # Region header composes with, not replaces, the proxy PSM header.
        self.assertEqual(req["headers"].get("x-devsre-proxy-consul-psm"),
                         "data.amltob.ops_cicd")

    def test_region_flag_overrides_env_var(self):
        self.run_cli(
            "list-foundation-gpu-types",
            "--mlops-region", "ap-southeast-1",
            extra_env={"MLOPS_STG_REGION": "cn-beijing"},
        )
        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/foundation_gpu_types")
        self.assertEqual(req["headers"].get("x-mlops-region"), "ap-southeast-1")

    # ------------------------------------------------------------------
    # Nacos
    # ------------------------------------------------------------------
    def test_nacos_instance_lifecycle(self):
        result = self.run_cli("list-nacos-instances", "--product-code", "maas")
        self.assertEqual(result["data"]["NacosInstances"][0]["InstanceID"],
                         "nctgj1oqh22vvfr2jqrr0")
        req = self._last("POST",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_instance")
        self.assertEqual(req["body"]["ProductCode"], "maas")
        self.assertEqual(req["body"]["PageNum"], 1)

        detail = self.run_cli("get-nacos-instance", "--instance-id", "nctgj1oqh22vvfr2jqrr0")
        self.assertEqual(detail["data"]["NacosInstance"]["InstanceID"],
                         "nctgj1oqh22vvfr2jqrr0")
        self.assertEqual(detail["data"]["NacosInstance"]["Region"], "cn-beijing")

    def test_nacos_namespace_and_config_flow(self):
        ns = self.run_cli("list-nacos-namespaces",
                          "--instance-id", "nctgj1oqh22vvfr2jqrr0",
                          "--page-size", "500")
        names = [x["NamespaceName"] for x in ns["data"]["Namespaces"]]
        self.assertIn("ml-maas-api-proxy", names)
        req = self._last("POST",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_namespace")
        self.assertEqual(req["body"]["InstanceID"], "nctgj1oqh22vvfr2jqrr0")
        self.assertEqual(req["body"]["PageSize"], 500)

        cfgs = self.run_cli("list-nacos-configs",
                            "--instance-id", "nctgj1oqh22vvfr2jqrr0",
                            "--namespace-name", "ml-maas-api-proxy",
                            "--group", "ml-maas-api-proxy",
                            "--data-id", "lb_config")
        self.assertEqual(cfgs["data"]["NacosConfigs"][0]["DataID"], "lb_config")
        req = self._last("POST",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config")
        self.assertEqual(req["body"]["Filter"]["DataID"], "lb_config")
        self.assertEqual(req["body"]["Filter"]["Group"], "ml-maas-api-proxy")

        detail = self.run_cli("get-nacos-config", "--id", "21")
        self.assertEqual(detail["data"]["NacosConfig"]["ID"], 21)
        self.assertTrue(detail["data"]["NacosConfig"]["OnlineVersion"]["IsRelease"])
        self.assertEqual(detail["data"]["NacosConfig"]["OnlineVersion"]["Version"], 154)

    def test_nacos_versions_and_deployments(self):
        versions = self.run_cli(
            "list-nacos-config-versions",
            "--instance-id", "nctgj1oqh22vvfr2jqrr0",
            "--data-id", "lb_config",
            "--group", "ml-maas-api-proxy",
            "--namespace-name", "ml-maas-api-proxy",
            "--page-size", "5",
        )
        self.assertEqual(versions["data"]["NacosConfigVersions"][0]["Version"], 154)
        self.assertEqual(versions["data"]["Pagination"]["Total"], 154)

        deployments = self.run_cli(
            "list-nacos-config-deployments",
            "--created-by", "liyang.112",
            "--status", "accepted",
            "--status", "reviewing",
            "--without-instance-id",
        )
        self.assertEqual(deployments["data"]["NacosConfigDeployments"][0]["ID"], 8833)
        req = self._last("POST",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_config_deployment")
        self.assertEqual(req["body"]["Filter"]["CreatedBy"], "liyang.112")
        self.assertEqual(req["body"]["Filter"]["Status"], ["accepted", "reviewing"])
        self.assertTrue(req["body"].get("WithoutInstanceID"))

        batch = self.run_cli("list-nacos-batch-deployments",
                             "--instance-id", "nctgj1oqh22vvfr2jqrr0")
        self.assertEqual(batch["data"]["Pagination"]["Total"], 0)

        d = self.run_cli("get-nacos-deployment", "--id", "8833")
        self.assertEqual(d["data"]["NacosConfigDeployment"]["ID"], 8833)
        self.assertEqual(d["data"]["NacosConfigDeployment"]["Status"], "success")
        self.assertEqual(d["data"]["NacosConfigDeployment"]["NacosConfig"]["DataID"],
                         "lb_config")

    def test_nacos_reviewers_and_cicd_reference_lists(self):
        reviewers = self.run_cli(
            "list-nacos-reviewers",
            "--nacos-config-id", "21",
        )
        self.assertEqual(reviewers["data"]["Reviewers"][0], "wulei.wl")
        self.assertFalse(reviewers["data"]["SelfApproval"])
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/common/list_reviewers",
        )
        self.assertEqual(req["body"], {"NacosConfigID": 21, "type": "nacos"})

        templates = self.run_cli("list-change-templates", "--page-size", "10000")
        self.assertEqual(templates["data"]["ChangeTemplates"][0]["ID"], 3368)
        req = self._last(
            "GET",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/change_template",
        )
        query = urllib.parse.parse_qs(req["query"])
        self.assertEqual(query["page_size"], ["10000"])
        self.assertEqual(query["_lc"], ["cn"])

        lanes = self.run_cli(
            "list-lane-deliveries",
            "--lane-id", "33",
            "--status", "reviewing",
            "--created-by", "liyang.112",
        )
        self.assertEqual(lanes["data"]["Deliveries"][0]["ID"], 110)
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery",
        )
        self.assertEqual(req["body"]["Filter"]["LaneID"], 33)
        self.assertEqual(req["body"]["Filter"]["Statuses"], ["reviewing"])
        self.assertEqual(req["body"]["Filter"]["CreatedBy"], "liyang.112")
        self.assertEqual(
            req["headers"].get("x-devsre-proxy-consul-psm"),
            "data.amltob.ops_cicd_lane",
        )

    def test_lane_pod_debugging(self):
        """GetModuleDeploy -> pod name -> logs/events, the debug chain."""
        detail = self.run_cli("get-lane-module-deploy", "--module-deploy-id", "99")
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["data"]["ModuleDeploy"]["ClusterID"],
                         "cckj929cfa0r3001mac8g")
        pods = [pod for resource in detail["data"]["Resources"]
                for pod in resource.get("Pods") or []]
        self.assertEqual(pods[0]["Name"], "ark-model-proxy-66d8f5b9f5-7mnsj")
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_module_deploy",
        )
        self.assertEqual(req["body"]["ModuleDeployID"], 99)
        self.assertEqual(
            req["headers"].get("x-devsre-proxy-consul-psm"),
            "data.amltob.ops_cicd_lane",
        )

        # --module-deploy-id alone resolves lane/cluster/namespace + container.
        logs = self.run_cli(
            "get-lane-pod-logs",
            "--module-deploy-id", "99",
            "--pod-name", "ark-model-proxy-66d8f5b9f5-7mnsj",
            "--limit", "20",
        )
        self.assertTrue(logs["ok"])
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_pod_logs",
        )
        self.assertEqual(req["body"]["LaneID"], 33)
        self.assertEqual(req["body"]["ClusterID"], "cckj929cfa0r3001mac8g")
        self.assertEqual(req["body"]["Namespace"], "lane-diffa")
        self.assertEqual(req["body"]["Limit"], 20)
        # Sidecar skipped; backend default "main" would have 500'd.
        self.assertEqual(req["body"]["ContainerName"], "ark-model-proxy-charts")

        explicit = self.run_cli(
            "get-lane-pod-logs",
            "--module-deploy-id", "99",
            "--pod-name", "ark-model-proxy-66d8f5b9f5-7mnsj",
            "--container-name", "traffic-proxy",
        )
        self.assertTrue(explicit["ok"])
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_pod_logs",
        )
        self.assertEqual(req["body"]["ContainerName"], "traffic-proxy")

        events = self.run_cli(
            "get-lane-pod-events",
            "--module-deploy-id", "99",
            "--pod-name", "ark-model-proxy-66d8f5b9f5-7mnsj",
            "--limit", "5",
        )
        self.assertEqual(events["data"]["Events"][0]["Reason"], "Unhealthy")
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_pod_events",
        )
        self.assertEqual(req["body"]["Namespace"], "lane-diffa")
        self.assertEqual(req["body"]["Limit"], 5)

    def test_lane_pod_container_extraction(self):
        """Indentation-aware YAML walk: env entries must not be mistaken
        for containers, and sidecars are skipped."""
        spec = importlib.util.spec_from_file_location("mlops_stg_cli_under_test",
                                                      str(CLI))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        names = module._yaml_pod_container_names(LANE_POD_LIVE_OBJECT)
        self.assertEqual(names, ["traffic-proxy", "ark-model-proxy-charts"])
        self.assertNotIn("META_PSM", names)
        self.assertNotIn("kube-api-access-sd5lf", names)
        self.assertEqual(module._yaml_pod_container_names("metadata:\n  name: x\n"), [])

    def test_lane_pod_requires_resolution_source(self):
        result = self.run_cli_error(
            "get-lane-pod-logs",
            "--pod-name", "ark-model-proxy-66d8f5b9f5-7mnsj",
        )
        self.assertFalse(result["ok"])
        self.assertIn("--module-deploy-id", result["error"])

    def test_lane_deploy_and_module_filters(self):
        deploys = self.run_cli(
            "list-lane-delivery-deploys",
            "--delivery-id", "110",
            "--status", "Failed",
        )
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/"
            "list_delivery_module_deploy_by_delivery",
        )
        self.assertEqual(req["body"]["DeliveryID"], 110)
        self.assertEqual(req["body"]["Filter"]["Statuses"], ["Failed"])
        self.assertTrue(deploys["ok"])

        # No filter flags -> no Filter key at all (unchanged legacy payload).
        self.run_cli("list-lane-delivery-deploys", "--delivery-id", "110")
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/"
            "list_delivery_module_deploy_by_delivery",
        )
        self.assertNotIn("Filter", req["body"])

        matched = self.run_cli(
            "list-lane-module-deploys", "--lane-id", "33", "--module-id", "167",
        )
        self.assertEqual(len(matched["data"]["ModuleDeploys"]), 1)
        missing = self.run_cli(
            "list-lane-module-deploys", "--lane-id", "33", "--module-id", "999",
        )
        self.assertEqual(missing["data"]["ModuleDeploys"], [])
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module_deploy",
        )
        self.assertEqual(req["body"]["Filter"]["ModuleID"], 999)

    def test_lane_catalog_and_filters(self):
        products = self.run_cli("list-lane-products")
        self.assertEqual(products["data"]["Products"][0]["Code"], "maas")

        instances = self.run_cli(
            "list-lane-product-instances",
            "--product-code", "maas",
        )
        self.assertEqual(instances["data"]["ProductRegionInstances"][1]["Region"],
                         "ap-southeast-1-stg")
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/"
            "list_product_region_instance",
        )
        self.assertEqual(req["body"], {"ProductCode": "maas"})

        lanes = self.run_cli(
            "list-lanes",
            "--product-id", "5",
            "--product-instance-id", "24",
            "--status", "Active",
            "--name", "diff",
            "--created-by", "liyang.112",
        )
        self.assertEqual(lanes["data"]["Lanes"][0]["ID"], 33)
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_lane",
        )
        self.assertEqual(req["body"]["Filter"], {
            "ProductID": 5,
            "ProductInstanceID": 24,
            "Statuses": ["Active"],
            "Name": "diff",
            "CreatedBy": "liyang.112",
        })

        detail = self.run_cli("get-lane", "--lane-id", "33")
        self.assertEqual(detail["data"]["Lane"]["Name"], "lane-diffa")

        modules = self.run_cli("list-lane-modules", "--product-id", "5")
        self.assertTrue(modules["data"]["Modules"][0]["SupportLane"])

        deploys = self.run_cli("list-lane-module-deploys", "--lane-id", "33")
        self.assertEqual(deploys["data"]["ModuleDeploys"][0]["Status"], "Succeeded")
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module_deploy",
        )
        self.assertEqual(req["body"]["Filter"], {"LaneID": 33})

    def test_lane_delivery_observation_endpoints(self):
        detail = self.run_cli("get-lane-delivery", "--delivery-id", "110")
        self.assertEqual(detail["data"]["Delivery"]["Stage"], "Finish")

        artifacts = self.run_cli(
            "list-lane-delivery-artifacts",
            "--delivery-id", "110",
        )
        self.assertEqual(
            artifacts["data"]["DeliveryArtifacts"][0]["ArtifactType"],
            "Image",
        )

        deploys = self.run_cli(
            "list-lane-delivery-deploys",
            "--delivery-id", "110",
        )
        self.assertEqual(
            deploys["data"]["DeliveryModuleDeploys"][0]["Status"],
            "Succeeded",
        )

        helm_diff = self.run_cli("list-lane-helm-diffs", "--delivery-id", "110")
        self.assertEqual(helm_diff["data"]["HelmRenderProgress"], "100%")

    def test_multi_lane_delivery_rejects_more_than_ten(self):
        args = ["create-multi-lane-deliveries"]
        for lane_id in range(1, 12):
            args.extend(["--lane-id", str(lane_id)])
        args.extend([
            "--module-json",
            '{"ModuleID":167,"DeployType":3,"GitRef":"main"}',
        ])
        error = self.run_cli_error(*args)
        self.assertIn("at most 10 lanes", error["error"])
        self.assertEqual(Handler.last_requests, [])

    @unittest.skipUnless(
        WRITE_TESTS_ENABLED,
        "默认跳过写接口；设置 MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1 后仅对本地 mock 执行",
    )
    def test_create_lane_delivery_structured_payload(self):
        module = {
            "ModuleID": 167,
            "DeployType": 3,
            "GitRepo": "machinelearning/model-proxy",
            "GitRef": "feat/diffy-egress-replay",
            "ReleaseCommit": "",
            "ChartGitRef": "master",
        }
        result = self.run_cli(
            "create-lane-delivery",
            "--product-id", "5",
            "--lane-id", "33",
            "--product-instance-id", "24",
            "--description", "本地 mock 发布",
            "--module-json", json.dumps(module),
        )
        self.assertEqual(result["data"]["ID"], 1033)
        self.assertIn("write_notice", result)
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/create_delivery",
        )
        self.assertEqual(req["body"]["DeployMode"], "ALL")
        self.assertTrue(req["body"]["StageAutoNext"])
        self.assertEqual(req["body"]["ModulesToDelivery"], [module])

    @unittest.skipUnless(
        WRITE_TESTS_ENABLED,
        "默认跳过写接口；设置 MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1 后仅对本地 mock 执行",
    )
    def test_create_multi_lane_deliveries_prefetches_then_writes(self):
        result = self.run_cli(
            "create-multi-lane-deliveries",
            "--lane-id", "33",
            "--lane-id", "34",
            "--description", "双泳道本地 mock 发布",
            "--module-json", '{"ModuleID":167,"DeployType":3,"GitRef":"main"}',
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["RequestedLaneCount"], 2)
        self.assertEqual(
            [item["LaneID"] for item in result["data"]["Results"]],
            [33, 34],
        )
        lane_requests = [
            item for item in Handler.last_requests
            if item["path"].endswith("/get_lane")
        ]
        create_requests = [
            item for item in Handler.last_requests
            if item["path"].endswith("/create_delivery")
        ]
        self.assertEqual([item["body"]["ID"] for item in lane_requests], [33, 34])
        self.assertEqual(
            [item["body"]["LaneID"] for item in create_requests],
            [33, 34],
        )
        self.assertTrue(all(
            item["body"]["ProductInstanceID"] == 24
            for item in create_requests
        ))

    def test_stg_write_rejects_prod_base_url_override(self):
        err = self.run_cli_error(
            "create-inference-config",
            "--env", "stg",
            "--base-url", "https://mlops.bytedance.net",
            "--payload-json", "{}",
        )
        self.assertIn("refuses the prod/online host", err["error"])
        self.assertEqual(Handler.last_requests, [])

    def test_switch_inference_template_env_requires_mutation(self):
        err = self.run_cli_error(
            "switch-inference-template-env",
            "--service-id", "msrv-20260112162223-bnskp",
        )
        self.assertIn("requires at least one template mutation", err["error"])
        self.assertEqual(Handler.last_requests, [])

    def test_sensitive_values_are_redacted(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mlops_cli_redact", str(CLI))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        value = {
            "changes": {
                "set_env": [
                    {"Name": "API_KEY_LIST", "Value": "new-key", "old": "old-key"},
                    {"Name": "LOG_LEVEL", "Value": "info"},
                ],
            },
            "access_token": "token-value",
        }
        redacted = mod._redact_sensitive(value)
        self.assertEqual(redacted["access_token"], "***REDACTED***")
        self.assertEqual(
            redacted["changes"]["set_env"][0]["Value"],
            "***REDACTED***",
        )
        self.assertEqual(redacted["changes"]["set_env"][1]["Value"], "info")

    def test_report_uses_nacos_flow_and_redacts_content(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mlops_report_builder",
            str(REPORT_BUILDER),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        counts = mod.collections.Counter({
            (
                "POST",
                "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/update_config",
            ): 1,
        })
        profile = mod._diagram_profile(counts, mod.collections.Counter())
        self.assertEqual(profile["flow_title"], "Nacos 配置保存与发布链路")
        redacted = mod._redact({
            "NacosConfigVersion": {
                "Content": "password: plaintext",
                "Type": "yaml",
            },
        })
        self.assertEqual(
            redacted["NacosConfigVersion"]["Content"],
            "***REDACTED***",
        )

    def test_report_recognizes_inference_label_update_flow(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mlops_report_builder_labels",
            str(REPORT_BUILDER),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        label_path = (
            "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/"
            "model_inferences_services/msrv-label-test/labels"
        )
        counts = mod.collections.Counter({("PATCH", label_path): 1})
        profile = mod._diagram_profile(counts, mod.collections.Counter())
        self.assertEqual(
            profile["flow_title"],
            "推理服务标签到服务发现标签的更新链路",
        )
        self.assertEqual(mod._business_name(label_path), "更新推理服务标签")
        self.assertTrue(mod._is_write_path(label_path))

    def test_report_recognizes_lane_delivery_and_redacts_resolved_values(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mlops_report_builder_lane",
            str(REPORT_BUILDER),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        lane_base = "/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/"
        counts = mod.collections.Counter({
            ("POST", lane_base + "create_delivery"): 1,
            ("POST", lane_base + "get_delivery"): 2,
        })
        profile = mod._diagram_profile(counts, mod.collections.Counter())
        self.assertEqual(profile["flow_title"], "多泳道发布与状态观测链路")
        self.assertEqual(
            mod._business_name(lane_base + "create_delivery"),
            "创建泳道发布单",
        )
        self.assertTrue(mod._is_write_path(lane_base + "create_delivery"))
        redacted = mod._redact({
            "ResolvedValues": "INNER_SK: secret-value\nNACOS_PASSWORD: pass",
        })
        self.assertEqual(redacted["ResolvedValues"], "***REDACTED***")

    def test_report_recognizes_base_service_vbh_flow(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "mlops_report_builder_vbh",
            str(REPORT_BUILDER),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        base = "/_sre/openapi/proxy/consul/api/v1"
        counts = mod.collections.Counter({
            ("GET", base + "/mlops_xcron/apps"): 1,
            ("GET", base + "/mlops_deploy/cmdb/regions"): 7,
            ("GET", base + "/mlops_deploy/cmdb/clusters"): 3,
            (
                "POST",
                base + "/mlops_deploy/vbh/get_or_create_vbh_login_message",
            ): 1,
        })
        profile = mod._diagram_profile(
            counts,
            mod.collections.Counter({
                "/toolbox/arkvbh": 11,
                "/toolbox/cronjob": 1,
            }),
        )
        self.assertEqual(profile["flow_title"], "基础服务与方舟堡垒机登录链路")
        self.assertIn(("查询登录信息", "get_or_create_vbh_login_message"),
                      profile["flow_nodes"])
        self.assertEqual(
            mod._business_name(base + "/mlops_xcron/apps"),
            "CronJob 应用目录",
        )
        self.assertTrue(
            mod._is_write_path(
                base + "/mlops_deploy/vbh/get_or_create_vbh_login_message"
            )
        )

    def test_non_idempotent_create_does_not_retry(self):
        import argparse
        import importlib.util
        spec = importlib.util.spec_from_file_location("mlops_cli_retry", str(CLI))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod._MLOPS_ENV = "stg"
        args = argparse.Namespace(
            base_url=self.base_url,
            payload_json="{}",
            payload_file=None,
            refresh_auth=False,
        )
        failure = {
            "ok": False,
            "status": 500,
            "url": self.base_url,
            "data": "invalid character '<'",
        }
        with mock.patch.object(mod, "_request", return_value=failure) as request:
            result = mod.cmd_create_inference_config(args)
        self.assertFalse(result["ok"])
        request.assert_called_once()

    @unittest.skipUnless(
        WRITE_TESTS_ENABLED,
        "默认跳过写接口；设置 MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1 后仅对本地 mock 执行",
    )
    def test_nacos_write_commands_against_local_mock(self):
        updated = self.run_cli(
            "update-nacos-config",
            "--payload-json",
            json.dumps({
                "NacosConfigID": 21,
                "Description": "",
                "Tags": ["maas-proxy-v3"],
                "NacosConfigVersion": {
                    "Content": "key: value\n",
                    "Type": "yaml",
                },
            }),
        )
        self.assertTrue(updated["data"]["Result"])

        created = self.run_cli(
            "create-nacos-deployment",
            "--nacos-config-id", "21",
            "--reviewer", "wulei.wl",
            "--reviewer", "xiaxiangning",
            "--comment", "测试发布",
        )
        self.assertEqual(created["data"]["ID"], 10066)

        published = self.run_cli(
            "publish-nacos-config",
            "--deployment-id", "10066",
            "--status", "accepted",
        )
        self.assertTrue(published["data"]["Result"])
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/publish_config",
        )
        self.assertEqual(req["body"], {
            "NacosDeploymentID": 10066,
            "Status": "accepted",
        })

    # ------------------------------------------------------------------
    # Delivery / CICD
    # ------------------------------------------------------------------
    def test_cicd_products_and_modules(self):
        products = self.run_cli("list-products")
        codes = [p["Code"] for p in products["data"]["Products"]]
        self.assertIn("maas", codes)
        self.assertIn("managed_agents", codes)

        modules = self.run_cli("list-modules", "--product-id", "5")
        self.assertEqual(modules["data"]["Modules"][0]["Name"],
                         "ark-account-level-runtime-config")
        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/module")
        self.assertIn("product_id=5", req["query"])

    def test_cicd_deliveries_and_release_train(self):
        d = self.run_cli("list-deliveries", "--status", "Running",
                         "--created-by", "liyang.112")
        self.assertEqual(d["data"]["Pagination"]["Total"], 0)
        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/delivery")
        self.assertIn("status%5B%5D=Running", req["query"])
        self.assertIn("created_by=liyang.112", req["query"])

        infra = self.run_cli("list-infrastructure-deliveries",
                             "--status", "Running", "--created-by", "liyang.112")
        self.assertEqual(infra["data"]["InfrastructureDeploys"], [])

        rt = self.run_cli("list-release-trains", "--status", "Running", "--lc", "cn")
        self.assertEqual(rt["data"]["ReleaseTrains"][0]["ID"], 238)
        self.assertIn("release/20260630", rt["data"]["ReleaseTrains"][0]["Name"])

        apply_list = self.run_cli("list-delivery-applies", "--page-size", "5", "--lc", "cn")
        self.assertEqual(apply_list["data"]["DeliveryApplies"][0]["ID"], 13)

    def test_cicd_delivery_events(self):
        events = self.run_cli(
            "list-delivery-events",
            "--start-time", "1783257698", "--end-time", "1783344098",
            "--product", "maas", "--page-size", "20",
        )
        self.assertEqual(events["data"]["DeliveryEvents"][0]["Status"], "succeed")
        self.assertEqual(events["data"]["DeliveryEvents"][0]["Product"], "maas")
        req = self._last("POST",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/list_delivery_events")
        self.assertEqual(req["body"]["Filter"]["StartTime"], 1783257698)
        self.assertEqual(req["body"]["Filter"]["Product"], "maas")

    # ------------------------------------------------------------------
    # Inference services
    # ------------------------------------------------------------------
    def test_inference_service_list_and_detail(self):
        svcs = self.run_cli(
            "list-inference-services",
            "--fuzzy-service-name", "press",
            "--statuses", "Running", "--statuses", "Abnormal",
            "--service-ids", "msrv-20260722160309-bqrzp",
            "--model-name", "doubao-seed-1-6",
        )
        self.assertEqual(svcs["data"]["Pagination"]["Total"], 292)
        self.assertEqual(len(svcs["data"]["InferenceServices"]), 2)
        self.assertEqual(svcs["data"]["InferenceServices"][0]["Id"],
                         "msrv-20260112162223-bnskp")

        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services")
        parsed = urllib.parse.parse_qs(req["query"])
        self.assertEqual(parsed.get("statuses[]"), ["Running", "Abnormal"])
        self.assertEqual(parsed.get("service_ids[]"), ["msrv-20260722160309-bqrzp"])
        self.assertEqual(parsed.get("model_name"), ["doubao-seed-1-6"])

        detail = self.run_cli("get-inference-service",
                              "--service-id", "msrv-20260112162223-bnskp")
        self.assertEqual(detail["data"]["InferenceService"]["ServiceName"],
                         "press-mock-wxd")
        self.assertEqual(detail["data"]["InferenceService"]["Status"], "Running")

    def test_update_inference_service_labels_requires_input_and_stg(self):
        missing = self.run_cli_error(
            "update-inference-service-labels",
            "--service-id", "msrv-label-test",
        )
        self.assertIn("requires --payload-json/--payload-file", missing["error"])
        self.assertEqual(Handler.last_requests, [])

        prod = self.run_cli_error(
            "update-inference-service-labels",
            "--env", "prod",
            "--service-id", "msrv-label-test",
            "--set-label", "support.scene.ark/ordinary=true",
            extra_env={"MLOPS_PROD_BASE_URL": self.base_url},
        )
        self.assertIn("only supported in stg", prod["error"])
        self.assertEqual(Handler.last_requests, [])

    @unittest.skipUnless(
        WRITE_TESTS_ENABLED,
        "默认跳过写接口；设置 MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1 后仅对本地 mock 执行",
    )
    def test_update_inference_service_labels_incremental_merge(self):
        result = self.run_cli(
            "update-inference-service-labels",
            "--service-id", "msrv-label-test",
            "--set-label", "support.scene.ark/ordinary=true",
            "--foundation-model-label", "doubao-seed-1-8=251128",
            "--remove-label", "support.foundation-model.ark/legacy_001",
            "--batch-to-online",
        )
        self.assertTrue(result["data"]["Updated"])
        self.assertIn("write_notice", result)
        req = self._last(
            "PATCH",
            "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/"
            "model_inferences_services/msrv-label-test/labels",
        )
        self.assertEqual(req["body"]["BatchToOnline"], True)
        self.assertEqual(
            req["body"]["Values"]["support.account-type.ark/internal"],
            "true",
        )
        self.assertEqual(
            req["body"]["Values"][
                "support.foundation-model.ark/doubao-seed-1-8_251128"
            ],
            "true",
        )
        self.assertNotIn(
            "support.foundation-model.ark/legacy_001",
            req["body"]["Values"],
        )

    @unittest.skipUnless(
        WRITE_TESTS_ENABLED,
        "默认跳过写接口；设置 MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1 后仅对本地 mock 执行",
    )
    def test_update_inference_service_labels_raw_payload(self):
        payload = {
            "Values": {
                "support.foundation-model.ark/doubao-seed-1-8_251128": "true",
            },
            "BatchToOnline": False,
        }
        result = self.run_cli(
            "update-inference-service-labels",
            "--service-id", "msrv-label-test",
            "--payload-json", json.dumps(payload),
        )
        self.assertTrue(result["data"]["Updated"])
        req = self._last(
            "PATCH",
            "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/"
            "model_inferences_services/msrv-label-test/labels",
        )
        self.assertEqual(req["body"], payload)

    def test_inference_service_subresources(self):
        events = self.run_cli("list-inference-service-events",
                              "--service-id", "msrv-20260112162223-bnskp")
        self.assertEqual(events["data"]["Events"][0]["Reason"], "BackOff")

        pods = self.run_cli("list-inference-service-pods",
                            "--service-id", "msrv-20260112162223-bnskp")
        roles = [p["Role"] for p in pods["data"]["Pods"]]
        self.assertIn("r-encoder", roles)
        self.assertIn("r-decoder", roles)

        metrics = self.run_cli("list-inference-hpa-metrics")
        names = [m["FullName"] for m in metrics["data"]["Metrics"]]
        self.assertIn("engine_utilization", names)
        self.assertIn("maas_engine_activity", names)

        hpa = self.run_cli("list-inference-hpa-jobs")
        self.assertEqual(hpa["data"]["Jobs"], [])

        stats = self.run_cli("get-inference-dcp-gpu-stats",
                             "--gpu-types", "CPU-16XLARGE", "--gpu-types", "NVIDIA-L20")
        self.assertEqual(stats["data"]["Ticks"][0]["GPUType"], "CPU-16XLARGE")

        rec = self.run_cli("list-inference-update-records",
                           "--service-id", "msrv-20260112162223-bnskp")
        self.assertEqual(rec["data"]["Records"][0]["Request"]["FoundationModelName"],
                         "doubao-seed-1-6")

    def test_call_maas_api(self):
        result = self.run_cli(
            "call-maas-api",
            "--action", "GetInferenceServiceResourceConfig",
            "--payload-json",
            json.dumps({"FoundationModelName": "doubao-seed-1-6",
                        "FoundationModelVersion": "mock",
                        "MaasServiceId": "msrv-20260112162223-bnskp"}),
        )
        self.assertEqual(result["data"]["Result"]["FoundationModelName"],
                         "doubao-seed-1-6")
        self.assertEqual(result["data"]["ResponseMetadata"]["Action"],
                         "GetInferenceServiceResourceConfig")
        req = self._last("POST",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/maas_api_proxy/")
        parsed = urllib.parse.parse_qs(req["query"])
        self.assertEqual(parsed.get("Action"), ["GetInferenceServiceResourceConfig"])
        self.assertEqual(parsed.get("Version"), ["2024-01-01"])
        self.assertEqual(req["body"]["MaasServiceId"], "msrv-20260112162223-bnskp")

    def test_prod_rejects_unknown_maas_action(self):
        result = self.run_cli_error(
            "call-maas-api",
            "--env", "prod",
            "--action", "RestartInferenceService",
            "--payload-json", "{}",
            extra_env={"MLOPS_PROD_BASE_URL": self.base_url},
        )
        self.assertIn("only supported in stg", result["error"])
        self.assertEqual(Handler.last_requests, [])

    # ------------------------------------------------------------------
    # Splitwise / DCP
    # ------------------------------------------------------------------
    def test_splitwise_and_dcp(self):
        fed = self.run_cli("list-fed-control-clusters")
        self.assertEqual(fed["data"]["FedControlClusters"][0]["Name"], "maas-dcp-stg")
        self.assertEqual(fed["data"]["FedControlClusters"][0]["Status"]["Phase"], "Running")

        members = self.run_cli("list-dcp-member-clusters",
                               "--dcp-control-cluster-id", "fcccq6it4l0k8ch8r53g6i0")
        self.assertEqual(members["data"]["MemberClusters"], [])

        tmpls = self.run_cli("list-inference-config-templates")
        self.assertEqual(tmpls["data"]["Configs"][0]["Name"], "seed-template")

        cfg = self.run_cli("list-official-inference-configs",
                           "--model-name", "doubao-seed-1-6",
                           "--model-version", "mock",
                           "--fuzzy-template-name", "seed-1-6-mock-press",
                           "--context-model-name", "seed-1-8",
                           "--context-model-version", "seedance-omni-pe-260128",
                           "--service-id", "msrv-20260722160309-bqrzp",
                           "--service-type", "online",
                           "--edit")
        self.assertEqual(cfg["data"]["Configs"][0]["Id"],
                         "fmvicv2-20260604172451-k88dl")
        self.assertEqual(cfg["data"]["Configs"][0]["Status"], "Active")
        req = self._last("GET",
                         "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs_official")
        parsed = urllib.parse.parse_qs(req["query"])
        self.assertEqual(parsed.get("modelName"), ["seed-1-8"])
        self.assertEqual(parsed.get("modelVersion"), ["seedance-omni-pe-260128"])
        self.assertEqual(parsed.get("serviceId"), ["msrv-20260722160309-bqrzp"])
        self.assertEqual(parsed.get("serviceType"), ["online"])
        self.assertEqual(parsed.get("edit"), ["true"])

    def test_create_inference_config_requires_payload_and_stg(self):
        missing_payload = self.run_cli_error("create-inference-config")
        self.assertIn("requires --payload-json or --payload-file", missing_payload["error"])
        self.assertEqual(Handler.last_requests, [])

        prod = self.run_cli_error(
            "create-inference-config",
            "--env", "prod",
            "--payload-json", "{}",
            extra_env={"MLOPS_PROD_BASE_URL": self.base_url},
        )
        self.assertIn("only supported in stg", prod["error"])
        self.assertEqual(Handler.last_requests, [])

    @unittest.skipUnless(
        WRITE_TESTS_ENABLED,
        "默认跳过写接口；设置 MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1 后仅对本地 mock 执行",
    )
    def test_splitwise_write_commands_against_local_mock(self):
        config_payload = {
            "FoundationModelName": "seed-1-8",
            "FoundationModelVersion": "seedance-omni-pe-260128",
            "TemplateName": "unit-test-template",
            "Application": {"Protocol": "http-acc", "WorkerSets": []},
        }
        created = self.run_cli(
            "create-inference-config",
            "--payload-json", json.dumps(config_payload),
        )
        self.assertEqual(created["data"]["Id"], "fmvicv2-20260727230124-5n9xh")
        self.assertIn("write_notice", created)

        update_payload = {
            "MaasServiceId": "msrv-unit-test",
            "Region": "cn-beijing",
            "InferenceConfigVersionV2Id": created["data"]["Id"],
            "WorkerSetResourceInfos": [],
        }
        preview = self.run_cli(
            "preview-update-inference-service",
            "--payload-json", json.dumps(update_payload),
        )
        self.assertEqual(
            preview["data"]["CandidateServiceResourceInfo"]["MaasServiceId"],
            "msrv-unit-test",
        )

        updated = self.run_cli(
            "update-inference-service",
            "--payload-json", json.dumps(update_payload),
        )
        self.assertTrue(updated["data"]["Updated"])
        self.assertEqual(updated["data"]["MaasServiceId"], "msrv-unit-test")

    @unittest.skipUnless(
        WRITE_TESTS_ENABLED,
        "默认跳过写接口；设置 MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1 后仅对本地 mock 执行",
    )
    def test_switch_inference_template_env_create_and_preview(self):
        # 不带 --apply 时仍创建模板版本并预览，但不更新推理服务。
        result = self.run_cli(
            "switch-inference-template-env",
            "--service-id", "msrv-20260112162223-bnskp",
            "--set-env", "MOCK_VLM=true",
            "--set-env", "MOCK_EP=doubao-seed-1-6-250615",  # unchanged → should be no-op
            "--unset-env", "GHOST_VAR",                     # not present → recorded as missing
        )
        data = result["data"]
        self.assertFalse(data["applied"])
        trace = data["trace"]
        stages = [s["stage"] for s in trace["step"]]
        self.assertEqual(
            stages,
            ["get-inference-service",
             "GetInferenceServiceResourceConfig",
             "ListWholeInferenceConfigsV2",
             "create-inference-config",
             "preview-update-inference-service"],
        )
        # Verify the mutations were recorded correctly
        changes = trace["changes"]
        adds = [c for c in changes["set_env"] if c["op"] == "add"]
        no_ops = [c for c in changes["set_env"] if c["op"] == "unchanged"]
        self.assertEqual([c["Name"] for c in adds], ["MOCK_VLM"])
        self.assertEqual([c["Name"] for c in no_ops], ["MOCK_EP"])
        self.assertEqual(changes["unset_env_missing"], ["GHOST_VAR"])
        # Verify the create-inference-config request body has MOCK_VLM in the
        # target Container's Env (singular).
        create_reqs = [r for r in Handler.last_requests
                       if r["method"] == "POST"
                       and r["path"].endswith("/splitwise_models/inference_configs")]
        self.assertEqual(len(create_reqs), 1)
        create_body = create_reqs[0]["body"]
        envs = (create_body["Application"]["WorkerSets"][0]
                       ["Roles"][0]["Containers"][0]["Env"])
        env_map = {e["Name"]: e["Value"] for e in envs}
        self.assertEqual(env_map.get("MOCK_VLM"), "true")
        self.assertEqual(env_map.get("MOCK_EP"), "doubao-seed-1-6-250615")
        # No update-inference-service POST should have happened
        apply_reqs = [r for r in Handler.last_requests
                      if r["method"] == "POST"
                      and r["path"].endswith("/splitwise_models/inference_services")]
        self.assertEqual(len(apply_reqs), 0,
                         "create-and-preview mode must NOT call update-inference-service")
        # Preview payload switches template id, keeps MaasServiceId, drops Usage
        preview_reqs = [r for r in Handler.last_requests
                        if r["method"] == "POST"
                        and r["path"].endswith("/splitwise_models/preview_update_inference_service")]
        self.assertEqual(len(preview_reqs), 1)
        prev_body = preview_reqs[0]["body"]
        self.assertEqual(prev_body["MaasServiceId"], "msrv-20260112162223-bnskp")
        self.assertEqual(prev_body["InferenceConfigVersionV2Id"],
                         "fmvicv2-20260727230124-5n9xh")   # from CREATED_INFERENCE_CONFIG mock
        self.assertEqual(prev_body["FoundationModelName"], "doubao-seed-1-6")
        self.assertEqual(prev_body["DeployType"], "Dynamic")
        self.assertNotIn("Usage", prev_body)

    @unittest.skipUnless(
        WRITE_TESTS_ENABLED,
        "默认跳过写接口；设置 MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1 后仅对本地 mock 执行",
    )
    def test_switch_inference_template_env_apply(self):
        # --apply should also POST to /splitwise_models/inference_services
        result = self.run_cli(
            "switch-inference-template-env",
            "--service-id", "msrv-20260112162223-bnskp",
            "--set-env", "MOCK_VLM=true",
            "--apply",
        )
        self.assertTrue(result["data"]["applied"])
        apply_reqs = [r for r in Handler.last_requests
                      if r["method"] == "POST"
                      and r["path"].endswith("/splitwise_models/inference_services")]
        self.assertEqual(len(apply_reqs), 1)
        self.assertEqual(apply_reqs[0]["body"]["InferenceConfigVersionV2Id"],
                         "fmvicv2-20260727230124-5n9xh")

    def test_switch_inference_template_env_prod_rejected(self):
        # Write path must reject prod/online
        err = self.run_cli_error(
            "switch-inference-template-env",
            "--env", "prod",
            "--service-id", "msrv-20260112162223-bnskp",
            "--set-env", "MOCK_VLM=true",
            extra_env={"MLOPS_PROD_BASE_URL": self.base_url},
        )
        self.assertIn("only supported in stg", err["error"])
        self.assertEqual(Handler.last_requests, [])

    # ------------------------------------------------------------------
    # CMDB
    # ------------------------------------------------------------------
    def test_cmdb_endpoints(self):
        regions = self.run_cli("list-regions",
                               "--filter-json", '{"ArkControlRegion":"cn-beijing"}')
        ids = [r["ID"] for r in regions["data"]["Regions"]]
        self.assertIn("cn-beijing", ids)
        self.assertIn("cn-shanghai", ids)

        clusters = self.run_cli("list-clusters", "--page-size", "200")
        self.assertEqual(clusters["data"]["Clusters"][0]["Base"]["ClusterName"],
                         "maas-stg-cn-3rd-y1-cn-neimenggu-1-gpu-cluster-01")
        req = self._last(
            "GET",
            "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/cmdb/clusters",
        )
        query = urllib.parse.parse_qs(req["query"])
        self.assertEqual(query["page_number"], ["1"])
        self.assertEqual(query["page_size"], ["200"])
        self.assertNotIn("page_num", query)

        queues = self.run_cli("list-resource-queues")
        self.assertEqual(queues["data"]["LocalQueues"][0]["Name"], "for-test")

        warmup = self.run_cli("list-sfcs-warmup",
                              "--service-id", "msrv-20260112162223-bnskp")
        self.assertEqual(warmup["data"]["Items"][0]["WarmupStatus"], "Success")

    # ------------------------------------------------------------------
    # Foundation
    # ------------------------------------------------------------------
    def test_foundation_catalog(self):
        models = self.run_cli("list-foundation-models", "--lc", "cn")
        names = [m["Name"] for m in models["data"]["FoundationModels"]]
        self.assertIn("doubao-seed-1-6", names)
        self.assertIn("doubao-seed-audio-1-0", names)

        gpus = self.run_cli("list-foundation-gpu-types")
        gpu_names = [g["Name"] for g in gpus["data"]["FoundationGPUTypes"]]
        self.assertIn("NVIDIA-L20", gpu_names)
        self.assertIn("NVIDIA-H20-SXM5-96GB", gpu_names)

        flavors = self.run_cli("list-foundation-flavors")
        self.assertEqual(flavors["data"]["Flavors"][0]["GPUSpecName"], "NPU-A2-HWC-16")

    # ------------------------------------------------------------------
    # Ancillary deploy
    # ------------------------------------------------------------------
    def test_ancillary_deploy(self):
        imgs = self.run_cli("list-inference-engine-images",
                            "--region", "cn-beijing",
                            "--fuzzy-image-url", "vegrid")
        self.assertEqual(imgs["data"]["Images"][0]["RepoName"], "vegrid-dev")

        series = self.run_cli("get-gputype-stat-series")
        self.assertEqual(series["data"]["Series"][0]["GPUType"], "所有卡型")
        self.assertGreater(series["data"]["Series"][0]["Cap"], 0)

        pri = self.run_cli("list-scheduling-priorities")
        self.assertIn("10", pri["data"]["SchedulingPriorities"])
        self.assertGreater(len(pri["data"]["SchedulingPriorities"]), 1)

    # ------------------------------------------------------------------
    # Event center
    # ------------------------------------------------------------------
    def test_event_center(self):
        alerts = self.run_cli(
            "list-service-alerts",
            "--service-ids", "msrv-20260112162223-bnskp",
            "--begin-at", "1783322302", "--end-at", "1783343902",
        )
        self.assertIn("Alerts", alerts["data"])
        self.assertIn("Stat", alerts["data"])
        self.assertEqual(alerts["data"]["_echo_service_ids"],
                         ["msrv-20260112162223-bnskp"])

        events = self.run_cli(
            "list-events",
            "--sources", "data.amltob.ops_deploy",
            "--modules", "InferenceService-Ops",
            "--resources", "msrv-20260611213334-r2mbj",
            "--begin-at", "1780752066", "--end-at", "1783344066",
        )
        self.assertEqual(events["data"]["Events"][0]["Type"], "op_log")
        self.assertEqual(events["data"]["Events"][0]["Module"],
                         "InferenceService-Ops")
        self.assertEqual(events["data"]["_echo_sources"], ["data.amltob.ops_deploy"])

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    def test_observability(self):
        saved = self.run_cli("list-saved-queries")
        self.assertEqual(saved["data"]["Items"], [])

        tok = self.run_cli("get-tls-sts-token",
                           "--sts-role", "StsRoleForTLSRead",
                           "--account-id", "2100339946",
                           "--region", "cn-beijing")
        self.assertTrue(tok["data"]["Token"])
        self.assertEqual(tok["data"]["DefaultProjectID"],
                         "5876cf33-2db4-4aa9-a0e6-44813c3fab85")
        self.assertEqual(tok["data"]["_echo"]["StsRole"], "StsRoleForTLSRead")

    # ------------------------------------------------------------------
    # build-url
    # ------------------------------------------------------------------
    def test_build_url_templates(self):
        r = self.run_cli(
            "build-url", "nacos-list",
            "--instance-id", "nctgj1oqh22vvfr2jqrr0", "--product", "maas", "--lc", "cn",
        )
        self.assertIn("/cicd/nacos?_lc=cn&instance_id=nctgj1oqh22vvfr2jqrr0&product=maas",
                      r["data"]["url"])

        r = self.run_cli(
            "build-url", "nacos-history",
            "--instance-id", "nctgj1oqh22vvfr2jqrr0",
            "--namespace", "ml-maas-api-proxy",
            "--data-id", "lb_config",
        )
        self.assertIn("/cicd/nacos/config_history?product=maas&instance_id=nctgj1oqh22vvfr2jqrr0"
                      "&namespace=ml-maas-api-proxy&data_id=lb_config",
                      r["data"]["url"])

        r = self.run_cli("build-url", "inference-detail",
                         "--service-id", "msrv-20260112162223-bnskp")
        self.assertIn("/maas/inferencesservice/msrv-20260112162223-bnskp/dcp-detail",
                      r["data"]["url"])

        r = self.run_cli("build-url", "splitwise")
        self.assertIn("/maas/serviceops/splitwise/config?_lc=cn",
                      r["data"]["url"])

        r = self.run_cli("build-url", "release-trains")
        self.assertIn("/cicd/releasetrains?_lc=cn", r["data"]["url"])

        r = self.run_cli("build-url", "cronjob")
        self.assertIn("/toolbox/cronjob?_lc=cn", r["data"]["url"])

        r = self.run_cli("build-url", "arkvbh")
        self.assertIn("/toolbox/arkvbh?_lc=cn", r["data"]["url"])

    def test_build_url_prod_env_uses_online_domain(self):
        r = self.run_cli("build-url", "inference-detail",
                         "--service-id", "msrv-x", "--env", "prod")
        self.assertEqual(r["data"]["env"], "prod")
        self.assertEqual(r["data"]["base_url"], "https://mlops.bytedance.net")
        self.assertEqual(r["data"]["url"],
                         "https://mlops.bytedance.net/maas/inferencesservice/msrv-x/dcp-detail?_lc=cn")

    def test_build_url_lc_from_region(self):
        r = self.run_cli("build-url", "inference-detail",
                         "--service-id", "msrv-20260629165948-n6jth",
                         "--mlops-region", "ap-southeast-1")
        self.assertIn("/maas/inferencesservice/msrv-20260629165948-n6jth/dcp-detail?_lc=bp",
                      r["data"]["url"])

        r = self.run_cli("build-url", "inference-detail",
                         "--service-id", "msrv-20260112162223-bnskp",
                         "--mlops-region", "cn-beijing")
        self.assertIn("/maas/inferencesservice/msrv-20260112162223-bnskp/dcp-detail?_lc=cn",
                      r["data"]["url"])

        r = self.run_cli("build-url", "inference-detail",
                         "--service-id", "msrv-x", "--mlops-region", "ap-southeast-1",
                         "--lc", "cn")
        self.assertIn("_lc=cn", r["data"]["url"])

        r = self.run_cli("build-url", "inference-detail", "--service-id", "msrv-x")
        self.assertIn("_lc=cn", r["data"]["url"])

    # ------------------------------------------------------------------
    # verify timeline-coverage
    # ------------------------------------------------------------------
    def test_verify_timeline_coverage(self):
        events = [
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_instance"},
            {"type": "NETWORK_REQUEST", "method": "GET",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services?page_num=1"},
            {"type": "NETWORK_REQUEST", "method": "GET",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/msrv-abc"},
            {"type": "NETWORK_REQUEST", "method": "PATCH",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_deploy/model_inferences_services/msrv-abc/labels"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/preview_update_inference_service"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_services"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_deploy/splitwise_models/inference_configs"},
            {"type": "NETWORK_REQUEST", "method": "GET",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd/change_template"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd/common/list_reviewers"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/update_config"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/create_deployment"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/publish_config"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery"},
            {"type": "NETWORK_REQUEST", "method": "GET",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_product"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_product_region_instance"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_lane"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_lane"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_module_deploy"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/get_delivery"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_artifact_by_delivery"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_delivery_module_deploy_by_delivery"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/list_helm_diff_by_delivery"},
            {"type": "NETWORK_REQUEST", "method": "POST",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_cicd_lane/create_delivery"},
            {"type": "NETWORK_REQUEST", "method": "GET",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/whoami"},
            {"type": "NETWORK_REQUEST", "method": "GET",
             "url": "https://mlops-stg.bytedance.net/_sre/openapi/proxy/consul/api/v1/mlops_deploy/does_not_exist"},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump(events, tf)
            timeline_path = tf.name
        self.addCleanup(lambda: os.unlink(timeline_path))

        result = self.run_cli("verify", "timeline-coverage", timeline_path, expect_ok=False)
        d = result["data"]
        self.assertEqual(d["total"], 26)
        self.assertEqual(d["covered_count"], 24)
        self.assertEqual(d["excluded_count"], 1)
        self.assertEqual(d["missing_count"], 1)

        covered_paths = {(c["method"], c["path"]) for c in d["covered"]}
        self.assertIn(("POST",
                       "/_sre/openapi/proxy/consul/api/v1/mlops_cicd/nacos/list_instance"),
                      covered_paths)
        # Subresource-vs-{id} ordering matters — /model_inferences_services/msrv-abc
        # must resolve to get-inference-service (NOT to a subresource route).
        for c in d["covered"]:
            if c["path"].endswith("/model_inferences_services/msrv-abc"):
                self.assertEqual(c["label"], "get-inference-service")
            if c["path"].endswith("/model_inferences_services/msrv-abc/labels"):
                self.assertEqual(c["label"], "update-inference-service-labels")
        excluded_paths = {(e["method"], e["path"]) for e in d["excluded_by_user_scope"]}
        self.assertIn(("GET", "/_sre/openapi/whoami"), excluded_paths)
        missing_paths = {(m["method"], m["path"]) for m in d["missing"]}
        self.assertIn(("GET",
                       "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/does_not_exist"),
                      missing_paths)

    def test_toolbox_recording_coverage(self):
        events = [
            {
                "type": "NETWORK_REQUEST",
                "method": "GET",
                "url": (
                    "https://mlops-stg.bytedance.net/_sre/openapi/proxy/"
                    "consul/api/v1/mlops_xcron/apps?page_num=1&page_size=10"
                ),
            },
            {
                "type": "NETWORK_REQUEST",
                "method": "GET",
                "url": (
                    "https://mlops-stg.bytedance.net/_sre/openapi/proxy/"
                    "consul/api/v1/mlops_deploy/cmdb/regions"
                ),
            },
            {
                "type": "NETWORK_REQUEST",
                "method": "GET",
                "url": (
                    "https://mlops-stg.bytedance.net/_sre/openapi/proxy/"
                    "consul/api/v1/mlops_deploy/cmdb/clusters"
                ),
            },
            {
                "type": "NETWORK_REQUEST",
                "method": "POST",
                "url": (
                    "https://mlops-stg.bytedance.net/_sre/openapi/proxy/"
                    "consul/api/v1/mlops_deploy/vbh/"
                    "get_or_create_vbh_login_message"
                ),
            },
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump(events, tf)
            timeline_path = tf.name
        self.addCleanup(lambda: os.unlink(timeline_path))

        result = self.run_cli(
            "verify",
            "timeline-coverage",
            timeline_path,
            expect_ok=False,
        )
        data = result["data"]
        self.assertEqual(data["total"], 4)
        self.assertEqual(data["covered_count"], 4)
        self.assertEqual(data["missing_count"], 0)
        labels = {item["label"] for item in data["covered"]}
        self.assertIn("list-cronjob-apps", labels)
        self.assertIn("get-or-create-vbh-login-message", labels)

    def test_vbh_write_command_requires_stg_and_cluster_fields(self):
        missing = self.run_cli_error("get-or-create-vbh-login-message")
        self.assertIn("requires", missing["error"])
        self.assertEqual(Handler.last_requests, [])

        prod = self.run_cli_error(
            "get-or-create-vbh-login-message",
            "--env", "prod",
            "--vke-cluster-region", "cn-beijing",
            "--vke-cluster-name", "maas-control-cn-beijing-stg",
            extra_env={"MLOPS_PROD_BASE_URL": self.base_url},
        )
        self.assertIn("only supported in stg", prod["error"])
        self.assertEqual(Handler.last_requests, [])

    @unittest.skipUnless(
        WRITE_TESTS_ENABLED,
        "默认跳过写接口；设置 MLOPS_STG_SKILL_ENABLE_WRITE_TESTS=1 后仅对本地 mock 执行",
    )
    def test_vbh_write_command_against_local_mock(self):
        result = self.run_cli(
            "get-or-create-vbh-login-message",
            "--vke-cluster-region", "cn-beijing",
            "--vke-cluster-name", "maas-control-cn-beijing-stg",
        )
        self.assertFalse(result["data"]["VkeClusterUnknown"])
        self.assertFalse(result["data"]["VkeClusterVbhUnSupported"])
        self.assertIn("LoginMessage", result["data"])
        req = self._last(
            "POST",
            "/_sre/openapi/proxy/consul/api/v1/mlops_deploy/vbh/"
            "get_or_create_vbh_login_message",
        )
        self.assertEqual(req["body"], {
            "VkeClusterRegion": "cn-beijing",
            "RequestType": "VkeCluster",
            "ProductName": "ark",
            "VkeClusterName": "maas-control-cn-beijing-stg",
        })

    # ------------------------------------------------------------------
    # Every business command from ENDPOINTS is registered in argparse
    # ------------------------------------------------------------------
    def test_every_business_command_registered(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mlops_cli", str(CLI))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        parser = mod.build_parser()
        actions = [a for a in parser._actions if isinstance(a, type(parser._actions[0]))]
        # Subparsers action is the one whose choices is a dict of parsers.
        subparsers = None
        for a in parser._actions:
            if hasattr(a, "choices") and isinstance(a.choices, dict) and "verify" in a.choices:
                subparsers = a
                break
        self.assertIsNotNone(subparsers, "no top-level subparsers action found")
        registered = set(subparsers.choices.keys())
        for name in mod.ENDPOINTS.keys():
            self.assertIn(name, registered, "%s missing from CLI" % name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
