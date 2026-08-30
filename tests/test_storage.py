import json

import pytest

from app import storage


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
