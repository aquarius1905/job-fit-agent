"""ローカルファイルへのスキルシート・履歴の保存/読み込み。

`namespace` を指定すると `data/testers/<namespace>/` 配下に保存する
（お試し利用者ごとにデータを分離するため）。省略時は従来通り `data/` 直下
（自分専用インスタンスでの利用）に保存する。
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SKILL_SHEET_PATH = DATA_DIR / "skill_sheet.txt"
WORK_STYLE_PATH = DATA_DIR / "work_style.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"


def _paths_for(namespace: str) -> tuple[Path, Path, Path]:
    if not namespace:
        return SKILL_SHEET_PATH, WORK_STYLE_PATH, HISTORY_PATH
    base = DATA_DIR / "testers" / namespace
    return base / "skill_sheet.txt", base / "work_style.json", base / "history.jsonl"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_skill_sheet(text: str, namespace: str = "") -> None:
    path, _, _ = _paths_for(namespace)
    _ensure_parent(path)
    path.write_text(text, encoding="utf-8")


def load_skill_sheet(namespace: str = "") -> str | None:
    path, _, _ = _paths_for(namespace)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def save_work_style(data: dict, namespace: str = "") -> None:
    _, path, _ = _paths_for(namespace)
    _ensure_parent(path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_work_style(namespace: str = "") -> dict:
    _, path, _ = _paths_for(namespace)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def append_history(
    job_title: str, job_posting_text: str, evaluation: dict, namespace: str = ""
) -> None:
    _, _, path = _paths_for(namespace)
    _ensure_parent(path)
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "job_title": job_title,
        "job_posting_text": job_posting_text,
        "evaluation": evaluation,
        "outcome": "",
        "outcome_reason": "",
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_history(namespace: str = "") -> list[dict]:
    _, _, path = _paths_for(namespace)
    if not path.exists():
        return []
    entries = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    entries.reverse()
    return entries


def update_history_outcome(
    entry_id: str, outcome: str, reason: str = "", namespace: str = ""
) -> bool:
    """指定したidの履歴エントリのoutcome/outcome_reasonを更新する。該当エントリがあればTrueを返す。"""
    _, _, path = _paths_for(namespace)
    if not path.exists():
        return False

    entries = []
    found = False
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("id") == entry_id:
                entry["outcome"] = outcome
                entry["outcome_reason"] = reason
                found = True
            entries.append(entry)

    if not found:
        return False

    _atomic_write_jsonl(entries, path)
    return True


def _atomic_write_jsonl(entries: list[dict], path: Path) -> None:
    """entriesを一時ファイルに書き出してからpathへ置き換える。

    直接pathへ書き込むと、途中でプロセスが落ちた場合に
    履歴ファイル全体が壊れる/失われる恐れがあるため、書き込みが
    完全に終わってから（同一ディレクトリ内での）アトミックな
    置き換えを行う。
    """
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".history-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        Path(tmp_path).replace(path)
    except BaseException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
