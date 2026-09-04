"""Small, defensive HTTP client for the DMP API."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import requests

from .auth import AuthState


class DMPAPIError(RuntimeError):
    """Raised when the DMP API returns an HTTP or business error."""


class DMPClient:
    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        token: Optional[str] = None,
        timeout: float = 10.0,
        endpoints: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.auth = AuthState(token)
        self.endpoints = {
            "login": "/v3/user/login",
            "rooms": "/v3/room/permitted/basic",
            "room_status": "/v3/dashboard/info/base",
            "system_status": "/v3/dashboard/info/sys",
            "online_players": "/v3/player/online",
            "game_logs": "/v3/logs/content",
        }
        if endpoints:
            self.endpoints.update(endpoints)

    def login(self) -> Any:
        response = self._request(
            "POST",
            self.endpoints["login"],
            json={"username": self.username, "password": self.password},
            authenticated=False,
        )
        if isinstance(response, str):
            self.auth.token = response
        else:
            self.auth.update_from_payload(response)
        if not self.auth.token:
            raise DMPAPIError("登录响应中未找到 JWT token")
        return response

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Optional[Mapping[str, Any]] = None,
        authenticated: bool = True,
        retry_auth: bool = True,
    ) -> Any:
        if authenticated and not self.auth.token:
            self.login()
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"Accept": "application/json", **self.auth.headers()}
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DMPAPIError(f"DMP 请求失败: {exc}") from exc
        self.auth.update_from_response(response.headers)
        if response.status_code == 401 and authenticated and retry_auth:
            self.auth.token = None
            self.login()
            return self._request(
                method,
                endpoint,
                params=params,
                json=json,
                authenticated=True,
                retry_auth=False,
            )
        if response.status_code >= 400:
            raise DMPAPIError(f"DMP HTTP {response.status_code}: {response.text[:300]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DMPAPIError("DMP 返回了非 JSON 内容") from exc
        self.auth.update_from_payload(payload)
        return self._unwrap(payload)

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        if not isinstance(payload, Mapping) or "code" not in payload:
            return payload
        code = payload.get("code")
        if code not in (0, 200, "0", "200", None):
            raise DMPAPIError(str(payload.get("message") or f"DMP 业务错误 code={code}"))
        return payload.get("data", payload)

    @staticmethod
    def _endpoint(template: str, room_id: str) -> str:
        return template.format(room_id=room_id)

    def get_rooms(self) -> Any:
        return self._request("GET", self.endpoints["rooms"])

    def get_room_status(self, room_id: str) -> Any:
        return self._request("GET", self.endpoints["room_status"], params={"roomID": room_id})

    def get_system_status(self) -> Any:
        return self._request("GET", self.endpoints["system_status"])

    def get_online_players(self, room_id: str) -> Any:
        return self._request("GET", self.endpoints["online_players"], params={"roomID": room_id})

    def get_game_logs(
        self, room_id: str, *, lines: int = 200, cursor: Optional[str] = None
    ) -> Any:
        params: dict[str, Any] = {
            "roomID": room_id,
            "worldID": cursor or "",
            "logType": "game",
            "lines": lines,
        }
        return self._request(
            "GET",
            self.endpoints["game_logs"],
            params=params,
        )
