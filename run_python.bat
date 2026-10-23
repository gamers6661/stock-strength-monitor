@echo off
setlocal
set "PYTHONUTF8=1"
set "TEMP=D:\Temp\stock-monitor"
set "TMP=D:\Temp\stock-monitor"
set "PATH=D:\_tools\stock-monitor;%PATH%"
set "PY=D:\_tools\stock-monitor\python\python.exe"
if exist "%~dp0cache\serve-python.txt" set /p "PY="<"%~dp0cache\serve-python.txt"
set "PY=%PY:pythonw.exe=python.exe%"
if not exist "%PY%" set "PY=python"
"%PY%" -X utf8 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"
if errorlevel 1 (
  echo Python 3.9+ required. Configure cache\serve-python.txt with the service Python path.
  exit /b 1
)
"%PY%" -X utf8 %*
exit /b %errorlevel%
