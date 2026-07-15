"""HTTP API, chat UI, and optional master-control UI for PermRAG."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sqlite3
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .auth import decode_token, issue_token
from .db import Database
from .retrieval import PermissionAwareRetriever
from .service import RagService


SAFE_ROLE_OR_USER = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


class PermRagApplication:
    def __init__(self, root: Path, master_enabled: bool = False) -> None:
        self.root = root.resolve()
        self.master_enabled = master_enabled
        self.secret = os.environ.get("PERMRAG_SECRET", "local-demo-only-change-me")
        self.database = Database(self.root / "data" / "permrag.sqlite3")
        self.database.initialize()
        self.retriever = PermissionAwareRetriever(self.root / "corpus", role_provider=self.database.role_names)
        self._gemini_key = os.environ.get("PERMRAG_GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        self._gemini_source = "environment" if self._gemini_key else "not configured"
        self._gemini_model = os.environ.get("PERMRAG_GEMINI_MODEL", "gemini-3.5-flash")
        self.service = RagService(self.retriever, self.database, self.gemini_settings)

    def gemini_settings(self) -> dict[str, str | None]:
        return {"key": self._gemini_key, "model": self._gemini_model}

    def public_gemini_state(self) -> dict[str, object]:
        return {"configured": bool(self._gemini_key), "model": self._gemini_model, "source": self._gemini_source}

    def configure_gemini(self, api_key: str, model: str, clear_key: bool) -> None:
        if clear_key:
            self._gemini_key, self._gemini_source = None, "not configured"
        elif api_key.strip():
            self._gemini_key, self._gemini_source = api_key.strip(), "master session"
        if model.strip():
            self._gemini_model = model.strip()

    def master_state(self) -> dict[str, object]:
        return {
            "roles": self.database.roles(), "users": self.database.users(),
            "documents": self.retriever.document_catalog(include_body=True), "gemini": self.public_gemini_state(),
        }

    def delete_role(self, role: str) -> None:
        if role == "admin":
            raise ValueError("The admin role is protected.")
        if any(role in document["allowed_roles"] for document in self.retriever.document_catalog()):
            raise ValueError("Remove this role from corpus permissions before deleting it.")
        self.database.delete_role(role)


class ApiHandler(SimpleHTTPRequestHandler):
    application: PermRagApplication

    def __init__(self, *args: Any, directory: str | None = None, **kwargs: Any) -> None:
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[PermRAG] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self.application.retriever._refresh_if_changed()
            return self._send_json(HTTPStatus.OK, {"status": "ok", "chunks": len(self.application.retriever.chunks)})
        if path == "/api/me":
            user = self._authenticated_user()
            if user:
                self._send_json(HTTPStatus.OK, {**user, "gemini": self.application.public_gemini_state()})
            return
        if path == "/api/audit":
            user = self._require_admin()
            if user:
                self._send_json(HTTPStatus.OK, {"entries": self.application.database.audit_rows()})
            return
        if path == "/api/documents":
            user = self._require_admin()
            if user:
                self._send_json(HTTPStatus.OK, {"documents": self.application.retriever.document_catalog()})
            return
        if path == "/api/master/state":
            user = self._require_master_admin()
            if user:
                self._send_json(HTTPStatus.OK, self.application.master_state())
            return
        if path in {"/master", "/master/"}:
            if not self.application.master_enabled:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "Start MASTERrun.py to enable the master console."})
            return self._send_file(self.application.root / "master_static" / "index.html")
        if path in {"/master.js", "/master.css"}:
            if not self.application.master_enabled:
                return self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return self._send_file(self.application.root / "master_static" / path.lstrip("/"))
        if path in {"/", "/index.html"}:
            return self._send_file(self.application.root / "static" / "index.html")
        if path in {"/app.js", "/styles.css"}:
            return self._send_file(self.application.root / "static" / path.lstrip("/"))
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        payload = self._read_json()
        if payload is None:
            return
        if path == "/api/login":
            user = self.application.database.authenticate(str(payload.get("username", "")), str(payload.get("password", "")))
            if not user:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Invalid username or password"})
                return
            self._send_json(HTTPStatus.OK, {"token": issue_token(user["username"], user["role"], self.application.secret), "user": user})
            return
        if path == "/api/chat":
            user = self._authenticated_user()
            if not user:
                return
            try:
                result = self.application.service.ask(username=user["username"], role=user["role"], query=str(payload.get("query", "")))
                self._send_json(HTTPStatus.OK, result)
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if path.startswith("/api/master/"):
            user = self._require_master_admin()
            if not user:
                return
            self._handle_master_post(path, payload, user)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _handle_master_post(self, path: str, payload: dict[str, Any], current_user: dict[str, str]) -> None:
        try:
            if path == "/api/master/roles":
                role = self._safe_name(payload.get("role"), "Role")
                self.application.database.create_role(role)
            elif path == "/api/master/roles/delete":
                self.application.delete_role(self._safe_name(payload.get("role"), "Role"))
            elif path == "/api/master/users":
                username = self._safe_name(payload.get("username"), "Username")
                password = str(payload.get("password", ""))
                if len(password) < 6:
                    raise ValueError("Password must contain at least 6 characters.")
                self.application.database.create_user(username, password, str(payload.get("role", "")).strip().lower())
            elif path == "/api/master/users/delete":
                username = self._safe_name(payload.get("username"), "Username")
                if username == current_user["username"]:
                    raise ValueError("You cannot delete the account currently controlling the master console.")
                self.application.database.delete_user(username)
            elif path == "/api/master/documents":
                roles = payload.get("allowed_roles", [])
                if not isinstance(roles, list):
                    raise ValueError("Permissions must be a list of roles.")
                self.application.retriever.upsert_document(
                    relative_path=str(payload.get("path", "")), department=str(payload.get("department", "")),
                    allowed_roles=[str(role) for role in roles], sensitivity=str(payload.get("sensitivity", "internal")),
                    body=str(payload.get("body", "")),
                )
            elif path == "/api/master/documents/delete":
                self.application.retriever.delete_document(str(payload.get("path", "")))
            elif path == "/api/master/gemini":
                self.application.configure_gemini(str(payload.get("api_key", "")), str(payload.get("model", "")), bool(payload.get("clear_key")))
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "state": self.application.master_state()})
        except (ValueError, sqlite3.IntegrityError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    @staticmethod
    def _safe_name(value: object, label: str) -> str:
        name = str(value).strip().lower()
        if not SAFE_ROLE_OR_USER.fullmatch(name):
            raise ValueError(f"{label} must use 2–32 lowercase letters, numbers, _ or -.")
        return name

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 80_000:
                raise ValueError("Request body is too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            return payload
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return None

    def _authenticated_user(self) -> dict[str, str] | None:
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
            return None
        try:
            claims = decode_token(authorization[7:], self.application.secret)
            user = self.application.database.current_user(str(claims["sub"]))
            if not user or user["role"] != claims["role"]:
                raise ValueError("Account is no longer active")
            return user
        except ValueError as exc:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
            return None

    def _require_admin(self) -> dict[str, str] | None:
        user = self._authenticated_user()
        if user and user["role"] != "admin":
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Admin role required"})
            return None
        return user

    def _require_master_admin(self) -> dict[str, str] | None:
        if not self.application.master_enabled:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Start MASTERrun.py to enable the master console."})
            return None
        return self._require_admin()

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(root: Path, host: str, port: int, master_enabled: bool = False) -> None:
    application = PermRagApplication(root, master_enabled=master_enabled)

    class BoundHandler(ApiHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(application.root / "static"), **kwargs)

    BoundHandler.application = application
    server = ThreadingHTTPServer((host, port), BoundHandler)
    print(f"PermRAG is running at http://{host}:{port}")
    if master_enabled:
        print(f"Master Control Center: http://{host}:{port}/master")
    print("Demo accounts: sales, engineering, hr, finance, admin (password equals username)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPermRAG stopped.")
    finally:
        server.server_close()
