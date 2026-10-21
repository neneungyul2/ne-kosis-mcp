import httpx
import pytest

from ne_kosis_mcp.cache import FileCache
from ne_kosis_mcp.client import ApiError, KosisClient

KEY = "SECRETKEY123"


def make_client(handler, cache=None):
    return KosisClient(KEY, transport=httpx.MockTransport(handler), cache=cache)


def data_row(period):
    return {"PRD_DE": period, "DT": "1", "C1": "A", "C1_NM": "a", "ITM_NM": "i"}


async def test_data_splits_range_on_too_large():
    calls = []

    def handler(request):
        p = request.url.params
        calls.append((p["startPrdDe"], p["endPrdDe"]))
        years = int(p["endPrdDe"]) - int(p["startPrdDe"]) + 1
        if years > 2:
            return httpx.Response(200, json={"err": "31", "errMsg": "too big"})
        return httpx.Response(
            200, json=[data_row(str(y)) for y in range(int(p["startPrdDe"]), int(p["endPrdDe"]) + 1)]
        )

    client = make_client(handler)
    rows = await client.data(
        org_id="101", tbl_id="T", itm_id="ALL", classifications=["ALL"], prd_se="Y", start="2000", end="2007"
    )
    assert [r["PRD_DE"] for r in rows] == [str(y) for y in range(2000, 2008)]
    assert calls[0] == ("2000", "2007")  # 처음엔 전체 범위로 한 번 요청
    await client.aclose()


async def test_data_no_data_returns_empty():
    client = make_client(lambda r: httpx.Response(200, json={"err": "30", "errMsg": "no"}))
    rows = await client.data(
        org_id="1", tbl_id="T", itm_id="ALL", classifications=["ALL"], prd_se="Y", recent=3
    )
    assert rows == []
    await client.aclose()


async def test_too_large_with_recent_is_not_split_and_raises():
    client = make_client(lambda r: httpx.Response(200, json={"err": "31", "errMsg": "big"}))
    with pytest.raises(ApiError, match="40,000"):
        await client.data(
            org_id="1", tbl_id="T", itm_id="ALL", classifications=["ALL"], prd_se="Y", recent=50
        )
    await client.aclose()


async def test_error_message_never_contains_key():
    client = make_client(lambda r: httpx.Response(200, json={"err": "10", "errMsg": "bad key"}))
    with pytest.raises(ApiError) as e:
        await client.search("인구")
    assert KEY not in str(e.value)
    await client.aclose()


async def test_http_error_and_non_json():
    c1 = make_client(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(ApiError, match="HTTP 500"):
        await c1.search("x")
    c2 = make_client(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(ApiError):
        await c2.search("x")
    await c1.aclose()
    await c2.aclose()


async def test_request_params_and_classification_levels():
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=[])

    client = make_client(handler)
    await client.data(
        org_id="101", tbl_id="T", itm_id="T1", classifications=["11 26", "ALL"], prd_se="Y", recent=2
    )
    assert seen["objL1"] == "11 26" and seen["objL2"] == "ALL"
    assert seen["newEstPrdCnt"] == "2" and "startPrdDe" not in seen
    assert seen["apiKey"] == KEY and seen["format"] == "json"
    await client.aclose()


async def test_cache_hit_avoids_second_call_and_excludes_key(tmp_path):
    n = {"calls": 0}

    def handler(request):
        n["calls"] += 1
        return httpx.Response(200, json=[{"TBL_ID": "T"}])

    cache = FileCache(tmp_path / "c", ttl_ms=10**9)
    client = make_client(handler, cache)
    await client.search("인구")
    await client.search("인구")
    assert n["calls"] == 1 and client.counter.hit == 1
    for f in (tmp_path / "c").glob("*.json"):
        assert KEY not in f.read_text(encoding="utf-8")
    await client.aclose()


async def test_too_many_classifications_rejected():
    client = make_client(lambda r: httpx.Response(200, json=[]))
    with pytest.raises(ValueError):
        await client.data(
            org_id="1", tbl_id="T", itm_id="ALL", classifications=["ALL"] * 9, prd_se="Y", recent=1
        )
    await client.aclose()
