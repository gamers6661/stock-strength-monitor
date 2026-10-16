@echo off
chcp 65001 >nul
rem ===== 自启动入口：启动隐藏守护，服务退出后自动拉起 =====
rem 本文件被「启动」文件夹里的同名副本调用；删掉那个副本即可取消自启动
if exist "%~dp0cache\serve.stop" del /q "%~dp0cache\serve.stop" >nul 2>nul
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0服务守护.ps1"
exit /b 0
