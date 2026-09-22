param(
    [ValidateSet("Manifest", "Market", "RiskFree", "All")]
    [string]$Mode = "Manifest",
    [ValidateSet("Mega", "ETF", "All")]
    [string]$Universe = "All",
    [ValidateSet("Yahoo", "Stooq")]
    [string]$Provider = "Yahoo",
    [switch]$IncludePre2010
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Backend virtual environment not found. Create backend\.venv first."
}

$env:PYTHONPATH = "$(Join-Path $projectRoot 'backend');$projectRoot"
$modeArg = switch ($Mode) {
    "RiskFree" { "risk-free" }
    default { $Mode.ToLowerInvariant() }
}
$arguments = @(
    "-m", "research.prepare_environment_v3",
    "--mode", $modeArg,
    "--universe", $Universe.ToLowerInvariant(),
    "--provider", $Provider.ToLowerInvariant()
)
if ($IncludePre2010) { $arguments += "--include-pre-2010" }

Push-Location $projectRoot
try {
    & $python @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

