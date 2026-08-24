from app import storage


def test_skill_sheet_roundtrip(isolated_data_dir):
    assert storage.load_skill_sheet() is None
    storage.save_skill_sheet("経歴テキスト")
    assert storage.load_skill_sheet() == "経歴テキスト"


def test_work_style_roundtrip(isolated_data_dir):
    assert storage.load_work_style() == {}
    storage.save_work_style({"rate_min": "1000"})
    assert storage.load_work_style() == {"rate_min": "1000"}


def test_history_append_and_load_order(isolated_data_dir):
    assert storage.load_history() == []
    storage.append_history("案件A", "求人票A", {"fit_score": 50})
    storage.append_history("案件B", "求人票B", {"fit_score": 80})

    entries = storage.load_history()
    assert len(entries) == 2
    # 新しい順(降順)で返る
    assert entries[0]["job_title"] == "案件B"
    assert entries[1]["job_title"] == "案件A"
    assert entries[0]["evaluation"]["fit_score"] == 80


def test_append_history_assigns_unique_id_and_empty_outcome(isolated_data_dir):
    storage.append_history("案件A", "求人票A", {"fit_score": 50})
    storage.append_history("案件B", "求人票B", {"fit_score": 80})

    entries = storage.load_history()
    assert entries[0]["outcome"] == ""
    assert entries[1]["outcome"] == ""
    assert entries[0]["id"] != entries[1]["id"]


def test_update_history_outcome(isolated_data_dir):
    storage.append_history("案件A", "求人票A", {"fit_score": 50})
    storage.append_history("案件B", "求人票B", {"fit_score": 80})
    entry_id = storage.load_history()[0]["id"]  # 案件B

    updated = storage.update_history_outcome(entry_id, "採用")
    assert updated is True

    entries = storage.load_history()
    by_id = {e["id"]: e for e in entries}
    assert by_id[entry_id]["outcome"] == "採用"
    # 他のエントリは影響を受けない
    other = [e for e in entries if e["id"] != entry_id][0]
    assert other["outcome"] == ""


def test_update_history_outcome_unknown_id_returns_false(isolated_data_dir):
    storage.append_history("案件A", "求人票A", {"fit_score": 50})
    assert storage.update_history_outcome("存在しないid", "採用") is False
