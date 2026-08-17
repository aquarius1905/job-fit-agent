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
                        "meets": {
                            "type": "boolean",
                            "description": "スキルシートの内容から見て満たしているか",
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
            "application_letter",
        ],
    },
}

_SYSTEM_PROMPT = """\
あなたはITフリーランス/エンジニアの案件マッチングを支援するエージェントです。
渡される「スキルシート」（応募者の経歴・スキル情報）「働き方の希望条件」（応募者が案件に求める働き方）と
「求人票」（案件情報）を読み、技術面・働き方面の両方から適合度を厳密に判定してください。

判定方針:
- スキルシートに明記されていない事項は「不明」として満たしていない(meets=false)扱いにし、reasonに「スキルシートに記載なし」等と明記する。憶測で満たしていると判定しない。
- 必須(MUST)条件と歓迎(WANT)条件は求人票の表現から判別し、requiredフィールドに反映する。
- 働き方の希望条件は、項目ごとに求人票の記載内容と照らし合わせてmatchesを判定する。求人票に該当する記載がなければreasonに「求人票に記載なし」と明記し、matchesはfalseにする。「どちらでも可」など希望に幅がある項目は、求人票がその範囲に収まっていればmatchesをtrueにする。
- 懸念点(concerns)には、経験年数不足・スキルのブランク・稼働条件（単価等）のミスマッチに加え、働き方の希望条件との重大な不一致（例: フルリモート希望なのに出社必須）があれば具体的に挙げる。
- 総合適合度(fit_score)は技術面のスキル充足だけでなく、働き方の希望条件との合致度も加味して判定する。働き方の希望条件で重大な不一致（必須級の希望に反する条件）がある場合は、技術面が満たされていてもスコアを大きく下げること。
- 応募文(application_letter)は、スキルシートの中から本案件に関連が強い経験を選んで簡潔にアピールし、丁寧だが定型文っぽくない日本語で書く。誇張や虚偽の経験を書かない。
"""


def compose_work_style_text(work_style: dict) -> str:
    """構造化された働き方の希望条件を、プロンプトに渡すテキストへ組み立てる。"""
    lines = []

    remote_options = work_style.get("remote_options") or []
    if remote_options:
        lines.append(f"出社に関する希望（許容できる働き方）: {'、'.join(remote_options)}")

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
            return block.input

    raise RuntimeError("Claudeからの評価結果を取得できませんでした。")
