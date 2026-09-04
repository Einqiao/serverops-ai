# ServerOps AI

**AI 辅助服务器运维与异常诊断系统**

ServerOps AI 是一个面向 DST（Don't Starve Together）服务器的外部运维分析服务。它通过 DMP 获取服务器状态和游戏日志，先使用可解释规则识别异常，再结合结构化 LLM 进行辅助诊断，并将结果沉淀为可查询的 Incident，通过 Dashboard 提供统一查看入口。

> 本项目为个人实践项目，目前主要用于个人服务器环境中的实际联调与验证。

## AI Coding 过程

本项目在开发过程中使用 AI Coding 工具辅助完成需求拆解、代码阅读、模块开发、问题定位与测试修复，并保留了完整的开发过程记录。

> 想了解项目是如何一步步完成的，可以查看：
>
> 📄 **[AI Coding 开发过程记录](./docs/ai-coding/)**

过程记录包括：
- 项目需求与功能拆解
- 对已有 DMP 项目的代码分析
- AI 辅助模块开发
- Webhook、AI 诊断、故障去重等功能实现
- 开发过程中遇到的问题与修复
- 测试与验证过程

## 项目背景

维护游戏服务器时，很多问题首先表现为日志中的几行信息：Lua 脚本异常、MOD 加载失败、连接超时或持续出现的运行警告。人工需要在状态、玩家、日志和历史记录之间反复切换，才能判断问题是否重复发生、影响范围是什么以及下一步该查哪里。

这个项目尝试把这条排查流程串起来：先保留规则检测的确定性，再把有限、相关的上下文交给 AI，最后将诊断结果沉淀为可查询的 Incident。

## 项目概览

ServerOps AI 不是 DST 管理平台本身，而是运行在 DMP 之外的分析层。它目前支持：

- 通过 DMP API 登录并读取房间、世界、系统状态、在线玩家和游戏日志
- 识别常见的 CRASH、LUA_ERROR、MOD_ERROR、CONNECTION、RESOURCE、WARNING 等异常
- 将状态和日志整理为 `DiagnosisContext`
- 通过 Mock 或 SiliconFlow 等结构化 LLM Provider 生成 `DiagnosisReport`
- 将 Incident 保存到 SQLite
- 对重复的 open Incident 使用 fingerprint 合并统计
- 提供一个只读 Dashboard
- 接收 DMP Webhook，并对 `keepalive_triggered` 事件进行后台诊断

整个系统围绕 **“异常检测 → 上下文提取 → AI 辅助诊断 → 故障记录”** 展开，其中规则检测负责基础异常识别，LLM 负责对已发现异常进行进一步分析。

## 核心流程

```text
DMP API
  │
  ├──► 状态 / 玩家 / 游戏日志
  │
  ▼
Collector
  │
  ▼
RuleDetector
  │
  ▼
DiagnosisContext
  │
  ▼
LLM 辅助诊断
  │
  ▼
DiagnosisReport
  │
  ▼
Incident
  │
  ├──► Dashboard
  └──► 历史查询


DMP Webhook
  │
  ▼
Webhook Receiver
  │
  └──► 触发后台诊断流程
```

## 核心功能

### DMP API 对接

`DMPClient` 使用 DMP 的账号密码登录机制，并在内存中维护认证状态。当前客户端封装了：

- 房间列表
- 房间基础状态和 worlds 信息
- 系统状态
- 房间在线玩家
- 指定房间、世界和日志类型的游戏日志

凭据通过配置文件或环境变量提供，不写入前端，也不应提交到仓库。

### 状态与日志采集

`StatusCollector` 获取房间、系统和在线玩家状态；`LogCollector` 获取有限行数的日志，并对滑动窗口进行简单的增量去重。`DiagnosisContext` 将事件时间、房间、世界、状态、日志和采集错误组织成统一输入。

### 异常检测

规则检测覆盖常见的：

- `CRASH`
- `LUA_ERROR`
- `MOD_ERROR`
- `CONNECTION`
- `RESOURCE`
- `WARNING`

规则结果包含故障类型、严重程度、匹配证据和相关日志行，便于后续诊断和解释。

### LLM 辅助诊断

系统采用“规则初筛 + LLM 辅助分析”的方式，而不是直接将完整日志交给模型。

- `MockLLMProvider`：用于本地流程测试和结构化结果验证
- `SiliconFlowLLMProvider`：调用 OpenAI 兼容的 Chat Completions 接口
- 通过 Prompt 约束输入范围和输出结构
- 将模型结果解析为结构化 `DiagnosisReport`

诊断结果包含故障类型、严重程度、摘要、可能原因、异常证据、影响和处理建议。规则检测作为基础能力独立运行，LLM 主要负责对已发现的异常进行进一步整理和分析。

### SQLite Incident

Incident 存储在现有 SQLite 数据库中，保存规则或 AI 诊断相关字段，包括：

- 故障类型与严重程度
- 摘要、可能原因、证据、影响和处理建议
- 首次发现时间与最近发现时间
- 当前状态
- `fingerprint`
- `occurrence_count`

重复的 open Incident 不会无限新增记录，而是更新出现次数和最近发现时间。不同房间、世界、故障类型或核心证据仍可形成不同 Incident。

### Dashboard

Dashboard 使用 FastAPI 内嵌 HTML/CSS/JavaScript 实现，不依赖 Vue、React 等前端框架。页面目前展示：

- DMP 连接状态、服务器状态、在线玩家和异常统计
- 房间与世界信息
- 近 7 日异常事件总数趋势
- 最近 Incident 列表
- Incident 的 AI 辅助诊断详情

