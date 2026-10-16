@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo   ============ 服务状态 ============
powershell -NoProfile -Command "try{$s=Invoke-RestMethod http://127.0.0.1:8848/__status -TimeoutSec 3;ConvertTo-Json -InputObject $s}catch{Write-Host '服务未响应（未启动或端口变化）'}"
echo.
echo   ============ 日志最后 40 行（logs\serve.log） ============
powershell -NoProfile -Command "if(Test-Path 'logs\serve.log'){Get-Content 'logs\serve.log' -Tail 40 -Encoding UTF8}else{Write-Host '暂无日志文件'}"
echo.
pause
