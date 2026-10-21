"""KOSIS 도구: 통계표 찾기, 목록 탐색, 메타 조회, 자료 조회, 추이 분석, 내보내기."""
import json
import os
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from .. import analysis, periods
from ..catalog import find_in_catalog
from ..client import KosisClient
from ..export import Sheet, export_sheets
from ..tool_filter import ToolRegistrar

DEFAULT_RECENT = 5
DEFAULT_MAX_ROWS = 300
SUMMARY_CHARS = 200

LIMITATIONS = [
    "KOSIS 수치는 통계표마다 단위·기준(명목/실질, 조사 개편 시점)이 다릅니다. 시계열을 이을 때 통계표 주석을 확인하세요.",
    "'-', '…' 같은 통계부호 값은 숫자가 아니므로 계산에서 빠지고 결측으로 표시됩니다.",
]

Org = Annotated[str, Field(description="기관 ID (예: 통계청 101). find_table 결과의 orgId")]
Tbl = Annotated[str, Field(description="통계표 ID (예: DT_1B040A3). find_table 결과의 tblId")]
Itm = Annotated[
    str,
    Field(description="항목 ID. 여러 개는 공백으로 구분, 전체는 'ALL' (kosis_table_meta로 확인)"),
]
Cls = Annotated[
    list[str],
    Field(
        description="분류 코드 목록: 첫 원소가 분류1(objL1), 둘째가 분류2... 최대 8개. "
        "전체는 'ALL', 여러 값은 공백으로 구분 (예: [\"11 26\", \"ALL\"])"
    ),
]
PrdSe = Annotated[
    str, Field(description="수록주기: Y(년) H(반기) Q(분기) M(월) D(일) F(2~10년 주기) IR(부정기)")
]
Start = Annotated[str | None, Field(description="시작 시점 (주기별 형식: Y=YYYY, Q/H=YYYYQQ/HH, M=YYYYMM)")]
End = Annotated[str | None, Field(description="종료 시점 (시작 시점과 같은 형식)")]
Recent = Annotated[
    int | None,
    Field(description=f"최근 N개 시점. 시작/종료를 주지 않으면 {DEFAULT_RECENT}개를 조회합니다"),
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _validate_range(prd_se: str, start: str | None, end: str | None, recent: int | None) -> int | None:
    """조회 기간 인자를 검사하고 최종 recent(없으면 None)를 돌려준다."""
    if prd_se not in periods.FORMATS and prd_se != "S":
        raise ValueError(f"prd_se는 {', '.join(periods.PRD_SE_CODES)} 중 하나여야 합니다: {prd_se!r}")
    if recent is not None and (start or end):
        raise ValueError("recent와 start/end는 함께 쓸 수 없습니다")
    if recent is not None:
        if recent < 1:
            raise ValueError("recent는 1 이상이어야 합니다")
        return recent
    if start or end:
        if not (start and end):
            raise ValueError("start와 end를 함께 지정하세요")
        periods.validate_period(prd_se, start, "start")
        periods.validate_period(prd_se, end, "end")
        if start > end:
            raise ValueError(f"start({start})가 end({end})보다 늦습니다")
        return None
    return DEFAULT_RECENT


def _compact_row(row: dict) -> dict:
    """분류 이름은 있는 것만 'C1', 'C2'... 키 대신 분류명으로 풀어 쓴다."""
    out: dict[str, Any] = {"period": row.get("PRD_DE"), "item": row.get("ITM_NM")}
    for level in range(1, 9):
        name = row.get(f"C{level}_NM")
        if name is None and f"C{level}" not in row:
            break
        label = row.get(f"C{level}_OBJ_NM") or f"분류{level}"
        out[str(label)] = name or row.get(f"C{level}")
    out["value"] = row.get("DT")
    out["unit"] = row.get("UNIT_NM")
    return out


async def _fetch(
    client: KosisClient,
    org_id: str,
    tbl_id: str,
    itm_id: str,
    classifications: list[str],
    prd_se: str,
    start: str | None,
    end: str | None,
    recent: int | None,
) -> tuple[list[dict], int | None]:
    final_recent = _validate_range(prd_se, start, end, recent)
    # 반기는 문서의 두 표가 H와 S로 달리 적혀 있다. 호출에는 H를 쓰고, 안 되면 S를 시도한다.
    rows = await client.data(
        org_id=org_id,
        tbl_id=tbl_id,
        itm_id=itm_id,
        classifications=classifications,
        prd_se="H" if prd_se == "S" else prd_se,
        start=start,
        end=end,
        recent=final_recent,
    )
    return rows, final_recent


def _search_hit(row: dict) -> dict:
    summary = str(row.get("CONTENTS") or "")
    return {
        "orgId": row.get("ORG_ID"),
        "tblId": row.get("TBL_ID"),
        "title": row.get("TBL_NM"),
        "organization": row.get("ORG_NM"),
        "survey": row.get("STAT_NM"),
        "path": row.get("MT_ATITLE"),
        "coverage": f"{row.get('STRT_PRD_DE') or ''}~{row.get('END_PRD_DE') or ''}",
        "summary": summary[:SUMMARY_CHARS] + ("…" if len(summary) > SUMMARY_CHARS else ""),
        "link": row.get("LINK_URL"),
    }


def _group_meta(rows: list[dict]) -> dict:
    """ITM/OBJ 메타 행을 분류별 코드 목록으로 묶는다. 예상한 키가 없으면 원본 행을 그대로 돌려준다."""
    classifications: dict[str, dict] = {}
    for row in rows:
        obj_id = row.get("OBJ_ID")
        if obj_id is None:
            return {"raw": rows}
        entry = classifications.setdefault(
            str(obj_id),
            {"objId": obj_id, "name": row.get("OBJ_NM"), "level": row.get("OBJ_ID_SN"), "values": []},
        )
        entry["values"].append(
            {"id": row.get("ITM_ID"), "name": row.get("ITM_NM"), "parent": row.get("UP_ITM_ID")}
        )
    return {"classifications": list(classifications.values())}


def register_stats_tools(
    registrar: ToolRegistrar, client: KosisClient | None, export_dir: Path | None = None
) -> None:
    def need_client() -> KosisClient:
        if client is None:
            raise ValueError("KOSIS 클라이언트가 초기화되지 않았습니다 (KOSIS_API_KEY 확인)")
        return client

    def resolve_export_dir() -> Path:
        configured = export_dir or os.environ.get("KOSIS_EXPORT_DIR", "").strip()
        return Path(configured) if configured else Path.cwd() / "exports"

    async def find_table(
        query: Annotated[str, Field(description="찾을 통계 주제 (예: '시도별 초등학생 수', '사교육비', '출생아 수')")],
        max_results: Annotated[int, Field(description="최대 결과 수 (기본 10)")] = 10,
        include_search: Annotated[
            bool,
            Field(description="True면 카탈로그에 결과가 있어도 KOSIS 통합검색을 함께 실행합니다"),
        ] = False,
    ) -> str:
        found = find_in_catalog(query, max_results)
        result: dict[str, Any] = {"query": query}
        if found:
            result["catalog"] = found
        if not found or include_search:
            hits = await need_client().search(query, count=max_results)
            result["kosisSearch"] = [_search_hit(h) for h in hits]
        if not found:
            result["note"] = (
                "카탈로그에 일치하는 통계표가 없어 KOSIS 통합검색 결과를 보여줍니다. "
                "표 이름과 수록기간을 확인한 뒤 kosis_table_meta로 분류·항목 코드를 조회하세요."
            )
        result["nextStep"] = "kosis_table_meta(org_id, tbl_id)로 분류·항목 코드를 확인한 뒤 kosis_data로 조회하세요"
        return _json(result)

    async def kosis_search(
        query: Annotated[str, Field(description="KOSIS 통합검색어")],
        org_id: Annotated[str | None, Field(description="기관 ID로 좁히기 (선택)")] = None,
        sort: Annotated[str, Field(description="RANK(정확도순) 또는 DATE(최신순)")] = "RANK",
        page: Annotated[int, Field(description="페이지 번호 (1부터)")] = 1,
        count: Annotated[int, Field(description="페이지당 결과 수")] = 20,
    ) -> str:
        if sort not in ("RANK", "DATE"):
            raise ValueError("sort는 RANK 또는 DATE여야 합니다")
        hits = await need_client().search(query, org_id=org_id, sort=sort, page=page, count=count)
        return _json({"query": query, "page": page, "results": [_search_hit(h) for h in hits]})

    async def kosis_list(
        vw_cd: Annotated[
            str, Field(description="목록 구분: MT_ZTITLE(주제별), MT_OTITLE(기관별) 등")
        ] = "MT_ZTITLE",
        parent_id: Annotated[str, Field(description="상위 목록 ID (최상위는 빈 값이 아니라 '0')")] = "0",
    ) -> str:
        rows = await need_client().list_statistics(vw_cd, parent_id)
        return _json({"vwCd": vw_cd, "parentId": parent_id, "entries": rows})

    async def kosis_table_meta(org_id: Org, tbl_id: Tbl) -> str:
        c = need_client()
        items = await c.table_meta(org_id, tbl_id, "ITM")
        objects = await c.table_meta(org_id, tbl_id, "OBJ")
        return _json(
            {
                "orgId": org_id,
                "tblId": tbl_id,
                "items": items,
                "classificationLevels": _group_meta(objects),
                "usage": "kosis_data의 itm_id에는 items의 ITM_ID를, classifications에는 분류값 id를 넣으세요 (전체는 'ALL')",
            }
        )

    async def kosis_data(
        org_id: Org,
        tbl_id: Tbl,
        prd_se: PrdSe,
        itm_id: Itm = "ALL",
        classifications: Cls = ["ALL"],  # noqa: B006
        start: Start = None,
        end: End = None,
        recent: Recent = None,
        max_rows: Annotated[int, Field(description="응답에 담을 최대 행 수 (넘치면 kosis_export 사용)")] = DEFAULT_MAX_ROWS,
    ) -> str:
        rows, final_recent = await _fetch(
            need_client(), org_id, tbl_id, itm_id, classifications, prd_se, start, end, recent
        )
        shown = rows[:max_rows]
        return _json(
            {
                "orgId": org_id,
                "tblId": tbl_id,
                "table": rows[0].get("TBL_NM") if rows else None,
                "period": f"최근 {final_recent}개 시점" if final_recent else f"{start}~{end}",
                "totalRows": len(rows),
                "returnedRows": len(shown),
                "truncated": len(rows) > len(shown),
                "rows": [_compact_row(r) for r in shown],
                "limitations": LIMITATIONS,
            }
        )

    async def kosis_trend(
        org_id: Org,
        tbl_id: Tbl,
        prd_se: PrdSe,
        itm_id: Itm,
        classifications: Cls,
        start: Start = None,
        end: End = None,
        recent: Recent = None,
        group_by: Annotated[
            list[int],
            Field(description="시계열을 나눌 분류 번호 (예: [1]이면 분류1별로 한 줄씩). 기본 [1]"),
        ] = [1],  # noqa: B006
        include_series: Annotated[
            bool, Field(description="False면 요약(증감률·CAGR)만 돌려줍니다")
        ] = True,
    ) -> str:
        rows, final_recent = await _fetch(
            need_client(), org_id, tbl_id, itm_id, classifications, prd_se, start, end, recent
        )
        for level in group_by:
            if not 1 <= level <= 8:
                raise ValueError(f"group_by는 1~8 사이여야 합니다: {level}")
        series = analysis.group_series(rows, group_by)
        effective_se = "H" if prd_se == "S" else prd_se
        out = []
        for s in series:
            entry = analysis.summarize(s, effective_se)
            if include_series:
                entry["series_values"] = analysis.period_over_period(s)
            out.append(entry)
        return _json(
            {
                "orgId": org_id,
                "tblId": tbl_id,
                "table": rows[0].get("TBL_NM") if rows else None,
                "period": f"최근 {final_recent}개 시점" if final_recent else f"{start}~{end}",
                "seriesCount": len(out),
                "series": out,
                "limitations": LIMITATIONS
                + ["연평균 성장률(CAGR)은 첫 시점과 끝 시점 값만으로 계산하며, 시작값이 0 이하이면 계산하지 않습니다."],
            }
        )

    async def kosis_export(
        org_id: Org,
        tbl_id: Tbl,
        prd_se: PrdSe,
        itm_id: Itm = "ALL",
        classifications: Cls = ["ALL"],  # noqa: B006
        start: Start = None,
        end: End = None,
        recent: Recent = None,
        file_name: Annotated[str | None, Field(description="저장 파일 이름(확장자 제외). 기본: 통계표 ID")] = None,
    ) -> str:
        rows, _ = await _fetch(
            need_client(), org_id, tbl_id, itm_id, classifications, prd_se, start, end, recent
        )
        if not rows:
            raise ValueError("조회된 자료가 없어 파일을 만들지 않았습니다")
        flat = [_compact_row(r) for r in rows]
        columns = list(dict.fromkeys(k for r in flat for k in r))
        data_sheet = Sheet(
            "data", columns, [[analysis.parse_value(r.get(c)) if c == "value" else r.get(c) for c in columns] for r in flat]
        )
        levels = [lv for lv in range(1, 9) if any(f"C{lv}" in r for r in rows)]
        series = analysis.group_series(rows, levels)
        all_periods = sorted({p for s in series for p in s.points})
        wide_sheet = Sheet(
            "wide",
            ["series", *all_periods],
            [[s.key, *[s.points.get(p) for p in all_periods]] for s in series],
        )
        result = export_sheets([data_sheet, wide_sheet], resolve_export_dir(), file_name or tbl_id)
        return _json({"rows": len(rows), **result.to_dict()})

    registrar.register(
        "find_table",
        find_table,
        "자연어로 통계표를 찾습니다. 검증된 카탈로그(통계표 ID와 분류·항목 설명)를 먼저 보고, 없으면 KOSIS 통합검색으로 넘어갑니다. 통계 조회의 첫 단계입니다.",
    )
    registrar.register(
        "kosis_search",
        kosis_search,
        "KOSIS 통합검색을 직접 실행합니다 (기관·정렬·페이지 지정 가능). 카탈로그에 없는 통계표를 찾을 때 씁니다.",
    )
    registrar.register(
        "kosis_list",
        kosis_list,
        "KOSIS 통계목록(주제별/기관별 분류 트리)을 한 단계씩 탐색합니다.",
    )
    registrar.register(
        "kosis_table_meta",
        kosis_table_meta,
        "통계표의 항목(ITM)과 분류(OBJ) 코드를 조회합니다. kosis_data에 넣을 코드를 확인하는 단계입니다.",
    )
    registrar.register(
        "kosis_data",
        kosis_data,
        "통계표 자료를 조회합니다 (기간 지정 또는 최근 N개 시점). 결과가 40,000셀을 넘으면 기간을 자동으로 나눠 받습니다. 행이 많으면 kosis_export를 쓰세요.",
    )
    registrar.register(
        "kosis_trend",
        kosis_trend,
        "통계표 자료를 시계열로 묶어 직전 시점 대비 증감·증감률과 구간 요약(변화량, 증감률, 연평균 성장률 CAGR)을 계산합니다. 거시 추이와 시장 규모 변화를 볼 때 씁니다.",
    )
    registrar.register(
        "kosis_export",
        kosis_export,
        "통계표 자료를 엑셀(xlsx)과 CSV로 저장합니다 (원자료 시트 + 시점별 가로 표 시트). 저장 폴더는 KOSIS_EXPORT_DIR로 지정합니다.",
    )
