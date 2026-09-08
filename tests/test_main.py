import json

from fastapi.testclient import TestClient

from app import llm, main, storage
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
    assert res.json()["ok"] is True
    assert res.json()["work_style"]["rate_min"] == "3000"
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


def test_evaluate_calls_llm_and_saves_history(isolated_data_dir, monkeypatch, make_evaluation):
    client.post("/skill-sheet", data={"manual_text": "経歴"})
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: make_evaluation())

    res = client.post(
        "/evaluate", data={"job_title": "案件X", "job_posting_text": "求人票テキスト"}
    )
    assert res.status_code == 200
    assert "42" in res.text
    assert "応募文サンプル" in res.text

    entries = storage.load_history()
    assert len(entries) == 1
    assert entries[0]["job_title"] == "案件X"


def test_evaluate_public_mode_uses_client_submitted_skill_sheet(
    isolated_data_dir, monkeypatch, make_evaluation
):
    """PUBLIC_MODEではサーバーに保存されたスキルシートを使わず、
    フォームで送られてきた内容（ブラウザのlocalStorage由来）をそのまま使う。"""
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: make_evaluation())
    monkeypatch.setattr(main, "PUBLIC_MODE", True)

    res = client.post(
        "/evaluate",
        data={
            "job_posting_text": "求人票テキスト",
            "client_skill_sheet": "ブラウザ保存の経歴",
            "client_work_style_json": json.dumps({"rate_min": "3000"}),
        },
    )
    assert res.status_code == 200
    assert "42" in res.text
    # サーバー側には一切保存されない
    assert storage.load_skill_sheet() is None
    assert storage.load_history() == []


def test_evaluate_public_mode_ignores_non_dict_work_style_json(
    isolated_data_dir, monkeypatch, make_evaluation
):
    """client_work_style_jsonが構文上は正しいJSONでもdictでなければ（配列・数値等）、
    500にならず空のwork_styleとして扱われること。通常のUI操作では発生しないが、
    直接APIを叩かれた場合の防御として。"""
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: make_evaluation())
    monkeypatch.setattr(main, "PUBLIC_MODE", True)

    res = client.post(
        "/evaluate",
        data={
            "job_posting_text": "求人票テキスト",
            "client_skill_sheet": "ブラウザ保存の経歴",
            "client_work_style_json": json.dumps([1, 2, 3]),
        },
    )
    assert res.status_code == 200
    assert "42" in res.text


def test_evaluate_public_mode_without_client_skill_sheet_redirects(
    isolated_data_dir, monkeypatch
):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    res = client.post(
        "/evaluate", data={"job_posting_text": "求人票"}, follow_redirects=False
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/skill-sheet"


def test_evaluate_public_mode_embeds_history_entry_for_client_storage(
    isolated_data_dir, monkeypatch, make_evaluation
):
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: make_evaluation())
    monkeypatch.setattr(main, "PUBLIC_MODE", True)

    res = client.post(
        "/evaluate",
        data={
            "job_title": "案件X",
            "job_posting_text": "求人票テキスト",
            "client_skill_sheet": "ブラウザ保存の経歴",
        },
    )
    assert res.status_code == 200
    assert "window.__jobfitHistoryEntry" in res.text
    assert '"job_title": "\\u6848\\u4ef6X"' in res.text or "案件X" in res.text


def test_evaluate_public_mode_logs_anonymous_telemetry(
    isolated_data_dir, monkeypatch, make_evaluation
):
    """判定が成功したら、内容を含まない匿名の利用統計（スコアと訪問者ハッシュのみ）が
    1件記録されること。"""
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: make_evaluation(fit_score=77))
    monkeypatch.setattr(main, "PUBLIC_MODE", True)

    client.post(
        "/evaluate",
        data={"job_posting_text": "求人票テキスト", "client_skill_sheet": "経歴"},
    )

    lines = storage.TELEMETRY_PATH.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "evaluate"
    assert entry["fit_score"] == 77
    assert entry["visitor_hash"]


def test_evaluate_not_public_mode_logs_no_telemetry(isolated_data_dir, monkeypatch, make_evaluation):
    client.post("/skill-sheet", data={"manual_text": "経歴"})
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: make_evaluation())
    monkeypatch.setattr(main, "PUBLIC_MODE", False)

    client.post("/evaluate", data={"job_posting_text": "求人票テキスト"})

    assert not storage.TELEMETRY_PATH.exists()


