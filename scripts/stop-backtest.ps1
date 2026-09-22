$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "backtest-common.ps1")

foreach ($role in @("watchdog", "frontend", "backend")) {
    $process = Get-BacktestProcess $role
    if ($process) {
        Stop-Process -Id $process.Id -Force
        Wait-Process -Id $process.Id -Timeout 5 -ErrorAction SilentlyContinue
        Write-Host "Stopped $role PID $($process.Id)."
    } elseif (Read-BacktestPid $role) {
        Write-Warning "Did not stop recorded $role PID because its command line does not belong to this project."
    }
    Remove-StaleBacktestPid $role
}
