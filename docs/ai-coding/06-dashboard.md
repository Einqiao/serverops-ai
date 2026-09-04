# 开发任务

## 需求

提供一个轻量的服务器运维 Dashboard，让用户查看 DMP 连接状态、当前房间和世界、在线玩家、异常统计、近 7 日趋势以及 Incident 的诊断详情。真实数据不可用时应显示暂无数据，Demo 数据必须明确标识。

## AI辅助方式

AI 辅助检查了 FastAPI 路由、内嵌 HTML/CSS/JavaScript、Dashboard 状态快照和数据库查询，并协助发现页面最初没有接入监控进程真实状态的问题。后续调整只围绕展示层和 Demo 数据，没有修改 DMPClient、RuleDetector、LLM 或 Incident 去重核心逻辑。

## 任务拆分

- 注册 `/dashboard` 页面路由。
- 提供 `/dashboard/api/summary` 摘要接口。
- 提供 Incident 列表和详情接口。
- 建立线程安全的 `DashboardState`。
- 将监控快照中的房间、世界、状态、玩家和更新时间写入 DashboardState。
- 从 SQLite 读取 Incident 和 7 日趋势。
- 对列表摘要做业务化展示。
- 为 Demo Incident 补充四类故障的完整诊断字段。

## 实现过程

`app/dashboard.py` 通过 `register_dashboard()` 注册页面和 API。`DashboardState` 使用锁保存监控线程更新的快照，包含 DMP 连接状态、room/world、服务器状态、在线玩家和更新时间。

`app/main.py` 中的 `_start_dashboard_server()` 创建 FastAPI 应用并在 `127.0.0.1:8081` 启动 Uvicorn；监控和 Dashboard 可以同时运行，Webhook 是否启用仍由原配置控制。

页面的趋势图最终简化为近 7 日每日异常总数柱状图，真实模式从 Incident 时间字段统计，Demo 模式使用跨日期的演示记录。Incident 列表使用 `get_business_summary()` 将内部规则或 LLM 失败文案转换为面向运维人员的故障摘要；详情保留故障类型、严重程度、原因、证据、影响和建议。

## 人工检查

人工检查了真实监控快照是否写入 Dashboard、页面 API 是否读取同一个 IncidentDatabase、Demo 标记是否可见，以及列表摘要是否泄露内部 Provider 或 LLM 失败状态。

## 遇到的问题

最初页面可以访问，但状态区域显示 unknown、未连接和 0 在线玩家，因为页面没有使用监控进程的真实快照。趋势图经过多次迭代后，复杂的多类型图例和多条序列仍然拥挤；此外，部分 Demo 详情字段为空会造成大量“暂无数据”。

## 修复与验证

通过 DashboardState 接入监控快照，页面能够显示真实 DMP、房间 4、Master world 207、服务器状态、在线玩家和更新时间。趋势图改为单一每日异常总数序列，Demo 数据分布在多个日期。Demo 详情补齐四类故障的诊断内容，并通过 Dashboard API 和页面访问验证；真实数据查询链路保持不变。

