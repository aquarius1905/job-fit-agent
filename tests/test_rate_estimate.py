import pytest

from app.rate_estimate import estimate_hourly_rate


def _entry(fit_score, hourly_min=None, hourly_max=None):
    posted_rate = {"stated_text": None, "hourly_min": hourly_min, "hourly_max": hourly_max}
    return {"evaluation": {"fit_score": fit_score, "posted_rate": posted_rate}}


def test_unavailable_when_no_entries():
    result = estimate_hourly_rate([])
    assert result == {"available": False, "sample_count": 0}


def test_unavailable_when_below_min_samples():
    entries = [
        _entry(80, 3000, 4000),
        _entry(90, 3200, 4200),
    ]
    result = estimate_hourly_rate(entries)
    assert result == {"available": False, "sample_count": 2}


def test_excludes_entries_below_fit_score_threshold():
    entries = [
        _entry(80, 3000, 4000),
        _entry(80, 3200, 4200),
        _entry(80, 3400, 4400),
        _entry(50, 100, 200),  # 適合度が低いので除外される
    ]
    result = estimate_hourly_rate(entries)
    assert result["available"] is True
    assert result["sample_count"] == 3


def test_excludes_entries_without_posted_rate():
    entries = [
        _entry(80, 3000, 4000),
        _entry(80, 3200, 4200),
        _entry(80, None, None),  # 単価記載なしなので除外される
        {"evaluation": {"fit_score": 80}},  # posted_rateキー自体がなくても落ちない
    ]
    result = estimate_hourly_rate(entries)
    assert result == {"available": False, "sample_count": 2}


def test_computes_median_hourly_and_monthly_equivalent():
    entries = [
        _entry(80, 3000, 4000),
        _entry(80, 4000, 5000),
        _entry(80, 5000, 6000),
    ]
    result = estimate_hourly_rate(entries)
    assert result["available"] is True
    assert result["sample_count"] == 3
    assert result["hourly_min"] == 4000
    assert result["hourly_max"] == 5000
    assert result["monthly_min"] == 4000 * 160
    assert result["monthly_max"] == 5000 * 160


def test_median_with_even_sample_count_averages_middle_two():
    entries = [
        _entry(80, 2000, 3000),
        _entry(80, 4000, 5000),
        _entry(80, 6000, 7000),
        _entry(80, 8000, 9000),
    ]
    result = estimate_hourly_rate(entries)
    assert result["hourly_min"] == 5000  # (4000+6000)/2
    assert result["hourly_max"] == 6000  # (5000+7000)/2


@pytest.mark.parametrize("min_fit_score", [90])
def test_custom_min_fit_score_threshold(min_fit_score):
    entries = [
        _entry(80, 3000, 4000),
        _entry(80, 3200, 4200),
        _entry(80, 3400, 4400),
    ]
    result = estimate_hourly_rate(entries, min_fit_score=min_fit_score)
    assert result == {"available": False, "sample_count": 0}
