import pytest
from dotenv import load_dotenv

from app import storage

load_dotenv()


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """storage.pyの保存先を一時ディレクトリに差し替え、テスト間でファイルを共有させない。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "SKILL_SHEET_PATH", data_dir / "skill_sheet.txt")
    monkeypatch.setattr(storage, "WORK_STYLE_PATH", data_dir / "work_style.json")
    monkeypatch.setattr(storage, "HISTORY_PATH", data_dir / "history.jsonl")
    return data_dir


@pytest.fixture
def make_evaluation():
    """テスト用の最小限の評価結果を組み立てるファクトリを返す。個別のフィールドは上書き可能。"""

    def _make(**overrides) -> dict:
        evaluation = {
            "fit_score": 42,
            "fit_label": "要検討",
            "required_skills": [],
            "work_style_fit": [],
            "concerns": [],
            "questions_to_ask": [],
            "application_letter": "応募文サンプル",
        }
        evaluation.update(overrides)
        return evaluation

    return _make


@pytest.fixture
def history_entry_id(isolated_data_dir):
    """履歴エントリを1件追加し、そのidを返す。"""
    storage.append_history("案件A", "求人票", {"fit_score": 50})
    return storage.load_history()[0]["id"]
