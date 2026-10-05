"""Embed UTF-8 process code page in our unsigned Windows CLI copy.

The upstream MinGW executable receives ANSI argv; filesystem expects UTF-8.
Resource-only patch: code/model weights remain unchanged. Windows 10 1903+.
"""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys

def patch(exe):
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.BeginUpdateResourceW.argtypes=[wintypes.LPCWSTR,wintypes.BOOL]
    api.BeginUpdateResourceW.restype=wintypes.HANDLE
    api.UpdateResourceW.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,wintypes.WORD,ctypes.c_void_p,wintypes.DWORD]
    api.UpdateResourceW.restype=wintypes.BOOL
    api.EndUpdateResourceW.argtypes=[wintypes.HANDLE,wintypes.BOOL]
    api.EndUpdateResourceW.restype=wintypes.BOOL
    data=Path(__file__).with_name('kimodo_utf8.manifest').read_bytes()
    buffer=ctypes.create_string_buffer(data)
    handle=api.BeginUpdateResourceW(str(Path(exe).resolve()),False)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    if not api.UpdateResourceW(handle,ctypes.c_void_p(24),ctypes.c_void_p(1),1033,buffer,len(data)):
        error=ctypes.get_last_error();api.EndUpdateResourceW(handle,True);raise ctypes.WinError(error)
    if not api.EndUpdateResourceW(handle,False):raise ctypes.WinError(ctypes.get_last_error())
if __name__=='__main__':patch(sys.argv[1])
