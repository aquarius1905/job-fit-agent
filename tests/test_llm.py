from app.llm import _enforce_experience_thresholds, compose_work_style_text


def test_enforce_experience_thresholds_full_match():
    skills = [{"required_years": 5, "actual_years": 5, "meets": "×"}]
    _enforce_experience_thresholds(skills)
    assert skills[0]["meets"] == "○"


def test_enforce_experience_thresholds_at_80_percent_boundary():
    skills = [{"required_years": 7, "actual_years": 5.6, "meets": "×"}]
    _enforce_experience_thresholds(skills)
    assert skills[0]["meets"] == "△"


def test_enforce_experience_thresholds_below_80_percent_overrides_model():
    # 実際に発生したバグ: モデルが57%(=実務4年/要件7年)と自ら計算しつつ
    # 「経験の幅がある」等を理由に△と自己申告してくるケース。
    # アプリ側の比率計算が必ず優先されなければならない。
    skills = [{"required_years": 7, "actual_years": 4, "meets": "△"}]
    _enforce_experience_thresholds(skills)
    assert skills[0]["meets"] == "×"


def test_enforce_experience_thresholds_no_year_requirement_is_untouched():
    skills = [{"required_years": None, "actual_years": None, "meets": "○"}]
    _enforce_experience_thresholds(skills)
    assert skills[0]["meets"] == "○"


def test_enforce_experience_thresholds_missing_actual_years_treated_as_zero():
    skills = [{"required_years": 3, "meets": "○"}]
    _enforce_experience_thresholds(skills)
    assert skills[0]["meets"] == "×"


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
