$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "backtest-common.ps1")

try { $lanIPv4 = Get-BacktestLanIPv4 } catch { $lanIPv4 = $null }
$frontend = Get-BacktestProcess "frontend"
$backend = Get-BacktestProcess "backend"
$watchdog = Get-BacktestProcess "watchdog"
Write-Host "Frontend: $($(if ($frontend) { 'Running' } else { 'Stopped' }))"
Write-Host "Frontend PID: $($(if ($frontend) { $frontend.Id } else { '-' }))"
Write-Host "Backend: $($(if ($backend) { 'Running' } else { 'Stopped' }))"
Write-Host "Backend PID: $($(if ($backend) { $backend.Id } else { '-' }))"
Write-Host "Watchdog: $($(if ($watchdog) { 'Running' } else { 'Stopped' }))"
Write-Host "LAN IPv4: $($(if ($lanIPv4) { $lanIPv4 } else { 'Unavailable' }))"
if ($lanIPv4) { Write-Host "Phone URL: http://${lanIPv4}:3000" }

$healthy = $false
if ($lanIPv4) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://${lanIPv4}:3000/api/health" -TimeoutSec 4
        $healthy = $response.StatusCode -eq 200 -and $response.Content -match '"status"\s*:\s*"ok"'
    } catch { }
}
Write-Host "Health /api/health: $($(if ($healthy) { 'HTTP 200 {status: ok}' } else { 'UNHEALTHY' }))"
if (-not $healthy) {
    Write-Host "Run: .\scripts\restart-backtest.ps1"
    foreach ($name in @("frontend-error.log", "backend-error.log", "watchdog.log")) {
        $path = Join-Path (Get-LogDirectory) $name
        if (Test-Path -LiteralPath $path) {
            Write-Host "--- $name (last 12 lines) ---"
            Get-Content -LiteralPath $path -Tail 12
        }
    }
}
if ($healthy) { exit 0 } else { exit 1 }
