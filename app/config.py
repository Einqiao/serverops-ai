"""YAML configuration and environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml


@dataclass
class DMPConfig:
    base_url: str = "http://127.0.0.1:8080"
    username: str = ""
    password: str = ""
    token: str = ""
    timeout_seconds: float = 10.0
    endpoints: dict[str, str] = field(default_factory=dict)


@dataclass
class MonitorConfig:
    room_id: str = ""
    poll_interval: int = 60
    log_lines: int = 200


@dataclass
class ThresholdConfig:
    cpu: float = 90.0
    memory: float = 90.0
    disk: float = 90.0


@dataclass
class LLMConfig:
    enabled: bool = False
    provider: str = "mock"
    base_url: str = "https://api.siliconflow.cn/v1"
    api_key: str = ""
    api_key_env: str = "SILICONFLOW_API_KEY"
    model: str = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"
    timeout_seconds: float = 30.0
    timeout: float | None = None


@dataclass
class StorageConfig:
    database_path: str = "data/serverops.db"


@dataclass
class WebhookConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8081
    secret: str = ""
    verification_enabled: bool = True


@dataclass
class AppConfig:
    dmp: DMPConfig = field(default_factory=DMPConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    threshold: ThresholdConfig = field(default_factory=ThresholdConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)


def _section(raw: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = raw.get(name, {})
    return value if isinstance(value, Mapping) else {}


def load_config(path: str = "config.yaml") -> AppConfig:
    raw: Mapping[str, Any] = {}
    config_path = Path(path)
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, Mapping):
            raise ValueError("配置文件根节点必须是 YAML mapping")
        raw = loaded

    dmp_raw, monitor_raw = _section(raw, "dmp"), _section(raw, "monitor")
    threshold_raw, llm_raw = _section(raw, "threshold"), _section(raw, "llm")
    storage_raw, webhook_raw = _section(raw, "storage"), _section(raw, "webhook")
    dmp = DMPConfig(**{k: v for k, v in dmp_raw.items() if k in DMPConfig.__dataclass_fields__})
    monitor = MonitorConfig(
        **{k: v for k, v in monitor_raw.items() if k in MonitorConfig.__dataclass_fields__}
    )
    threshold = ThresholdConfig(
        **{k: v for k, v in threshold_raw.items() if k in ThresholdConfig.__dataclass_fields__}
    )
    llm = LLMConfig(**{k: v for k, v in llm_raw.items() if k in LLMConfig.__dataclass_fields__})
    storage = StorageConfig(**{k: v for k, v in storage_raw.items() if k in StorageConfig.__dataclass_fields__})
    webhook = WebhookConfig(**{k: v for k, v in webhook_raw.items() if k in WebhookConfig.__dataclass_fields__})

    # Environment variables intentionally take precedence for credentials and endpoints.
    dmp.base_url = os.getenv("DMP_BASE_URL", dmp.base_url)
    dmp.username = os.getenv("DMP_USERNAME", dmp.username)
    dmp.password = os.getenv("DMP_PASSWORD", dmp.password)
    dmp.token = os.getenv("DMP_TOKEN", dmp.token)
    llm.api_key = os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY", llm.api_key))
    llm.base_url = os.getenv("LLM_BASE_URL", llm.base_url)
    llm.model = os.getenv("LLM_MODEL", llm.model)
    monitor.room_id = os.getenv("SERVEROPS_ROOM_ID", monitor.room_id)
    storage.database_path = os.getenv("SERVEROPS_DB_PATH", storage.database_path)
    webhook.secret = os.getenv("WEBHOOK_SECRET", webhook.secret)
    return AppConfig(
        dmp=dmp,
        monitor=monitor,
        threshold=threshold,
        llm=llm,
        storage=storage,
        webhook=webhook,
    )
