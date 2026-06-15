import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _isolate_history_log(tmp_path, monkeypatch):
    """JSONL tarih logunun testlerde production dosyasına yazılmasını engelle."""
    import portfolio as portfolio_mod
    monkeypatch.setattr(portfolio_mod, "HISTORY_LOG_FILE", tmp_path / "history.jsonl")
