"""Small MCP Streamable HTTP client used by the category-decision skill.

Standard library only: no requests / httpx dependency.
- POST JSON-RPC to an MCP endpoint
- keep cookies across initialize -> tools/call
- accept application/json or text/event-stream
- never log the API key
"""

from __future__ import annotations

import http.cookiejar
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class MCPError(RuntimeError):
    pass


def _with_key(url: str, key: str) -> str:
    if not key:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "key" not in query:
        query["key"] = key
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _parse_payload(text: str, content_type: str) -> Dict[str, Any]:
    if "text/event-stream" in (content_type or "").lower():
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
        raise MCPError("MCP returned an SSE stream without a JSON data event")
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MCPError("MCP returned non-JSON response") from exc
    if not isinstance(obj, dict):
        raise MCPError("MCP returned an unexpected JSON payload")
    return obj


class MCPClient:
    def __init__(
        self,
        url: str,
        key: str = "",
        timeout: int = 60,
        protocol_version: str = "2024-11-05",
        user_agent: str = "category-decision-skill/1.0",
    ) -> None:
        self.url = _with_key(url, key)
        self.timeout = timeout
        self.protocol_version = protocol_version
        self.user_agent = user_agent
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self._initialized = False
        self._request_id = 0

    def _headers(self) -> Dict[str, str]:
        h = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        if self._initialized:
            h["MCP-Protocol-Version"] = self.protocol_version
        return h

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, headers=self._headers(), method="POST")
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
                ctype = resp.headers.get("content-type", "")
                status = resp.status
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise MCPError(f"MCP HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise MCPError(f"MCP connection failed: {exc.reason}") from exc
        if status >= 400:
            raise MCPError(f"MCP HTTP {status}")
        obj = _parse_payload(text, ctype)
        if "error" in obj:
            err = obj["error"]
            raise MCPError(f"MCP error {err.get('code')}: {err.get('message')}")
        return obj

    def initialize(self) -> Dict[str, Any]:
        self._request_id += 1
        result = self._post({
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": self.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "category-decision-skill", "version": "1.0.0"},
            },
        })
        # Mark initialized before notification so the protocol header is sent.
        self._initialized = True
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except MCPError:
            pass
        return result

    def ensure_initialized(self) -> None:
        if not self._initialized:
            self.initialize()

    def list_tools(self) -> list[Dict[str, Any]]:
        self.ensure_initialized()
        self._request_id += 1
        obj = self._post({"jsonrpc": "2.0", "id": self._request_id, "method": "tools/list", "params": {}})
        return ((obj.get("result") or {}).get("tools") or [])

    def call(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        self.ensure_initialized()
        self._request_id += 1
        obj = self._post({
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        result = obj.get("result") or {}
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content") or []
        if not content:
            return None
        first = content[0]
        if first.get("type") == "text":
            text = first.get("text", "")
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        return first


def retry_call(client: MCPClient, name: str, args: Dict[str, Any], attempts: int = 3, delay: float = 1.5) -> Any:
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            return client.call(name, args)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i + 1 < attempts:
                time.sleep(delay * (i + 1))
    raise MCPError(f"{name} failed after {attempts} attempts: {last}")
