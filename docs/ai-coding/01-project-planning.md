# 开发任务

## 需求

将 ServerOps AI 拆分为一个运行在 DMP 之外的 Python 服务，完成服务器状态与日志获取、异常检测、AI 辅助诊断、故障记录和可视化展示。项目需要同时支持真实 DMP 联调和本地 Demo 验证，并尽量保持各模块职责清晰。

## AI辅助方式

开发过程中使用 AI 辅助梳理需求、检查现有代码结构、生成模块初稿和定位问题。这里记录的是根据当前代码能够确认的工作内容，不还原不存在的具体对话或 Prompt。

## 任务拆分

- 配置和 DMP 客户端：负责连接参数、登录和只读 API。
- Collector：分别采集服务器状态、在线玩家和日志。
- Detector：用可解释规则识别常见异常。
- Diagnosis：统一现场上下文并调用结构化 LLM Provider。
- Storage：使用 SQLite 保存 Incident 和 Webhook 事件。
- Dashboard：展示实时状态、趋势和故障详情。
- Webhook：提供可选的 DMP 事件接收入口。

## 实现过程

项目最终形成了 `app`、`collector`、`detector`、`llm` 和 `storage` 等目录。`app/main.py` 负责配置加载、依赖装配、一次性执行和轮询入口；具体能力由各模块提供，避免把 DMP 请求、规则、数据库和页面逻辑全部放在入口文件中。

实现过程中先建立可运行的采集和规则链路，再接入结构化诊断、Incident 持久化和 Dashboard。Demo 入口使用 `--seed-demo`，与真实监控路径共用 Incident 数据结构。

## 人工检查

人工检查了项目目录、配置示例、入口装配以及各模块之间的调用关系，重点确认：

- DMP 访问由 `DMPClient` 统一封装。
- 规则检测和 LLM 诊断是可替换的独立步骤。
- Dashboard 不需要另建一套 Demo 数据模型。
- 数据库负责 Incident 的保存和查询。

## 遇到的问题

早期功能涉及真实 DMP、外部 LLM 和 Dashboard，容易把联调行为、演示数据和核心业务逻辑混在一起。真实 LLM 还可能受外部网络和模型响应影响，不能假设始终可用。

## 修复与验证

通过拆分客户端、采集器、检测器、诊断、存储和页面模块，保留了真实模式与 Demo 模式的边界。现有验证包括 Python 模块编译、真实 DMP 只读联调、规则检测、Mock 诊断链路、Incident 保存和 Dashboard 访问。

