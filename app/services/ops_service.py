from __future__ import annotations

import ctypes
import os
import shutil
import threading
import time
from pathlib import Path


class OpsService:
    def __init__(self, storage_dir: str, project_dir: str | None = None) -> None:
        self._storage_dir = Path(storage_dir)
        self._project_dir = Path(project_dir) if project_dir else self._storage_dir.parent.parent
        self._started_at = time.time()
        self._cpu_lock = threading.Lock()
        self._last_cpu_wall = time.perf_counter()
        self._last_cpu_process = time.process_time()

    def get_metrics(self) -> dict:
        process_memory = self._get_process_memory()
        system_memory = self._get_system_memory()
        storage_usage = self._get_storage_usage()
        project_usage = self._get_project_usage()
        disk_usage = shutil.disk_usage(self._storage_dir)

        return {
            "process": {
                "pid": os.getpid(),
                "cpu_percent": self._sample_process_cpu_percent(),
                "working_set_bytes": process_memory.get("working_set_bytes"),
                "private_bytes": process_memory.get("private_bytes"),
                "uptime_seconds": round(time.time() - self._started_at, 1),
            },
            "storage": {
                "app_store_bytes": storage_usage,
                "project_bytes": project_usage,
                "disk_total_bytes": disk_usage.total,
                "disk_used_bytes": disk_usage.used,
                "disk_free_bytes": disk_usage.free,
                "storage_dir": str(self._storage_dir),
                "project_dir": str(self._project_dir),
            },
            "system": {
                "cpu_count": os.cpu_count() or 1,
                "total_memory_bytes": system_memory.get("total_memory_bytes"),
                "available_memory_bytes": system_memory.get("available_memory_bytes"),
            },
            "captured_at_epoch": time.time(),
        }

    def _sample_process_cpu_percent(self) -> float:
        with self._cpu_lock:
            current_wall = time.perf_counter()
            current_process = time.process_time()
            wall_delta = current_wall - self._last_cpu_wall
            process_delta = current_process - self._last_cpu_process
            self._last_cpu_wall = current_wall
            self._last_cpu_process = current_process

        if wall_delta <= 0:
            return 0.0

        cpu_count = os.cpu_count() or 1
        cpu_percent = (process_delta / (wall_delta * cpu_count)) * 100
        return round(max(cpu_percent, 0.0), 2)

    def _get_storage_usage(self) -> int:
        return self._get_directory_size(self._storage_dir)

    def _get_project_usage(self) -> int:
        return self._get_directory_size(self._project_dir)

    @staticmethod
    def _get_directory_size(directory: Path) -> int:
        total_bytes = 0
        if not directory.exists():
            return total_bytes

        for path in directory.rglob("*"):
            if path.is_file():
                try:
                    total_bytes += path.stat().st_size
                except OSError:
                    continue
        return total_bytes

    @staticmethod
    def _get_process_memory() -> dict:
        if os.name == "nt":
            return _get_windows_process_memory()
        return {"working_set_bytes": None, "private_bytes": None}

    @staticmethod
    def _get_system_memory() -> dict:
        if os.name == "nt":
            return _get_windows_system_memory()
        return {"total_memory_bytes": None, "available_memory_bytes": None}


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _get_windows_process_memory() -> dict:
    counters = _ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(_ProcessMemoryCountersEx)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    process_handle = kernel32.GetCurrentProcess()
    success = psapi.GetProcessMemoryInfo(
        process_handle,
        ctypes.byref(counters),
        counters.cb,
    )
    if not success:
        return {"working_set_bytes": None, "private_bytes": None}
    return {
        "working_set_bytes": int(counters.WorkingSetSize),
        "private_bytes": int(counters.PrivateUsage),
    }


def _get_windows_system_memory() -> dict:
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
    kernel32.GlobalMemoryStatusEx.restype = ctypes.c_int
    success = kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    if not success:
        return {"total_memory_bytes": None, "available_memory_bytes": None}
    return {
        "total_memory_bytes": int(status.ullTotalPhys),
        "available_memory_bytes": int(status.ullAvailPhys),
    }
