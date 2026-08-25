import pytest

from app.llm import _enforce_experience_thresholds, compose_work_style_text


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
