from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.backtest.models import BacktestRequest
from app.db.repository import BacktestRepository


def test_sqlite_history_survives_repository_restart(tmp_path):
    database = tmp_path / "persistent" / "backtests.sqlite3"
    first = BacktestRepository(database)
    identifier = first.create_pending({
        "ticker": "NVDA", "strategy": "simple", "start_date": "2025-01-01", "end_date": "2025-02-01",
        "parameters": {}, "initial_capital": 100_000,
    })
    second = BacktestRepository(database)
    assert second.get(identifier)["ticker"] == "NVDA"


def test_repository_migrates_legacy_history_with_nullable_strategy_version(tmp_path):
    import sqlite3

    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE backtests (
            id TEXT PRIMARY KEY, created_at TEXT, ticker TEXT, strategy TEXT,
            start_date TEXT, end_date TEXT, parameters_json TEXT, initial_capital REAL,
            final_equity REAL, total_return REAL, cagr REAL, max_drawdown REAL,
            sharpe REAL, status TEXT, result_json TEXT
        )""")
    repository = BacktestRepository(database)
    with repository.connect() as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(backtests)")}
    assert "strategy_version" in columns


@pytest.mark.parametrize("ticker", ["../NVDA", "NVDA;DROP", "NVDA/../../etc"])
def test_ticker_rejects_path_and_command_characters(ticker):
    with pytest.raises(ValidationError):
        BacktestRequest(ticker=ticker, strategy="simple", start_date=date(2025, 1, 1), end_date=date(2025, 2, 1))


def test_date_range_rejects_more_than_twenty_years():
    with pytest.raises(ValidationError):
        BacktestRequest(ticker="NVDA", strategy="simple", start_date=date(2000, 1, 1), end_date=date(2025, 2, 1))


def test_windows_launcher_is_project_scoped_and_loopback_backend():
    root = Path(__file__).resolve().parents[2]
    start = (root / "scripts" / "start-backtest.ps1").read_text(encoding="utf-8")
    stop = (root / "scripts" / "stop-backtest.ps1").read_text(encoding="utf-8")
    common = (root / "scripts" / "backtest-common.ps1").read_text(encoding="utf-8")
    watchdog = (root / "scripts" / "watchdog-backtest.ps1").read_text(encoding="utf-8")
    startup = (root / "scripts" / "install-startup-task.ps1").read_text(encoding="utf-8")
    approval = (root / "scripts" / "approve-windows-launcher.vbs").read_text(encoding="utf-8")
    one_click = (root / "開啟股票回測網站.vbs").read_text(encoding="utf-8-sig")
    assert '"127.0.0.1", "--port", "8000"' in common
    assert "backend\\.venv\\Scripts\\python.exe" in common
    assert "Start-BacktestFrontend $lanIPv4" in start
    assert "Stop-Process -Id $process.Id" in stop
    assert "taskkill" not in stop.lower()
    assert "five" not in watchdog.lower() or "Start-Sleep -Seconds 15" in watchdog
    assert "$restartTimes.Count -ge 5" in watchdog
    assert "System32\\WindowsPowerShell\\v1.0\\powershell.exe" in start
    assert "System32\\WindowsPowerShell\\v1.0\\powershell.exe" in startup
    assert "codex-runtimes" not in start.lower() and "codex-runtimes" not in startup.lower()
    assert "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" in startup
    assert "LogonType Interactive" in startup
    assert "RunLevel Limited" in startup
    assert "WindowsIdentity]::GetCurrent().Name" in startup
    assert all(account not in startup for account in ("SYSTEM", "LocalService", "NetworkService"))
    assert '"runas"' in approval
    assert "install-startup-task.ps1" in approval
    assert "codex-runtimes" not in approval.lower()
    assert "start-backtest.ps1" in one_click
    assert "System32\\WindowsPowerShell\\v1.0\\powershell.exe" in one_click
    assert "codex-runtimes" not in one_click.lower()
