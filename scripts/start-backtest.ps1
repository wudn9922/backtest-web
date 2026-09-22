param(
    [switch]$SkipBuild,
    [switch]$NoWatchdog
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "backtest-common.ps1")

$root = Get-BacktestRoot
$lanIPv4 = Get-BacktestLanIPv4
foreach ($role in @("backend", "frontend", "watchdog")) { Remove-StaleBacktestPid $role }
Assert-BacktestPortAvailable 8000 "backend"
Assert-BacktestPortAvailable 3000 "frontend"

if (-not $SkipBuild) {
    Write-Host "Building the production frontend..."
    Push-Location (Join-Path $root "frontend")
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Frontend production build failed." }
    } finally { Pop-Location }
}

if (-not (Get-BacktestProcess "backend")) { Start-BacktestBackend | Out-Null }
if (-not (Wait-BacktestHealth "http://127.0.0.1:8000/health" 30)) { throw "Backend did not become healthy. Check .logs\backend-error.log." }
if (-not (Get-BacktestProcess "frontend")) { Start-BacktestFrontend $lanIPv4 | Out-Null }
if (-not (Wait-BacktestHealth "http://${lanIPv4}:3000/api/health" 45)) { throw "Frontend proxy did not become healthy. Check .logs\frontend-error.log." }

if (-not $NoWatchdog -and -not (Get-BacktestProcess "watchdog")) {
    # Always supervise from the normal Windows user environment.  Never retain
    # the transient Codex runtime PowerShell executable as a service dependency.
    $shell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $shell)) { throw "Windows PowerShell is unavailable." }
    $logs = Get-LogDirectory
    $watchdog = Start-Process -FilePath $shell -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "watchdog-backtest.ps1")) -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardInput (Get-BacktestNullInput) -RedirectStandardOutput (Join-Path $logs "watchdog-output.log") -RedirectStandardError (Join-Path $logs "watchdog-error.log") -PassThru
    Write-BacktestPid "watchdog" $watchdog.Id
}

Write-Host ""
Write-Host "Backtest Web is running."
Write-Host "Computer URL: http://${lanIPv4}:3000"
Write-Host "Phone URL:    http://${lanIPv4}:3000"
Write-Host "Backend:     http://127.0.0.1:8000"
