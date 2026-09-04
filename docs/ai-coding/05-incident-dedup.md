# 开发任务

## 需求

解决轮询或重复事件导致同一异常不断创建 Incident 的问题。在不删除已有数据、不改变 DMPClient 和 RuleDetector 规则的前提下，将相同的 open 异常合并为一次 Incident，并记录出现次数和最近时间。

## AI辅助方式

AI 辅助检查了 Incident 草稿、数据库初始化、诊断保存和 Dashboard 字段使用关系，并根据已有数据结构提出增量迁移和稳定 fingerprint 方案。没有通过重构核心检测规则来解决重复问题。

## 任务拆分

- 在 Incident 草稿中增加稳定 fingerprint。
- 将房间、世界、故障类型和核心证据纳入 fingerprint。
- 为旧表增加缺失字段，不删除已有数据。
- 保存 Incident 前查询相同 fingerprint 的 open 记录。
- 重复时递增 `occurrence_count` 并更新 `last_seen`。
- 保留 `detected_at` 作为首次发现时间。
- 让 Dashboard 使用这些字段展示历史和重复情况。

## 实现过程

`detector/incident.py` 的 `IncidentDraft.fingerprint` 会对证据进行归一化，去掉日志行前的时间戳样式前缀并排序，再结合 `room_id`、`world_id` 和故障类型计算 SHA-256。

`storage/database.py` 在初始化时检查 `incidents` 表字段，并以 `ALTER TABLE` 增量补充 `event_type`、`fault_type`、诊断字段、`fingerprint`、`occurrence_count` 和 `last_seen`。旧记录在 fingerprint 为空时补算。

`save_incident()` 和 `save_diagnosis_incident()` 都会先查询相同 fingerprint 且状态为 `open` 的记录。找到后只更新次数和最近时间；找不到时才插入新记录。

## 人工检查

人工检查了 fingerprint 的组成，确认不同房间、世界、故障类型或核心证据不会被粗暴合并。还检查了旧数据库迁移逻辑、open 状态限制和 Dashboard 的 `first_seen`、`last_seen`、`occurrence_count` 字段。

## 遇到的问题

轮询日志使用滑动窗口时，同一条 Lua 错误可能在多轮采集中再次出现。若只按故障类型去重，不同 Lua 错误会被错误合并；若只按 Incident ID 判断，又无法识别重复事件。

## 修复与验证

采用稳定 fingerprint，并让重复更新集中在数据库保存层。现有验证连续读取真实日志时，同一 `LUA_ERROR` 没有新增第二条 open Incident，已有记录的 `occurrence_count` 增加；使用不同证据或故障类型时仍可形成不同 Incident。该改动没有改变日志采集或规则匹配。

