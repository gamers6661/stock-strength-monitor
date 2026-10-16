@echo off
chcp 65001 >nul
setlocal

rem ===== 停止本地服务（通过 /__status 拿真实 pid，避免误杀） =====

if not exist "%~dp0cache" mkdir "%~dp0cache" >nul 2>nul
>"%~dp0cache\serve.stop" echo manual-stop

set "PID="
for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "try{(Invoke-RestMethod http://127.0.0.1:8848/__status -TimeoutSec 3).pid}catch{''}"`) do set "PID=%%i"

if "%PID%"=="" (
  echo   服务未在运行。
  pause
  exit /b 0
)

taskkill /pid %PID% /f >nul 2>nul
echo   已停止本地服务（PID %PID%）。
pause
