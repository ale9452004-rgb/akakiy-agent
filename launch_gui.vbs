' Launcher для запуска Акакий Desktop Shell без консольного окна
Option Explicit
Dim fso, scriptDir, WshShell
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = scriptDir
WshShell.Run """" & scriptDir & "\.venv\Scripts\pythonw.exe"" main.py --gui", 0, False
Set WshShell = Nothing
Set fso = Nothing
