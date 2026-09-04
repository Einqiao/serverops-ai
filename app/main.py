"""ServerOps AI MVP command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.config import AppConfig, load_config
from app.dmp.client import DMPAPIError, DMPClient
from collector.logs import LogCollector
from collector.status import StatusCollector
from app.diagnosis.context import DiagnosisContext
from detector.incident import build_incident
from detector.rules import detect_context, detect_lines, detect_resources
from llm.diagnosis import (
    Diagnosis,
    DiagnosisPromptBuilder,
    LLMProvider,
    OpenAICompatibleProvider,
    SiliconFlowLLMProvider,
    StructuredLLMProvider,
    parse_diagnosis_response,
)
from storage.database import IncidentDatabase
from app.dashboard import DashboardState, register_dashboard
from app.webhook.receiver import create_app
from llm.diagnosis import MockLLMProvider
from types import SimpleNamespace


def _first_room_id(rooms: Any) -> str:
    values = rooms.get("items", rooms.get("rooms", [])) if isinstance(rooms, dict) else rooms
    if isinstance(values, list) and values:
        first = values[0]
        if isinstance(first, dict):
            for key in ("room_id", "roomId", "id"):
                if first.get(key) is not None:
                    return str(first[key])
        if isinstance(first, (str, int)):
            return str(first)
    return ""


def _provider(config: AppConfig) -> LLMProvider:
    if config.llm.enabled and config.llm.provider == "siliconflow":
        timeout = config.llm.timeout if config.llm.timeout is not None else config.llm.timeout_seconds
        return SiliconFlowLLMProvider(
            config.llm.base_url,
            config.llm.model,
            config.llm.api_key_env,
            timeout,
        )
    return OpenAICompatibleProvider(
        config.llm.base_url,
        config.llm.api_key if config.llm.enabled else "",
        config.llm.model,
        config.llm.timeout_seconds,
    )


def _webhook_provider(config: AppConfig) -> StructuredLLMProvider | None:
    if not config.llm.enabled:
        return None
    timeout = config.llm.timeout if config.llm.timeout is not None else config.llm.timeout_seconds
    if config.llm.provider == "mock":
        return MockLLMProvider()
    if config.llm.provider == "siliconflow":
        return SiliconFlowLLMProvider(
            config.llm.base_url,
            config.llm.model,
            config.llm.api_key_env,
            timeout,
        )
    raise ValueError(f"不支持的 Webhook LLM provider: {config.llm.provider}")


def _seed_demo(database: IncidentDatabase) -> None:
    now = datetime.now(timezone.utc)
    database.connection.execute("DELETE FROM incidents WHERE event_type = 'demo_test_data'")
    database.connection.commit()
    samples = (
        ("LUA_ERROR", "MEDIUM", "检测到服务器脚本运行异常，当前未发现服务器整体停止迹象。",
         ["模组脚本运行过程中出现异常", "某个 Mod 与当前游戏版本存在兼容性问题"],
         ["attempt to index a nil value", "stack traceback", "modmain.lua:42"],
         "可能导致相关 Mod 功能异常，但通常不代表服务器整体不可用。",
         ["查看 Lua traceback", "定位具体 mod 文件及代码行", "检查近期更新的 Mod", "必要时回滚 Mod 版本"]),
        ("MOD_ERROR", "HIGH", "检测到服务器模组加载异常，可能影响相关游戏功能。",
         ["MOD 脚本存在语法或运行时错误", "MOD 依赖组件缺失或版本不兼容",
          "MOD 更新后与当前游戏版本存在兼容性问题"],
         ["Error loading modmain.lua", "stack traceback", "modmain.lua:42", "Mod failed to load"],
         "相关 MOD 功能可能无法正常加载，严重情况下可能影响服务器正常运行。",
         ["定位 modmain.lua 对应代码位置", "检查 MOD 依赖及版本", "对比最近一次 MOD 更新", "必要时暂时禁用异常 MOD"]),
        ("CONNECTION", "MEDIUM", "检测到服务器连接异常，可能影响玩家进入或游戏过程中的连接稳定性。",
         ["网络链路出现短暂抖动", "远端连接响应超时"],
         ["connection timeout", "connection lost", "retrying connection"],
         "玩家连接和服务器间歇性通信可能受到影响。",
         ["检查网络延迟与丢包", "确认端口和防火墙配置", "观察后续连接是否恢复"]),
        ("WARNING", "LOW", "检测到服务器运行警告，当前未发现明确故障，但建议持续关注。",
         ["运行配置需要关注", "部分功能可能使用了兼容性较弱的设置"],
         ["WARNING", "deprecated configuration", "performance warning"],
         "当前影响有限，但持续积累可能影响运行稳定性。",
         ["核对相关配置", "关注后续日志变化", "在维护窗口进行优化"]),
        ("WARNING", "LOW", "检测到服务器运行警告，当前未发现明确故障，但建议持续关注。",
         ["检测到配置兼容性提示"], ["WARNING", "deprecated configuration"],
         "当前影响有限，但持续积累可能影响运行稳定性。",
         ["核对相关配置", "关注后续日志变化"]),
        ("MOD_ERROR", "MEDIUM", "检测到服务器模组加载异常，建议检查近期更新的模组及其依赖。",
         ["MOD 依赖组件版本不一致"], ["Mod failed to load", "dependency mismatch"],
         "部分 MOD 功能可能无法正常使用。",
         ["检查 MOD 依赖版本", "对比最近一次更新"]),
        ("WARNING", "LOW", "检测到服务器运行警告，目前未发现明确的服务中断迹象。",
         ["检测到短暂的性能提示"], ["performance warning", "tick rate warning"],
         "当前预计不会影响服务器整体运行，但建议持续观察。",
         ["关注后续日志是否持续出现", "结合服务器运行状态判断是否需要处理"]),
    )
    for index, (fault_type, severity, summary, causes, evidence, impact, recommendations) in enumerate(samples):
        context = SimpleNamespace(
            room_id="demo-room",
            world_id="demo-world",
            event_type="demo_test_data",
            collected_at=(now - timedelta(days=6 - index)).isoformat(),
        )
        report = SimpleNamespace(
            fault_type=fault_type,
            severity=severity,
            summary=summary,
            probable_cause=causes,
            evidence=evidence,
            impact=impact,
            recommendations=recommendations,
        )
        database.save_diagnosis_incident(context, report)


def _start_webhook_server(
    config: AppConfig, database: IncidentDatabase, client: DMPClient
) -> None:
    if not config.webhook.enabled:
        return
    if not config.webhook.secret and config.webhook.verification_enabled:
        raise ValueError("webhook.enabled=true 时必须配置 webhook.secret")
    import uvicorn

    app = create_app(
        database,
        config.webhook.secret,
        config.webhook.verification_enabled,
        client,
        config.monitor.log_lines,
        _webhook_provider(config),
    )
    thread = threading.Thread(
        target=uvicorn.run,
        kwargs={
            "app": app,
            "host": config.webhook.host,
            "port": config.webhook.port,
            "log_level": "info",
        },
        name="serverops-webhook",
        daemon=True,
    )
    thread.start()


def _start_dashboard_server(database: IncidentDatabase, state: DashboardState) -> None:
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="ServerOps AI Dashboard")
    register_dashboard(app, database, state)
    thread = threading.Thread(
        target=uvicorn.run,
        kwargs={
            "app": app,
            "host": "127.0.0.1",
            "port": 8081,
            "log_level": "info",
        },
        name="serverops-dashboard",
        daemon=True,
    )
    thread.start()


def run_once(
    client: DMPClient,
    status_collector: StatusCollector,
    log_collector: LogCollector,
    database: IncidentDatabase,
    provider: LLMProvider,
    thresholds: Any,
    enabled: bool = True,
    dashboard_state: DashboardState | None = None,
) -> list[dict[str, Any]]:
    snapshot = status_collector.collect_once()
    if dashboard_state:
        dashboard_state.update(snapshot)
    if snapshot.world_id:
        log_collector.world_id = snapshot.world_id
    batch = log_collector.collect_once()
    matches = detect_lines(batch.lines) if enabled else []
    if enabled:
        matches.extend(detect_resources(snapshot.system_status, thresholds))
    saved: list[dict[str, Any]] = []
    for match in matches:
        # Pipeline: detect -> incident -> context -> diagnosis -> save.
        incident = build_incident(snapshot.room_id, snapshot.world_id, match)
        context = {
            **snapshot.as_context(),
            "type": incident.type,
            "severity": incident.severity,
            "trigger": incident.trigger,
            "evidence": incident.evidence,
        }
        try:
            if isinstance(provider, StructuredLLMProvider):
                diagnosis_context = DiagnosisContext(
                    event_type="polling_detection",
                    event_timestamp=snapshot.captured_at,
                    room_id=snapshot.room_id,
                    room_name="",
                    world_id=snapshot.world_id,
                    collected_at=snapshot.captured_at,
                    server_status={
                        "room": snapshot.room_status,
                        "system": snapshot.system_status,
                        "online_players": snapshot.online_players,
                    },
                    recent_logs=batch.lines,
                    collection_errors=[],
                )
                diagnosis_result = detect_context(diagnosis_context)
                prompt = DiagnosisPromptBuilder().build(diagnosis_context, diagnosis_result)
                report = parse_diagnosis_response(provider.diagnose(prompt))
                if report.diagnosis_error:
                    raise RuntimeError(report.diagnosis_error)
                diagnosis = Diagnosis(
                    summary=report.summary,
                    possible_causes=report.probable_cause,
                    suggestions=report.recommendations,
                )
            else:
                diagnosis = provider.diagnose(context)
        except Exception as exc:
            print(f"LLM 诊断失败: {type(exc).__name__}: {exc}", file=sys.stderr)
            diagnosis = Diagnosis(
                summary=f"检测到 {incident.type}，LLM 诊断失败，保留规则检测结果。",
                possible_causes=[],
                suggestions=["检查异常日志和服务器状态。"],
            )
        incident.summary = diagnosis.summary
        incident.possible_causes = diagnosis.possible_causes
        incident.suggestions = diagnosis.suggestions
        database.save_incident(incident)
        saved.append(incident.as_record())
    return saved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DST ServerOps AI MVP")
    parser.add_argument("--config", default="config.yaml", help="YAML 配置路径")
    parser.add_argument("--once", action="store_true", help="仅采集一轮后退出")
    parser.add_argument("--seed-demo", action="store_true", help="写入明确标记的 Dashboard 演示数据后退出")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.seed_demo:
            database = IncidentDatabase(config.storage.database_path)
            try:
                _seed_demo(database)
            finally:
                database.close()
            print("Demo incidents seeded")
            return 0
        client = DMPClient(
            config.dmp.base_url,
            config.dmp.username,
            config.dmp.password,
            config.dmp.token or None,
            config.dmp.timeout_seconds,
            config.dmp.endpoints,
        )
        room_id = config.monitor.room_id
        if not room_id:
            room_id = _first_room_id(client.get_rooms())
        if not room_id:
            raise DMPAPIError("未配置 room_id，且 DMP 未返回可用房间")
        database = IncidentDatabase(config.storage.database_path)
        dashboard_state = DashboardState(room_id)
        status_collector = StatusCollector(client, room_id)
        log_collector = LogCollector(client, room_id, recent_lines=config.monitor.log_lines)
        provider = _provider(config)
        _start_dashboard_server(database, dashboard_state)
        _start_webhook_server(config, database, client)
        print("ServerOps AI started")
        print("DMP: connected")
        print(f"Monitoring: room={room_id}")
        if config.webhook.enabled:
            print(f"Webhook: http://{config.webhook.host}:{config.webhook.port}/webhook/dmp")
        try:
            while True:
                try:
                    incidents = run_once(
                        client,
                        status_collector,
                        log_collector,
                        database,
                        provider,
                        config.threshold,
                        True,
                        dashboard_state=dashboard_state,
                    )
                    for incident in incidents:
                        print("incident:", json.dumps(incident, ensure_ascii=False))
                except DMPAPIError as exc:
                    print(f"采集失败: {exc}", file=sys.stderr)
                if args.once:
                    break
                time.sleep(max(1, config.monitor.poll_interval))
        except KeyboardInterrupt:
            print("ServerOps AI 已停止")
        finally:
            database.close()
        return 0
    except (OSError, ValueError, DMPAPIError) as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
