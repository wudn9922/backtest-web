$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "backtest-common.ps1")

$log = Join-Path (Get-LogDirectory) "watchdog.log"
$restartTimes = @()
while ($true) {
    $now = Get-Date
    $restartTimes = @($restartTimes | Where-Object { $_ -gt $now.AddMinutes(-10) })
    foreach ($role in @("backend", "frontend")) {
        if (Get-BacktestProcess $role) { continue }
        if ($restartTimes.Count -ge 5) {
            Add-Content -LiteralPath $log -Value "$($now.ToString('o')) Restart limit reached; waiting before retry."
            continue
        }
        try {
            Remove-StaleBacktestPid $role
            if ($role -eq "backend") {
                if (-not (Get-ListeningProcessId 8000)) { Start-BacktestBackend | Out-Null }
            } else {
                if (-not (Get-ListeningProcessId 3000)) { Start-BacktestFrontend (Get-BacktestLanIPv4) | Out-Null }
            }
            $restartTimes += $now
            Add-Content -LiteralPath $log -Value "$($now.ToString('o')) Restarted $role."
        } catch {
            $restartTimes += $now
            Add-Content -LiteralPath $log -Value "$($now.ToString('o')) Failed to restart ${role}: $($_.Exception.Message)"
        }
    }
    Start-Sleep -Seconds 15
}
