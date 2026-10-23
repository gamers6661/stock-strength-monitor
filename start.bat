@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   ==========================================
echo     股票强势监测系统  ·  本地看板（前台模式）
echo   ==========================================
echo.
echo   端口已占用且是本系统实例时，会自动打开浏览器后退出
echo   服务日志写入 logs\serve.log（即使关掉窗口也不丢）
echo   关闭本窗口即停止服务
echo.
call "%~dp0run_python.bat" serve.py
echo.
echo   服务已退出。
pause
