from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def console_safe(value: str) -> str:
    return value.encode("ascii", errors="backslashreplace").decode("ascii")


def run(args: list[str], *, cwd: Path, label: str, quiet_tail: int = 0) -> None:
    result = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        print(f"{label}: FAIL (exit {result.returncode})", flush=True)
        print(console_safe(output[-8000:]), flush=True)
        raise SystemExit(result.returncode or 1)
    if quiet_tail:
        lines = output.splitlines()
        print(f"{label}: PASS", flush=True)
        print(console_safe("\n".join(lines[-quiet_tail:])), flush=True)
    else:
        print(f"{label}: PASS", flush=True)


def main() -> int:
    backend_only = "--backend-only" in sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix="backtest-web-c0-clean-clone-") as temp:
        temp_root = Path(temp).resolve()
        clone = temp_root / "backtest-web"
        clone.mkdir()
        for variable in ("DATABASE_URL", "DATA_DIR", "CACHE_DIR", "RESEARCH_DATA_DIR", "RESEARCH_REPORTS_DIR", "PYTEST_ADDOPTS"):
            os.environ.pop(variable, None)
        os.environ["DATA_DIR"] = str(clone / "data")
        os.environ["CACHE_DIR"] = str(clone / "data" / "cache")
        os.environ["RESEARCH_DATA_DIR"] = str(clone / "data")
        os.environ["RESEARCH_REPORTS_DIR"] = str(clone / "reports")
        os.environ["PYTHONUTF8"] = "1"
        prefix = clone.as_posix().rstrip("/") + "/"
        run(["git", "checkout-index", "--all", f"--prefix={prefix}"], cwd=ROOT, label="Rebuild clean source tree from Git index")
        run(["git", "init", "--initial-branch=main"], cwd=clone, label="Initialize isolated index", quiet_tail=2)
        run(["git", "add", "-A"], cwd=clone, label="Stage clean-tree source")

        listed = subprocess.run(["git", "ls-files", "-z"], cwd=clone, capture_output=True, check=True)
        paths = [item.decode("utf-8", errors="surrogateescape") for item in listed.stdout.split(b"\0") if item]
        forbidden = [
            name
            for name in paths
            if name.casefold().endswith((".sqlite", ".sqlite3", ".sqlite-wal", ".sqlite-shm", ".sqlite3-wal", ".sqlite3-shm", ".db", ".parquet", ".feather", ".arrow"))
            or "/node_modules/" in f"/{name.casefold()}/"
            or "/.next/" in f"/{name.casefold()}/"
        ]
        if forbidden:
            print("Clean-clone source unexpectedly includes local database/cache/build files:")
            for name in forbidden:
                print(f"  {name}")
            return 1
        if (clone / "data" / "backtests.sqlite3").exists() or (clone / "data" / "background-jobs.sqlite3").exists():
            print("Clean-clone source unexpectedly contains a production SQLite database.")
            return 1
        print(f"Clean source tree: PASS ({len(paths)} files; no production DB, cache, or build output)", flush=True)

        python = sys.executable
        run([python, "scripts/check_secrets.py"], cwd=clone, label="Clean-clone secret scan")
        run([python, "scripts/check_git_large_files.py"], cwd=clone, label="Clean-clone large-file scan")
        run([python, "scripts/check_frozen_hashes.py"], cwd=clone, label="Clean-clone frozen fingerprint tests", quiet_tail=4)
        run([python, "scripts/run_c0_backend_checks.py"], cwd=clone, label="Clean-clone backend test suites", quiet_tail=6)
        run([python, "-m", "compileall", "-q", "backend", "scripts"], cwd=clone, label="Clean-clone Python compile check")

        if backend_only:
            print("Clean-clone backend-only simulation: PASS", flush=True)
            return 0

        frontend = clone / "frontend"
        pnpm = "pnpm.cmd" if os.name == "nt" else "pnpm"
        isolated_store = temp_root / "pnpm-store"
        run(
            [pnpm, "install", "--frozen-lockfile", "--store-dir", str(isolated_store)],
            cwd=frontend,
            label="Install frontend from clean lockfile",
            quiet_tail=5,
        )
        run([pnpm, "test"], cwd=frontend, label="Clean-clone frontend tests", quiet_tail=9)
        run([pnpm, "build"], cwd=frontend, label="Clean-clone Next.js production build", quiet_tail=16)
        print("Clean-clone simulation: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
