@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

rem 用户明确打开看板，解除本次会话的手动停止标记
if exist "%~dp0cache\serve.stop" del /q "%~dp0cache\serve.stop" >nul 2>nul

rem ===== 智能打开看板：没起服务就静默拉起，起了就直接开页面 =====
rem 推荐用本脚本做自启动入口（比 start.bat 可靠：先探活再打开，不会出现拒绝连接）
rem 设 SKIP_OPEN=1 则只保证服务在跑、不开浏览器（供自动化/排查用）

set "PORT=8848"
rem 注意：这里不能使用 PowerShell 管道符（|），否则 cmd 会把一行拆成两条命令，
rem 双击时只会闪退；用 $null= 接收结果，保持探活命令对 cmd 安全。
set "PING=$ProgressPreference='SilentlyContinue';try{$null=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT%/__ping -TimeoutSec 2;exit 0}catch{exit 1}"

set "PYW=%USERPROFILE%\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
if not exist "%PYW%" (
  for /f "delims=" %%i in ('where pythonw 2^>nul') do set "PYW=%%i"
)
if not exist "%PYW%" set "PYW=python"

powershell -NoProfile -Command "%PING%" >nul 2>nul
if not errorlevel 1 goto open

echo   [启动] 本地服务未运行，正在静默启动（pythonw 无窗口）...
start "" "%PYW%" "%~dp0serve.py" --no-browser

set /a n=0
:wait
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "%PING%" >nul 2>nul
if not errorlevel 1 goto open
set /a n+=1
if %n% lss 30 goto wait

echo   [失败] 服务 60 秒内未就绪，请双击「诊断服务.bat」查看原因
pause
exit /b 1

:open
if /i "%~1"=="/silent" set "SKIP_OPEN=1"
if "%SKIP_OPEN%"=="1" (
  echo   [OK] 服务已就绪（静默模式，不打开浏览器）
  exit /b 0
)
start "" "http://127.0.0.1:%PORT%/dashboard.html"
exit /b 0
