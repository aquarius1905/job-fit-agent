import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from app import storage


def _increment_at(path_str: str, limit: int, today: str) -> bool:
    """複数プロセスでの排他制御をテストするためのヘルパー。
    ProcessPoolExecutorで別プロセスとして実行されるため、pickle可能な
    モジュールトップレベル関数として定義する。"""
    storage.PUBLIC_USAGE_PATH = Path(path_str)
    return storage.increment_public_usage(limit, today)


@pytest.fixture
def two_history_entries(isolated_data_dir):
    """案件A・案件Bの2件を追加する（案件Bが新しい）。"""
    storage.append_history("案件A", "求人票A", {"fit_score": 50})
    storage.append_history("案件B", "求人票B", {"fit_score": 80})


def test_skill_sheet_roundtrip(isolated_data_dir):
    assert storage.load_skill_sheet() is None
    storage.save_skill_sheet("経歴テキスト")
    assert storage.load_skill_sheet() == "経歴テキスト"


def test_work_style_roundtrip(isolated_data_dir):
    assert storage.load_work_style() == {}
    storage.save_work_style({"rate_min": "1000"})
    assert storage.load_work_style() == {"rate_min": "1000"}


def test_load_history_empty_when_no_data(isolated_data_dir):
    assert storage.load_history() == []


def test_history_append_and_load_order(two_history_entries):
    entries = storage.load_history()
    assert len(entries) == 2
    # 新しい順(降順)で返る
    assert entries[0]["job_title"] == "案件B"
    assert entries[1]["job_title"] == "案件A"
    assert entries[0]["evaluation"]["fit_score"] == 80


def test_append_history_assigns_unique_id_and_empty_outcome(two_history_entries):
    entries = storage.load_history()
    assert entries[0]["outcome"] == ""
    assert entries[0]["outcome_reason"] == ""
    assert entries[1]["outcome"] == ""
    assert entries[0]["id"] != entries[1]["id"]


def test_update_history_outcome(two_history_entries):
    entry_id = storage.load_history()[0]["id"]  # 案件B

    updated = storage.update_history_outcome(entry_id, "オファー")
    assert updated is True

    entries = storage.load_history()
    by_id = {e["id"]: e for e in entries}
    assert by_id[entry_id]["outcome"] == "オファー"
    # 他のエントリは影響を受けない
    other = [e for e in entries if e["id"] != entry_id][0]
    assert other["outcome"] == ""


def test_update_history_outcome_saves_reason(two_history_entries):
    entry_id = storage.load_history()[0]["id"]  # 案件B

    storage.update_history_outcome(entry_id, "商談で見送り", "他候補者との比較の上、お見送り")

    entries = storage.load_history()
    by_id = {e["id"]: e for e in entries}
    assert by_id[entry_id]["outcome_reason"] == "他候補者との比較の上、お見送り"


def test_increment_public_usage_allows_until_limit(isolated_data_dir):
    assert storage.increment_public_usage(2, "2026-09-08") is True
    assert storage.increment_public_usage(2, "2026-09-08") is True
    assert storage.increment_public_usage(2, "2026-09-08") is False


def test_increment_public_usage_resets_on_new_day(isolated_data_dir):
    assert storage.increment_public_usage(1, "2026-09-08") is True
    assert storage.increment_public_usage(1, "2026-09-08") is False
    assert storage.increment_public_usage(1, "2026-09-09") is True


def test_increment_public_usage_is_safe_across_processes(isolated_data_dir):
    """複数ワーカープロセスから同時に呼ばれても、上限を超えて許可されないこと
    （ファイルロックなしだと、複数プロセスが同時にcountを読んで両方許可してしまう）。"""
    limit = 10
    today = "2026-09-08"
    path_str = str(storage.PUBLIC_USAGE_PATH)

    with ProcessPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(_increment_at, [path_str] * 30, [limit] * 30, [today] * 30)
        )

    # ちょうどlimit回だけ許可され、残りは全て拒否されること
    assert sum(results) == limit
    data = json.loads(Path(path_str).read_text(encoding="utf-8"))
    assert data["count"] == limit


