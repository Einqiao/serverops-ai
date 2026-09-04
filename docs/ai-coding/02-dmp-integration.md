# 开发任务

## 需求

让独立的 ServerOps AI 服务通过 DMP API 自动获取目标房间的运行信息，为后续规则检测和 AI 诊断提供可靠输入。接入范围限定为当前客户端已经实现的只读接口。

## AI辅助方式

AI 辅助检查了 DMP 客户端的请求封装、认证状态管理、响应解包和调用方使用方式，并根据源码整理接口职责。没有把浏览器抓包或无法确认的接口行为写入本记录。

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

真实 DMP 的业务响应外层包含统一字段，客户端如果不解包，调用方会误把 `data` 外层当成日志内容。认证过期时也需要避免直接把 401 当作普通日志采集失败。

## 修复与验证

客户端集中实现 `_request()` 和 `_unwrap()`，统一处理认证、HTTP 错误和业务错误。随后进行过真实 DMP 只读验证，确认房间 4、Master world 207 的状态、在线玩家和游戏日志可以被读取；该过程没有修改 DMP 或 DST。

