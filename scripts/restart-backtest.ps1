param([switch]$SkipBuild)
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "stop-backtest.ps1")
if ($LASTEXITCODE -ne 0) { throw "Stop failed." }
$arguments = @{}
if ($SkipBuild) { $arguments.SkipBuild = $true }
& (Join-Path $PSScriptRoot "start-backtest.ps1") @arguments
