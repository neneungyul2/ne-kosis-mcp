"""KOSIS_TOOLS_ALLOW로 노출할 도구를 제한하고, 예상된 실패를 ToolError로 바꾼다."""
import functools
import sys
import traceback
from collections.abc import Callable
from typing import Any, Protocol

from mcp.server.mcpserver.exceptions import ToolError

from .client import ApiError
from .config import CredentialsError

# 사용자가 이해하고 고칠 수 있는 "예상된 실패". mcp 2.x는 이 밖의 예외를 서버 충돌로 보고
# 원래 메시지를 클라이언트에 보내지 않으므로, 이 예외들은 ToolError로 바꿔 메시지를 전달한다.
EXPECTED_ERRORS: tuple[type[Exception], ...] = (ApiError, CredentialsError, ValueError)


def surface_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """예상된 실패를 ToolError로 바꿔 메시지가 클라이언트에 그대로 보이게 한다 (시그니처는 유지)."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except ToolError:
            raise
        except (*EXPECTED_ERRORS, OSError) as e:
            raise ToolError(str(e)) from e
        except Exception as e:  # noqa: BLE001
            # 스택은 서버 로그(stderr)에 남긴다. 예외 문구에는 인증키가 들어가지 않는다.
            traceback.print_exc(file=sys.stderr)
            raise ToolError(f"예상하지 못한 오류 ({type(e).__name__}): {e}") from e

    return wrapper


class _Server(Protocol):
    def add_tool(self, fn: Callable[..., Any], name: str | None = None, description: str | None = None, **kwargs: Any) -> None: ...


def parse_tool_allow_list(raw: str | None) -> set[str] | None:
    """쉼표 구분 이름의 집합. 비어 있으면 None(전체 허용)."""
    names = {s.strip() for s in (raw or "").split(",") if s.strip()}
    return names or None


class ToolRegistrar:
    """허용 목록에 있는 도구만 서버에 등록한다."""

    def __init__(self, server: _Server, allow: set[str] | None) -> None:
        self.server = server
        self.allow = allow
        self.known: set[str] = set()

    def register(self, name: str, fn: Callable[..., Any], description: str) -> None:
        self.known.add(name)
        if self.allow is not None and name not in self.allow:
            return
        self.server.add_tool(
            surface_errors(fn), name=name, description=description, structured_output=False
        )

    def warn_unknown(self) -> None:
        """허용 목록에 있지만 알려진 도구가 아닌 이름(오타 등)을 stderr에 경고한다."""
        if self.allow is None:
            return
        unknown = sorted(self.allow - self.known)
        if unknown:
            print(
                f"[경고] KOSIS_TOOLS_ALLOW에 알 수 없는 도구 이름이 있습니다: {', '.join(unknown)}",
                file=sys.stderr,
            )
