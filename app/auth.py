"""Small HS256 JWT implementation using only the Python standard library."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Return a salted PBKDF2 hash suitable for the demo user database."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 210_000)
    return f"pbkdf2_sha256${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_encoded, digest_encoded = encoded.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        calculated = hash_password(password, _b64decode(salt_encoded))
        return hmac.compare_digest(calculated, encoded)
    except (ValueError, TypeError):
        return False


def issue_token(subject: str, role: str, secret: str, lifetime_seconds: int = 8 * 3600) -> str:
    """Issue a compact HS256 JWT containing the authenticated role."""
    header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64encode(
        json.dumps(
            {"sub": subject, "role": role, "iat": int(time.time()), "exp": int(time.time()) + lifetime_seconds},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64encode(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def decode_token(token: str, secret: str) -> dict[str, Any]:
    """Validate signature and expiry and return the token claims."""
    try:
        header, payload, signature = token.split(".")
        expected = _b64encode(hmac.new(secret.encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            raise ValueError("bad signature")
        claims = json.loads(_b64decode(payload))
        if not isinstance(claims, dict) or int(claims.get("exp", 0)) < int(time.time()):
            raise ValueError("expired token")
        if not isinstance(claims.get("sub"), str) or not isinstance(claims.get("role"), str):
            raise ValueError("bad claims")
        return claims
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or expired authentication token") from exc
