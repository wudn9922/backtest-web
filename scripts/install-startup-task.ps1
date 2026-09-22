param([switch]$StartNow)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "backtest-common.ps1")
$taskName = "BacktestWebLocal"
$startScript = Join-Path $PSScriptRoot "start-backtest.ps1"
$shell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path -LiteralPath $shell)) { throw "Windows PowerShell is unavailable." }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
if ($identity -match "CodexSandbox") { throw "The launcher must be approved once in the normal Windows user context." }
$argument = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`" -SkipBuild"
$launcherKind = "scheduled_task"
try {
    $action = New-ScheduledTaskAction -Execute $shell -Argument $argument -ErrorAction Stop
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity -ErrorAction Stop
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited -ErrorAction Stop
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -ErrorAction Stop
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Start Backtest Web after Windows sign-in" -Force -ErrorAction Stop | Out-Null
    Write-Host "Installed current-user scheduled startup task '$taskName'."
} catch {
    # Managed Windows accounts can deny Task Scheduler registration. HKCU Run
    # is the non-admin current-user fallback and launches the same supervisor.
    $runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $command = "`"$shell`" $argument"
    New-Item -Path $runKey -Force | Out-Null
    New-ItemProperty -Path $runKey -Name $taskName -Value $command -PropertyType String -Force | Out-Null
    $launcherKind = "current_user_startup"
    Write-Host "Installed current-user sign-in startup registration '$taskName'."
}

if ($StartNow) {
    & (Join-Path $PSScriptRoot "stop-backtest.ps1")
    if ($launcherKind -eq "scheduled_task") {
        Start-ScheduledTask -TaskName $taskName
    } else {
        Start-Process -FilePath $shell -ArgumentList $argument -WorkingDirectory (Get-BacktestRoot) -WindowStyle Hidden
    }
    $ready = Wait-BacktestHealth "http://127.0.0.1:8000/health" 45
    $providerCheckQueued = $false
    if ($ready) {
        try {
            $job = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/jobs/provider-connectivity-check" -Method Post -TimeoutSec 5
            $providerCheckQueued = [bool]$job.id
        } catch { }
    }
    $result = @{
        installed = $true
        identity = $identity
        logon_type = "Interactive"
        run_level = "Limited"
        launcher_kind = $launcherKind
        backend_ready = $ready
        provider_check_queued = $providerCheckQueued
        completed_at = (Get-Date).ToString("o")
    }
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path (Get-RuntimeDirectory) "windows-launcher-install.json") -Encoding utf8
    if (-not $ready) { throw "The Windows user service did not become healthy." }
}
