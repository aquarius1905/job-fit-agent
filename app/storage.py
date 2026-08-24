"""ローカルファイルへのスキルシート・履歴の保存/読み込み。"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SKILL_SHEET_PATH = DATA_DIR / "skill_sheet.txt"
WORK_STYLE_PATH = DATA_DIR / "work_style.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"


def save_skill_sheet(text: str) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    SKILL_SHEET_PATH.write_text(text, encoding="utf-8")


def load_skill_sheet() -> str | None:
    if not SKILL_SHEET_PATH.exists():
        return None
    return SKILL_SHEET_PATH.read_text(encoding="utf-8")


def save_work_style(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    WORK_STYLE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_work_style() -> dict:
    if not WORK_STYLE_PATH.exists():
        return {}
    return json.loads(WORK_STYLE_PATH.read_text(encoding="utf-8"))


def append_history(job_title: str, job_posting_text: str, evaluation: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "job_title": job_title,
        "job_posting_text": job_posting_text,
        "evaluation": evaluation,
        "outcome": "",
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


def update_history_outcome(entry_id: str, outcome: str) -> bool:
    """指定したidの履歴エントリのoutcomeを更新する。該当エントリがあればTrueを返す。"""
    if not HISTORY_PATH.exists():
        return False

    entries = []
    found = False
    with HISTORY_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("id") == entry_id:
                entry["outcome"] = outcome
                found = True
            entries.append(entry)

    if not found:
        return False

    with HISTORY_PATH.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True
