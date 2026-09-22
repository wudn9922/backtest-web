from __future__ import annotations

import csv
import ctypes
import getpass
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.data.yahoo import YAHOO_HOSTS, safe_yahoo_error


PROBE_HOSTS = (
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
    "stooq.com",
    "fred.stlouisfed.org",
    "www.google.com",
)
CODEX_RUNTIME_FRAGMENT = "\\.cache\\codex-runtimes\\"


class _ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_ulong),
        ("cntUsage", ctypes.c_ulong),
        ("th32ProcessID", ctypes.c_ulong),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", ctypes.c_ulong),
        ("cntThreads", ctypes.c_ulong),
        ("th32ParentProcessID", ctypes.c_ulong),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.c_ulong),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _process_executable(process_id: int) -> str | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, process_id)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return None
    finally:
        kernel32.CloseHandle(handle)


def _process_tree(max_depth: int = 8) -> list[dict[str, Any]]:
    """Capture a bounded parent chain for the local-only diagnostic log."""
    if os.name != "nt":
        return [{"pid": os.getpid(), "parent_pid": os.getppid(), "executable": str(Path(sys.executable).resolve())}]
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    invalid_handle = wintypes.HANDLE(-1).value
    if not snapshot or snapshot == invalid_handle:
        return [{"pid": os.getpid(), "parent_pid": os.getppid(), "executable": str(Path(sys.executable).resolve())}]
    processes: dict[int, dict[str, Any]] = {}
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
        found = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while found:
            process_id = int(entry.th32ProcessID)
            processes[process_id] = {
                "pid": process_id,
                "parent_pid": int(entry.th32ParentProcessID),
                "image_name": entry.szExeFile,
            }
            found = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)

    chain: list[dict[str, Any]] = []
    process_id = os.getpid()
    visited: set[int] = set()
    while process_id and process_id not in visited and len(chain) < max_depth:
        visited.add(process_id)
        row = dict(processes.get(process_id, {"pid": process_id, "parent_pid": 0, "image_name": None}))
        row["executable"] = _process_executable(process_id)
        chain.append(row)
        process_id = int(row.get("parent_pid") or 0)
    return chain


def _windows_username() -> str:
    if os.name != "nt":
        return getpass.getuser()
    size = ctypes.c_ulong(256)
    buffer = ctypes.create_unicode_buffer(size.value)
    if ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(size)):
        return buffer.value
    return getpass.getuser()


def _session_id() -> int | None:
    if os.name != "nt":
        return None
    value = ctypes.c_ulong()
    return int(value.value) if ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(value)) else None


def _active_console_session() -> int | None:
    if os.name != "nt":
        return None
    value = int(ctypes.windll.kernel32.WTSGetActiveConsoleSessionId())
    return None if value == 0xFFFFFFFF else value


