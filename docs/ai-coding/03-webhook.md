# 开发任务

## 需求

为 ServerOps AI 增加可选的 DMP Webhook 接收能力，使外部事件可以被记录，并在满足条件时触发一次后台诊断。Webhook 不能绕过已有的上下文、规则、LLM 和 Incident 链路。

## AI辅助方式

这一阶段先确定 Webhook 在系统中的职责：接收 DMP 产生的事件，并作为后续异常诊断流程的触发入口。

在明确接口、签名验证和事件处理边界后，使用 Cursor 辅助完成接收器、数据模型、签名验证和事件处理代码。

实现完成后，通过实际 HTTP 请求分别验证正常签名和错误签名，并检查事件是否正确写入 SQLite。验证重点放在实际行为。
## 任务拆分

- 建立 `POST /webhook/dmp` 接收入口。
- 读取原始请求 body 和 `X-DMP-Signature`。
- 按配置决定是否进行 HMAC 签名校验。
- 将 JSON 转换为 `DMPWebhookEvent` 并保存 Webhook 事件。
- 仅在 `keepalive_triggered` 且依赖存在时启动后台诊断。
- 复用 `DiagnosisContext`、`RuleDetector`、结构化 Provider 和 `IncidentDatabase`。

## 实现过程

`app/webhook/receiver.py` 的 `create_app()` 创建 FastAPI 应用并注册 Webhook 路由。请求先读取原始 body，再调用 `verify_signature()` 校验签名；无效签名返回 401，非法 JSON 或非法事件返回 400。

合法事件由 `handle_event()` 保存。对于 `keepalive_triggered`，接收函数启动名为 `serverops-diagnosis` 的后台线程，执行：

```text
collect_diagnosis_context
→ detect_context
→ DiagnosisPromptBuilder.build
→ diagnosis_provider.diagnose
→ parse_diagnosis_response
→ save_diagnosis_incident
```

Webhook 默认可以关闭；启用签名验证时必须配置 secret。

## 人工检查

人工检查了签名使用的 body 是否为原始内容、无效请求是否会被拒绝、后台诊断是否只对指定事件触发，以及 Webhook 是否复用既有 Incident 保存逻辑。

## 遇到的问题

Webhook 诊断会访问 DMP 并可能调用外部 LLM，不能阻塞 HTTP 请求。另一方面，签名校验和 secret 配置如果处理不严谨，会导致接口在启用后接受未验证请求。

## 修复与验证

完成 Webhook 后进行了实际 HTTP 验证：

- 使用正确的 HMAC-SHA256 签名发送请求，确认请求能够正常接收。
- 使用错误签名发送请求，确认能够被拒绝。
- 检查 SQLite 中的 `webhook_events`，确认有效事件能够正确保存。
- 验证 Webhook 与后续诊断流程之间的数据传递关系。
