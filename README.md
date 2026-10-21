# ne-kosis-mcp

국가통계포털(KOSIS) OpenAPI를 쓰는 MCP(Model Context Protocol) 서버입니다. 인구, 지역별 학생 수, 사교육비 같은 통계를 찾고(`find_table`), 조회하고(`kosis_data`), 추이와 성장률을 계산하고(`kosis_trend`), 엑셀/CSV로 내보냅니다(`kosis_export`). 거시 트렌드와 시장 규모 파악이 목적입니다.

> **구조 참고:** 설정, 캐시, 도구 허용 목록, 내보내기 구조는 [ne-naver-api-mcp](../naver-search-mcp)(원본: [isnow890/naver-search-mcp](https://github.com/isnow890/naver-search-mcp), MIT License)에서 가져왔습니다. 원본의 저작권 고지는 [`LICENSE`](LICENSE)에 그대로 유지됩니다.

## 상태

- **키 없이 검증한 것:** 단위 테스트(가짜 응답), 기간 분할, 수치 파싱, 증감률·CAGR 계산, 카탈로그 검색, 서버 도구 등록.
- **실제 KOSIS 호출로 아직 검증하지 못한 것:** 응답 구조, 오류 형식(`err`/`errMsg`), 메타(`getMeta` ITM/OBJ) 응답 키, 반기 코드(`H` vs `S`), `parentListId`/`parentId` 중 맞는 이름. KOSIS 문서에 샘플 응답이 없어 추정으로 구현했습니다. 키를 넣고 `KOSIS_LIVE_TEST=1 uv run pytest tests/live`로 확인하세요.
- **카탈로그(`data/catalog.json`)는 비어 있습니다.** 통계표 ID를 기억에 의존해 적으면 틀린 값이 들어갈 수 있어서, 키로 실제 호출해 검증한 표만 넣기로 했습니다. 아래 "카탈로그 채우기"를 보세요. 그전에는 `find_table`이 KOSIS 통합검색으로 대신합니다.

## 도구 (7개)

| 도구 | 하는 일 |
|---|---|
| `find_table` | 자연어로 통계표를 찾습니다. 카탈로그 → 없으면 KOSIS 통합검색 |
| `kosis_search` | KOSIS 통합검색 직접 실행 (기관, 정렬, 페이지) |
| `kosis_list` | 주제별/기관별 통계목록 트리 탐색 |
| `kosis_table_meta` | 통계표의 항목(ITM)과 분류(OBJ) 코드 조회 |
| `kosis_data` | 자료 조회 (기간 지정 또는 최근 N개 시점). 40,000셀을 넘으면 기간을 자동 분할 |
| `kosis_trend` | 시계열로 묶어 직전 시점 대비 증감률, 구간 변화량·증감률·연평균 성장률(CAGR) 계산 |
| `kosis_export` | `<표ID>.xlsx`(원자료 + 시점별 가로 표)와 시트별 CSV(UTF-8 BOM) 저장 |

권장 흐름: `find_table` → `kosis_table_meta` → `kosis_data` 또는 `kosis_trend` → `kosis_export`.

## 설치

필요한 것: [uv](https://docs.astral.sh/uv/), KOSIS 인증키(<https://kosis.kr/openapi> 로그인 후 활용신청).

```
claude mcp add ne-kosis -s user ^
  -e KOSIS_API_KEY=발급키 ^
  -e KOSIS_EXPORT_DIR=C:\Users\내이름\Documents\kosis-exports ^
  -- uvx --from D:\repos\ne-kosis-mcp ne-kosis-mcp
```

(줄 끝 `^`는 Windows cmd의 줄 이음입니다.) 개발 중에는 이 폴더의 `.env`에 `KOSIS_API_KEY=...`를 넣으면 서버가 읽습니다(`.env`는 git에 올라가지 않습니다).

### 환경변수

| 이름 | 설명 | 기본값 |
|---|---|---|
| `KOSIS_API_KEY` | KOSIS 인증키 (필수) | — |
| `KOSIS_EXPORT_DIR` | 엑셀/CSV 저장 폴더. 지정을 권장합니다 | `<작업 폴더>/exports` |
| `KOSIS_CACHE_DIR` | API 응답 캐시 폴더 | `<홈>/.ne-kosis-mcp/cache` |
| `KOSIS_CACHE_TTL_HOURS` | 캐시 유지 시간 | `24` |
| `KOSIS_TOOLS_ALLOW` | 노출할 도구 이름(쉼표 구분, 비우면 전체) | 전체 |

## 카탈로그

`src/ne_kosis_mcp/data/catalog.json`은 사람이 확인한 통계표 목록입니다. 항목 하나의 형식:

```json
{
  "id": "student-count-by-region",
  "orgId": "...", "tblId": "...",
  "title": "표 이름",
  "topic": "교육 > 학생 수",
  "description": "무엇을 재는지, 어떤 질문에 답하는지",
  "prdSe": "Y", "period": "1990~2024",
  "unit": "명",
  "items": [{"id": "T1", "name": "학생수"}],
  "classifications": [{"level": 1, "name": "시도", "note": "ALL이면 전체 시도"}],
  "keywords": ["학생 수", "초등학생", "학령인구"],
  "notes": ["2021년부터 조사 기준 변경"],
  "verified": "YYYY-MM-DD"
}
```

`find_table`은 `keywords`(가중치 최고), `title`, `topic`, `description` 순으로 점수를 매깁니다.

### 카탈로그 채우기

키가 있으면 `uv run python scripts/build_catalog.py "학생수" "사교육비" ...`로 주제별 후보를 KOSIS 통합검색과 메타 조회로 모아 `catalog.draft.json`에 씁니다. 후보를 사람이 확인(실제 `kosis_data` 호출로 값 확인)하고 설명·키워드·주의사항을 채워 `catalog.json`에 옮깁니다.

## 한계

- ELT 시장 규모처럼 KOSIS에 직접 없는 지표는 대리 지표(영어 사교육비, 학원업 사업체·매출, 학령인구 등)로 추정해야 합니다. 도구는 통계표의 값만 돌려주며 시장 규모를 추정하지 않습니다.
- 통계표마다 단위와 조사 기준이 다릅니다. 모든 결과에 `limitations`가 붙습니다.
- 기간 자동 분할은 연/반기/분기/월 주기와 시작·종료 지정일 때만 됩니다 (일 주기, 최근 N개는 범위를 직접 좁혀야 합니다).

## 개발

```
uv sync
uv run pytest
```