def _task_installed() -> bool:
    if os.name != "nt":
        return False
    task = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "schtasks.exe"
    try:
        result = subprocess.run(
            [str(task), "/Query", "/TN", "BacktestWebLocal"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def launch_windows_launcher_approval(project_root: Path) -> bool:
    """Open Explorer with the fixed one-time setup item selected.

    A restricted service must not try to elevate itself.  Explorer only shows
    the project-owned item; the interactive user explicitly double-clicks it
    and then decides whether to approve the normal Windows security dialog.
    No request data is used to build paths or commands.
    """
    if os.name != "nt":
        return False
    script = (project_root / "完成股票回測網站設定.vbs").resolve()
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve()
    host = system_root / "explorer.exe"
    if not script.is_file() or script.parent != project_root.resolve() or not host.is_file():
        return False
    try:
        subprocess.Popen(
            [str(host), f'/select,"{script}"'],
            cwd=str(project_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        return True
    except OSError:
        return False


def runtime_environment(project_root: Path) -> dict[str, Any]:
    """Return safe runtime flags for the UI plus full paths for a local-only log."""
    expected = (project_root / "backend" / ".venv" / "Scripts" / "python.exe").resolve()
    executable = Path(sys.executable).resolve()
    username = _windows_username()
    session = _session_id()
    active_session = _active_console_session()
    process_tree = _process_tree()
    restricted_identity = "codexsandbox" in username.lower()
    interactive = session is not None and session == active_session and not restricted_identity
    values = [
        str(executable),
        str(getattr(sys, "base_prefix", "")),
        str(getattr(sys, "prefix", "")),
        *(str(row.get("executable") or row.get("image_name") or "") for row in process_tree),
    ]
    runtime_path_detected = any(CODEX_RUNTIME_FRAGMENT in value.lower() for value in values)
    parent_executable = process_tree[1].get("executable") if len(process_tree) > 1 else None
    return {
        "context_status": "current_interactive_user" if interactive else "restricted_or_noninteractive",
        "python_path_expected": executable == expected,
        "launcher_installed": _task_installed(),
        "repair_required": bool(not interactive or executable != expected or runtime_path_detected),
        "technical": {
            "backend_executable": str(executable),
            "python_executable": str(executable),
            "python_prefix": str(getattr(sys, "prefix", "")),
            "python_base_prefix": str(getattr(sys, "base_prefix", "")),
            "expected_python": str(expected),
            "process_id": os.getpid(),
            "parent_process_id": os.getppid(),
            "parent_process_executable": parent_executable,
            "process_tree": process_tree,
            "windows_user": username,
            "session_id": session,
            "active_console_session_id": active_session,
            "windows_session_type": "interactive_console" if interactive else "restricted_or_noninteractive",
            "interactive_user_session": interactive,
            "runtime_path_detected": runtime_path_detected,
            "proxy_environment": {
                name: _safe_proxy(os.environ.get(name))
                for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
            },
        },
    }


def _safe_proxy(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme and parsed.hostname:
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{parsed.hostname}{port}"
    except ValueError:
        pass
    return "set" if value else None


def _network_probe(host: str) -> dict[str, Any]:
    result: dict[str, Any] = {"host": host, "dns": False, "tcp_443": False, "https": False}
    try:
        addresses = sorted({row[4][0] for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
        result["dns"] = bool(addresses)
        result["addresses"] = addresses[:8]
    except OSError as exc:
        result["dns_error"] = safe_yahoo_error(exc)
        return result
    try:
        with socket.create_connection((host, 443), timeout=5):
            result["tcp_443"] = True
    except OSError as exc:
        result["tcp_error"] = safe_yahoo_error(exc)
        return result
    request = urllib.request.Request(
        f"https://{host}/",
        headers={"User-Agent": "BacktestLab-Connectivity/1", "Range": "bytes=0-4095"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            response.read(4096)
            result["http_status"] = int(getattr(response, "status", 200) or 200)
            result["https"] = True
    except urllib.error.HTTPError as exc:
        # A real HTTP response proves DNS/TCP/TLS/HTTPS connectivity even when
        # a provider rejects its web root. Provider health is classified by
        # the actual data endpoint separately below.
        result["http_status"] = int(exc.code)
        result["https"] = True
    except Exception as exc:
        result["https_error"] = safe_yahoo_error(exc)
    return result


def _classify(has_data: bool, kind: str | None, http_status: int | None) -> tuple[str, str | None]:
    if has_data:
        return "online", None
    if http_status == 429 or kind == "rate_limited" or (http_status is not None and http_status >= 500):
        return "restricted", "RATE_LIMITED" if http_status == 429 or kind == "rate_limited" else "UPSTREAM_UNAVAILABLE"
    if kind == "timeout":
        return "offline", "PROVIDER_TIMEOUT"
    if kind == "connection" or http_status is None:
        return "offline", "PROVIDER_CONNECTION_ERROR"
    return "validation_failed", "PROVIDER_VALIDATION_FAILED"


def _probe_yahoo(provider: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    end = date.today(); start = end - timedelta(days=10)
    hosts: list[dict[str, Any]] = []
    for host in YAHOO_HOSTS:
        frame, error, kind, status_code = provider._run_request(host, "SPY", start, end)
        status, error_type = _classify(not frame.empty, kind, status_code)
        hosts.append({
            "host": host, "status": status, "error_type": error_type,
            "http_status": status_code, "bars": int(len(frame)), "safe_error": safe_yahoo_error(error) if error else None,
        })
    if any(row["status"] == "online" for row in hosts):
        status, error_type = "online", None
    elif any(row["status"] == "restricted" for row in hosts):
        status, error_type = "restricted", next(row["error_type"] for row in hosts if row["status"] == "restricted")
    elif all(row["status"] == "offline" for row in hosts):
        status, error_type = "offline", next((row["error_type"] for row in hosts if row["error_type"]), "PROVIDER_CONNECTION_ERROR")
    else:
        status, error_type = "validation_failed", "PROVIDER_VALIDATION_FAILED"
    return {"status": status, "error_type": error_type}, {"actual_endpoint": "Yahoo chart v8 / SPY / recent daily", "hosts": hosts}


def _probe_stooq(provider: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    end = date.today(); start = end - timedelta(days=10)
    frame, error, kind, status_code = provider._run_request("SPY", start, end)
    status, error_type = _classify(not frame.empty, kind, status_code)
    return {"status": status, "error_type": error_type}, {
        "actual_endpoint": "Stooq q/d/l CSV / SPY / recent daily", "http_status": status_code,
        "bars": int(len(frame)), "kind": kind, "safe_error": safe_yahoo_error(error) if error else None,
    }


def _parse_fred(payload: bytes) -> int:
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    if not rows:
        raise ValueError("FRED returned no observations")
    date_key = "observation_date" if "observation_date" in rows[0] else "DATE" if "DATE" in rows[0] else None
    if not date_key or "DGS3MO" not in rows[0]:
        raise ValueError("FRED response schema does not contain DGS3MO")
    return sum(1 for row in rows if row.get(date_key) and row.get("DGS3MO") not in (None, "", "."))


def fetch_fred_sample(start: date, end: date) -> tuple[bytes, int, int]:
    query = urllib.parse.urlencode({"id": "DGS3MO", "cosd": start.isoformat(), "coed": end.isoformat()})
    request = urllib.request.Request(
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?{query}",
        headers={"User-Agent": "BacktestLab-Research/3"}, method="GET",
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        http_status = int(getattr(response, "status", 200) or 200)
        payload = response.read(1024 * 1024)
    observations = _parse_fred(payload)
    if observations < 1:
        raise ValueError("FRED returned no numeric DGS3MO observations")
    return payload, observations, http_status


def write_fred_smoke_cache(data_dir: Path, start: date, end: date) -> dict[str, Any]:
    """Persist a small real FRED sample outside the production rate manifest."""
    payload, observations, http_status = fetch_fred_sample(start, end)
    root = (data_dir / "connectivity-smoke").resolve()
    if root.parent != data_dir.resolve():
        raise ValueError("invalid smoke cache directory")
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / f"DGS3MO_{start.isoformat()}_{end.isoformat()}.csv"
    manifest_path = root / "risk-free-smoke-manifest.json"
    csv_path.write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "provider": "Federal Reserve Bank of St. Louis FRED",
        "series_id": "DGS3MO",
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "observations": observations,
        "http_status": http_status,
        "cache_sha256": hashlib.sha256(payload).hexdigest(),
        "fabricated_observations": 0,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "cache_written": csv_path.is_file(), "manifest_written": manifest_path.is_file()}


def _probe_fred() -> tuple[dict[str, Any], dict[str, Any]]:
    end = date.today(); start = end - timedelta(days=14)
    try:
        _payload, observations, http_status = fetch_fred_sample(start, end)
        return {"status": "online", "error_type": None}, {
            "actual_endpoint": "FRED fredgraph.csv / DGS3MO", "http_status": http_status, "observations": observations,
        }
    except urllib.error.HTTPError as exc:
        status, error_type = _classify(False, "rate_limited" if exc.code == 429 else "upstream", int(exc.code))
        return {"status": status, "error_type": error_type}, {"actual_endpoint": "FRED fredgraph.csv / DGS3MO", "http_status": int(exc.code), "safe_error": safe_yahoo_error(exc)}
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        kind = "timeout" if isinstance(exc, (socket.timeout, TimeoutError)) else "connection"
        status, error_type = _classify(False, kind, None)
        return {"status": status, "error_type": error_type}, {"actual_endpoint": "FRED fredgraph.csv / DGS3MO", "safe_error": safe_yahoo_error(exc)}
    except Exception as exc:
        return {"status": "validation_failed", "error_type": "PROVIDER_VALIDATION_FAILED"}, {"actual_endpoint": "FRED fredgraph.csv / DGS3MO", "safe_error": safe_yahoo_error(exc)}


def run_diagnostic(provider_chain: Any, project_root: Path) -> dict[str, Any]:
    """Run only inside the serving backend and keep sensitive context in a local log."""
    environment = runtime_environment(project_root)
    host_results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=len(PROBE_HOSTS), thread_name_prefix="provider-probe") as pool:
        futures = {pool.submit(_network_probe, host): host for host in PROBE_HOSTS}
        for future in as_completed(futures):
            host = futures[future]
            try:
                host_results[host] = future.result()
            except Exception as exc:  # pragma: no cover - defensive boundary
                host_results[host] = {"host": host, "dns": False, "tcp_443": False, "https": False, "safe_error": safe_yahoo_error(exc)}

    providers: dict[str, dict[str, Any]] = {}
    technical_providers: dict[str, Any] = {}
    for name, probe in (
        ("yahoo", lambda: _probe_yahoo(provider_chain.yahoo)),
        ("stooq", lambda: _probe_stooq(provider_chain.alternative)),
        ("fred", _probe_fred),
    ):
        try:
            providers[name], technical_providers[name] = probe()
        except Exception as exc:
            providers[name] = {"status": "validation_failed", "error_type": "PROVIDER_VALIDATION_FAILED"}
            technical_providers[name] = {"safe_error": safe_yahoo_error(exc)}

    technical = {
        "schema_version": 1,
        "environment": environment["technical"],
        "launcher_installed": environment["launcher_installed"],
        "host_connectivity": {key: host_results[key] for key in sorted(host_results)},
        "provider_endpoint_probes": technical_providers,
    }
    log_dir = project_root / ".logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "connectivity-diagnostic.json").write_text(json.dumps(technical, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    safe_environment = {key: value for key, value in environment.items() if key != "technical"}
    google = host_results.get("www.google.com", {})
    return {
        "providers": providers,
        "network_control": {"google_https": bool(google.get("https")), "google_tcp_443": bool(google.get("tcp_443"))},
        "runtime": safe_environment,
        "technical_log_written": True,
    }
