import json
import shlex
from . import register_tool
from ..config import config

# 有状态 Mock 集群
MOCK_CLUSTER = {
    "pods": {
        "payment-svc-abc": {"status": "Running", "restarts": 5},
        "payment-svc-def": {"status": "Running", "restarts": 1},
        "user-svc-ghi": {"status": "Running", "restarts": 0},
        "user-svc-jkl": {"status": "CrashLoopBackOff", "restarts": 12},
        "order-svc-mno": {"status": "Running", "restarts": 2},
    },
    "deployments": {
        "payment-service": {"replicas": 2},
        "user-service": {"replicas": 2},
        "order-service": {"replicas": 1}
    },
    "services": {
        "payment-service": {"type": "ClusterIP", "port": 8080},
        "user-service": {"type": "ClusterIP", "port": 8081},
        "order-service": {"type": "ClusterIP", "port": 8082}
    },
    "logs_db": {
        "payment-svc-abc": [
            "[2025-06-01 09:15:32] ERROR timeout connecting to database",
            "[2025-06-01 09:16:01] WARN retry attempt 1 failed",
            "[2025-06-01 09:16:30] ERROR database connection pool exhausted"
        ],
        "payment-svc-def": [
            "[2025-06-01 09:20:00] INFO health check passed"
        ],
        "user-svc-ghi": [
            "[2025-06-01 08:00:00] INFO user login successful"
        ],
        "user-svc-jkl": [
            "[2025-06-01 07:59:59] FATAL out of memory",
            "[2025-06-01 08:00:00] ERROR container terminated"
        ],
        "order-svc-mno": []
    }
}


# ==================== kubectl_exec 工具 ====================
@register_tool(
    name="kubectl_exec",
    description="执行 kubectl 命令，用于管理 Kubernetes 集群，支持 get pods、logs、scale deployment 等操作。",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "完整的 kubectl 命令，如 'kubectl get pods'"}
        },
        "required": ["command"]
    }
)
def kubectl_exec(command: str) -> str:
    if config.env == "real":
        import subprocess
        # 安全修复：shell=False + shlex 解析，消除命令注入风险
        args = shlex.split(command.strip())
        result = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=30)
        return result.stdout if result.returncode == 0 else result.stderr
    else:
        cmd_parts = command.strip().split()
        if len(cmd_parts) == 0:
            return "命令为空"

        # get pods
        if "get" in cmd_parts and "pods" in cmd_parts:
            lines = [
                f"{pod}   {info['status']}   {info['restarts']}"
                for pod, info in MOCK_CLUSTER["pods"].items()
            ]
            return "NAME   STATUS   RESTARTS\n" + "\n".join(lines)

        # logs <pod-name>
        elif "logs" in cmd_parts:
            pod = cmd_parts[-1]
            # 1. 精确匹配
            if pod in MOCK_CLUSTER["logs_db"]:
                logs = MOCK_CLUSTER["logs_db"][pod]
            else:
                # 2. 模糊匹配：找包含该关键词的第一个 Pod
                matched_pods = [p for p in MOCK_CLUSTER["logs_db"] if pod in p]
                if matched_pods:
                    logs = MOCK_CLUSTER["logs_db"][matched_pods[0]]
                else:
                    logs = []
            return "\\\\n".join(logs) if logs else "没有日志"

        # scale deployment <name> --replicas=N
        elif "scale" in cmd_parts:
            try:
                deploy_idx = cmd_parts.index("deployment")
                deploy_name = cmd_parts[deploy_idx + 1]
                replicas_part = [p for p in cmd_parts if p.startswith("--replicas=")][0]
                replicas = int(replicas_part.split("=")[1])
                if deploy_name in MOCK_CLUSTER["deployments"]:
                    MOCK_CLUSTER["deployments"][deploy_name]["replicas"] = replicas
                    return f"deployment {deploy_name} scaled to {replicas} replicas (mock)"
                else:
                    return f"deployment {deploy_name} 不存在"
            except Exception as e:
                return f"scale 命令解析失败：{str(e)}"

        else:
            return f"Mock 不支持命令: {command}"


# ==================== list_k8s_resources 工具 ====================
@register_tool(
    name="list_k8s_resources",
    description="列出 Kubernetes 集群中指定类型的资源。可用于发现集群中有哪些服务、Pod、Deployment 等。",
    parameters={
        "type": "object",
        "properties": {
            "resource_type": {
                "type": "string",
                "description": "资源类型，如 pods, deployments, services",
                "enum": ["pods", "deployments", "services"]
            },
            "namespace": {
                "type": "string",
                "description": "命名空间，默认为 default",
                "default": "default"
            }
        },
        "required": ["resource_type"]
    }
)
def list_k8s_resources(resource_type: str, namespace: str = "default") -> str:
    if config.env == "real":
        # 真实环境调用 K8s API
        raise NotImplementedError("真实 K8s API 尚未实现")
    else:
        # Mock：从 MOCK_CLUSTER 字典中提取
        if resource_type == "pods":
            data = list(MOCK_CLUSTER["pods"].keys())
        elif resource_type == "deployments":
            data = list(MOCK_CLUSTER["deployments"].keys())
        elif resource_type == "services":
            data = list(MOCK_CLUSTER.get("services", {}).keys())
        else:
            data = []
        return json.dumps(data, ensure_ascii=False)