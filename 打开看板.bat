@echo off
chcp 65001 >nul
cd /d "%~dp0"
"D:\_tools\stock-monitor\python\python.exe" -X utf8 "%~dp0launch_dashboard.py" %*
if errorlevel 1 pause
