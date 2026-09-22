$ErrorActionPreference = "Stop"
$taskName = "BacktestWebLocal"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed startup task '$taskName'."
} else {
    Write-Host "Startup task '$taskName' is not installed."
}
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Remove-ItemProperty -Path $runKey -Name $taskName -ErrorAction SilentlyContinue
