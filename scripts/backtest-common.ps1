$ErrorActionPreference = "Stop"

function Get-BacktestRoot {
    return (Split-Path -Parent $PSScriptRoot)
}

function Get-BacktestLanIPv4 {
    $addresses = @([System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
        Where-Object { $_.OperationalStatus -eq [System.Net.NetworkInformation.OperationalStatus]::Up -and $_.NetworkInterfaceType -ne [System.Net.NetworkInformation.NetworkInterfaceType]::Loopback } |
        Where-Object { $_.GetIPProperties().GatewayAddresses.Count -gt 0 } |
        ForEach-Object { $_.GetIPProperties().UnicastAddresses } |
        Where-Object { $_.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork } |
        ForEach-Object { $_.Address.IPAddressToString } |
        Where-Object { $_ -and $_ -notlike "127.*" -and $_ -notlike "169.254.*" })
    if (-not $addresses) { throw "No active private LAN IPv4 address was detected." }
    $private = @($addresses | Where-Object { $_ -match '^10\.' -or $_ -match '^192\.168\.' -or $_ -match '^172\.(1[6-9]|2\d|3[01])\.' })
    return [string]$(if ($private) { $private[0] } else { $addresses[0] })
}

function Get-RuntimeDirectory {
    $path = Join-Path (Get-BacktestRoot) ".runtime"
    New-Item -ItemType Directory -Force $path | Out-Null
    return $path
}

function Get-LogDirectory {
    $path = Join-Path (Get-BacktestRoot) ".logs"
    New-Item -ItemType Directory -Force $path | Out-Null
    return $path
}

function Get-BacktestNullInput {
    $path = Join-Path (Get-RuntimeDirectory) "detached.stdin"
    if (-not (Test-Path -LiteralPath $path)) { Set-Content -LiteralPath $path -Value "" -NoNewline -Encoding ascii }
    return $path
}

function Read-BacktestPid([string]$Role) {
    $path = Join-Path (Get-RuntimeDirectory) "$Role.pid"
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    $value = (Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue).Trim()
    if ($value -notmatch '^\d+$') { return $null }
    return [int]$value
}

function Get-BacktestProcess([string]$Role) {
    $processId = Read-BacktestPid $Role
    if (-not $processId) { return $null }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    $stampPath = Join-Path (Get-RuntimeDirectory) "$Role.startticks"
    if (-not (Test-Path -LiteralPath $stampPath)) { return $null }
    $expectedTicks = (Get-Content -LiteralPath $stampPath -Raw -ErrorAction SilentlyContinue).Trim()
    if ([string]$process.StartTime.Ticks -ne $expectedTicks) { return $null }
    switch ($Role) {
        "backend" {
            if ($process.Name -notlike "python*" -or (Get-ListeningProcessId 8000) -ne $processId) { return $null }
        }
        "frontend" {
            if ($process.Name -ne "node" -or (Get-ListeningProcessId 3000) -ne $processId) { return $null }
        }
        "watchdog" {
            if ($process.Name -notmatch "powershell|pwsh") { return $null }
        }
        default { return $null }
    }
    return $process
}

function Write-BacktestPid([string]$Role, [int]$ProcessId) {
    Set-Content -LiteralPath (Join-Path (Get-RuntimeDirectory) "$Role.pid") -Value $ProcessId -Encoding ascii
    $process = Get-Process -Id $ProcessId -ErrorAction Stop
    Set-Content -LiteralPath (Join-Path (Get-RuntimeDirectory) "$Role.startticks") -Value $process.StartTime.Ticks -Encoding ascii
}

function Remove-StaleBacktestPid([string]$Role) {
    if (Get-BacktestProcess $Role) { return }
    $path = Join-Path (Get-RuntimeDirectory) "$Role.pid"
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
    $stampPath = Join-Path (Get-RuntimeDirectory) "$Role.startticks"
    if (Test-Path -LiteralPath $stampPath) { Remove-Item -LiteralPath $stampPath -Force }
}

function Get-ListeningProcessId([int]$Port) {
    foreach ($line in (& netstat.exe -ano -p tcp 2>$null)) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") { return [int]$Matches[1] }
    }
    return $null
}

function Assert-BacktestPortAvailable([int]$Port, [string]$Role) {
    if (Get-BacktestProcess $Role) { return }
    $listenerPid = Get-ListeningProcessId $Port
    if ($listenerPid) { throw "Port $Port is already used by PID $listenerPid. Stop that service or choose another port." }
}

function Start-BacktestBackend {
    $root = Get-BacktestRoot
    $python = Join-Path $root "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) { throw "Stable Windows Python runtime is missing: $python" }
    $logs = Get-LogDirectory
    $arguments = @("-m", "uvicorn", "app.main:app", "--app-dir", (Join-Path $root "backend"), "--host", "127.0.0.1", "--port", "8000")
    $oldData = $env:DATA_DIR; $oldCache = $env:CACHE_DIR; $oldDatabase = $env:DATABASE_URL; $oldPythonPath = $env:PYTHONPATH
    try {
        $env:DATA_DIR = Join-Path $root "data"
        $env:CACHE_DIR = Join-Path $root "data\cache"
        $env:DATABASE_URL = "sqlite:///" + (Join-Path $root "data\backtests.sqlite3")
        $env:PYTHONPATH = ((Join-Path $root "backend\.venv\Lib\site-packages"), (Join-Path $root "backend"), $root) -join ";"
        $process = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory (Join-Path $root "backend") -WindowStyle Hidden -RedirectStandardInput (Get-BacktestNullInput) -RedirectStandardOutput (Join-Path $logs "backend.log") -RedirectStandardError (Join-Path $logs "backend-error.log") -PassThru
    } finally {
        $env:DATA_DIR = $oldData; $env:CACHE_DIR = $oldCache; $env:DATABASE_URL = $oldDatabase; $env:PYTHONPATH = $oldPythonPath
    }
    $deadline = (Get-Date).AddSeconds(15)
    do {
        $listenerPid = Get-ListeningProcessId 8000
        if ($listenerPid) { break }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if (-not $listenerPid) { throw "Backend did not bind port 8000." }
    Write-BacktestPid "backend" $listenerPid
    return $process
}

function Start-BacktestFrontend([string]$LanIPv4) {
    $root = Get-BacktestRoot
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    $next = Join-Path $root "frontend\node_modules\next\dist\bin\next"
    if (-not (Test-Path -LiteralPath $next)) { throw "Frontend dependencies are missing. Run npm install in frontend." }
    $logs = Get-LogDirectory
    $process = Start-Process -FilePath $node -ArgumentList @($next, "start", "--hostname", $LanIPv4, "--port", "3000") -WorkingDirectory (Join-Path $root "frontend") -WindowStyle Hidden -RedirectStandardInput (Get-BacktestNullInput) -RedirectStandardOutput (Join-Path $logs "frontend.log") -RedirectStandardError (Join-Path $logs "frontend-error.log") -PassThru
    Write-BacktestPid "frontend" $process.Id
    return $process
}

function Wait-BacktestHealth([string]$Uri, [int]$Seconds = 30) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $response = Invoke-RestMethod -Uri $Uri -TimeoutSec 2
            if ($response.status -eq "ok") { return $true }
        } catch { }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $false
}
