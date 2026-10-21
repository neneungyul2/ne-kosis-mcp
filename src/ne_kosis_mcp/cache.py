"""응답 값만 저장하는 파일 TTL 캐시와 API 호출 횟수 카운터."""
import hashlib
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")
_WARNED: set[str] = set()


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def cache_key(endpoint: str, params: object) -> str:
    """키 순서와 무관하게 같은 요청이면 같은 키(sha256 hex)."""
    return hashlib.sha256(f"{endpoint}\n{_stable_json(params)}".encode()).hexdigest()


class FileCache:
    """`<directory>/<key>.json`에 `{savedAt, value}`만 저장한다 (요청 인자와 헤더는 저장하지 않는다)."""

    def __init__(
        self, directory: Path, ttl_ms: int, now: Callable[[], float] | None = None
    ) -> None:
        self.directory = Path(directory)
        self.ttl_ms = ttl_ms
        self._now = now or (lambda: time.time() * 1000)

    def _file(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> object | None:
        try:
            raw = json.loads(self._file(key).read_text(encoding="utf-8"))
            saved_at = raw["savedAt"]
            if not isinstance(saved_at, int | float):
                return None
            if self._now() - saved_at > self.ttl_ms:
                return None
            return raw.get("value")
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def set(self, key: str, value: object) -> None:
        """저장은 최선 노력이다: 폴더를 쓸 수 없어도 이미 호출 비용을 치른 응답을 버리지 않는다."""
        if value is None:  # None은 "없음"과 구분할 수 없으므로 저장하지 않는다
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({"savedAt": self._now(), "value": value}, ensure_ascii=False)
            self._file(key).write_text(payload, encoding="utf-8")
        except OSError as e:
            directory = str(self.directory)
            if directory not in _WARNED:  # 같은 폴더의 경고는 한 번만
                _WARNED.add(directory)
                print(
                    f"[경고] 캐시를 저장할 수 없어 캐시 없이 계속합니다 ({directory}): {e}. "
                    "KOSIS_CACHE_DIR을 확인하세요.",
                    file=sys.stderr,
                )


def default_cache() -> FileCache:
    """환경변수 KOSIS_CACHE_DIR, KOSIS_CACHE_TTL_HOURS로 만든 캐시 (기본: 홈 폴더, 24시간)."""
    directory = os.environ.get("KOSIS_CACHE_DIR", "").strip() or str(
        Path.home() / ".ne-kosis-mcp" / "cache"
    )
    try:
        hours = float(os.environ.get("KOSIS_CACHE_TTL_HOURS", ""))
    except ValueError:
        hours = 0
    if not hours > 0:
        hours = 24
    return FileCache(Path(directory), ttl_ms=int(hours * 3600 * 1000))


@dataclass
class CallCounter:
    used: int = 0
    hit: int = 0


async def cached_call(
    cache: FileCache,
    counter: CallCounter,
    endpoint: str,
    params: object,
    fn: Callable[[], Awaitable[T]],
) -> T:
    """캐시에 있으면 hit만 세고, 없으면 fn을 호출해 used를 세고 저장한다."""
    key = cache_key(endpoint, params)
    cached = cache.get(key)
    if cached is not None:
        counter.hit += 1
        return cached  # type: ignore[return-value]
    value = await fn()
    counter.used += 1
    cache.set(key, value)
    return value
