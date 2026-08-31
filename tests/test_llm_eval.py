"""実際にClaude APIを呼び出し、判定精度そのものを検証するevalテスト。

コストと非決定性があるため、通常の `pytest` 実行では自動的に除外される
（pyproject.tomlの addopts 参照）。明示的に実行するには:

    .venv/bin/pytest -m llm_eval

ANTHROPIC_API_KEY が未設定の場合は自動でスキップする。
"""
from __future__ import annotations

import os

import pytest

from app import llm

pytestmark = [
    pytest.mark.llm_eval,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="ANTHROPIC_API_KEY が未設定のためevalテストをスキップ",
    ),
]


def _find_skill(result: dict, keyword: str) -> dict:
    for skill in result["required_skills"]:
        if keyword in skill["skill"]:
            return skill
    raise AssertionError(f"'{keyword}' を含むスキル項目が結果に見つからない: {result['required_skills']}")


def test_unrelated_domain_experience_is_not_credited_toward_year_requirement():
    """他領域(デスクトップアプリ開発)の経験年数を、対象領域(Web開発)の年数要件に合算しないこと。

    実際にこのバグ（無関係な経験年数を合算して○と誤判定）が本番で発生し、
    ユーザーからの指摘を受けてプロンプト・コード側の閾値強制ロジックを
    追加した経緯がある。回帰検知のためのeval。
    """
    skill_sheet = (
        "C++/C#での業務系デスクトップアプリケーション開発が約10年（2012年〜2022年）。"
        "Web関連の実務は2022年9月頃（ESG/SDGsプラットフォーム開発）から2026年現在まで約4年。"
        "Vue.js/Reactでのフロントエンド開発、FastAPI/Django REST frameworkでのバックエンド"
        "API開発を複数案件で経験。"
    )
    job_posting = "【必須】WEBアプリのフロントエンド・バックエンド共に7年程度の開発経験。"

    result = llm.evaluate(skill_sheet, "", job_posting)

    skill = _find_skill(result, "7年")
    assert skill["meets"] == "×", skill["reason"]


def test_sufficient_matching_years_are_credited():
    """求人要件を満たす実務年数がある場合は○と判定されること。"""
    skill_sheet = (
        "Pythonでのバックエンド開発を2018年から2026年現在まで一貫して担当（約8年）。"
        "FastAPI/Django REST frameworkでのAPI開発、AWS上での運用経験あり。"
    )
    job_posting = "【必須】Pythonでのバックエンド開発経験3年以上。"

    result = llm.evaluate(skill_sheet, "", job_posting)

    skill = _find_skill(result, "Python")
    assert skill["meets"] == "○", skill["reason"]


def test_or_condition_is_not_split_into_separate_must_items():
    """「以下いずれか」のようなOR条件は1項目にまとめ、満たす選択肢が1つでもあれば○と判定すること。

    実際にユーザーから「必須要件のOR条件を全部必須として判定してしまう」との
    指摘を受け、選択肢ごとに分解せず1つのrequired_skills項目としてまとめる
    ようプロンプトを修正した経緯がある。回帰検知のためのeval。
    """
    skill_sheet = "AWSでのインフラ構築・運用の実務経験が3年。GCP・Azureの実務経験はなし。"
    job_posting = "【必須】以下いずれかの実務経験\n・AWS\n・GCP\n・Azure"

    result = llm.evaluate(skill_sheet, "", job_posting)

    cloud_items = [
        s
        for s in result["required_skills"]
        if any(k in s["skill"] for k in ("AWS", "GCP", "Azure"))
    ]
    assert len(cloud_items) == 1, (
        "OR条件が個別のMUST項目に分解されている: "
        f"{result['required_skills']}"
    )
    assert cloud_items[0]["meets"] == "○", cloud_items[0]["reason"]


