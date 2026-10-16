@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   ==========================================
echo     股票强势监测  ·  全量重建 + 生成报告
echo   ==========================================
echo.
echo   全量重建约需 3-5 分钟（重建K线缓存与全部映射），请勿关闭窗口...
echo.
python daily.py --full
if errorlevel 1 goto fail
echo.
echo   ==========================================
echo     完成！
echo     看板：dashboard.html （双击打开）
echo     报告：snapshot_report.md
echo   ==========================================
echo.
pause
exit /b 0

:fail
echo.
echo   [错误] 扫描失败，请检查网络连接。
echo.
pause
exit /b 1
