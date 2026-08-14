"""ローカルファイルへのスキルシート・履歴の保存/読み込み。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SKILL_SHEET_PATH = DATA_DIR / "skill_sheet.txt"
HISTORY_PATH = DATA_DIR / "history.jsonl"


def save_skill_sheet(text: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    SKILL_SHEET_PATH.write_text(text, encoding="utf-8")


def load_skill_sheet() -> str | None:
    if not SKILL_SHEET_PATH.exists():
        return None
    return SKILL_SHEET_PATH.read_text(encoding="utf-8")


def append_history(job_title: str, job_posting_text: str, evaluation: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_title": job_title,
        "job_posting_text": job_posting_text,
        "evaluation": evaluation,
    }
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    entries = []
    with HISTORY_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    entries.reverse()
    return entries
