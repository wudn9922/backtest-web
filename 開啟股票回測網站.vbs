Option Explicit

Dim shell, files, root, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
command = Chr(34) & shell.ExpandEnvironmentStrings("%SystemRoot%") & _
    "\System32\WindowsPowerShell\v1.0\powershell.exe" & Chr(34) & _
    " -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " & _
    Chr(34) & root & "\scripts\start-backtest.ps1" & Chr(34) & " -SkipBuild"
shell.Run command, 0, False

