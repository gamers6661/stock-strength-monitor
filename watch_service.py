"""Windows单实例守护，独立于任何编辑器进程。"""
import ctypes
import os
import time
from launch_dashboard import ROOT,alive,detached


def main():
    mutex=None
    if os.name=='nt':
        from ctypes import wintypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        api.CreateMutexW.restype=wintypes.HANDLE
        mutex=api.CreateMutexW(None,False,'Local\\StockStrengthMonitorWatchdog8848')
        if ctypes.get_last_error()==183:return
    while True:
        if not (ROOT/'cache/serve.stop').exists() and not alive():detached('serve.py')
        time.sleep(30)


if __name__=='__main__':main()
