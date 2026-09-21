@echo off
rem Starts AniHUB without leaving a console window behind (the hidden launcher run.vbs does it).
start "" wscript.exe "%~dp0run.vbs"
exit
