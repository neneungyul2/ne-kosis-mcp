"""수록주기(prdSe)별 시점 형식 검증과 기간 분할.

KOSIS는 한 번에 40,000셀까지만 돌려주므로, 결과가 너무 크면 기간을 반으로 나눠 다시 요청한다.
"""
import re

# 수록주기 코드 → (시점 형식 정규식, 설명)
FORMATS: dict[str, tuple[re.Pattern[str], str]] = {
    "Y": (re.compile(r"^\d{4}$"), "YYYY"),
    "F": (re.compile(r"^\d{4}$"), "YYYY"),
    "H": (re.compile(r"^\d{4}0[12]$"), "YYYYHH (HH=01,02)"),
    "Q": (re.compile(r"^\d{4}0[1-4]$"), "YYYYQQ (QQ=01~04)"),
    "M": (re.compile(r"^\d{4}(0[1-9]|1[0-2])$"), "YYYYMM"),
    "D": (re.compile(r"^\d{8}$"), "YYYYMMDD"),
    "IR": (re.compile(r"^\d{4}(\d{2}(\d{2})?)?$"), "YYYY, YYYYMM 또는 YYYYMMDD"),
}
PRD_SE_CODES = tuple(FORMATS)
# 분할 가능한 주기와 한 해의 시점 수
_PER_YEAR = {"Y": 1, "H": 2, "Q": 4, "M": 12}


def validate_period(prd_se: str, value: str, label: str) -> None:
    if prd_se not in FORMATS:
        raise ValueError(f"prd_se는 {', '.join(PRD_SE_CODES)} 중 하나여야 합니다: {prd_se!r}")
    pattern, description = FORMATS[prd_se]
    if not pattern.match(value):
        raise ValueError(f"{label} 형식이 올바르지 않습니다: {value!r} (prd_se={prd_se} 는 {description})")


def _to_index(prd_se: str, value: str) -> int:
    year = int(value[:4])
    if prd_se == "Y":
        return year
    return year * _PER_YEAR[prd_se] + int(value[4:6]) - 1


def _from_index(prd_se: str, index: int) -> str:
    if prd_se == "Y":
        return f"{index:04d}"
    year, sub = divmod(index, _PER_YEAR[prd_se])
    return f"{year:04d}{sub + 1:02d}"


def can_split(prd_se: str, start: str, end: str) -> bool:
    """연/반기/분기/월 주기이고 시점이 2개 이상일 때만 기간을 나눌 수 있다."""
    return prd_se in _PER_YEAR and _to_index(prd_se, start) < _to_index(prd_se, end)


def split_range(prd_se: str, start: str, end: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """[start, end]를 시점 수가 비슷한 두 구간으로 나눈다 (겹치지 않음)."""
    if not can_split(prd_se, start, end):
        raise ValueError("더 나눌 수 없는 기간입니다")
    lo, hi = _to_index(prd_se, start), _to_index(prd_se, end)
    mid = (lo + hi) // 2
    return (start, _from_index(prd_se, mid)), (_from_index(prd_se, mid + 1), end)