def test_telemetry_outcome_logs_anonymous_entry_in_public_mode(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)

    res = client.post(
        "/telemetry/outcome",
        data={"outcome": "オファー", "fit_score": "85"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    lines = storage.TELEMETRY_PATH.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "outcome"
    assert entry["outcome"] == "オファー"
    assert entry["fit_score"] == 85
    assert entry["visitor_hash"]


def test_telemetry_outcome_rejects_unknown_outcome_value(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", True)

    res = client.post(
        "/telemetry/outcome",
        data={"outcome": "検討中", "fit_score": "50"},
    )
    assert res.status_code == 400
    assert not storage.TELEMETRY_PATH.exists()


def test_telemetry_outcome_disabled_outside_public_mode(isolated_data_dir, monkeypatch):
    monkeypatch.setattr(main, "PUBLIC_MODE", False)

    res = client.post(
        "/telemetry/outcome",
        data={"outcome": "オファー", "fit_score": "85"},
    )
    assert res.status_code == 404
    assert not storage.TELEMETRY_PATH.exists()


def test_telemetry_outcome_uses_cf_connecting_ip_header(isolated_data_dir, monkeypatch):
    """Cloudflare Tunnel経由では素の接続元IPが常にローカルアドレスになるため、
    CF-Connecting-IPヘッダーがあればそちらを訪問者IPとして使うこと。"""
    monkeypatch.setattr(main, "PUBLIC_MODE", True)

    res1 = client.post(
        "/telemetry/outcome",
        data={"outcome": "オファー", "fit_score": "85"},
        headers={"CF-Connecting-IP": "203.0.113.5"},
    )
    res2 = client.post(
        "/telemetry/outcome",
        data={"outcome": "オファー", "fit_score": "85"},
        headers={"CF-Connecting-IP": "203.0.113.5"},
    )
    assert res1.status_code == 200
    assert res2.status_code == 200

    lines = storage.TELEMETRY_PATH.read_text(encoding="utf-8").strip().splitlines()
    hash1 = json.loads(lines[0])["visitor_hash"]
    hash2 = json.loads(lines[1])["visitor_hash"]
    assert hash1 == hash2


def test_evaluate_blocks_when_public_daily_limit_reached(
    isolated_data_dir, monkeypatch, make_evaluation
):
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: make_evaluation())
    monkeypatch.setattr(main, "PUBLIC_MODE", True)
    monkeypatch.setattr(main, "PUBLIC_DAILY_EVALUATE_LIMIT", 1)

    data = {"job_posting_text": "求人票1", "client_skill_sheet": "経歴"}
    res1 = client.post("/evaluate", data=data)
    assert res1.status_code == 200
    assert "42" in res1.text

    res2 = client.post("/evaluate", data={**data, "job_posting_text": "求人票2"})
    assert res2.status_code == 200
    assert "本日の利用上限に達しました" in res2.text


def test_evaluate_not_limited_when_public_mode_off(
    isolated_data_dir, monkeypatch, make_evaluation
):
    client.post("/skill-sheet", data={"manual_text": "経歴"})
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: make_evaluation())
    monkeypatch.setattr(main, "PUBLIC_MODE", False)
    monkeypatch.setattr(main, "PUBLIC_DAILY_EVALUATE_LIMIT", 1)

    client.post("/evaluate", data={"job_posting_text": "求人票1"})
    res = client.post("/evaluate", data={"job_posting_text": "求人票2"})
    assert res.status_code == 200
    assert "42" in res.text
    assert len(storage.load_history()) == 2


def test_evaluate_shows_distinct_error_when_history_save_fails(
    isolated_data_dir, monkeypatch, make_evaluation
):
    client.post("/skill-sheet", data={"manual_text": "経歴"})
    monkeypatch.setattr(llm, "evaluate", lambda *a, **k: make_evaluation())

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


def test_history_entry_with_no_concerns_shows_fallback_text(isolated_data_dir, make_evaluation):
    storage.append_history(
        "懸念なし案件",
        "求人票",
        make_evaluation(fit_score=90, fit_label="応募推奨", application_letter="応募文"),
    )

    res = client.get("/history")
    assert res.status_code == 200
    assert "特になし" in res.text


def test_history_hides_rate_estimate_when_not_enough_samples(isolated_data_dir):
    res = client.get("/history")
    assert res.status_code == 200
    assert "rate-estimate" not in res.text


def test_history_shows_rate_estimate_when_enough_samples(isolated_data_dir, make_evaluation):
    for i in range(3):
        storage.append_history(
            f"案件{i}",
            "求人票",
            make_evaluation(
                fit_score=80,
                posted_rate={"stated_text": "70万円/月", "hourly_min": 4000, "hourly_max": 4500},
            ),
        )

    res = client.get("/history")
    assert res.status_code == 200
    assert "データ不足のため未算出" not in res.text
    assert "推定適正単価" in res.text
    assert "4,000円" in res.text
    assert "4,500円" in res.text


def test_history_sort_by_score(isolated_data_dir):
    storage.append_history("低スコア案件", "求人票", {"fit_score": 10})
    storage.append_history("高スコア案件", "求人票", {"fit_score": 90})

    res = client.get("/history?sort=score")
    assert res.status_code == 200
    assert res.text.index("高スコア案件") < res.text.index("低スコア案件")


def test_history_public_mode_renders_empty_shell(isolated_data_dir, monkeypatch):
    """PUBLIC_MODEでは履歴はサーバーに無いので、GET /historyは空の状態を返す
    （実際のエントリはブラウザ側のJSが/history/renderに投げて差し込む）。"""
    storage.append_history("案件A", "求人票", {"fit_score": 50})
    monkeypatch.setattr(main, "PUBLIC_MODE", True)

    res = client.get("/history")
    assert res.status_code == 200
    assert "まだ判定履歴がありません" in res.text
    assert "案件A" not in res.text


def test_history_render_endpoint_renders_posted_entries_without_saving(isolated_data_dir):
    entries = [
        {
            "id": "1",
            "timestamp": "2026-09-01T00:00:00+00:00",
            "job_title": "ブラウザ保存の案件",
            "job_posting_text": "求人票",
            "evaluation": {
                "fit_score": 77,
                "fit_label": "要検討",
                "required_skills": [],
                "work_style_fit": [],
                "concerns": [],
                "questions_to_ask": [],
                "application_letter": "応募文",
            },
            "outcome": "",
            "outcome_reason": "",
        }
    ]
    res = client.post(
        "/history/render",
        data={"history_json": json.dumps(entries), "page": "1", "sort": "date"},
    )
    assert res.status_code == 200
    assert "ブラウザ保存の案件" in res.text
    # サーバー側には一切保存されない
    assert storage.load_history() == []


def test_history_render_endpoint_paginates_and_sorts(isolated_data_dir):
    entries = [
        {
            "id": str(i),
            "timestamp": "2026-09-01T00:00:00+00:00",
            "job_title": f"案件{i}",
            "job_posting_text": "求人票",
            "evaluation": {
                "fit_score": i,
                "fit_label": "要検討",
                "required_skills": [],
                "work_style_fit": [],
                "concerns": [],
                "questions_to_ask": [],
                "application_letter": "応募文",
            },
            "outcome": "",
            "outcome_reason": "",
        }
        for i in range(12)
    ]
    res = client.post(
        "/history/render",
        data={"history_json": json.dumps(entries), "page": "1", "sort": "score"},
    )
    assert res.status_code == 200
    assert res.text.count('class="history-item"') == 10
    assert res.text.index("案件11") < res.text.index("案件10")


def test_history_render_endpoint_ignores_invalid_json(isolated_data_dir):
    res = client.post(
        "/history/render",
        data={"history_json": "not json", "page": "1", "sort": "date"},
    )
    assert res.status_code == 200
    assert "まだ判定履歴がありません" in res.text


def test_history_render_endpoint_filters_out_malformed_entries(isolated_data_dir):
    """localStorageの中身が壊れていても(evaluation欠落、非dict要素、不正なtimestamp等)、
    500にならず該当エントリだけを無視して描画すること。"""
    valid_entry = {
        "id": "ok",
        "timestamp": "2026-09-01T00:00:00+00:00",
        "job_title": "正常な案件",
        "job_posting_text": "求人票",
        "evaluation": {
            "fit_score": 80,
            "fit_label": "要検討",
            "required_skills": [],
            "work_style_fit": [],
            "concerns": [],
            "questions_to_ask": [],
            "application_letter": "応募文",
        },
        "outcome": "",
        "outcome_reason": "",
    }
    malformed = [
        1,
        "not-a-dict",
        {"id": "no-evaluation", "timestamp": "2026-09-01T00:00:00+00:00"},
        {"id": "bad-fit-score", "timestamp": "2026-09-01T00:00:00+00:00", "evaluation": {"fit_score": "N/A"}},
        {"id": "bad-timestamp", "timestamp": "not-a-date", "evaluation": {"fit_score": 50}},
        {"id": "missing-timestamp", "evaluation": {"fit_score": 50}},
    ]
    entries = [valid_entry, *malformed]

    res = client.post(
        "/history/render",
        data={"history_json": json.dumps(entries), "page": "1", "sort": "date"},
    )
    assert res.status_code == 200
    assert "正常な案件" in res.text
    assert res.text.count('class="history-item"') == 1


def test_set_history_outcome_blocked_in_public_mode(history_entry_id, monkeypatch):
    """PUBLIC_MODEでは履歴はサーバーに保存されないので、このエンドポイントは
    サーバー側の共有ファイルを一切書き換えてはいけない。"""
    entry_id = history_entry_id
    monkeypatch.setattr(main, "PUBLIC_MODE", True)

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "オファー"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 404
    assert res.json()["ok"] is False
    # サーバー側のデータは変更されない
    assert storage.load_history()[0]["outcome"] == ""


def test_set_history_outcome_ajax(history_entry_id):
    entry_id = history_entry_id

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "オファー"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert storage.load_history()[0]["outcome"] == "オファー"


def test_set_history_outcome_unknown_entry_id_returns_404(history_entry_id):
    res = client.post(
        "/history/存在しないid/outcome",
        data={"outcome": "オファー"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 404
    assert res.json()["ok"] is False
    # 既存エントリには影響しない
    assert storage.load_history()[0]["outcome"] == ""


def test_set_history_outcome_rejects_unknown_value(history_entry_id):
    entry_id = history_entry_id

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "検討中"},  # OUTCOME_OPTIONSに存在しない値
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 400
    assert res.json()["ok"] is False
    # 不正な値は保存されない
    assert storage.load_history()[0]["outcome"] == ""


def test_set_history_outcome_accepts_offer_declined(history_entry_id):
    entry_id = history_entry_id

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "オファー辞退"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 200
    assert storage.load_history()[0]["outcome"] == "オファー辞退"


def test_set_history_outcome_accepts_entry_declined(history_entry_id):
    entry_id = history_entry_id

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "エントリー見送り"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 200
    assert storage.load_history()[0]["outcome"] == "エントリー見送り"


def test_set_history_outcome_empty_value_clears_outcome(history_entry_id):
    entry_id = history_entry_id
    storage.update_history_outcome(entry_id, "オファー")

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": ""},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 200
    assert storage.load_history()[0]["outcome"] == ""


def test_set_history_outcome_returns_error_status_on_storage_failure(
    history_entry_id, monkeypatch
):
    """保存に失敗した場合、非2xxを返すこと（フロント側のfetch().catch()で
    エラー表示・選択欄のロールバックを発火させる引き金になる契約）。"""
    entry_id = history_entry_id

    def fail_update(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(storage, "update_history_outcome", fail_update)

    error_client = TestClient(app, raise_server_exceptions=False)
    res = error_client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "オファー"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code >= 500
    # 失敗しているので保存されていないこと
    assert storage.load_history()[0]["outcome"] == ""


def test_set_history_outcome_non_ajax_redirects(history_entry_id):
    entry_id = history_entry_id

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "商談で見送り"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/history"
    assert storage.load_history()[0]["outcome"] == "商談で見送り"


def test_set_history_outcome_saves_reason(history_entry_id):
    entry_id = history_entry_id

    res = client.post(
        f"/history/{entry_id}/outcome",
        data={"outcome": "商談で見送り", "reason": "他候補者との比較の上、お見送り"},
        headers={"X-Requested-With": "fetch"},
    )
    assert res.status_code == 200
    assert storage.load_history()[0]["outcome_reason"] == "他候補者との比較の上、お見送り"


def test_history_page_shows_saved_reason(history_entry_id):
    storage.update_history_outcome(history_entry_id, "商談で見送り", "他候補者との比較の上、お見送り")

    res = client.get("/history")
    assert res.status_code == 200
    assert "他候補者との比較の上、お見送り" in res.text


def test_history_page_shows_outcome_badge(history_entry_id):
    storage.update_history_outcome(history_entry_id, "オファー")

    res = client.get("/history")
    assert res.status_code == 200
    assert "オファー" in res.text


def test_history_page_shows_offer_declined_badge_distinct_from_rejected(history_entry_id):
    storage.update_history_outcome(history_entry_id, "オファー辞退")

    res = client.get("/history")
    assert res.status_code == 200
    assert 'outcome-badge declined"' in res.text
    assert 'outcome-badge rejected"' not in res.text


def test_history_page_shows_entry_declined_badge_distinct_from_rejected(history_entry_id):
    storage.update_history_outcome(history_entry_id, "エントリー見送り")

    res = client.get("/history")
    assert res.status_code == 200
    assert 'outcome-badge declined"' in res.text
    assert 'outcome-badge rejected"' not in res.text
