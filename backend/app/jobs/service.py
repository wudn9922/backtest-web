from __future__ import annotations

import json
import queue
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.backtest.models import BacktestError
from app.data.base import validate_daily_ohlcv
from app.data.stooq import StooqDataProvider
from app.data.yahoo import YahooDataProvider, safe_yahoo_error
from app.jobs.connectivity import (
    launch_windows_launcher_approval,
    run_diagnostic,
    runtime_environment,
    write_fred_smoke_cache,
)
from app.jobs.repository import JobRepository
from app.db.repository import BacktestRepository


MARKET_JOB = "RESEARCH_MARKET_DATA_DOWNLOAD"
RATE_JOB = "RISK_FREE_DATA_DOWNLOAD"
CONNECTIVITY_JOB = "PROVIDER_CONNECTIVITY_CHECK"
REPAIR_JOB = "PROVIDER_CONNECTIVITY_REPAIR"
SMOKE_JOB = "PROVIDER_DOWNLOAD_SMOKE_TEST"
RESEARCH_JOB = "RESEARCH_ENVIRONMENT_VALIDATION"
MA_OPTIMIZATION_JOB = "MA_PERIOD_OPTIMIZATION"
ALLOWED_JOB_TYPES = {MARKET_JOB, RATE_JOB, CONNECTIVITY_JOB, REPAIR_JOB, SMOKE_JOB, RESEARCH_JOB, MA_OPTIMIZATION_JOB}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _enable_research_imports() -> Path:
    root = _project_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _safe_error(value: object) -> str:
    return safe_yahoo_error(value)[:500]


