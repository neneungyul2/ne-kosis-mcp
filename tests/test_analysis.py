import pytest

from ne_kosis_mcp import analysis


def row(period, value, c1="서울", item="학생수", unit="명"):
    return {"PRD_DE": period, "DT": value, "C1": "11", "C1_NM": c1, "ITM_NM": item, "UNIT_NM": unit}


def test_parse_value():
    assert analysis.parse_value("1,234") == 1234.0
    assert analysis.parse_value("-12.5") == -12.5
    assert analysis.parse_value("-") is None
    assert analysis.parse_value("…") is None
    assert analysis.parse_value("") is None
    assert analysis.parse_value(None) is None


def test_group_series_by_classification():
    rows = [row("2020", "100", "서울"), row("2021", "110", "서울"), row("2020", "50", "부산"), row("2021", "-", "부산")]
    series = analysis.group_series(rows, [1])
    by_key = {s.key: s for s in series}
    assert set(by_key) == {"서울 / 학생수 (명)", "부산 / 학생수 (명)"}
    assert by_key["서울 / 학생수 (명)"].points == {"2020": 100.0, "2021": 110.0}
    assert by_key["부산 / 학생수 (명)"].points == {"2020": 50.0, "2021": None}


def test_summarize_with_cagr():
    s = analysis.Series("x", {"2020": 100.0, "2022": 121.0})
    r = analysis.summarize(s, "Y")
    assert r["change"] == 21.0
    assert r["changePct"] == pytest.approx(21.0)
    assert r["cagrPct"] == pytest.approx(10.0)


def test_summarize_monthly_years():
    s = analysis.Series("x", {"202001": 100.0, "202201": 121.0})
    assert analysis.summarize(s, "M")["cagrPct"] == pytest.approx(10.0)


def test_summarize_skips_missing_and_short_series():
    s = analysis.Series("x", {"2020": None, "2021": 5.0})
    r = analysis.summarize(s, "Y")
    assert r["missingPeriods"] == ["2020"]
    assert "note" in r and "from" not in r


def test_cagr_undefined_cases():
    assert analysis.cagr(0, 10, 2) is None
    assert analysis.cagr(10, 20, 0) is None
    assert analysis.cagr(-5, 10, 2) is None


def test_period_over_period_skips_missing_base():
    s = analysis.Series("x", {"2020": 100.0, "2021": None, "2022": 150.0})
    out = analysis.period_over_period(s)
    assert "change" not in out[0] and "change" not in out[1]
    assert out[2]["change"] == 50.0 and out[2]["changePct"] == pytest.approx(50.0)
