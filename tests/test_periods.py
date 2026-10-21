import pytest

from ne_kosis_mcp import periods


def test_validate_period_formats():
    periods.validate_period("Y", "2024", "start")
    periods.validate_period("M", "202412", "start")
    periods.validate_period("Q", "202404", "start")
    for prd_se, bad in [("Y", "24"), ("M", "202413"), ("Q", "202405"), ("H", "202403"), ("D", "202401")]:
        with pytest.raises(ValueError):
            periods.validate_period(prd_se, bad, "start")


def test_unknown_prd_se():
    with pytest.raises(ValueError):
        periods.validate_period("X", "2024", "start")


def test_split_year_range_is_contiguous():
    (a0, a1), (b0, b1) = periods.split_range("Y", "2000", "2009")
    assert (a0, a1, b0, b1) == ("2000", "2004", "2005", "2009")


def test_split_month_across_years():
    (a0, a1), (b0, b1) = periods.split_range("M", "202311", "202402")
    assert a0 == "202311" and b1 == "202402"
    # 두 구간이 이어지고 겹치지 않는다
    assert periods._to_index("M", b0) == periods._to_index("M", a1) + 1


def test_split_quarter_is_contiguous():
    (a0, a1), (b0, b1) = periods.split_range("Q", "202301", "202404")
    assert a0 == "202301" and b1 == "202404"
    assert periods._to_index("Q", b0) == periods._to_index("Q", a1) + 1


def test_cannot_split_single_period_or_daily():
    assert not periods.can_split("Y", "2020", "2020")
    assert not periods.can_split("D", "20200101", "20200131")
    with pytest.raises(ValueError):
        periods.split_range("Y", "2020", "2020")
