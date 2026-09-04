# 开发任务

## 需求

把规则检测到的异常转换成有限、可解释且经过脱敏的诊断上下文，再交给结构化 LLM Provider，最终得到可保存、可展示的 `DiagnosisReport`。LLM 不是日志采集器，也不能替代规则初筛。

## AI辅助方式

AI 辅助梳理了 `DiagnosisContext`、`DiagnosisPromptBuilder`、Provider 和报告解析器之间的调用链，并协助检查 JSON 解析失败和外部请求失败的处理。文档不声称存在无法从代码确认的模型对话内容。

## 任务拆分

- 定义 `DiagnosisContext`，承载事件、房间、世界、状态和日志。
- 从 DMP 获取房间状态、系统状态、在线玩家和有限日志。
- 使用 `detect_context()` 识别故障类型、严重程度、证据和匹配日志。
- 使用 `DiagnosisPromptBuilder` 生成有边界的 Prompt。
- 提供 `MockLLMProvider` 和 `SiliconFlowLLMProvider`。
- 将普通 JSON 或 fenced JSON 解析为 `DiagnosisReport`。
- 将有效报告保存到 Incident。

## 实现过程

`app/diagnosis/context.py` 定义了 `DiagnosisContext`，并由 `collect_diagnosis_context()` 负责现场采集。`llm/diagnosis.py` 中的 Prompt Builder 只取最近有限数量的日志和匹配日志，并对状态数据中的 password、token、secret 等字段进行过滤。

规则检测完成后，`DiagnosisPromptBuilder.build(context, result)` 生成要求固定字段的 JSON 输出说明。Provider 返回文本后，由 `parse_diagnosis_response()` 解析为：

- `fault_type`
- `severity`
- `summary`
- `probable_cause`
- `evidence`
- `impact`
- `recommendations`

`MockLLMProvider` 用于本地链路验证；SiliconFlow Provider 使用配置的 OpenAI 兼容接口和模型。入口会把 Provider 失败视为可记录的诊断失败，而不是假装模型已经返回有效报告。

## 人工检查

人工检查了真实日志从采集到报告保存的连续链路，并使用 Mock Provider 验证了不依赖外部模型时的结构化流程。还检查了 Prompt 中的日志数量限制和敏感字段过滤。

## 遇到的问题

真实日志可能同时包含多种关键词，规则需要先选择主故障类型；外部 LLM 还可能超时、返回 fenced JSON 或非法 JSON。若直接把模型原文当作报告，数据库和 Dashboard 都难以稳定使用。

## 修复与验证

通过 `DiagnosisResult`、`DiagnosisPromptBuilder` 和 `DiagnosisReport` 分离规则结果、Prompt 和最终报告，并在解析失败时返回带 `diagnosis_error` 的报告对象。真实 DMP 日志曾检测到 `LUA_ERROR`，Mock 链路也验证了报告生成和 Incident 保存；SiliconFlow 的可用性则保持为配置和外部网络条件，不在代码中假设始终成功。

