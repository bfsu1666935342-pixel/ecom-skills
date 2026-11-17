"""Provider adapters: Sorftime and a configurable generic MCP provider (SIF)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from mcp_client import MCPClient, MCPError, retry_call

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "providers.json"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def load_provider_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise MCPError(f"Missing provider config: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


class Provider:
    """Canonical provider interface used by fetch/normalize."""

    canonical_tools = [
        "category_search",
        "category_report",
        "category_products",
        "category_keywords",
        "category_trend",
        "keyword_detail",
        "keyword_trend",
        "keyword_search_results",
        "product_detail",
        "product_customers_say",
        "product_content",
        "category_tree",
    ]

    def __init__(self, name: str, url: str, key: str, tool_map: Dict[str, str]) -> None:
        if not url:
            raise MCPError(f"{name}: MCP URL is empty")
        self.name = name
        self.client = MCPClient(url, key)
        self.tool_map = tool_map

    def tool(self, canonical: str) -> str:
        name = self.tool_map.get(canonical)
        if not name:
            raise MCPError(
                f"{self.name}: no tool mapping for '{canonical}'. "
                f"Edit config/providers.json after running `doctor --list-tools`."
            )
        return name

    def call(self, canonical: str, args: Dict[str, Any]) -> Any:
        return retry_call(self.client, self.tool(canonical), args)

    def doctor(self) -> Dict[str, Any]:
        tools = self.client.list_tools()
        names = {t.get("name") for t in tools}
        missing = [k for k in self.canonical_tools if not self.tool_map.get(k) or self.tool_map[k] not in names]
        return {"provider": self.name, "tools": sorted(names), "missing_mapped_tools": missing}


class SorftimeProvider(Provider):
    def __init__(self) -> None:
        cfg = load_provider_config()["sorftime"]
        url = os.getenv("SORFTIME_MCP_URL", "https://mcp.sorftime.com")
        key = os.getenv("SORFTIME_MCP_KEY", "")
        super().__init__("sorftime", url, key, cfg["tools"])


class SIFProvider(Provider):
    """SIF is supported through the same MCP protocol.

    Tool names vary by SIF deployment. Fill config/providers.json -> sif.tools
    after running `doctor --provider sif --list-tools`.
    """

    def __init__(self) -> None:
        cfg = load_provider_config()["sif"]
        url = os.getenv("SIF_MCP_URL", "")
        key = os.getenv("SIF_MCP_KEY", "")
        super().__init__("sif", url, key, cfg.get("tools", {}))


def get_provider(name: str) -> Provider:
    load_dotenv(ROOT / ".env")
    name = (name or "").lower()
    if name == "sorftime":
        return SorftimeProvider()
    if name == "sif":
        return SIFProvider()
    raise MCPError(f"Unknown provider: {name}. Use sorftime or sif.")
