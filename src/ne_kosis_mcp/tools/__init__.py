"""도구 등록."""
from pathlib import Path

from ..client import KosisClient
from ..tool_filter import ToolRegistrar
from .stats import register_stats_tools


def register_all_tools(
    registrar: ToolRegistrar, client: KosisClient | None, export_dir: Path | None = None
) -> None:
    register_stats_tools(registrar, client, export_dir)
