import os
import yaml
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class AgentConfig:
    model: str = "qwen-max"
    env: str = "mock"               # mock / real
    db_path: str = "data/demo.db"
    tickets_path: str = "data/tickets.json"
    k8s_kubeconfig: str = ""
    db_conn_str: str = ""

    @classmethod
    def from_yaml(cls, path: str = None) -> "AgentConfig":
        # 自动基于本文件所在目录定位 config.yaml
        if path is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(current_dir, "config.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # 环境变量可覆盖配置文件
        data["env"] = os.getenv("AGENT_ENV", data.get("env", "mock"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def __post_init__(self):
        # 将相对路径转为基于 agent 目录的绝对路径，确保在任何工作目录下都能找到
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if not os.path.isabs(self.db_path):
            self.db_path = os.path.join(base_dir, self.db_path)
        if not os.path.isabs(self.tickets_path):
            self.tickets_path = os.path.join(base_dir, self.tickets_path)
        # k8s_kubeconfig 如果是相对路径也可处理，但通常为空或绝对路径，可先保留

# 全局配置实例，模块加载时初始化
config = AgentConfig.from_yaml()