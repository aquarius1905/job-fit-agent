import pytest

from app import storage


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """storage.pyの保存先を一時ディレクトリに差し替え、テスト間でファイルを共有させない。"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(storage, "DATA_DIR", data_dir)
    monkeypatch.setattr(storage, "SKILL_SHEET_PATH", data_dir / "skill_sheet.txt")
    monkeypatch.setattr(storage, "WORK_STYLE_PATH", data_dir / "work_style.json")
    monkeypatch.setattr(storage, "HISTORY_PATH", data_dir / "history.jsonl")
    return data_dir
