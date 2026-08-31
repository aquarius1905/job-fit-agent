import pytest

from app.llm import (
    _cap_fit_score_for_unmet_conditions,
    _enforce_experience_thresholds,
    compose_work_style_text,
)


@pytest.mark.parametrize(
    ("required_years", "actual_years", "initial_meets", "expected_meets"),
    [
        pytest.param(5, 5, "×", "○", id="full_match"),
        pytest.param(7, 5.6, "×", "△", id="exactly_80_percent_boundary"),
        # 実際に発生したバグ: モデルが57%(=実務4年/要件7年)と自ら計算しつつ
        # 「経験の幅がある」等を理由に△と自己申告してくるケース。
        # アプリ側の比率計算が必ず優先されなければならない。
        pytest.param(7, 4, "△", "×", id="below_80_percent_overrides_model"),
        pytest.param(None, None, "○", "○", id="no_year_requirement_untouched"),
        pytest.param(3, None, "○", "×", id="missing_actual_years_treated_as_zero"),
        # required_years=0(経験不問)はNone(条件なし)と区別しつつ、0除算を起こさず○にする
        pytest.param(0, 0, "×", "○", id="zero_required_years_always_met"),
    ],
)
def test_enforce_experience_thresholds(
    required_years, actual_years, initial_meets, expected_meets
):
    skills = [
        {"required_years": required_years, "actual_years": actual_years, "meets": initial_meets}
    ]
    _enforce_experience_thresholds(skills)
    assert skills[0]["meets"] == expected_meets


def _make_result(fit_score, fit_label, required_skills=None, work_style_fit=None):
    return {
        "fit_score": fit_score,
        "fit_label": fit_label,
        "required_skills": required_skills or [],
        "work_style_fit": work_style_fit or [],
    }


def test_cap_fit_score_when_required_skill_unmet():
    # 実際に発生したケース: 必須スキルが×/△なのに応募推奨(70点台)が出ていた
    result = _make_result(
        78,
        "応募推奨",
        required_skills=[
            {"skill": "LLM開発経験", "required": True, "meets": "×"},
            {"skill": "Python経験", "required": True, "meets": "○"},
        ],
    )
    _cap_fit_score_for_unmet_conditions(result)
    assert result["fit_score"] == 60
    assert result["fit_label"] == "要検討"


def test_cap_fit_score_when_full_remote_preference_mismatched():
    result = _make_result(
        75,
        "応募推奨",
        work_style_fit=[
            {"item": "出社に関する希望", "preference": "フルリモート希望", "matches": False},
        ],
    )
    _cap_fit_score_for_unmet_conditions(result)
    assert result["fit_score"] == 60
    assert result["fit_label"] == "要検討"


def test_cap_fit_score_when_remote_mismatch_stated_in_item_field_only():
    # 実際に発生したケース: 「フルリモート」の文言がpreferenceではなくitem側にのみ
    # 書かれることがあり、item欄も見ないと検出漏れになる
    result = _make_result(
        70,
        "応募推奨",
        work_style_fit=[
            {"item": "フルリモート", "preference": "◯希望", "matches": False},
        ],
    )
    _cap_fit_score_for_unmet_conditions(result)
    assert result["fit_score"] == 60
    assert result["fit_label"] == "要検討"


def test_cap_fit_score_untouched_when_all_required_met():
    result = _make_result(
        85,
        "応募推奨",
        required_skills=[{"skill": "Python経験", "required": True, "meets": "○"}],
        work_style_fit=[
            {"item": "出社に関する希望", "preference": "フルリモート希望", "matches": True}
        ],
    )
    _cap_fit_score_for_unmet_conditions(result)
    assert result["fit_score"] == 85
    assert result["fit_label"] == "応募推奨"


def test_cap_fit_score_does_not_raise_score_or_overwrite_cautious_label():
    result = _make_result(
        40,
        "見送り推奨",
        required_skills=[{"skill": "LLM開発経験", "required": True, "meets": "×"}],
    )
    _cap_fit_score_for_unmet_conditions(result)
    assert result["fit_score"] == 40
    assert result["fit_label"] == "見送り推奨"


def test_cap_fit_score_ignores_optional_skill_gap():
    result = _make_result(
        80,
        "応募推奨",
        required_skills=[{"skill": "リーダー経験", "required": False, "meets": "×"}],
    )
    _cap_fit_score_for_unmet_conditions(result)
    assert result["fit_score"] == 80
    assert result["fit_label"] == "応募推奨"


def test_compose_work_style_text_includes_all_sections():
    text = compose_work_style_text(
        {
            "remote_options": ["フルリモート"],
            "weekly_days": ["週3日", "週4日"],
            "rate_min": "3000",
            "rate_max": "6000",
            "leader_ok": False,
            "pm_ok": True,
            "free_text": "備考です",
        }
    )
    assert "フルリモート" in text
    assert "週3日、週4日" in text
    assert "3000円/時" in text
    assert "6000円/時" in text
    assert "リーダーポジション: NG" in text
    assert "PMポジション: OK" in text
    assert "備考です" in text


def test_compose_work_style_text_empty():
    assert compose_work_style_text({}) == ""
