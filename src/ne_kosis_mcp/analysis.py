"""KOSIS 자료 행을 시계열로 바꾸고 증감률과 연평균 성장률(CAGR)을 계산한다."""
import math
import re
from dataclasses import dataclass

# KOSIS 수치값(DT)은 문자열이고, 값이 없으면 "-", "…", "X" 같은 통계부호가 올 수 있다.
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def parse_value(raw: object) -> float | None:
    """쉼표를 없애 숫자로 바꾼다. 숫자가 아니면(통계부호, 빈 값) None."""
    if isinstance(raw, int | float):
        return float(raw)
    if not isinstance(raw, str):
        return None
    text = raw.strip().replace(",", "")
    return float(text) if _NUMBER.match(text) else None


def class_label(row: dict, level: int) -> str:
    """분류 level(1~8)의 값 이름. 이름이 없으면 코드."""
    return str(row.get(f"C{level}_NM") or row.get(f"C{level}") or "")


@dataclass
class Series:
    key: str
    points: dict[str, float | None]  # 시점 → 값 (시점 오름차순)


def group_series(
    rows: list[dict], group_levels: list[int], item: str | None = None
) -> list[Series]:
    """행을 (분류 level들의 이름 + 항목명) 별로 묶어 시점→값 시계열로 만든다.
    같은 키와 시점이 겹치면 합산하지 않고 마지막 값을 쓴다 (KOSIS는 겹치는 행을 주지 않는다)."""
    grouped: dict[str, dict[str, float | None]] = {}
    for row in rows:
        parts = [class_label(row, lv) for lv in group_levels]
        item_name = str(row.get("ITM_NM") or "")
        if item is None and item_name:
            parts.append(item_name)
        unit = str(row.get("UNIT_NM") or "")
        key = " / ".join(p for p in parts if p) or item_name or "전체"
        if unit:
            key = f"{key} ({unit})"
        period = str(row.get("PRD_DE") or "")
        grouped.setdefault(key, {})[period] = parse_value(row.get("DT"))
    return [Series(k, dict(sorted(v.items()))) for k, v in grouped.items()]


def _years_between(first: str, last: str, prd_se: str) -> float | None:
    """첫 시점과 끝 시점 사이의 햇수. 알 수 없으면 None."""
    if prd_se in ("Y", "F"):
        return float(int(last[:4]) - int(first[:4]))
    if prd_se in ("H", "S", "Q", "M"):
        per_year = {"H": 2, "S": 2, "Q": 4, "M": 12}[prd_se]
        lo = int(first[:4]) * per_year + int(first[4:6]) - 1
        hi = int(last[:4]) * per_year + int(last[4:6]) - 1
        return (hi - lo) / per_year
    return None


def cagr(first_value: float, last_value: float, years: float) -> float | None:
    """연평균 성장률(%). 시작값이 0 이하이거나 끝값이 음수, 기간이 0 이하면 계산하지 않는다."""
    if years <= 0 or first_value <= 0 or last_value < 0:
        return None
    return (math.pow(last_value / first_value, 1 / years) - 1) * 100


def summarize(series: Series, prd_se: str) -> dict:
    """시작·끝 값, 증감, 증감률(%), 연평균 성장률(%), 결측 시점 수."""
    valued = [(p, v) for p, v in series.points.items() if v is not None]
    missing = [p for p, v in series.points.items() if v is None]
    result: dict = {
        "series": series.key,
        "points": len(series.points),
        "missingPeriods": missing,
    }
    if len(valued) < 2:
        result["note"] = "비교할 수 있는 값이 2개 미만입니다"
        return result
    (p0, v0), (p1, v1) = valued[0], valued[-1]
    result.update(
        {
            "from": {"period": p0, "value": v0},
            "to": {"period": p1, "value": v1},
            "change": v1 - v0,
            "changePct": None if v0 == 0 else (v1 - v0) / abs(v0) * 100,
        }
    )
    years = _years_between(p0, p1, prd_se)
    result["cagrPct"] = cagr(v0, v1, years) if years else None
    return result


def period_over_period(series: Series) -> list[dict]:
    """직전 시점 대비 증감과 증감률(%)."""
    out: list[dict] = []
    previous: float | None = None
    for period, value in series.points.items():
        entry: dict = {"period": period, "value": value}
        if value is not None and previous is not None:
            entry["change"] = value - previous
            entry["changePct"] = None if previous == 0 else (value - previous) / abs(previous) * 100
        out.append(entry)
        if value is not None:
            previous = value
    return out
