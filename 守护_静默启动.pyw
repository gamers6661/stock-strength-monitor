# -*- coding: utf-8 -*-
"""股票强势监测 · 静默启动器
被计划任务 StockMonitorGuardian 调用（登录触发）。
pythonw 本身无控制台窗口，再以 CREATE_NO_WINDOW 拉起守护脚本，全程零窗口。
守护逻辑唯一实现在 服务守护.ps1，本文件只负责无窗口拉起它。
"""
import os
import subprocess

ROOT = r"D:\股票强势监测"
PS1 = os.path.join(ROOT, "服务守护.ps1")

subprocess.Popen(
    [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        PS1,
    ],
    cwd=ROOT,
    creationflags=subprocess.CREATE_NO_WINDOW,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL,
)
