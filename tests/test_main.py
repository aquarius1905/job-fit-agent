from fastapi.testclient import TestClient

from app import llm, storage
from app.main import app

client = TestClient(app)


def test_index_without_skill_sheet(isolated_data_dir):
    res = client.get("/")
    assert res.status_code == 200
    assert "まだスキルシートが登録されていません" in res.text


def test_skill_sheet_save_redirects_and_persists(isolated_data_dir):
    res = client.post(
        "/skill-sheet", data={"manual_text": "テスト経歴"}, follow_redirects=False
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/skill-sheet?saved=1"

    res = client.get("/skill-sheet?saved=1")
    assert "テスト経歴" in res.text
    assert "保存しました" in res.text


def test_skill_sheet_ajax_success(isolated_data_dir):
    res = client.post(
        "/skill-sheet",
        data={"manual_text": "Ajax保存テスト"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True, "skill_sheet_text": "Ajax保存テスト"}


def test_skill_sheet_ajax_unsupported_file(isolated_data_dir):
    res = client.post(
        "/skill-sheet",
        files={"file": ("resume.pdf", b"dummy", "application/pdf")},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 400
    body = res.json()
    assert body["ok"] is False
    assert "対応していないファイル形式です" in body["error"]


def test_work_style_ajax_save(isolated_data_dir):
    res = client.post(
        "/work-style",
        data={"remote_options": ["フルリモート"], "rate_min": "3000"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert storage.load_work_style()["rate_min"] == "3000"


def test_evaluate_without_skill_sheet_redirects(isolated_data_dir):
    res = client.post(
        "/evaluate", data={"job_posting_text": "求人票"}, follow_redirects=False
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/skill-sheet"


def test_evaluate_missing_posting_text_shows_error(isolated_data_dir):
    client.post("/skill-sheet", data={"manual_text": "経歴"})
    res = client.post("/evaluate", data={"job_posting_text": ""})
    assert res.status_code == 200
    assert "求人票のテキストを入力するかファイルを選択してください" in res.text


def test_evaluate_unsupported_job_posting_file_shows_error(isolated_data_dir):
    client.post("/skill-sheet", data={"manual_text": "経歴"})
    res = client.post(
        "/evaluate",
        files={"job_posting_file": ("posting.pdf", b"dummy", "application/pdf")},
    )
    assert res.status_code == 200
    assert "対応していないファイル形式です" in res.text


def test_skill_sheet_corrupt_xlsx_shows_error_instead_of_500(isolated_data_dir):
    res = client.post(
        "/skill-sheet",
        files={"file": ("skill.xlsx", b"not a real zip file", "application/octet-stream")},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 400
    body = res.json()
    assert body["ok"] is False
    assert "読み込めませんでした" in body["error"]


def test_evaluate_calls_llm_and_saves_history(isolated_data_dir, monkeypatch):
    client.post("/skill-sheet", data={"manual_text": "経歴"})

    fake_result = {
        "fit_score": 42,
        "fit_label": "要検討",
        "required_skills": [],
        "work_style_fit": [],
        "concerns": [],
        "questions_to_ask": [],
        "application_letter": "応募文サンプル",
    }
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: fake_result)

    res = client.post(
        "/evaluate", data={"job_title": "案件X", "job_posting_text": "求人票テキスト"}
    )
    assert res.status_code == 200
    assert "42" in res.text
    assert "応募文サンプル" in res.text

    entries = storage.load_history()
    assert len(entries) == 1
    assert entries[0]["job_title"] == "案件X"


def test_evaluate_shows_distinct_error_when_history_save_fails(
    isolated_data_dir, monkeypatch
):
    client.post("/skill-sheet", data={"manual_text": "経歴"})

    fake_result = {
        "fit_score": 42,
        "fit_label": "要検討",
        "required_skills": [],
        "work_style_fit": [],
        "concerns": [],
        "questions_to_ask": [],
        "application_letter": "応募文サンプル",
    }
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: fake_result)

    def fail_append_history(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "append_history", fail_append_history)

    res = client.post(
        "/evaluate", data={"job_title": "案件X", "job_posting_text": "求人票テキスト"}
    )
    assert res.status_code == 200
    # 評価自体は成功しているので、結果はそのまま表示される
    assert "応募文サンプル" in res.text
    # ただし保存に失敗したことが分かるメッセージが出る（判定失敗と誤解させない）
    assert "履歴への保存に失敗しました" in res.text


def test_history_pagination(isolated_data_dir):
    for i in range(15):
        storage.append_history(f"案件{i}", "求人票", {"fit_score": i})

    res = client.get("/history")
    assert res.status_code == 200
    assert res.text.count('class="history-item"') == 10
    assert "1 / 2" in res.text

    res = client.get("/history?page=2")
    assert res.text.count('class="history-item"') == 5
    assert "2 / 2" in res.text

    # 範囲外のページは最終ページにクランプされる
    res = client.get("/history?page=99")
    assert "2 / 2" in res.text


def test_history_entry_with_no_concerns_shows_fallback_text(isolated_data_dir):
    storage.append_history(
        "懸念なし案件",
        "求人票",
        {
            "fit_score": 90,
            "fit_label": "応募推奨",
            "required_skills": [],
            "work_style_fit": [],
            "concerns": [],
            "questions_to_ask": [],
            "application_letter": "応募文",
        },
    )

    res = client.get("/history")
    assert res.status_code == 200
    assert "特になし" in res.text


def test_history_sort_by_score(isolated_data_dir):
    storage.append_history("低スコア案件", "求人票", {"fit_score": 10})
    storage.append_history("高スコア案件", "求人票", {"fit_score": 90})

    res = client.get("/history?sort=score")
    assert res.status_code == 200
    assert res.text.index("高スコア案件") < res.text.index("低スコア案件")


def test_set_history_outcome_ajax(isolated_data_dir):
    storage.append_history("案件A", "求人票", {"fit_score": 50})
    entry_id = storage.load_history()[0]["id"]

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "採用"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert storage.load_history()[0]["outcome"] == "採用"


def test_set_history_outcome_rejects_unknown_value(isolated_data_dir):
    storage.append_history("案件A", "求人票", {"fit_score": 50})
    entry_id = storage.load_history()[0]["id"]

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "内定辞退"},  # OUTCOME_OPTIONSに存在しない値
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 400
    assert res.json()["ok"] is False
    # 不正な値は保存されない
    assert storage.load_history()[0]["outcome"] == ""


def test_set_history_outcome_empty_value_clears_outcome(isolated_data_dir):
    storage.append_history("案件A", "求人票", {"fit_score": 50})
    entry_id = storage.load_history()[0]["id"]
    storage.update_history_outcome(entry_id, "採用")

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": ""},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 200
    assert storage.load_history()[0]["outcome"] == ""


def test_set_history_outcome_returns_error_status_on_storage_failure(
    isolated_data_dir, monkeypatch
):
    """保存に失敗した場合、非2xxを返すこと（フロント側のfetch().catch()で
    エラー表示・選択欄のロールバックを発火させる引き金になる契約）。"""
    storage.append_history("案件A", "求人票", {"fit_score": 50})
    entry_id = storage.load_history()[0]["id"]

    def fail_update(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "update_history_outcome", fail_update)

    error_client = TestClient(app, raise_server_exceptions=False)
    res = error_client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "採用"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code >= 500
    # 失敗しているので保存されていないこと
    assert storage.load_history()[0]["outcome"] == ""


def test_set_history_outcome_non_ajax_redirects(isolated_data_dir):
    storage.append_history("案件A", "求人票", {"fit_score": 50})
    entry_id = storage.load_history()[0]["id"]

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "商談で不採用"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/history"
    assert storage.load_history()[0]["outcome"] == "商談で不採用"


def test_history_page_shows_outcome_badge(isolated_data_dir):
    storage.append_history("案件A", "求人票", {"fit_score": 50})
    entry_id = storage.load_history()[0]["id"]
    storage.update_history_outcome(entry_id, "採用")

    res = client.get("/history")
    assert res.status_code == 200
    assert "採用" in res.text
