"""Claude APIを使って求人票とスキルシートの適合度を判定する。"""
from __future__ import annotations

import os

from anthropic import Anthropic

DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

_EVALUATION_TOOL = {
    "name": "submit_evaluation",
    "description": "求人票とスキルシートを比較した適合度評価結果を提出する",
    "input_schema": {
        "type": "object",
        "properties": {
            "fit_score": {
                "type": "integer",
                "description": "総合適合度スコア（0〜100）",
            },
            "fit_label": {
                "type": "string",
                "description": "一言の総合判定（例: 応募推奨 / 要検討 / 見送り推奨）",
            },
            "required_skills": {
                "type": "array",
                "description": "求人票に書かれている必須・歓迎スキル/条件ごとの充足判定",
                "items": {
                    "type": "object",
                    "properties": {
                        "skill": {"type": "string", "description": "スキル・条件名"},
                        "required": {
                            "type": "boolean",
                            "description": "必須(true)か歓迎(false)か",
                        },
                        "required_years": {
                            "type": ["number", "null"],
                            "description": (
                                "この項目について求人票が具体的な実務経験年数（「○年以上」「○年程度」等）を"
                                "指定している場合のみ、その年数（例: 7）。年数の指定がない項目はnull。"
                            ),
                        },
                        "actual_years": {
                            "type": ["number", "null"],
                            "description": (
                                "required_yearsを設定した場合のみ設定。スキルシートに基づく、"
                                "その技術・領域そのものの実務年数（無関係な別領域の経験は含めない）。"
                                "算出できない場合は0。required_yearsがnullの項目ではnullでよい。"
                            ),
                        },
                        "meets": {
                            "type": "string",
                            "enum": ["○", "△", "×"],
                            "description": (
                                "スキルシートの内容から見て満たしているか。"
                                "○=明確に満たしている、△=関連経験はあるが年数や範囲が明確に不足・不明瞭、"
                                "×=満たしていない、または判定材料がない"
                            ),
                        },
                        "reason": {
                            "type": "string",
                            "description": "判定理由の短い説明",
                        },
                    },
                    "required": ["skill", "required", "meets", "reason"],
                },
            },
            "work_style_fit": {
                "type": "array",
                "description": "働き方の希望条件ごとの、求人内容との合致判定",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {
                            "type": "string",
                            "description": "働き方の項目名（例: フルリモート、出社あり、会議多め等）",
                        },
                        "preference": {
                            "type": "string",
                            "description": "応募者側の希望内容（例: ◯希望 / ×希望しない / どちらでも可）",
                        },
                        "matches": {
                            "type": "boolean",
                            "description": "求人票に書かれた条件が応募者の希望に合っているか",
                        },
                        "reason": {
                            "type": "string",
                            "description": "判定理由の短い説明。求人票に記載がなければその旨を書く",
                        },
                    },
                    "required": ["item", "preference", "matches", "reason"],
                },
            },
            "concerns": {
                "type": "array",
                "description": "応募前に確認・注意すべき懸念点",
                "items": {"type": "string"},
            },
            "questions_to_ask": {
                "type": "array",
                "description": (
                    "応募前に案件担当者（エージェント等）に確認したい質問のリスト。"
                    "特に働き方の希望条件と求人票の記載が一致しない・記載が曖昧な場合に、"
                    "頻度や条件の詳細を確認するための具体的な質問を含める"
                    "（例: フルリモート希望だが出社ありと書かれている場合「出社の頻度・エリアを教えてください」）"
                ),
                "items": {"type": "string"},
            },
            "application_letter": {
                "type": "string",
                "description": "この求人にそのまま送れる日本語の応募文（完成形、追記不要なレベル）",
            },
        },
        "required": [
            "fit_score",
            "fit_label",
            "required_skills",
            "work_style_fit",
            "concerns",
            "questions_to_ask",
            "application_letter",
        ],
    },
}