def test_matching_rate_is_not_flagged_as_concern_or_penalized():
    """単価がwork_style_fitの登録条件（希望単価下限）を満たしているにもかかわらず、
    モデルが登録されていない独自の「経験年数に対して相場的に低い」という基準を
    持ち込んでconcernsに指摘したり、fit_scoreを不当に下げたりしないこと。

    実際に本番で発生したバグ（希望単価4000円/時以上に対し実際の単価4000〜5000円/時で
    work_style_fit側はmatches=trueなのに、concernsで「経験・スキル水準に対してかなり
    低め」と指摘され、fit_scoreが42まで下がっていた）の回帰検知のためのeval。
    """
    skill_sheet = "Pythonでのバックエンド開発経験10年。FastAPI/Djangoでのバックエンド開発多数。"
    work_style = "希望単価（時給）: 4000円/時 〜 上限指定なし"
    job_posting = (
        "【必須】Pythonでのバックエンド開発経験3年以上。\n"
        "【勤務地】フルリモート。\n"
        "【報酬】月額単価320,000〜400,000円（月80h/週20h稼働の場合）、時間単価4,000〜5,000円/時程度。"
    )

    result = llm.evaluate(skill_sheet, work_style, job_posting)

    rate_items = [w for w in result["work_style_fit"] if "単価" in w["item"]]
    assert rate_items, result["work_style_fit"]
    assert rate_items[0]["matches"] is True, rate_items[0]["reason"]

    # 「稼働時間が短いため月額の絶対額は控えめ」といった、時間単価とは別の正当な指摘は許容する。
    # 禁止したいのは、経験・スキル水準を理由に単価そのもの（時間単価水準）を否定する主張。
    for concern in result["concerns"]:
        has_experience_basis = "経験" in concern or "スキル水準" in concern
        has_rate_topic = "単価" in concern or "報酬" in concern
        has_negative_judgement = "低" in concern or "ミスマッチ" in concern or "不足" in concern
        assert not (has_experience_basis and has_rate_topic and has_negative_judgement), (
            "単価が希望条件を満たしているのに、経験・スキル水準を理由に"
            f"単価を否定する懸念が挙げられている: {concern}"
        )

    assert result["fit_score"] >= 70, (
        f"必須スキルを満たし単価も条件通りなのに、fit_scoreが不当に低い: {result}"
    )


def test_broad_weekly_days_preference_matches_reduced_hours_posting():
    """稼働日数の希望が「週1〜5日いずれも可」のような幅のある条件の場合、
    求人票の稼働時間（例: 月80h/週20h程度＝週1〜2日相当）がその範囲に
    収まっていればmatches=trueにすること。

    実際に発生したバグ: reasonでは「応募者の希望範囲（週1〜5日）には収まる」と
    書きながら、matchesはfalseにするという自己矛盾が起きていた。回帰検知のためのeval。
    """
    skill_sheet = "Pythonでのバックエンド開発経験10年。"
    work_style = "希望稼働日数（週あたり、許容できる範囲）: 週1日、週2日、週3日、週4日、週5日(フルタイム)"
    job_posting = (
        "【必須】Pythonでのバックエンド開発経験3年以上。\n"
        "【稼働時間】月80h/週20h稼働（週1〜2日相当）。\n"
        "【勤務地】フルリモート。"
    )

    result = llm.evaluate(skill_sheet, work_style, job_posting)

    days_items = [w for w in result["work_style_fit"] if "稼働日数" in w["item"]]
    assert days_items, result["work_style_fit"]
    assert days_items[0]["matches"] is True, days_items[0]["reason"]


def test_explicit_onsite_requirement_conflicts_with_full_remote_preference():
    """フルリモート希望と、求人票の明確な出社必須条件との不一致が検知されること。"""
    skill_sheet = "Pythonでのバックエンド開発経験5年。"
    work_style = "出社に関する希望（許容できる働き方）: フルリモート"
    job_posting = (
        "【勤務地】東京本社に週5日フルタイム出社必須。リモートワーク不可。"
        "【必須】Pythonでのバックエンド開発経験3年以上。"
    )

    result = llm.evaluate(skill_sheet, work_style, job_posting)

    remote_items = [w for w in result["work_style_fit"] if "リモート" in w["item"]]
    assert remote_items, result["work_style_fit"]
    assert remote_items[0]["matches"] is False, remote_items[0]["reason"]
    assert result["concerns"], "出社必須とフルリモート希望の不一致が懸念点に挙がっていない"
