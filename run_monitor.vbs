Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
script = root & "\main.py"
shell.Run Chr(34) & pythonw & Chr(34) & " -B " & Chr(34) & script & Chr(34), 0, False
