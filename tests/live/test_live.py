"""실제 KOSIS 호출로 응답 구조와 오류 형식을 확인한다 (KOSIS_LIVE_TEST=1, KOSIS_API_KEY 필요).

문서에 샘플 응답이 없어 추정으로 구현한 부분(오류 형식, 메타 키, 반기 코드, 목록 파라미터 이름)을 검증한다.
"""
import os

import pytest

from ne_kosis_mcp.client import ApiError, KosisClient
from ne_kosis_mcp.config import load_dotenv_if_present, resolve_api_key

pytestmark = pytest.mark.live


@pytest.fixture
async def client():
    load_dotenv_if_present()
    c = KosisClient(resolve_api_key(os.environ))
    yield c
    await c.aclose()


async def test_search_returns_expected_fields(client):
    hits = await client.search("인구", count=3)
    assert hits and {"ORG_ID", "TBL_ID", "TBL_NM"} <= set(hits[0])


async def test_list_top_level(client):
    entries = await client.list_statistics("MT_ZTITLE", "0")
    assert entries


async def test_meta_and_data_roundtrip(client):
    hit = (await client.search("주민등록인구", count=1))[0]
    org, tbl = hit["ORG_ID"], hit["TBL_ID"]
    items = await client.table_meta(org, tbl, "ITM")
    objects = await client.table_meta(org, tbl, "OBJ")
    assert items and objects
    assert {"ITM_ID", "ITM_NM"} <= set(items[0])
    assert {"OBJ_ID", "OBJ_NM"} <= set(objects[0])


async def test_bad_key_error_shape():
    c = KosisClient("invalid-key")
    try:
        with pytest.raises(ApiError):
            await c.search("인구")
    finally:
        await c.aclose()
