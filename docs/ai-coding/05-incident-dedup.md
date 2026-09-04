# 开发任务

## 需求

解决轮询或重复事件导致同一异常不断创建 Incident 的问题。在不删除已有数据、不改变 DMPClient 和 RuleDetector 规则的前提下，将相同的 open 异常合并为一次 Incident，并记录出现次数和最近时间。

## AI辅助方式


这一部分由我先定位到“滑动日志窗口导致同一异常重复创建 Incident”的问题，并确定不修改 DMPClient 和 RuleDetector，而是在 Incident 持久化层解决。

AI Coding 主要用于分析 Incident 从检测、诊断到数据库保存的调用链，并辅助设计 fingerprint、增量迁移和重复更新逻辑。我负责判断 fingerprint 的组成以及哪些字段应该参与事件身份识别，并通过连续运行和不同异常组合进行验证。

没有通过重构核心检测规则来解决重复问题。

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

这一设计的重点不是“相同故障类型去重”，而是判断两个 Incident 是否代表同一个具体异常，因此将故障类型与异常证据一起纳入事件身份。

`storage/database.py` 在初始化时检查 `incidents` 表字段，并以 `ALTER TABLE` 增量补充 `event_type`、`fault_type`、诊断字段、`fingerprint`、`occurrence_count` 和 `last_seen`。旧记录在 fingerprint 为空时补算。

`save_incident()` 和 `save_diagnosis_incident()` 都会先查询相同 fingerprint 且状态为 `open` 的记录。找到后只更新次数和最近时间；找不到时才插入新记录。

## 人工检查

人工检查了 fingerprint 的组成，确认不同房间、世界、故障类型或核心证据不会被粗暴合并。还检查了旧数据库迁移逻辑、open 状态限制和 Dashboard 的 `first_seen`、`last_seen`、`occurrence_count` 字段。

## 遇到的问题

轮询日志使用滑动窗口时，同一条 Lua 错误可能在多轮采集中再次出现。若只按故障类型去重，不同 Lua 错误会被错误合并；若只按 Incident ID 判断，又无法识别重复事件。

## 修复与验证

采用稳定 fingerprint，并将重复判断集中在数据库保存层，避免影响上游日志采集和规则检测。

验证过程中连续读取真实 DMP 日志，确认同一 `LUA_ERROR` 不会重复创建新的 open Incident，而是更新原 Incident 的 `occurrence_count` 和 `last_seen`；进一步使用不同异常证据、故障类型或房间/世界进行测试，确认不同事件仍可以形成独立 Incident。

该改动最终实现了“检测层持续发现异常、存储层负责判断是否为同一事件”的职责分离。
