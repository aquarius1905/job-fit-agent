"""ローカルファイルへのスキルシート・履歴の保存/読み込み（自分専用インスタンス向け）。

PUBLIC_MODE（お試し公開用インスタンス）では、スキルシートや履歴はサーバーに
保存せずブラウザのlocalStorageに保存する方式に変えたため、ここでの保存関数は
自分専用インスタンスでのみ使われる。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SKILL_SHEET_PATH = DATA_DIR / "skill_sheet.txt"
WORK_STYLE_PATH = DATA_DIR / "work_style.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"
PUBLIC_USAGE_PATH = DATA_DIR / "public_usage.json"
TELEMETRY_PATH = DATA_DIR / "telemetry.jsonl"
TELEMETRY_SALT_PATH = DATA_DIR / "telemetry_salt.txt"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_skill_sheet(text: str) -> None:
    _ensure_parent(SKILL_SHEET_PATH)
    SKILL_SHEET_PATH.write_text(text, encoding="utf-8")


def load_skill_sheet() -> str | None:
    if not SKILL_SHEET_PATH.exists():
        return None
    return SKILL_SHEET_PATH.read_text(encoding="utf-8")


def save_work_style(data: dict) -> None:
    _ensure_parent(WORK_STYLE_PATH)
    WORK_STYLE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_work_style() -> dict:
    if not WORK_STYLE_PATH.exists():
        return {}
    return json.loads(WORK_STYLE_PATH.read_text(encoding="utf-8"))


def build_history_entry(job_title: str, job_posting_text: str, evaluation: dict) -> dict:
    """履歴エントリの中身を組み立てるだけで、ファイルには書き込まない。

    PUBLIC_MODE（ブラウザ側にのみ履歴を保存する）で、サーバーを経由させずに
    idやtimestampの採番だけ揃えたエントリを作りたい場合に使う。
    """
    return {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "job_title": job_title,
        "job_posting_text": job_posting_text,
        "evaluation": evaluation,
        "outcome": "",
        "outcome_reason": "",
    }


def append_history(job_title: str, job_posting_text: str, evaluation: dict) -> dict:
    entry = build_history_entry(job_title, job_posting_text, evaluation)
    _ensure_parent(HISTORY_PATH)
    with HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


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


def update_history_outcome(entry_id: str, outcome: str, reason: str = "") -> bool:
    """指定したidの履歴エントリのoutcome/outcome_reasonを更新する。該当エントリがあればTrueを返す。"""
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
                entry["outcome_reason"] = reason
                found = True
            entries.append(entry)

    if not found:
        return False

    _atomic_write_jsonl(entries, HISTORY_PATH)
    return True


def increment_public_usage(limit: int, today: str) -> bool:
    """PUBLIC_MODEでの1日あたりのClaude API呼び出し回数を管理する（全利用者共通）。

    上限未満なら回数を1増やしてTrueを返す。上限に達していれば増やさずFalseを返す。
    JST日付が変わったらカウントは自動的にリセットされる。

    呼び出し元（アプリ側）でスレッドプール実行にすることに加え、複数ワーカー
    プロセスで動かした場合でも読み取り→更新→書き込みの間に他プロセスが
    割り込んで上限を超過させることがないよう、ファイルロックで排他制御する。
    """
    path = PUBLIC_USAGE_PATH
    _ensure_parent(path)
    lock_path = path.with_name(path.name + ".lock")

    with open(lock_path, "w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            data = {"date": today, "count": 0}
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    data = {"date": today, "count": 0}
            if data.get("date") != today:
                data = {"date": today, "count": 0}
            if data["count"] >= limit:
                return False
            data["count"] += 1

            fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".public-usage-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(json.dumps(data))
                Path(tmp_path).replace(path)
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise
            return True
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _get_or_create_telemetry_salt() -> str:
    """匿名利用統計のハッシュ化に使うソルトを取得する。なければ生成して保存する。

    このソルト自体は誰かを特定する情報ではなく、同じIP+User-Agentが毎回同じ
    ハッシュ値になるようにするための固定値（トライアル期間を通じて再訪判定の
    一貫性を保つため、サーバー再起動をまたいで永続化する）。
    """
    if TELEMETRY_SALT_PATH.exists():
        return TELEMETRY_SALT_PATH.read_text(encoding="utf-8").strip()
    salt = secrets.token_hex(16)
    _ensure_parent(TELEMETRY_SALT_PATH)
    TELEMETRY_SALT_PATH.write_text(salt, encoding="utf-8")
    return salt


def hash_visitor(ip: str, user_agent: str) -> str:
    """IPアドレスとUser-Agentから、元に戻せない訪問者の目安ハッシュを作る。

    生のIPアドレスは一切保存しない。あくまで大まかな再訪判定にのみ使う
    （同一回線の複数人での共有、回線切り替え等により精度は粗い）。
    """
    salt = _get_or_create_telemetry_salt()
    digest = hashlib.sha256(f"{salt}:{ip}:{user_agent}".encode()).hexdigest()
    return digest[:16]


def append_telemetry(event: str, **fields: object) -> None:
    """個人・内容を一切含まない匿名の利用統計を追記する。

    PUBLIC_MODEでの利用傾向（実際に使われた回数、再訪の目安、判定スコアと
    選考結果の相関）を把握するためだけに使う。スキルシート・求人票・応募文等の
    内容は絶対に含めないこと。
    """
    _ensure_parent(TELEMETRY_PATH)
    entry = {"timestamp": datetime.now(UTC).isoformat(), "event": event, **fields}
    with TELEMETRY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
