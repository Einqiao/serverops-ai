"""Authentication state used by the DMP client."""

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass
class AuthState:
    """Holds the current JWT and accepts token rotation by the DMP server."""

    token: Optional[str] = None

    def headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"X-DMP-TOKEN": self.token}

    def update_from_response(self, headers: Mapping[str, Any]) -> None:
        token = headers.get("X-DMP-NEW-TOKEN") or headers.get("x-dmp-new-token")
        if token:
            self.token = str(token)

    def update_from_payload(self, payload: Any) -> None:
        if not isinstance(payload, Mapping):
            return
        data = payload.get("data")
        if isinstance(data, str) and data:
            self.token = data
            return
        for key in ("token", "access_token", "jwt"):
            value = payload.get(key)
            if value:
                self.token = str(value)
                return
        if isinstance(data, Mapping):
            self.update_from_payload(data)
