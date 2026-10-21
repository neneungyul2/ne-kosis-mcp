from ne_kosis_mcp.catalog import find_in_catalog, load_catalog

CATALOG = [
    {"id": "students", "orgId": "1", "tblId": "A", "title": "시도별 학생수", "keywords": ["초등학생", "학령인구"], "description": "학교급별 학생 수"},
    {"id": "spend", "orgId": "1", "tblId": "B", "title": "사교육비 조사", "keywords": ["사교육비"], "description": ""},
]


def test_keyword_match_ranks_first():
    r = find_in_catalog("사교육비", catalog=CATALOG)
    assert [e["id"] for e in r] == ["spend"]


def test_token_match_and_ordering():
    r = find_in_catalog("초등학생 학생수", catalog=CATALOG)
    assert r[0]["id"] == "students"


def test_no_match_and_blank():
    assert find_in_catalog("우주", catalog=CATALOG) == []
    assert find_in_catalog("  ", catalog=CATALOG) == []


def test_shipped_catalog_loads():
    assert isinstance(load_catalog(), list)