_SYSTEM_PROMPT = """\
あなたはITフリーランス/エンジニアの案件マッチングを支援するエージェントです。
渡される「スキルシート」（応募者の経歴・スキル情報）「働き方の希望条件」（応募者が案件に求める働き方）と
「求人票」（案件情報）を読み、技術面・働き方面の両方から適合度を厳密に判定してください。

判定方針:
- スキルシートに明記されていない事項は「不明」として満たしていない(meets="×")扱いにし、reasonに「スキルシートに記載なし」等と明記する。憶測で満たしていると判定しない。
- 必須(MUST)条件と歓迎(WANT)条件は求人票の表現から判別し、requiredフィールドに反映する。
- 求人票に「以下いずれか」「◯◯・△△のいずれかを満たすこと」のようなOR条件（複数の選択肢のうち少なくとも1つを満たせばよい条件）がある場合、選択肢ごとに別々のrequired_skills項目を作らないこと。選択肢をまとめて1つのrequired_skills項目にし（例: skill="AWS / GCP / Azureのいずれかの実務経験"）、スキルシートがそのうち少なくとも1つを満たしていればmeets="○"、どれも満たしていなければ"×"と判定する。reasonには、どの選択肢を満たしている（または満たしていない）かを具体的に書く。これを守らずOR条件を個別のMUST項目に分解すると、実際には要件を満たしているのに未充足の必須項目が並んでいるように見えてしまうため、必ず1項目にまとめること。
- 経験年数要件（「○年以上」「○年程度」等）がある項目は、required_yearsに求人票が要求する年数を、actual_yearsにスキルシートに基づく「その技術・領域そのもの」の実務年数を必ず数値で入れること。無関係・別領域の経験年数（他分野の開発経験、社会人経験全体、フリーランス経験全体など）をactual_yearsに合算しない。算出できない場合はactual_years=0とする。年数要件がない項目はrequired_years/actual_yearsともにnullでよい。
  meetsはこの2つの数値の比率（actual_years / required_years）を機械的に反映すること: 100%以上→"○"、80%以上100%未満→"△"、80%未満または算出不能→"×"。経験の幅広さ・関連スキルの多さ・案件数の多さなど比率に含まれない要素を理由に、この比率より甘い側へ判定を格上げしてはならない（このmeetsの値はアプリ側でも上記比率から再計算され、矛盾があれば上書きされる）。
  reasonには必ず実際の年数と求人要件年数を対比して明記する（例: 「実務約4年 / 求人要件7年程度で約57%相当のため不足」）。
- 働き方の希望条件は、項目ごとに求人票の記載内容と照らし合わせてmatchesを判定する。求人票に該当する記載がなければreasonに「求人票に記載なし」と明記し、matchesはfalseにする。「どちらでも可」など希望に幅がある項目は、求人票がその範囲に収まっていればmatchesをtrueにする。
- 懸念点(concerns)には、経験年数不足・スキルのブランク・稼働条件（単価等）のミスマッチに加え、働き方の希望条件との重大な不一致（例: フルリモート希望なのに出社必須）があれば具体的に挙げる。
- 確認質問(questions_to_ask)には、懸念点のうち求人票の記載だけでは判断がつかないもの（例: フルリモート希望なのに「原則リモート、必要に応じて出社」等の曖昧な条件）について、案件担当者に直接聞けば解消しうる具体的な質問を作成する。「出社の頻度は？」のような曖昧な聞き方ではなく、「月にどの程度の出社が発生しますか？」「出社が必要な場合、最寄り駅・エリアはどこですか？」のように、相手がそのまま回答できる粒度で書く。働き方の希望条件との不一致がなければ無理に作らず、空配列でよい。
- 総合適合度(fit_score)は技術面のスキル充足だけでなく、働き方の希望条件との合致度も加味して判定する。働き方の希望条件で重大な不一致（必須級の希望に反する条件）がある場合は、技術面が満たされていてもスコアを大きく下げること。
- 応募文(application_letter)は、スキルシートの中から本案件に関連が強い経験を選んで簡潔にアピールし、丁寧だが定型文っぽくない日本語で書く。誇張や虚偽の経験を書かない。
"""


def compose_work_style_text(work_style: dict) -> str:
    """構造化された働き方の希望条件を、プロンプトに渡すテキストへ組み立てる。"""
    lines = []

    remote_options = work_style.get("remote_options") or []
    if remote_options:
        lines.append(f"出社に関する希望（許容できる働き方）: {'、'.join(remote_options)}")

    weekly_days = work_style.get("weekly_days") or []
    if weekly_days:
        lines.append(f"希望稼働日数（週あたり、許容できる範囲）: {'、'.join(weekly_days)}")

    rate_min = work_style.get("rate_min")
    rate_max = work_style.get("rate_max")
    if rate_min or rate_max:
        min_str = f"{rate_min}円/時" if rate_min else "下限指定なし"
        max_str = f"{rate_max}円/時" if rate_max else "上限指定なし"
        lines.append(f"希望単価（時給）: {min_str} 〜 {max_str}")

    if "leader_ok" in work_style:
        lines.append(f"リーダーポジション: {'OK' if work_style['leader_ok'] else 'NG'}")
    if "pm_ok" in work_style:
        lines.append(f"PMポジション: {'OK' if work_style['pm_ok'] else 'NG'}")

    free_text = (work_style.get("free_text") or "").strip()
    if free_text:
        lines.append(free_text)

    return "\n".join(lines)


def evaluate(skill_sheet_text: str, work_style_text: str, job_posting_text: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が設定されていません。.env に設定してください。"
        )

    client = Anthropic(api_key=api_key)

    user_content = (
        "## スキルシート\n"
        f"{skill_sheet_text}\n\n"
        "## 働き方の希望条件\n"
        f"{work_style_text or '(未設定)'}\n\n"
        "## 求人票\n"
        f"{job_posting_text}\n\n"
        "上記を比較し、submit_evaluation ツールで評価結果を提出してください。"
    )

    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        tools=[_EVALUATION_TOOL],
        tool_choice={"type": "tool", "name": "submit_evaluation"},
        messages=[{"role": "user", "content": user_content}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_evaluation":
            result = block.input
            _enforce_experience_thresholds(result.get("required_skills") or [])
            return result

    raise RuntimeError("Claudeからの評価結果を取得できませんでした。")


def _enforce_experience_thresholds(required_skills: list[dict]) -> None:
    """required_years/actual_yearsが設定された項目のmeetsを、比率に基づき機械的に上書きする。"""
    for item in required_skills:
        required_years = item.get("required_years")
        if required_years is None:
            continue
        if required_years <= 0:
            item["meets"] = "○"
            continue
        actual_years = item.get("actual_years") or 0
        ratio = actual_years / required_years
        epsilon = 1e-9  # 浮動小数点の誤差で境界値が誤判定されるのを防ぐ
        if ratio >= 1 - epsilon:
            item["meets"] = "○"
        elif ratio >= 0.8 - epsilon:
            item["meets"] = "△"
        else:
            item["meets"] = "×"
