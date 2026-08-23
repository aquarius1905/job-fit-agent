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
