Set shell = CreateObject("WScript.Shell")
folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
' Same as run.vbs, but opens straight on Anime > Music (see app.py's --music handling).
shell.Run """" & folder & "\.venv\Scripts\pythonw.exe"" -m anihub --music", 0, False
