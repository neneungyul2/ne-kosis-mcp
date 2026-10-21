"""자격증명(KOSIS 인증키)과 .env 로딩."""
import locale
import os
import sys
from collections.abc import Mapping, MutableMapping
from pathlib import Path

API_KEY_NAME = "KOSIS_API_KEY"

SETUP_GUIDE = f"""
KOSIS 인증키를 환경변수로 설정하세요: {API_KEY_NAME}
  발급: https://kosis.kr/openapi > 활용신청 (로그인 필요)"""


class CredentialsError(Exception):
    pass


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def resolve_api_key(env: Mapping[str, str | None]) -> str:
    key = _clean(env.get(API_KEY_NAME))
    if key:
        return key
    raise CredentialsError(f"자격증명이 설정되지 않았습니다.{SETUP_GUIDE}")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _read_env_text(file: Path) -> str | None:
    """UTF-8(BOM 허용)로 읽고, 안 되면 이 PC의 기본 인코딩(예: 옛 메모장의 cp949)으로 다시 읽는다.
    읽을 수 없으면 파일 이름만 stderr에 알리고 건너뛴다 (내용은 출력하지 않는다)."""
    try:
        raw = file.read_bytes()
    except OSError:
        return None
    for encoding in ("utf-8-sig", locale.getpreferredencoding(False)):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    print(f"[경고] {file} 을(를) 읽을 수 없어 건너뜁니다 (UTF-8로 저장했는지 확인하세요).", file=sys.stderr)
    return None


def load_dotenv_if_present(
    path: Path | None = None, env: MutableMapping[str, str] | None = None
) -> None:
    """작업 폴더(또는 path)의 .env를 읽어 env에 채운다. 이미 값이 있는 변수는 덮어쓰지 않는다."""
    target = env if env is not None else os.environ
    file = path if path is not None else Path.cwd() / ".env"
    text = _read_env_text(file)
    if text is None:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key, value = key.strip(), _unquote(value.strip())
        if not sep or not key or not value:
            continue
        if _clean(target.get(key)) is None:
            target[key] = value
