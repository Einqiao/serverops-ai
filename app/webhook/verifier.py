"""HMAC-SHA256 verification for DMP webhook requests."""

from __future__ import annotations

import hashlib
import hmac


def verify_signature(body: bytes, signature: str, secret: str, enabled: bool = True) -> bool:
    if not enabled:
        return True
    if not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return bool(signature) and hmac.compare_digest(expected, signature.strip())