def test_update_history_outcome_defaults_reason_to_empty(two_history_entries):
    entry_id = storage.load_history()[0]["id"]  # 案件B

    storage.update_history_outcome(entry_id, "オファー")

    entries = storage.load_history()
    by_id = {e["id"]: e for e in entries}
    assert by_id[entry_id]["outcome_reason"] == ""


def test_update_history_outcome_unknown_id_returns_false(history_entry_id):
    assert storage.update_history_outcome("存在しないid", "オファー") is False


def test_update_history_outcome_leaves_original_file_intact_on_write_failure(
    two_history_entries, monkeypatch
):
    """書き込み中に失敗しても、history.jsonl全体が壊れたり消えたりしないこと。"""
    original_content = storage.HISTORY_PATH.read_text(encoding="utf-8")
    entry_id = storage.load_history()[0]["id"]  # 案件B

    real_dumps = json.dumps
    call_count = {"n": 0}

    def flaky_dumps(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:  # 1件目の書き込みは成功、2件目で書き込み失敗を模擬
            raise ValueError("boom")
        return real_dumps(*args, **kwargs)

    monkeypatch.setattr(json, "dumps", flaky_dumps)

    with pytest.raises(ValueError):
        storage.update_history_outcome(entry_id, "オファー")

    # 元のファイルは書き込み失敗前のまま残っている（壊れていない）
    assert storage.HISTORY_PATH.read_text(encoding="utf-8") == original_content
    # 一時ファイルも残っていない
    assert list(storage.DATA_DIR.glob(".history-*.tmp")) == []


def test_build_history_entry_does_not_write_to_disk(isolated_data_dir):
    entry = storage.build_history_entry("案件A", "求人票A", {"fit_score": 50})

    assert entry["job_title"] == "案件A"
    assert entry["evaluation"] == {"fit_score": 50}
    assert entry["outcome"] == ""
    assert entry["id"]
    assert entry["timestamp"]
    assert not storage.HISTORY_PATH.exists()


def test_append_history_returns_the_written_entry(isolated_data_dir):
    entry = storage.append_history("案件A", "求人票A", {"fit_score": 50})

    assert entry["job_title"] == "案件A"
    assert storage.load_history()[0]["id"] == entry["id"]


def test_hash_visitor_is_deterministic_for_same_input(isolated_data_dir):
    h1 = storage.hash_visitor("203.0.113.1", "Mozilla/5.0")
    h2 = storage.hash_visitor("203.0.113.1", "Mozilla/5.0")
    assert h1 == h2


def test_hash_visitor_differs_for_different_ip(isolated_data_dir):
    h1 = storage.hash_visitor("203.0.113.1", "Mozilla/5.0")
    h2 = storage.hash_visitor("203.0.113.2", "Mozilla/5.0")
    assert h1 != h2


def test_hash_visitor_does_not_leak_raw_ip(isolated_data_dir):
    h = storage.hash_visitor("203.0.113.1", "Mozilla/5.0")
    assert "203.0.113.1" not in h


def test_hash_visitor_salt_persists_across_calls(isolated_data_dir):
    """ソルトファイルが一度作られたら、以後同じ値が使われ続けること
    （サーバー再起動をまたいでもハッシュの一貫性が保たれる前提）。"""
    storage.hash_visitor("203.0.113.1", "Mozilla/5.0")
    assert storage.TELEMETRY_SALT_PATH.exists()
    saved_salt = storage.TELEMETRY_SALT_PATH.read_text(encoding="utf-8")

    h_before = storage.hash_visitor("203.0.113.9", "curl/8.0")
    assert storage.TELEMETRY_SALT_PATH.read_text(encoding="utf-8") == saved_salt
    h_after = storage.hash_visitor("203.0.113.9", "curl/8.0")
    assert h_before == h_after


def test_append_telemetry_writes_only_given_fields(isolated_data_dir):
    storage.append_telemetry("evaluate", fit_score=85, visitor_hash="abc123")

    lines = storage.TELEMETRY_PATH.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "evaluate"
    assert entry["fit_score"] == 85
    assert entry["visitor_hash"] == "abc123"
    assert "timestamp" in entry
    # スキルシート・求人票等の内容フィールドは一切存在しない
    assert set(entry.keys()) == {"timestamp", "event", "fit_score", "visitor_hash"}
