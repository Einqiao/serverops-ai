"""Small read-only dashboard API and page."""

from __future__ import annotations

from threading import Lock
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from storage.database import IncidentDatabase


class DashboardState:
    def __init__(self, room_id: str) -> None:
        self._lock = Lock()
        self._data: dict[str, Any] = {
            "dmp_connected": False,
            "room_id": room_id,
            "world_id": None,
            "world_name": None,
            "world_type": None,
            "server_status": "暂无数据",
            "online_players": None,
            "updated_at": None,
        }

    def update(self, snapshot: Any) -> None:
        with self._lock:
            self._data.update(
                {
                    "dmp_connected": True,
                    "room_id": str(snapshot.room_id),
                    "world_id": str(snapshot.world_id) if snapshot.world_id else None,
                    "world_name": _world_field(snapshot.room_status, snapshot.world_id, ("worldName", "name")),
                    "world_type": _world_type(snapshot.room_status, snapshot.world_id),
                    "server_status": _server_status(snapshot.room_status),
                    "online_players": _player_count(snapshot.online_players),
                    "updated_at": snapshot.captured_at,
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)


def register_dashboard(
    app: FastAPI, database: IncidentDatabase, state: DashboardState | None = None
) -> None:
    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page() -> str:
        return DASHBOARD_HTML

    @app.get("/dashboard/api/summary")
    async def dashboard_summary() -> JSONResponse:
        try:
            counts = database.incident_summary()
            live = state.snapshot() if state else {}
            return JSONResponse(
                {
                    "server_status": live.get("server_status", "暂无数据"),
                    "online_players": live.get("online_players"),
                    "room_id": live.get("room_id"),
                    "world_id": live.get("world_id"),
                    "world_name": live.get("world_name"),
                    "world_type": live.get("world_type"),
                    "incident_count": counts["incident_count"],
                    "critical_count": counts["high_risk_count"],
                    "updated_at": live.get("updated_at"),
                    "dmp_connected": live.get("dmp_connected", False),
                    "trend": _dashboard_trend(database),
                    "demo_mode": any(
                        item.get("event_type") == "demo_test_data"
                        for item in database.list_incidents(500)
                    ),
                }
            )
        except Exception:
            return JSONResponse({"detail": "无法读取 Dashboard 摘要"}, status_code=500)

    @app.get("/dashboard/api/incidents")
    async def dashboard_incidents(
        limit: int = Query(50, ge=1, le=500),
        status: str | None = None,
        severity: str | None = None,
    ) -> JSONResponse:
        try:
            incidents = database.list_incidents(limit, status, severity)
            for incident in incidents:
                incident["first_seen"] = incident.get("detected_at")
                incident["is_demo"] = incident.get("event_type") == "demo_test_data"
                _complete_demo_incident(incident)
                incident["display_summary"] = get_business_summary(incident)
            return JSONResponse(incidents)
        except Exception:
            return JSONResponse({"detail": "无法读取 Incident 列表"}, status_code=500)

    @app.get("/dashboard/api/incidents/{incident_id}")
    async def dashboard_incident(incident_id: str) -> JSONResponse:
        try:
            incident = database.get_incident(incident_id)
        except Exception:
            return JSONResponse({"detail": "无法读取 Incident"}, status_code=500)
        if incident is None:
            return JSONResponse({"detail": "Incident 不存在"}, status_code=404)
        incident["first_seen"] = incident.get("detected_at")
        incident["is_demo"] = incident.get("event_type") == "demo_test_data"
        _complete_demo_incident(incident)
        incident["display_summary"] = get_business_summary(incident)
        return JSONResponse(incident)


def get_business_summary(incident: dict[str, Any]) -> str:
    summaries = {
        "LUA_ERROR": "检测到服务器脚本运行异常，建议结合异常日志进一步定位。",
        "MOD_ERROR": "检测到服务器模组异常，建议检查近期更新的模组及其依赖。",
        "CONNECTION": "检测到服务器连接异常，可能影响玩家连接稳定性。",
        "WARNING": "检测到服务器运行警告，当前未发现明确故障，建议持续关注。",
    }
    fault_type = str(incident.get("fault_type") or incident.get("type") or "").upper()
    return summaries.get(fault_type, str(incident.get("summary") or "暂无数据"))


DEMO_DIAGNOSTICS = {
    "LUA_ERROR": {
        "severity": "MEDIUM",
        "summary": "检测到服务器脚本运行异常，当前未发现服务器整体停止迹象。",
        "probable_cause": ["某个 Mod 脚本执行过程中出现异常", "Mod 与当前游戏版本存在兼容性问题", "游戏对象状态异常导致脚本访问空对象"],
        "evidence": ["attempt to index a nil value", "stack traceback", "modmain.lua:42"],
        "impact": "可能导致相关 Mod 功能异常，但通常不代表服务器整体不可用。",
        "recommendations": ["查看 Lua traceback，定位具体脚本和代码位置", "检查近期更新或安装的 Mod", "确认相关 Mod 与当前游戏版本兼容", "如果异常持续出现，可尝试回滚最近修改的 Mod"],
    },
    "MOD_ERROR": {
        "severity": "HIGH",
        "summary": "检测到服务器模组加载异常，可能影响相关游戏功能。",
        "probable_cause": ["Mod 加载失败", "Mod 依赖缺失", "Mod 与当前游戏版本不兼容"],
        "evidence": ["Error loading modmain.lua", "stack traceback", "Mod failed to load"],
        "impact": "相关 Mod 功能可能无法正常使用，严重时可能影响服务器启动或运行稳定性。",
        "recommendations": ["检查 Mod 加载日志", "确认 Mod 依赖是否完整", "检查最近更新的 Mod", "必要时回滚到上一版本"],
    },
    "CONNECTION": {
        "severity": "MEDIUM",
        "summary": "检测到服务器连接异常，可能影响玩家连接稳定性。",
        "probable_cause": ["网络连接短暂中断", "服务端连接请求超时", "网络波动导致连接异常"],
        "evidence": ["connection timeout", "connection lost", "retrying connection"],
        "impact": "可能导致玩家掉线或无法正常进入服务器。",
        "recommendations": ["检查服务器网络状态", "查看连接超时相关日志", "观察异常是否重复发生", "必要时检查服务器所在节点网络状况"],
    },
    "WARNING": {
        "severity": "LOW",
        "summary": "检测到服务器运行警告，目前未发现明确的服务中断迹象。",
        "probable_cause": ["游戏运行过程中出现非致命警告", "某项功能出现短暂异常"],
        "evidence": ["WARNING", "deprecated configuration", "performance warning"],
        "impact": "当前预计不会影响服务器整体运行，但建议持续观察。",
        "recommendations": ["关注后续日志是否持续出现", "如果频繁出现，再进一步定位相关模块", "结合服务器运行状态判断是否需要处理"],
    },
}


def _complete_demo_incident(incident: dict[str, Any]) -> None:
    if not incident.get("is_demo"):
        return
    diagnosis = DEMO_DIAGNOSTICS.get(
        str(incident.get("fault_type") or incident.get("type") or "").upper()
    )
    if diagnosis:
        incident.update(diagnosis)


def _world_field(status: Any, world_id: str, keys: tuple[str, ...]) -> str | None:
    world = _find_world(status, world_id)
    if isinstance(world, dict):
        for key in keys:
            value = world.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _world_type(status: Any, world_id: str) -> str | None:
    world = _find_world(status, world_id)
    if isinstance(world, dict):
        if world.get("isMaster") is True:
            return "主世界"
        if str(world.get("location", "")).lower() == "cave":
            return "洞穴"
        if world.get("location") not in (None, ""):
            return str(world["location"])
    return None


def _find_world(status: Any, world_id: str) -> dict[str, Any] | None:
    if isinstance(status, dict):
        worlds = status.get("worlds")
        if isinstance(worlds, list):
            for world in worlds:
                if isinstance(world, dict) and str(
                    world.get("id", world.get("worldID", world.get("worldId", "")))
                ) == str(world_id):
                    return world
        nested = status.get("world")
        if isinstance(nested, dict):
            return nested
    return None


def _server_status(status: Any) -> str:
    value = _find_key(status, {"status", "serverStatus", "state", "isRunning", "running"})
    if isinstance(value, bool):
        return "Running" if value else "Stopped"
    if value not in (None, ""):
        return str(value)
    return "暂无数据"


def _player_count(value: Any) -> int | None:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        for key in ("onlinePlayers", "onlineCount", "playerCount", "count"):
            candidate = value.get(key)
            if isinstance(candidate, int):
                return candidate
        for key in ("players", "items", "data"):
            if key in value:
                count = _player_count(value[key])
                if count is not None:
                    return count
    return None


def _find_key(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {candidate.lower() for candidate in keys}:
                return item
        for item in value.values():
            found = _find_key(item, keys)
            if found is not None:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_key(item, keys)
            if found is not None:
                return found
    return None


def _dashboard_trend(database: IncidentDatabase) -> list[dict[str, Any]]:
    grouped: dict[str, int] = defaultdict(int)
    for incident in database.list_incidents(500):
        detected_at = str(incident.get("last_seen") or incident.get("detected_at") or "")
        day = detected_at[:10]
        if day:
            grouped[day] += max(1, int(incident.get("occurrence_count") or 1))
    return [
        {"day": day, "count": count}
        for day, count in sorted(grouped.items())[-7:]
    ]


DASHBOARD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ServerOps AI · 服务器运维与异常诊断</title>
<style>
:root{font-family:Inter,Segoe UI,Arial,sans-serif;color:#172033;background:#f4f6f9}
*{box-sizing:border-box}body{margin:0}.shell{max-width:1440px;margin:auto;padding:30px}
header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px}
h1{margin:0;font-size:26px}header p{margin:7px 0;color:#697386}.status{background:#fff;border:1px solid #e5e9f0;border-radius:12px;padding:12px 16px;color:#586174;font-size:14px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#9aa4b2;margin-right:7px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.card,.panel{background:#fff;border:1px solid #e6eaf0;border-radius:14px;box-shadow:0 3px 12px #1f29370a}
.metric{padding:20px}.metric label{display:block;color:#768195;font-size:13px}.metric strong{display:block;margin-top:12px;font-size:25px}
.layout{display:grid;grid-template-columns:1fr 1.25fr;gap:16px;margin-top:20px}.panel{padding:22px}.panel h2{font-size:17px;margin:0 0 18px}
.facts{display:grid;grid-template-columns:1fr 1fr;gap:15px}.fact span{display:block;color:#7b8495;font-size:12px}.fact b{display:block;margin-top:5px}
.trend-chart{display:flex;align-items:flex-end;height:190px;gap:10px;border-bottom:1px solid #edf0f4;padding:12px 8px 28px}.trend-day{flex:1;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;min-width:30px}.trend-bar{width:clamp(16px,55%,32px);min-height:3px;background:#6f98c5;border-radius:4px 4px 0 0}.trend-count{font-size:11px;color:#697386;margin-bottom:4px}.trend-date{font-size:11px;color:#8a93a3;margin-top:8px;white-space:nowrap}
.events{margin-top:20px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:14px 12px;border-bottom:1px solid #edf0f4;white-space:nowrap}th{color:#7b8495;font-weight:500}tbody tr{cursor:pointer}tbody tr:hover{background:#f8fafc}
.tag{display:inline-block;border-radius:6px;padding:4px 8px;font-size:11px;font-weight:600}.critical{color:#b42318;background:#fff0ee}.high{color:#b54708;background:#fff5e8}.medium{color:#a15c00;background:#fff9df}.low,.info{color:#526581;background:#f0f4fa}
.detail{display:none;margin-top:16px}.detail.show{display:block}.detail-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.detail h3{font-size:13px;color:#788397;margin:0 0 7px}.detail p,.detail ul{margin:0;line-height:1.65}
.error{color:#b42318;background:#fff0ee;padding:12px;border-radius:8px;display:none;margin-bottom:14px}
@media(max-width:900px){.grid,.layout{grid-template-columns:1fr 1fr}.layout{grid-template-columns:1fr}}@media(max-width:600px){.shell{padding:18px}.grid,.facts,.detail-grid{grid-template-columns:1fr}}
</style></head>
<body><main class="shell"><header><div><h1>ServerOps AI</h1><p>服务器运维与异常诊断</p></div><div class="status"><span class="dot"></span><span id="connection">DMP 未连接</span><br><small id="updated">等待更新</small></div></header>
<div id="error" class="error"></div><section class="grid">
<div class="card metric"><label>服务器状态</label><strong id="server-status">暂无数据</strong></div><div class="card metric"><label>在线玩家</label><strong id="players">暂无数据</strong></div><div class="card metric"><label>异常事件</label><strong id="incident-count">0</strong></div><div class="card metric"><label>高风险事件</label><strong id="critical-count">0</strong></div></section>
<section class="layout"><div class="panel"><h2>运行状态</h2><div class="facts"><div class="fact"><span>连接状态</span><b id="dmp-state">等待监控数据</b></div><div class="fact"><span>房间</span><b id="room-id">暂无数据</b></div><div class="fact"><span>世界</span><b id="world-id">暂无数据</b></div><div class="fact"><span>最近数据</span><b id="last-event">暂无数据</b></div></div></div><div class="panel"><h2>近 7 日异常事件</h2><div class="trend-chart" id="trend"></div></div></section>
<section class="panel events"><h2>最近异常事件</h2><div class="table-wrap"><table><thead><tr><th>首次发现</th><th>最近发现</th><th>房间</th><th>故障类型</th><th>严重程度</th><th>出现次数</th><th>摘要</th><th>状态</th></tr></thead><tbody id="rows"></tbody></table></div><div id="detail" class="detail"><h2>AI 诊断详情 <small id="d-source"></small></h2><div class="detail-grid"><div><h3>故障类型 / 严重程度</h3><p id="d-type"></p><h3 style="margin-top:15px">首次发现</h3><p id="d-first"></p><h3 style="margin-top:15px">最近发现</h3><p id="d-last"></p><h3 style="margin-top:15px">出现次数</h3><p id="d-count"></p><h3 style="margin-top:15px">诊断摘要</h3><p id="d-summary"></p><h3 style="margin-top:15px">影响</h3><p id="d-impact"></p></div><div><h3>可能原因</h3><ul id="d-causes"></ul><h3 style="margin-top:15px">异常证据</h3><ul id="d-evidence"></ul><h3 style="margin-top:15px">处理建议</h3><ul id="d-recommendations"></ul></div></div></div></section></main>
<script>
const $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let incidents=[];
function list(v){return Array.isArray(v)?v:[]}
async function load(){try{const [s,i]=await Promise.all([fetch('/dashboard/api/summary'),fetch('/dashboard/api/incidents?limit=50')]);if(!s.ok||!i.ok)throw Error('Dashboard API 请求失败');const summary=await s.json();incidents=await i.json();$('server-status').textContent=summary.server_status??'暂无数据';$('players').textContent=summary.online_players??'暂无数据';$('incident-count').textContent=summary.incident_count;$('critical-count').textContent=summary.critical_count;$('connection').textContent=summary.dmp_connected?'DMP 已连接':(summary.demo_mode?'演示数据':'等待 DMP 数据');$('dmp-state').textContent=summary.dmp_connected?'DMP 已连接':(summary.demo_mode?'演示数据':'等待监控数据');$('room-id').textContent=summary.room_id??'暂无数据';$('world-id').textContent=summary.world_id?(summary.world_name?summary.world_id+' · '+summary.world_name+(summary.world_type?' · '+summary.world_type:''):summary.world_id):'暂无数据';$('last-event').textContent=summary.updated_at?new Date(summary.updated_at).toLocaleString():'暂无数据';$('updated').textContent=summary.updated_at?'最后更新 '+new Date(summary.updated_at).toLocaleString():(summary.demo_mode?'演示数据':'等待监控数据');render();renderTrend(summary.trend||[]);}catch(e){$('error').textContent=e.message;$('error').style.display='block'}}
function render(){const rows=$('rows');rows.innerHTML=incidents.map((x,n)=>`<tr onclick="show(${n})"><td>${esc(x.first_seen||x.detected_at)}</td><td>${esc(x.last_seen||x.detected_at)}</td><td>${esc(x.room_name||x.room_id||'—')}</td><td>${esc(x.fault_type||x.type)}</td><td><span class="tag ${(x.severity||'info').toLowerCase()}">${esc(x.severity)}</span></td><td>${esc(x.occurrence_count??1)}${(x.occurrence_count||1)>1?' · 持续发生':''}</td><td>${esc(x.display_summary||x.summary||'暂无数据')}</td><td>${esc(x.status||'open')}</td></tr>`).join('')||'<tr><td colspan="8">暂无 Incident 数据</td></tr>'}
function renderTrend(items){const box=$('trend');const days=items.slice(-7);if(!days.length){box.innerHTML='<span class="trend-date">暂无数据</span>';return}const max=Math.max(...days.map(x=>x.count||0),1);box.innerHTML=days.map(x=>{const count=x.count||0;return `<div class="trend-day"><span class="trend-count">${count}</span><span class="trend-bar" style="height:${Math.max(4,count/max*100)}%"></span><span class="trend-date">${esc(x.day.slice(5))}</span></div>`}).join('')}
function show(n){const x=incidents[n];$('detail').classList.add('show');$('d-source').textContent=x.is_demo?' · AI 辅助诊断 · Demo':'';$('d-type').textContent=(x.fault_type||x.type)+' / '+x.severity;$('d-first').textContent=x.first_seen||x.detected_at||'暂无数据';$('d-last').textContent=x.last_seen||x.detected_at||'暂无数据';$('d-count').textContent=(x.occurrence_count??1)+' 次';$('d-summary').textContent=x.display_summary||x.summary||'暂无数据';$('d-impact').textContent=x.impact||'暂无数据';['causes','evidence','recommendations'].forEach(k=>$(('d-'+k)).innerHTML=list(x[k==='causes'?'probable_cause':k]).map(v=>`<li>${esc(v)}</li>`).join('')||'<li>暂无数据</li>');$('detail').scrollIntoView({behavior:'smooth',block:'nearest'})}
load();
</script></body></html>"""
