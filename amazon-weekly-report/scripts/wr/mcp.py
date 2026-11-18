"""MCP Streamable HTTP client (stdlib only).

Supports:
- initialize / notifications/initialized / tools/list (cursor pagination) / tools/call
- auth by header (e.g. Lingxing X-Mcp-Key) or query parameter (e.g. Sorftime ?key=)
- session id returned through ``mcp-session-id``
- application/json and text/event-stream responses
- retry on 429 / 5xx and network errors

Secrets are never logged.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class MCPError(RuntimeError):
    pass


def _with_query(url: str, key: str, param: str) -> str:
    if not key:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if param and param not in query:
        query[param] = key
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _parse(text: str, content_type: str, request_id: Optional[int] = None) -> Dict[str, Any]:
    if "text/event-stream" in (content_type or "").lower():
        events: List[Dict[str, Any]] = []
        current: List[str] = []
        for raw_line in text.splitlines():
            line = raw_line.rstrip("\r")
            if not line:
                if current:
                    payload = "\n".join(current)
                    current = []
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        events.append(obj)
                continue
            if line.startswith("data:"):
                current.append(line[5:].strip())
        if current:
            try:
                obj = json.loads("\n".join(current))
                if isinstance(obj, dict):
                    events.append(obj)
            except json.JSONDecodeError:
                pass
        if not events:
            raise MCPError("MCP returned an SSE stream without JSON data")
        for event in reversed(events):
            if request_id is None or event.get("id") == request_id or "result" in event or "error" in event:
                return event
        return events[-1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MCPError(f"MCP returned non-JSON: {text[:200]}") from exc
    if not isinstance(obj, dict):
        raise MCPError("MCP returned unexpected JSON")
    return obj


class MCPClient:
    def __init__(
        self,
        url: str,
        key: str = "",
        *,
        auth: str = "query",          # query | header | none
        key_param: str = "key",
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 45,
        label: str = "mcp",
        verbose: bool = False,
    ) -> None:
        if not url:
            raise MCPError(f"{label}: MCP url is empty")
        self.label = label
        self.verbose = verbose
        self.timeout = timeout
        self.headers = dict(headers or {})
        self.auth = auth
        self.key = key
        if auth == "query":
            url = _with_query(url, key, key_param)
        elif auth == "header" and key:
            self.headers.setdefault(key_param, key)
        self.url = url
        self.protocol = "2024-11-05"
        self.session_id = ""
        self._seq = 0
        self._initialized = False

    # ------------------------------------------------------------------ transport
    def _request_headers(self) -> Dict[str, str]:
        head = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "amazon-weekly-report/1.0",
        }
        if self._initialized:
            head["MCP-Protocol-Version"] = self.protocol
        if self.session_id:
            head["mcp-session-id"] = self.session_id
        head.update(self.headers)
        return head

    def _post(self, payload: Dict[str, Any], *, retries: int = 2) -> Optional[Dict[str, Any]]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last: Optional[Exception] = None
        for attempt in range(retries + 1):
            request = urllib.request.Request(self.url, data=body, headers=self._request_headers(), method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    sid = response.headers.get("mcp-session-id")
                    if sid:
                        self.session_id = sid
                    text = response.read().decode("utf-8", errors="replace")
                    status = response.status
                    ctype = response.headers.get("content-type", "")
                if status in (202, 204) or not text.strip():
                    return None
                obj = _parse(text, ctype, payload.get("id"))
                if "error" in obj and obj["error"]:
                    err = obj["error"]
                    raise MCPError(f"{self.label} error {err.get('code')}: {err.get('message')}")
                return obj
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                if exc.code in (401, 403):
                    raise MCPError(f"{self.label} 鉴权失败 HTTP {exc.code}: {detail}") from exc
                if exc.code == 429 or exc.code >= 500:
                    last = MCPError(f"{self.label} HTTP {exc.code}: {detail}")
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise MCPError(f"{self.label} HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                last = MCPError(f"{self.label} 连接失败: {exc.reason}")
                time.sleep(1.0 * (attempt + 1))
                continue
        raise last or MCPError(f"{self.label} request failed")

    def _send(self, method: str, params: Optional[Dict[str, Any]] = None, *, notify: bool = False) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            self._seq += 1
            payload["id"] = self._seq
        if params is not None:
            payload["params"] = params
        return self._post(payload)

    # ------------------------------------------------------------------ protocol
    def initialize(self) -> Dict[str, Any]:
        result = self._send(
            "initialize",
            {
                "protocolVersion": self.protocol,
                "capabilities": {},
                "clientInfo": {"name": "amazon-weekly-report", "version": "1.0.0"},
            },
        )
        payload = (result or {}).get("result") or {}
        if payload.get("protocolVersion"):
            self.protocol = payload["protocolVersion"]
        self._initialized = True
        try:
            self._send("notifications/initialized", None, notify=True)
        except MCPError:
            pass
        return payload

    def ensure(self) -> None:
        if not self._initialized:
            self.initialize()

    def list_tools(self) -> List[Dict[str, Any]]:
        self.ensure()
        tools: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(20):
            result = self._send("tools/list", {"cursor": cursor} if cursor else {})
            payload = (result or {}).get("result") or {}
            batch = payload.get("tools") or []
            tools.extend(batch)
            cursor = payload.get("nextCursor")
            if not cursor or not batch:
                break
        return tools

    def call(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        self.ensure()
        result = (self._send("tools/call", {"name": name, "arguments": arguments or {}}) or {}).get("result") or {}
        if result.get("isError"):
            raise MCPError(f"{self.label} tool {name} returned error: {_content_text(result)[:400]}")
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content") or []
        if not content:
            return None
        text = _content_text(result)
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"_text": text} if text else None


def _content_text(result: Dict[str, Any]) -> str:
    blocks = result.get("content") or []
    parts: List[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif block.get("type") == "resource":
            resource = block.get("resource") or {}
            parts.append(str(resource.get("text") or resource.get("uri") or ""))
    return "\n".join(parts)


def rows_from(payload: Any) -> List[Dict[str, Any]]:
    """Find the first list-of-dicts in a nested MCP payload."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "list", "rows", "records", "result", "items", "content"):
        value = payload.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
        if isinstance(value, dict):
            found = rows_from(value)
            if found:
                return found
    for value in payload.values():
        if isinstance(value, dict):
            found = rows_from(value)
            if found:
                return found
    return []
