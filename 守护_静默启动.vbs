' 股票强势监测 · 静默守护启动器
' 被计划任务 StockMonitorGuardian 调用；wscript 无控制台，以隐藏方式拉起守护脚本
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "D:\股票强势监测"
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""D:\股票强势监测\服务守护.ps1""", 0, False