class JobService:
    """Single-worker durable queue owned by the formal Windows backend."""

    def __init__(self, data_dir: Path, provider_chain: Any, backtest_repository: BacktestRepository | None = None):
        self.data_dir = data_dir.resolve()
        self.provider_chain = provider_chain
        self.backtest_repository = backtest_repository or BacktestRepository(self.data_dir / "backtests.sqlite3")
        self.repository = JobRepository(self.data_dir / "background-jobs.sqlite3")
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="backtest-background-jobs", daemon=True)

    def start(self) -> None:
        for identifier in self.repository.recover_interrupted():
            self._queue.put(identifier)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set(); self._queue.put(None)
        self._thread.join(timeout=5)

    def create(self, job_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if job_type not in ALLOWED_JOB_TYPES:
            raise ValueError("unsupported job type")
        payload = payload or {}
        if job_type == MA_OPTIMIZATION_JOB:
            try:
                combinations = ((int(payload["ma_max"]) - int(payload["ma_min"])) // int(payload["ma_step"])) + 1
                if payload.get("mode", "single") == "rolling_6m":
                    from app.optimization.models import MAOptimizationRequest
                    from app.optimization.windows import build_rolling_six_month_windows
                    spec = MAOptimizationRequest.model_validate(payload)
                    windows = build_rolling_six_month_windows(spec.backtest.start_date, spec.backtest.end_date)
                    # Structure mode keeps an independent Performance
                    # comparator and adds a Structure-selected Test track;
                    # the latter may reuse a canonical result but still has a
                    # visible/persisted progress phase.
                    extra_test_track = 1 if spec.selection_mode == "STRUCTURE_V1" else 0
                    total = len(windows) * (combinations + 2 + extra_test_track)
                else:
                    total = combinations + (1 if bool((payload.get("train_test") or {}).get("enabled")) else 0)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                total = 0
        else:
            total = 23 if job_type == MARKET_JOB else 3 if job_type in {CONNECTIVITY_JOB, REPAIR_JOB} else 2 if job_type == SMOKE_JOB else 1
        job, created = self.repository.create(job_type, payload, total)
        if created:
            self._queue.put(str(job["id"]))
        return job

    def retry(self, identifier: str) -> dict[str, Any]:
        source = self.repository.get(identifier)
        if not source:
            raise KeyError(identifier)
        failed = [str(row.get("ticker")) for row in source.get("errors", []) if row.get("ticker")]
        payload = dict(source.get("payload", {}))
        payload["retry_of"] = identifier
        if source["job_type"] == MARKET_JOB:
            payload["tickers"] = list(dict.fromkeys(failed))
        return self.create(str(source["job_type"]), payload)

    def _run(self) -> None:
        while not self._stop.is_set():
            identifier = self._queue.get()
            if identifier is None:
                break
            job = self.repository.get(identifier)
            if not job or job["status"] != "QUEUED":
                continue
            self.repository.mark_running(identifier)
            try:
                result = self._dispatch(identifier, job)
                if result is not None and (self.repository.get(identifier) or {}).get("status") == "RUNNING":
                    self.repository.finish(identifier, "COMPLETED", "工作已完成。", result=result)
            except Exception as exc:
                validation_failure = exc.__class__.__name__ == "EnvironmentValidationError"
                self.repository.finish(
                    identifier,
                    "FAILED_VALIDATION" if validation_failure else "FAILED",
                    "研究輸出一致性驗證失敗，未發布矛盾報告。" if validation_failure else "工作未完成，稍後可以重試。",
                    errors=[{
                        "code": "RESEARCH_REPORT_VALIDATION_FAILED" if validation_failure else "JOB_FAILED",
                        "message": _safe_error(exc),
                    }],
                )

    def _dispatch(self, identifier: str, job: dict[str, Any]) -> dict[str, Any] | None:
        kind = job["job_type"]
        if kind == CONNECTIVITY_JOB:
            return self._connectivity(identifier)
        if kind == REPAIR_JOB:
            return self._repair_connectivity(identifier)
        if kind == SMOKE_JOB:
            return self._download_smoke_test(identifier)
        if kind == MARKET_JOB:
            return self._market(identifier, job.get("payload", {}))
        if kind == RATE_JOB:
            return self._risk_free(identifier)
        if kind == RESEARCH_JOB:
            return self._research_validation(identifier)
        if kind == MA_OPTIMIZATION_JOB:
            from app.optimization.runner import run_ma_optimization
            return run_ma_optimization(
                identifier, job.get("payload", {}), self.repository,
                self.backtest_repository, self.provider_chain,
            )
        raise ValueError("unsupported job type")

    def _connectivity(self, identifier: str) -> dict[str, Any]:
        self.repository.progress(identifier, 0, 3, "NETWORK", "正在由回測引擎檢查外部連線。")
        diagnostic = run_diagnostic(self.provider_chain, _project_root())
        results = diagnostic["providers"]
        for index, name in enumerate(("yahoo", "stooq", "fred"), start=1):
            row = results[name]
            status, error = str(row["status"]), row.get("error_type")
            if status == "online":
                message = None
            elif status == "restricted":
                message = "資料來源暫時限制請求，稍後可再試。"
            elif status == "validation_failed":
                message = "資料來源有回應，但資料驗證未通過。"
            else:
                message = "資料來源目前無法連線。"
            self.repository.update_provider(name, status, error, message)
            self.repository.progress(identifier, index, 3, name.upper() if index < 3 else None, f"{name.upper()} 檢查完成。", result={"providers": results})
        return {
            "providers": results,
            "network_control": diagnostic["network_control"],
            "runtime": diagnostic["runtime"],
            "technical_log_written": True,
        }

    def _repair_connectivity(self, identifier: str) -> dict[str, Any] | None:
        self.repository.progress(identifier, 0, 3, "WINDOWS", "正在確認 Windows 服務啟動環境。")
        runtime = runtime_environment(_project_root())
        if runtime["repair_required"]:
            approval_launched = launch_windows_launcher_approval(_project_root())
            self.repository.finish(
                identifier,
                "FAILED",
                "一次性設定檔已在檔案總管選取；請雙擊它，再按允許／是。" if approval_launched else "Windows 使用者啟動環境尚未完成一次性核准。",
                errors=[{
                    "code": "WINDOWS_LAUNCHER_APPROVAL_REQUIRED" if approval_launched else "WINDOWS_LAUNCHER_APPROVAL_FAILED",
                    "message": "請雙擊已選取的設定檔，再完成一次 Windows 圖形介面確認。" if approval_launched else "無法開啟 Windows 圖形確認流程。",
                }],
                result={
                    "runtime": {key: value for key, value in runtime.items() if key != "technical"},
                    "gui_approval_required": True,
                    "gui_approval_launched": approval_launched,
                },
            )
            return None
        result = self._connectivity(identifier)
        result["repair_completed"] = True
        return result

    def runtime_health(self) -> dict[str, Any]:
        value = runtime_environment(_project_root())
        return {key: item for key, item in value.items() if key != "technical"}

    def _download_smoke_test(self, identifier: str) -> dict[str, Any] | None:
        """Run two tiny real downloads through the formal backend process.

        The market sample uses the production Yahoo adapter and Parquet cache.
        The FRED sample is isolated from the completeness/readiness manifest so
        a short connectivity test can never masquerade as full research data.
        """
        end = date.today() - timedelta(days=1)
        start = end - timedelta(days=20)
        results: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []

        self.repository.progress(identifier, 0, 2, "YAHOO", "正在下載小型 Yahoo 日線測試資料。")
        yahoo = self.provider_chain.yahoo
        candidates = ("VTI", "KO", "JNJ", "XOM")
        ticker = next((item for item in candidates if not yahoo.cache.has_any(item, "1d")), candidates[0])
        try:
            market = yahoo.get_market_data(ticker, start, end)
            valid, issue = validate_daily_ohlcv(market.daily)
            if not valid or market.daily.empty:
                raise RuntimeError(issue or "Yahoo returned no daily bars")
            coverage = yahoo.cache.read_coverage(ticker, "1d", start, end)
            results["market"] = {
                "ticker": ticker,
                "provider": "yahoo",
                "bars": int(len(market.daily)),
                "first_date": market.daily.index[0].date().isoformat(),
                "last_date": market.daily.index[-1].date().isoformat(),
                "cache_written": bool(coverage.paths),
                "cache_complete": bool(coverage.complete),
            }
            self.repository.update_provider("yahoo", "online")
        except BacktestError as exc:
            status = "restricted" if exc.code == "RATE_LIMITED" else "offline"
            self.repository.update_provider("yahoo", status, exc.code, "Yahoo 暫時受限。" if status == "restricted" else "Yahoo 目前無法連線。")
            errors.append({"ticker": ticker, "code": exc.code, "message": "Yahoo 小型資料下載未完成。", "technical": _safe_error(exc.message)})
        except Exception as exc:
            errors.append({"ticker": ticker, "code": "MARKET_SMOKE_DOWNLOAD_FAILED", "message": "Yahoo 小型資料下載未完成。", "technical": _safe_error(exc)})
        self.repository.progress(identifier, 1, 2, "FRED", "Yahoo 測試完成，正在下載小型 FRED 資料。", errors=errors, result=results)

        try:
            manifest = write_fred_smoke_cache(self.data_dir, start, end)
            results["risk_free"] = manifest
            self.repository.update_provider("fred", "online")
        except Exception as exc:
            errors.append({"code": "RISK_FREE_SMOKE_DOWNLOAD_FAILED", "message": "FRED 小型資料下載未完成。", "technical": _safe_error(exc)})
        self.repository.progress(identifier, 2, 2, None, "小型真實下載驗證完成。", errors=errors, result=results)

        if errors:
            status = "PARTIAL_SUCCESS" if results else "FAILED"
            self.repository.finish(identifier, status, "小型驗證部分完成。" if results else "小型驗證未完成。", errors=errors, result=results)
            return None
        return results

    def _market(self, identifier: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        root = _enable_research_imports()
        from research.environment_v3_design import ETF_RESEARCH_UNIVERSE, MEGA_CAP_TECH_UNIVERSE, PRIMARY_HISTORY
        from research.prepare_environment_v3 import write_manifests

        all_tickers = list(dict.fromkeys((*MEGA_CAP_TECH_UNIVERSE, *ETF_RESEARCH_UNIVERSE)))
        requested = payload.get("tickers")
        tickers = [ticker for ticker in all_tickers if not requested or ticker in requested]
        total = len(tickers)
        yahoo = YahooDataProvider(root / "data/research-cache/yahoo")
        stooq = StooqDataProvider(root / "data/research-cache/stooq")
        completed: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        rate_limited = False
        for index, ticker in enumerate(tickers, start=1):
            self.repository.progress(identifier, index - 1, total, ticker, f"正在處理 {ticker}。", errors=errors, result={"completed": completed})
            if rate_limited:
                errors.append({"ticker": ticker, "code": "RATE_LIMITED", "message": "Yahoo 暫時限制下載速度，請稍後繼續。"})
                self.repository.progress(identifier, index, total, ticker, f"{ticker} 等待稍後重試。", errors=errors, result={"completed": completed})
                continue
            try:
                cached = yahoo.get_cached_market_data(ticker, PRIMARY_HISTORY["start"], PRIMARY_HISTORY["end"])
                if cached is not None:
                    completed.append({"ticker": ticker, "status": "CACHE_COMPLETE", "provider": "yahoo", "bars": len(cached.daily)})
                else:
                    market = yahoo.get_market_data(ticker, PRIMARY_HISTORY["start"], PRIMARY_HISTORY["end"])
                    valid, issue = validate_daily_ohlcv(market.daily)
                    if not valid:
                        raise RuntimeError(issue)
                    completed.append({"ticker": ticker, "status": "DOWNLOADED", "provider": "yahoo", "bars": len(market.daily)})
                    self.repository.update_provider("yahoo", "online")
            except BacktestError as exc:
                if exc.code == "RATE_LIMITED":
                    rate_limited = True
                    self.repository.update_provider("yahoo", "restricted", "RATE_LIMITED", "Yahoo 暫時限制下載速度，系統會稍後繼續。")
                else:
                    self.repository.update_provider("yahoo", "offline", exc.code, "Yahoo 目前無法連線。")
                # A fallback is downloaded only into its isolated namespace. It
                # is never spliced into the Yahoo dataset.
                try:
                    fallback = stooq.get_market_data(ticker, PRIMARY_HISTORY["start"], PRIMARY_HISTORY["end"])
                    valid, issue = validate_daily_ohlcv(fallback.daily)
                    if not valid:
                        raise RuntimeError(issue)
                    completed.append({"ticker": ticker, "status": "FALLBACK_ISOLATED", "provider": "stooq", "bars": len(fallback.daily)})
                    self.repository.update_provider("stooq", "online")
                    errors.append({"ticker": ticker, "code": "ADJUSTMENT_BASIS_REVIEW", "message": "已取得替代來源資料，但不會與 Yahoo 資料混合。"})
                except Exception:
                    errors.append({"ticker": ticker, "code": exc.code, "message": "Yahoo 暫時限制下載速度，系統會稍後繼續。" if exc.code == "RATE_LIMITED" else "此標的目前無法安全補齊資料。", "technical": _safe_error(exc.message)})
            except Exception as exc:
                errors.append({"ticker": ticker, "code": "DOWNLOAD_ERROR", "message": "此標的目前無法安全補齊資料。", "technical": _safe_error(exc)})
            self.repository.progress(identifier, index, total, ticker, f"{ticker} 處理完成。", errors=errors, result={"completed": completed})

        market_manifest, universe_manifest = write_manifests()
        result = {
            "completed": completed,
            "failed_tickers": [row["ticker"] for row in errors],
            "long_history_ready": market_manifest["long_history_validation_ready"],
            "universe_readiness": market_manifest["universe_readiness"],
            "manifest_generated_at": market_manifest["generated_at"],
            "provider_mixing": False,
        }
        status = "PARTIAL_SUCCESS" if errors else "COMPLETED"
        message = "部分資料尚未補齊，可稍後繼續重試。" if errors else "研究資料已補齊。"
        self.repository.finish(identifier, status, message, errors=errors, result=result)
        return None

    def _risk_free(self, identifier: str) -> dict[str, Any] | None:
        _enable_research_imports()
        from research.environment_v3_data import download_risk_free
        from research.environment_v3_design import PRIMARY_HISTORY
        self.repository.progress(identifier, 0, 1, "DGS3MO", "正在下載 3 個月美國國庫券利率。")
        try:
            manifest = download_risk_free(PRIMARY_HISTORY["start"], PRIMARY_HISTORY["end"])
        except Exception as exc:
            self.repository.update_provider("fred", "offline", "DOWNLOAD_FAILED", "下載失敗。")
            self.repository.finish(identifier, "FAILED", "無風險利率下載失敗，沒有建立任何假資料。", errors=[{"code": "RISK_FREE_DOWNLOAD_FAILED", "message": "FRED 目前無法提供資料。", "technical": _safe_error(exc)}])
            return None
        self.repository.update_provider("fred", "online")
        self.repository.progress(identifier, 1, 1, None, "無風險利率已更新。", result={"manifest": manifest})
        return {"manifest": manifest}

    def readiness(self) -> dict[str, Any]:
        _enable_research_imports()
        from research.environment_v3_data import build_data_manifest
        from research.environment_v3_snapshot import validate_risk_free_input
        manifest = build_data_manifest()
        risk_free = validate_risk_free_input(data_dir=self.data_dir)
        mega = manifest["universe_readiness"]["MEGA_CAP_TECH_UNIVERSE"]
        etf = manifest["universe_readiness"]["ETF_RESEARCH_UNIVERSE"]
        market_ready = bool(manifest["long_history_validation_ready"])
        readiness = {
            "market_long_history_ready": market_ready,
            "mega_cap_universe_ready": mega["status"] == "READY",
            "etf_universe_ready": etf["status"] == "READY",
            "risk_free_ready": bool(risk_free["ready"]),
        }
        readiness["research_validation_ready"] = all(readiness.values())
        readiness["reasons"] = {
            "market_long_history": "Validated current market cache is ready." if market_ready else "One or more market datasets are missing or invalid.",
            "mega_cap_universe": f"{mega['target_requests_complete']}/{mega['symbols']} target requests validated.",
            "etf_universe": f"{etf['target_requests_complete']}/{etf['symbols']} target requests validated.",
            "risk_free": risk_free["reason"],
        }
        return {
            "market_data_ready": bool(readiness["market_long_history_ready"]),
            "risk_free_ready": bool(readiness["risk_free_ready"]),
            "research_validation_ready": bool(readiness["research_validation_ready"]),
            "mega_cap_universe_ready": bool(readiness["mega_cap_universe_ready"]),
            "etf_universe_ready": bool(readiness["etf_universe_ready"]),
            "reasons": readiness["reasons"],
            "universe_readiness": manifest["universe_readiness"],
            "risk_free": {
                key: risk_free.get(key) for key in (
                    "status", "reason", "series_id", "first_observation", "last_observation",
                    "observations", "validation_status",
                )
            },
        }

    def _research_validation(self, identifier: str) -> dict[str, Any] | None:
        _enable_research_imports()
        from research.environment_v3_snapshot import EnvironmentValidationError, build_environment_snapshot
        snapshot: dict[str, Any] | None = None
        try:
            # This is the authoritative run boundary. It is created after the
            # queued job starts, not copied from the request-time readiness view.
            snapshot = build_environment_snapshot(persist=True)
            ready = snapshot["readiness"]
            if not ready["research_validation_ready"]:
                self.repository.finish(
                    identifier, "FAILED", "研究資料尚未準備完成，請先補齊資料與無風險利率。",
                    errors=[{"code": "RESEARCH_INPUTS_NOT_READY", "message": "長期市場資料或無風險利率尚未完成。"}],
                    result={"readiness": ready, "environment_snapshot_id": snapshot["environment_snapshot_id"]},
                )
                return None

            self.repository.progress(
                identifier, 0, 1, "Research Environment v3",
                f"正在使用環境快照 {snapshot['environment_snapshot_id']} 重新驗證研究環境。",
                result={"environment_snapshot_id": snapshot["environment_snapshot_id"]},
            )

            def update(current: int, total: int, item: str, message: str) -> None:
                self.repository.progress(
                    identifier, current, total, item, message,
                    result={"environment_snapshot_id": snapshot["environment_snapshot_id"]},
                )

            from research.environment_v3_extension import run
            study = run(progress=update, snapshot=snapshot)
            from research.build_environment_v3 import build as build_environment
            from research.build_framework_catalog import build as build_catalog
            published = build_environment(snapshot=snapshot, extension=study)
            build_catalog()
            total = max(1, int((self.repository.get(identifier) or {}).get("progress_total") or 1))
            result = {
                "status": "COMPLETED",
                "report_id": "research-environment-v3",
                "detail_report_id": "research-environment-v3-long-history",
                "environment_snapshot_id": snapshot["environment_snapshot_id"],
                "environment_snapshot_created_at": snapshot["created_at"],
                "input_fingerprint_sha256": snapshot["input_fingerprint_sha256"],
                "rows": len(study["full_period"]),
                "sensitivity_classification": published["sensitivity_classification"],
                "next_family": published["next_family"],
                "immutability": study["immutability"],
            }
            self.repository.progress(identifier, total, total, None, "研究環境長期驗證完成。", result=result)
            return result
        except EnvironmentValidationError as exc:
            result = {
                "environment_snapshot_id": snapshot.get("environment_snapshot_id") if snapshot else None,
                "environment_snapshot_created_at": snapshot.get("created_at") if snapshot else None,
            }
            self.repository.finish(
                identifier, "FAILED_VALIDATION", "研究輸出一致性驗證失敗，未發布矛盾報告。",
                errors=[{"code": "RESEARCH_REPORT_VALIDATION_FAILED", "message": _safe_error(exc)}],
                result=result,
            )
            return None
