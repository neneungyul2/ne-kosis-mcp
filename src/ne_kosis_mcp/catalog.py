"""검증된 통계표 카탈로그: 자연어로 통계표(orgId + tblId)와 분류·항목 코드를 찾는다.

KOSIS 통합검색은 결과가 많고 엉뚱한 표가 섞이므로, 사람이 확인한 표를 `data/catalog.json`에 두고
먼저 찾는다. 항목 형식은 README의 "카탈로그" 절을 보라.
"""
import json
import sys
from functools import lru_cache
from importlib import resources

# 필드별 가중치: 키워드가 가장 정확한 신호이고, 설명은 약한 신호다
WEIGHTS = {"keywords": 30, "title": 20, "topic": 15, "description": 5}
WHOLE_QUERY_BONUS = 25


@lru_cache(maxsize=1)
def load_catalog() -> list[dict]:
    """패키지에 포함된 catalog.json을 읽는다 (작업 폴더와 무관). 실패하면 빈 목록."""
    try:
        text = (resources.files("ne_kosis_mcp") / "data" / "catalog.json").read_text(
            encoding="utf-8"
        )
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except (OSError, ValueError) as e:
        print(f"카탈로그 데이터 로딩 실패: {e}", file=sys.stderr)
        return []


def _field_text(entry: dict, field: str) -> str:
    value = entry.get(field)
    if isinstance(value, list):
        return " ".join(str(v) for v in value).lower()
    return str(value or "").lower()


def _score(entry: dict, query: str, tokens: list[str]) -> int:
    score = 0
    for field, weight in WEIGHTS.items():
        text = _field_text(entry, field)
        if not text:
            continue
        if query in text:
            score += weight + WHOLE_QUERY_BONUS
        score += sum(weight for token in tokens if token in text)
    return score


def find_in_catalog(
    query: str, max_results: int = 10, *, catalog: list[dict] | None = None
) -> list[dict]:
    """점수가 높은 순으로 카탈로그 항목을 돌려준다 (일치가 없으면 빈 목록)."""
    data = catalog if catalog is not None else load_catalog()
    q = query.lower().strip()
    if not q:
        return []
    tokens = [t for t in q.split() if t]
    scored = [(s, e) for e in data if (s := _score(e, q, tokens)) > 0]
    scored.sort(key=lambda t: (-t[0], str(t[1].get("id", ""))))
    return [{**e, "score": s} for s, e in scored[:max_results]]
