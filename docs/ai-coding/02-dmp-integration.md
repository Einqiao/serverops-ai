# 开发任务

## 需求

让独立的 ServerOps AI 服务通过 DMP API 自动获取目标房间的运行信息，为后续规则检测和 AI 诊断提供可靠输入。接入范围限定为当前客户端已经实现的只读接口。

## AI辅助方式

这一阶段主要先通过阅读 DMP 现有代码和接口实现，确认登录方式、Token 传递、API 路径以及返回数据结构，再确定 ServerOps AI 的客户端封装方式。

Cursor 主要用于辅助阅读和梳理已有代码，并根据已经确认的接口行为辅助完成客户端实现。完成后通过实际请求和返回结果进行验证，再针对接口行为和异常处理进行调整。

这一阶段的重点是先明确 DMP 的实际接口能力，再将其封装为 ServerOps AI 可以复用的客户端。

## 任务拆分

- 从配置和环境变量读取 DMP 地址、账号、密码、Token 和房间 ID。
- 实现 `POST /v3/user/login` 登录。
- 维护请求所需的 DMP Token，并处理响应中的 Token 更新。
- 封装房间、房间状态、系统状态、在线玩家和游戏日志接口。
- 将 DMP 的 `{code, message, data}` 响应解包成 Python 侧数据。
- 将 HTTP、业务错误和非 JSON 响应转换为 `DMPAPIError`。

## 实现过程

`app/dmp/client.py` 中的 `DMPClient` 使用 `requests.Session` 发起请求，默认 API 版本为 `v3`。认证由 `app/dmp/auth.py` 的 `AuthState` 管理，请求头使用 DMP 约定的 `X-DMP-TOKEN`。

当前封装的主要接口包括：

- `get_rooms()`：`GET /v3/room/permitted/basic`
- `get_room_status(room_id)`：`GET /v3/dashboard/info/base`
- `get_system_status()`：`GET /v3/dashboard/info/sys`
- `get_online_players(room_id)`：`GET /v3/player/online`
- `get_game_logs(room_id, lines, cursor)`：`GET /v3/logs/content`

日志请求会传递 `roomID`、`worldID`、`logType=game` 和 `lines`。客户端还会在认证请求返回 401 时重新登录并重试一次。

## 人工检查

人工检查了 URL 拼接、请求参数、Token 是否进入请求头、响应解包以及异常处理。特别确认了日志数据在 Python 侧最终作为字符串列表使用，而不是把整个响应对象直接交给检测器。

## 遇到的问题

DMP 的不同接口在请求参数和返回结构上存在一定差异，如果在业务代码中分别处理这些请求，后续维护和接口调整都会比较麻烦。

因此将登录、Token 处理以及 HTTP 请求统一收敛到 `DMPClient`，上层 Collector 只负责调用业务接口，不直接处理底层请求细节。

## 修复与验证

客户端集中实现 `_request()` 和 `_unwrap()`，统一处理认证、HTTP 错误和业务错误。随后进行过真实 DMP 只读验证，确认房间 4、Master world 207 的状态、在线玩家和游戏日志可以被读取；该过程没有修改 DMP 或 DST。

