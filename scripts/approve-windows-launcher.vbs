Option Explicit

Dim shell, files, scriptPath, powershellPath, arguments
Set shell = CreateObject("Shell.Application")
Set files = CreateObject("Scripting.FileSystemObject")
scriptPath = files.BuildPath(files.GetParentFolderName(WScript.ScriptFullName), "install-startup-task.ps1")
powershellPath = CreateObject("WScript.Shell").ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
arguments = "-NoProfile -ExecutionPolicy Bypass -File " & Chr(34) & scriptPath & Chr(34) & " -StartNow"
shell.ShellExecute powershellPath, arguments, "", "runas", 0
