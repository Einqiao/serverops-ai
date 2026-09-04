# 开发任务

## 需求

把规则检测到的异常转换成有限、可解释且经过脱敏的诊断上下文，再交给结构化 LLM Provider，最终得到可保存、可展示的 `DiagnosisReport`。LLM 不是日志采集器，也不能替代规则初筛。

## AI辅助方式

这一阶段先确定诊断流程采用“规则初筛 + LLM 辅助分析”的方式。

规则检测负责从日志中快速识别异常类型，并提供可解释的异常证据；LLM 不直接承担基础异常检测，而是基于已经整理好的上下文进一步生成原因、影响和处理建议。

在方案确定后，使用 Cursor 辅助实现规则检测、`DiagnosisContext`、Prompt 构造以及结构化 LLM Provider，并通过实际运行结果不断检查和调整。

## 任务拆分

- 定义 `DiagnosisContext`，承载事件、房间、世界、状态和日志。
- 从 DMP 获取房间状态、系统状态、在线玩家和有限日志。
- 使用 `detect_context()` 识别故障类型、严重程度、证据和匹配日志。
- 使用 `DiagnosisPromptBuilder` 生成有边界的 Prompt。
- 提供 `MockLLMProvider` 和 `SiliconFlowLLMProvider`。
- 将普通 JSON 或 fenced JSON 解析为 `DiagnosisReport`。
- 将有效报告保存到 Incident。
- 保证 LLM 不可用时，规则检测仍可以独立工作。


## 人工检查

人工检查了真实日志从采集到报告保存的连续链路，并使用 Mock Provider 验证了不依赖外部模型时的结构化流程。还检查了 Prompt 中的日志数量限制和敏感字段过滤。

## 遇到的问题

真实日志可能同时包含多种关键词，不能简单地把所有匹配结果直接交给模型，否则上下文容易膨胀，也难以确定当前主要异常。

因此需要先由规则检测确定主要故障类型和相关证据，再将有限上下文交给 LLM。

另外，外部 LLM 的响应存在不确定性，可能出现超时、fenced JSON 或非法 JSON 等情况。如果直接保存模型原始输出，后续 Incident 和 Dashboard 都难以稳定使用，因此需要增加统一的结构化解析和错误处理。

## 修复与验证

通过 `DiagnosisResult`、`DiagnosisPromptBuilder` 和 `DiagnosisReport` 分离规则结果、Prompt 和最终报告，并在解析失败时返回带 `diagnosis_error` 的报告对象。真实 DMP 日志曾检测到 `LUA_ERROR`，Mock 链路也验证了报告生成和 Incident 保存；SiliconFlow 的可用性则保持为配置和外部网络条件，不在代码中假设始终成功。

