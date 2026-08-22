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
