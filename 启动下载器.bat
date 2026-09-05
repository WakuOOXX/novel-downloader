@echo off
chcp 65001 >nul
title 小说下载器
cd /d "%~dp0"
set PY="C:\Users\pc\AppData\Local\Microsoft\WindowsApps\pythonw.exe"
if exist %PY% (
  start "" %PY% "%~dp0app.py"
) else (
  set PY="C:\Users\pc\AppData\Local\Microsoft\WindowsApps\python.exe"
  start "" %PY% "%~dp0app.py"
)
exit
