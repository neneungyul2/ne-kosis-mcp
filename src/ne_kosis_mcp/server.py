"""MCP 서버 조립과 실행 진입점."""
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .cache import default_cache
from .client import KosisClient
from .config import CredentialsError, load_dotenv_if_present, resolve_api_key
from .tool_filter import ToolRegistrar, parse_tool_allow_list
from .tools import register_all_tools

SERVER_NAME = "ne-kosis-mcp"


def create_server(
    client: KosisClient | None = None,
    *,
    allow: set[str] | None = None,
    export_dir: Path | None = None,
) -> MCPServer:
    """서버를 만들고 도구를 등록한다. 종료할 때 client를 닫는다."""

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if client is not None:
                await client.aclose()

    server = MCPServer(SERVER_NAME, lifespan=lifespan)
    registrar = ToolRegistrar(server, allow)
    register_all_tools(registrar, client, export_dir)
    registrar.warn_unknown()
    return server


def main() -> None:
    """stdio로 서버를 실행한다. stdout에는 MCP 프로토콜만 나가고 로그와 오류는 stderr로 간다."""
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv_if_present()
    try:
        api_key = resolve_api_key(os.environ)
    except CredentialsError as e:
        print(f"[오류] {e}", file=sys.stderr)
        sys.exit(1)
    allow = parse_tool_allow_list(os.environ.get("KOSIS_TOOLS_ALLOW"))
    client = KosisClient(api_key, cache=default_cache())
    create_server(client, allow=allow).run()


if __name__ == "__main__":
    main()