页面访问地址通常为：

```text
http://127.0.0.1:8081/dashboard
```

### Webhook

可选的 FastAPI Webhook 接收入口为 `POST /webhook/dmp`。当启用签名校验时，服务使用配置的 secret 校验 `X-DMP-Signature`。收到 `keepalive_triggered` 后，系统会在后台采集上下文、执行规则检测和结构化诊断，并保存 Incident。

Webhook 是否启用由配置决定；默认示例配置中为关闭状态。

## 系统架构

```mermaid
flowchart LR
    DMP[DMP API] --> Client[DMPClient]
    Client --> Status[StatusCollector]
    Client --> Logs[LogCollector]
    Status --> Context[DiagnosisContext]
    Logs --> Context
    Context --> Rules[RuleDetector]
    Rules --> Prompt[DiagnosisPromptBuilder]
    Prompt --> Provider[Structured LLM Provider]
    Provider --> Report[DiagnosisReport]
    Report --> DB[(SQLite IncidentDatabase)]
    Rules --> DB
    DB --> Dashboard[FastAPI Dashboard]
    Webhook[DMP Webhook] --> Receiver[Webhook Receiver]
    Receiver --> Context
```

## AI 诊断


AI 不直接接收完整服务器日志，而是在规则初筛后使用经过限制和脱敏的上下文进行辅助分析。当前链路是：

1. 先读取有限范围的服务器状态和日志
2. 使用规则发现异常类型并提取匹配证据
3. 组装 `DiagnosisContext`
4. 使用 `DiagnosisPromptBuilder` 限制日志数量并过滤敏感字段
5. 调用结构化 LLM Provider
6. 解析 JSON 为 `DiagnosisReport`
7. 将报告保存为 Incident

这样做的目的，是让规则负责快速、可解释的初筛，让模型负责摘要、可能原因、影响和建议，而不是把所有判断都交给模型。

## Dashboard

Dashboard 页面提供服务器运行概况、近 7 日异常趋势、最近异常列表和诊断详情。



![Dashboard](docs/dashboard.png)
![Dashboard2](docs/dashboard2.png)

## 故障记录与去重

每个 Incident 会根据以下信息生成稳定 fingerprint：

- `room_id`
- `world_id`
- `fault_type`
- 归一化后的核心异常证据

当相同 fingerprint 的 Incident 仍处于 `open` 状态时，系统会：

- 保留原 Incident
- 增加 `occurrence_count`
- 更新 `last_seen`

`detected_at` 用于记录首次发现时间，Dashboard 对外展示为 `first_seen`。该机制用于减少轮询滑动窗口导致的重复事件，同时不会把所有 Lua 错误粗略合并为一个事件。

## 我的工作

这是一个个人项目。我围绕真实的 DST/DMP 运维场景，独立完成了：

- 分析 DMP 现有 API 与服务器日志能力，设计外部运维分析层
- 实现 DMP API 客户端、认证及状态/日志采集
- 设计并实现基于规则的异常检测机制
- 设计 `DiagnosisContext`，整理服务器状态、日志和事件信息
- 实现 Prompt 构造、结构化 LLM Provider 与 `DiagnosisReport`
- 实现 SQLite Incident 持久化、兼容迁移及 fingerprint 重复事件去重
- 实现 DMP Webhook 接收与 `keepalive_triggered` 后台诊断流程
- 使用 FastAPI 完成 Dashboard 和诊断结果展示
- 在开发过程中使用 AI Coding 工具辅助代码阅读、模块实现、问题定位与测试修复

> 项目用于展示完整的 AI 应用开发与 AI Coding 实践流程，目前主要运行于个人服务器环境。

## 技术栈

- Python
- FastAPI
- Uvicorn
- SQLite
- `requests`
- PyYAML
- `python-dotenv`
- HTML / CSS / JavaScript
- OpenAI 兼容的 LLM HTTP 接口

## 项目运行

进入 `serverops-ai` 目录后安装依赖：

```bash
python -m pip install -r requirements.txt
```

准备配置文件：

```bash
copy config.yaml.example config.yaml
```

在本地 `.env` 或 `config.yaml` 中配置 DMP 连接信息。常用环境变量包括：

```text
DMP_BASE_URL=你的DMP地址
DMP_USERNAME=你的DMP用户名
DMP_PASSWORD=你的DMP密码
SERVEROPS_ROOM_ID=目标房间ID
```

启动监控、Dashboard 和配置中启用的 Webhook：

```bash
python -m app.main
```

只执行一次采集和检测：

```bash
python -m app.main --once
```

生成明确标记为 Demo 的 Incident 数据：

```bash
python -m app.main --seed-demo
```

启动后访问：

```text
python -m app.main
http://127.0.0.1:8081/dashboard
```

## 开发与使用说明

### 真实服务器 / DMP 联调

真实模式通过配置的 DMP 地址、账号和房间进行读取。程序会调用 DMP 获取状态、在线玩家和游戏日志；是否能读取到具体数据取决于 DMP 服务、权限和目标房间当前状态。


### LLM 可用性

项目同时提供 Mock Provider 和 SiliconFlow Provider，分别用于本地流程验证和外部模型调用。外部模型的实际可用性取决于 API 密钥、网络和服务状态。

## 当前边界

- 当前项目是轻量运维分析工具，不包含自动修复、远程 Shell 执行、MOD 安装或服务器控制面板。
- 未提供完整的用户权限系统、任务队列或高可用部署方案。
