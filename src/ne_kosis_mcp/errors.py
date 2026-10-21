"""KOSIS OpenAPI 오류 메시지 형식.

KOSIS는 실패해도 HTTP 200으로 `{"err": "...", "errMsg": "..."}` 를 돌려주는 것으로 알려져 있다.
공식 문서에 오류 형식이 없어 실제 호출로 확인하기 전까지는 방어적으로 다룬다.
"""
import json
import re

LABEL = "KOSIS"

# 오류 코드(err)별 안내. 코드 의미는 KOSIS 개발가이드의 에러코드표 기준이며 실제 호출로 검증이 필요하다.
CODE_HINTS = {
    "10": "인증키가 누락되었거나 올바르지 않습니다. KOSIS_API_KEY를 확인하세요.",
    "11": "인증키가 만료되었습니다. KOSIS에서 활용신청을 갱신하세요.",
    "20": "필수 요청변수가 누락되었습니다.",
    "21": "요청변수 값이 올바르지 않습니다. 코드와 기간 형식을 확인하세요.",
    "30": "조회 결과가 없습니다. 분류·항목 코드와 기간을 확인하세요.",
    "31": "조회 결과가 40,000셀을 넘습니다. 기간이나 분류를 좁히세요.",
    "40": "호출 가능 건수를 초과했습니다.",
    "41": "호출 가능 건수를 초과했습니다 (조회 결과 건수).",
    "42": "과도한 호출로 이용이 제한되었습니다.",
    "50": "KOSIS 서버 오류입니다. 잠시 후 다시 시도하세요.",
}

# 결과가 너무 커서 기간을 나눠 다시 요청하면 풀릴 수 있는 오류
TOO_LARGE_CODES = frozenset({"31"})
NO_DATA_CODES = frozenset({"30"})

_KEY_PARAM = re.compile(r"(apiKey=)[^&\s\"']+", re.IGNORECASE)


def mask_key(text: str) -> str:
    """URL이나 메시지에 섞인 apiKey 값을 가린다."""
    return _KEY_PARAM.sub(r"\1***", text)


def _stringify(body: object) -> str:
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    try:
        return json.dumps(body, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(body)


def format_api_error(url: str, status: int | None, body: object) -> str:
    """상태 코드, URL, 응답 본문을 담은 오류 메시지. 키 값은 절대 넣지 않는다."""
    status_text = "no response" if status is None else f"HTTP {status}"
    lines = [mask_key(f"[{LABEL}] {status_text} — {url}")]
    text = mask_key(_stringify(body))
    if text:
        lines.append(text)
    return "\n".join(lines)


def kosis_error_code(payload: object) -> tuple[str, str] | None:
    """KOSIS 오류 응답이면 (err, errMsg)를, 아니면 None을 돌려준다."""
    if isinstance(payload, dict) and "err" in payload:
        return str(payload.get("err")), str(payload.get("errMsg") or "")
    return None


def format_kosis_error(url: str, code: str, message: str) -> str:
    lines = [mask_key(f"[{LABEL}] 오류 {code} — {url}")]
    if message:
        lines.append(mask_key(message))
    hint = CODE_HINTS.get(code)
    if hint:
        lines.append(hint)
    return "\n".join(lines)
