import json

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from ne_kosis_mcp.client import KosisClient
from ne_kosis_mcp.server import create_server
from ne_kosis_mcp.tool_filter import ToolRegistrar
from ne_kosis_mcp.tools import register_all_tools

TOOLS = {
    "find_table", "kosis_search", "kosis_list", "kosis_table_meta",
    "kosis_data", "kosis_trend", "kosis_export",
}


class CaptureServer:
    def __init__(self):
        self.tools = {}

    def add_tool(self, fn, name=None, description=None, **kwargs):
        self.tools[name] = fn


def rows(c1_name, values):
    return [
        {
            "TBL_NM": "시도별 학생수", "PRD_DE": str(2020 + i), "DT": v, "C1": "x", "C1_NM": c1_name,
            "C1_OBJ_NM": "시도", "ITM_NM": "학생수", "UNIT_NM": "명",
        }
        for i, v in enumerate(values)
    ]


def build(handler, tmp_path, allow=None):
    client = KosisClient("K", transport=httpx.MockTransport(handler))
    server = CaptureServer()
    register_all_tools(ToolRegistrar(server, allow), client, tmp_path)
    return server.tools


def data_handler(request):
    return httpx.Response(200, json=rows("서울", ["100", "110", "121"]) + rows("부산", ["50", "-", "60"]))


async def test_all_tools_registered(tmp_path):
    assert set(build(data_handler, tmp_path)) == TOOLS


async def test_allow_list_limits_tools(tmp_path):
    assert set(build(data_handler, tmp_path, {"kosis_data"})) == {"kosis_data"}


async def test_kosis_data_truncates_and_labels_columns(tmp_path):
    tools = build(data_handler, tmp_path)
    out = json.loads(await tools["kosis_data"]("101", "T", "Y", recent=3, max_rows=2))
    assert out["totalRows"] == 6 and out["returnedRows"] == 2 and out["truncated"] is True
    assert out["rows"][0]["시도"] == "서울" and out["rows"][0]["value"] == "100"
    assert out["limitations"]


async def test_kosis_trend_computes_summary(tmp_path):
    tools = build(data_handler, tmp_path)
    out = json.loads(await tools["kosis_trend"]("101", "T", "Y", "ALL", ["ALL"], start="2020", end="2022"))
    by = {s["series"]: s for s in out["series"]}
    seoul = by["서울 / 학생수 (명)"]
    assert seoul["changePct"] == pytest.approx(21.0)
    assert seoul["cagrPct"] == pytest.approx(10.0)
    assert by["부산 / 학생수 (명)"]["missingPeriods"] == ["2021"]


async def test_range_validation_errors(tmp_path):
    tools = build(data_handler, tmp_path)
    with pytest.raises(ToolError):
        await tools["kosis_data"]("101", "T", "Y", start="2020")  # end 없음
    with pytest.raises(ToolError):
        await tools["kosis_data"]("101", "T", "Y", start="2022", end="2020")
    with pytest.raises(ToolError):
        await tools["kosis_data"]("101", "T", "Y", start="2020", end="2021", recent=2)
    with pytest.raises(ToolError):
        await tools["kosis_data"]("101", "T", "Z", recent=2)


async def test_default_recent_when_no_range(tmp_path):
    seen = {}

    def handler(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=[])

    tools = build(handler, tmp_path)
    await tools["kosis_data"]("101", "T", "Y")
    assert seen["newEstPrdCnt"] == "5"


async def test_find_table_falls_back_to_search(tmp_path):
    def handler(request):
        assert "statisticsSearch" in str(request.url)
        return httpx.Response(
            200,
            json=[{"ORG_ID": "101", "TBL_ID": "DT_X", "TBL_NM": "표", "CONTENTS": "가" * 300, "LINK_URL": "u"}],
        )

    tools = build(handler, tmp_path)
    out = json.loads(await tools["find_table"]("없는주제"))
    assert out["kosisSearch"][0]["tblId"] == "DT_X"
    assert out["kosisSearch"][0]["summary"].endswith("…")
    assert "catalog" not in out and "note" in out


async def test_table_meta_groups_classifications(tmp_path):
    def handler(request):
        if "type=ITM" in str(request.url):
            return httpx.Response(200, json=[{"ITM_ID": "T1", "ITM_NM": "학생수"}])
        return httpx.Response(
            200,
            json=[
                {"OBJ_ID": "A", "OBJ_NM": "시도", "OBJ_ID_SN": "1", "ITM_ID": "11", "ITM_NM": "서울"},
                {"OBJ_ID": "A", "OBJ_NM": "시도", "OBJ_ID_SN": "1", "ITM_ID": "26", "ITM_NM": "부산"},
            ],
        )

    tools = build(handler, tmp_path)
    out = json.loads(await tools["kosis_table_meta"]("101", "T"))
    cls = out["classificationLevels"]["classifications"]
    assert len(cls) == 1 and [v["id"] for v in cls[0]["values"]] == ["11", "26"]


async def test_table_meta_unexpected_shape_returns_raw(tmp_path):
    tools = build(lambda r: httpx.Response(200, json=[{"weird": 1}]), tmp_path)
    out = json.loads(await tools["kosis_table_meta"]("101", "T"))
    assert out["classificationLevels"] == {"raw": [{"weird": 1}]}


async def test_export_writes_files(tmp_path):
    tools = build(data_handler, tmp_path)
    out = json.loads(await tools["kosis_export"]("101", "DT_1", "Y", start="2020", end="2022"))
    assert out["rows"] == 6
    assert (tmp_path / "DT_1.xlsx").exists()
    assert len(out["csvPaths"]) == 2


async def test_export_refuses_empty(tmp_path):
    tools = build(lambda r: httpx.Response(200, json=[]), tmp_path)
    with pytest.raises(ToolError):
        await tools["kosis_export"]("101", "T", "Y", recent=1)


async def test_server_wraps_expected_errors_as_tool_error(tmp_path):
    from ne_kosis_mcp.tool_filter import surface_errors

    tools = build(lambda r: httpx.Response(200, json={"err": "10", "errMsg": "x"}), tmp_path)
    with pytest.raises(ToolError, match="인증키"):
        await surface_errors(tools["kosis_search"])("인구")


def test_create_server_smoke():
    client = KosisClient("K", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    assert create_server(client) is not None
