Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
' hidden window (0), do not wait (False): no console window at all
shell.Run """" & folder & "\.venv\Scripts\pythonw.exe"" -m anihub", 0, False
