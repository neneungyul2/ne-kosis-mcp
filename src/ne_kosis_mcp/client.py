"""KOSIS OpenAPI HTTP 클라이언트 (httpx 비동기)."""
from typing import Any

import httpx

from . import periods
from .cache import CallCounter, FileCache, cached_call
from .errors import (
    NO_DATA_CODES,
    TOO_LARGE_CODES,
    format_api_error,
    format_kosis_error,
    kosis_error_code,
)

BASE = "https://kosis.kr/openapi"
LIST_URL = f"{BASE}/statisticsList.do?method=getList"
SEARCH_URL = f"{BASE}/statisticsSearch.do?method=getList"
META_URL = f"{BASE}/statisticsData.do?method=getMeta"
DATA_URL = f"{BASE}/Param/statisticsParameterData.do?method=getList"

MAX_SPLIT_DEPTH = 6  # 기간 분할은 최대 2^6 = 64번 호출까지
MAX_CLASSIFICATIONS = 8


class ApiError(Exception):
    """KOSIS 호출 실패. 메시지는 키 값을 가린 상태다."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class KosisClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
        cache: FileCache | None = None,
    ) -> None:
        self._api_key = api_key
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)
        self._cache = cache
        self.counter = CallCounter()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _fetch(self, url: str, params: dict[str, Any]) -> Any:
        """GET 한 번. HTTP 실패와 KOSIS 오류(err)는 ApiError로 바꾼다."""
        full = {**params, "apiKey": self._api_key, "format": "json", "jsonVD": "Y"}
        try:
            response = await self._http.get(url, params=full)
        except httpx.HTTPError as e:
            raise ApiError(format_api_error(url, None, str(e) or type(e).__name__)) from None
        if response.status_code >= 400:
            raise ApiError(format_api_error(url, response.status_code, response.text)) from None
        try:
            payload = response.json()
        except ValueError:
            raise ApiError(format_api_error(url, response.status_code, response.text[:500])) from None
        error = kosis_error_code(payload)
        if error:
            code, message = error
            raise ApiError(format_kosis_error(url, code, message), code=code)
        return payload

    async def _get(self, url: str, params: dict[str, Any]) -> Any:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        if self._cache is None:
            return await self._fetch(url, clean)
        # 캐시 키에는 인증키가 들어가지 않는다 (_fetch가 요청 직전에만 붙인다)
        return await cached_call(
            self._cache, self.counter, url, clean, lambda: self._fetch(url, clean)
        )

    async def list_statistics(self, vw_cd: str, parent_id: str) -> list[dict]:
        payload = await self._get(LIST_URL, {"vwCd": vw_cd, "parentListId": parent_id})
        return payload if isinstance(payload, list) else []

    async def search(
        self,
        query: str,
        *,
        org_id: str | None = None,
        sort: str = "RANK",
        page: int = 1,
        count: int = 20,
    ) -> list[dict]:
        payload = await self._get(
            SEARCH_URL,
            {
                "searchNm": query,
                "orgId": org_id,
                "sort": sort,
                "startCount": page,
                "resultCount": count,
            },
        )
        return payload if isinstance(payload, list) else []

    async def table_meta(self, org_id: str, tbl_id: str, meta_type: str) -> list[dict]:
        """통계표 메타(type: TBL 표 이름, ITM 항목, OBJ 분류, PRD 수록주기 등)."""
        payload = await self._get(
            META_URL, {"type": meta_type, "orgId": org_id, "tblId": tbl_id}
        )
        return payload if isinstance(payload, list) else []

    async def data(
        self,
        *,
        org_id: str,
        tbl_id: str,
        itm_id: str,
        classifications: list[str],
        prd_se: str,
        start: str | None = None,
        end: str | None = None,
        recent: int | None = None,
        _depth: int = 0,
    ) -> list[dict]:
        """통계자료 조회. 40,000셀을 넘으면 기간(start~end)을 반으로 나눠 다시 요청한다."""
        if not classifications:
            raise ValueError("분류 코드가 하나 이상 필요합니다 (objL1). 전체는 'ALL'")
        if len(classifications) > MAX_CLASSIFICATIONS:
            raise ValueError(f"분류는 최대 {MAX_CLASSIFICATIONS}개까지입니다")
        params: dict[str, Any] = {
            "orgId": org_id,
            "tblId": tbl_id,
            "itmId": itm_id,
            "prdSe": prd_se,
        }
        for i, code in enumerate(classifications, start=1):
            params[f"objL{i}"] = code
        if recent is not None:
            params["newEstPrdCnt"] = recent
        else:
            params["startPrdDe"] = start
            params["endPrdDe"] = end
        try:
            payload = await self._get(DATA_URL, params)
        except ApiError as e:
            if e.code in NO_DATA_CODES:
                return []
            can_split = (
                e.code in TOO_LARGE_CODES
                and recent is None
                and start
                and end
                and _depth < MAX_SPLIT_DEPTH
                and periods.can_split(prd_se, start, end)
            )
            if not can_split:
                raise
            first, second = periods.split_range(prd_se, start, end)  # type: ignore[arg-type]
            common = dict(
                org_id=org_id,
                tbl_id=tbl_id,
                itm_id=itm_id,
                classifications=classifications,
                prd_se=prd_se,
                _depth=_depth + 1,
            )
            head = await self.data(start=first[0], end=first[1], **common)
            tail = await self.data(start=second[0], end=second[1], **common)
            return head + tail
        return payload if isinstance(payload, list) else []
