import ctypes
import os
import shutil
from datetime import datetime

import torch
import folder_paths


INPUT_CACHE_DIR_PREFIX = "scail2_loop_input_cache_"
INPUT_CACHE_MARKER = ".wananimateplus_scail2_loop_input_cache"
MAX_MEMORY_USED_RATIO = 0.93
MIN_FREE_MEMORY_BYTES = int(1.8 * 1024 ** 3)


def _system_memory_info():
    try:
        import psutil

        mem = psutil.virtual_memory()
        return int(mem.available), int(mem.total)
    except Exception:
        pass

    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullAvailPhys), int(status.ullTotalPhys)

    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        avail_pages = os.sysconf("SC_AVPHYS_PAGES")
        return int(avail_pages * page_size), int(phys_pages * page_size)
    except Exception:
        return None, None


def tensor_nbytes(tensor):
    return int(tensor.numel() * tensor.element_size())


def dtype_nbytes(dtype):
    return int(torch.empty((), dtype=dtype).element_size())


def memory_allows_allocation(additional_bytes, max_used_ratio=MAX_MEMORY_USED_RATIO, min_free_bytes=MIN_FREE_MEMORY_BYTES):
    additional_bytes = max(int(additional_bytes or 0), 0)
    available, total = _system_memory_info()
    if available is None or total is None or total <= 0:
        return True
    remaining = available - additional_bytes
    if remaining < min_free_bytes:
        return False
    used_after = total - remaining
    return (used_after / total) <= max_used_ratio


def is_loop_sequence(value):
    return (
        isinstance(value, dict)
        and value.get("type") == "scail2_loop_sequence"
        and value.get("storage") in ("disk", "mixed")
    )


def is_disk_sequence(value):
    return is_loop_sequence(value)


def _is_input_cache_dir_name(name):
    if not name.startswith(INPUT_CACHE_DIR_PREFIX):
        return False
    suffix = name[len(INPUT_CACHE_DIR_PREFIX):]
    parts = suffix.split("_")
    return (
        len(parts) == 4
        and len(parts[0]) == 8 and parts[0].isdigit()
        and len(parts[1]) == 6 and parts[1].isdigit()
        and len(parts[2]) == 6 and parts[2].isdigit()
        and parts[3].isdigit()
    )


def _norm_path(path):
    if path is None:
        return None
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return path


def cleanup_stale_input_cache_dirs(logger=None, exclude_paths=None):
    output_dir = folder_paths.get_output_directory()
    exclude = {_norm_path(path) for path in (exclude_paths or []) if path is not None}
    try:
        entries = list(os.scandir(output_dir))
    except Exception as e:
        if logger is not None:
            logger.warning(f"SCAIL-2 loop: failed to scan temporary input cache folders in {output_dir}: {e}")
        return

    for entry in entries:
        try:
            if not entry.is_dir():
                continue
            if _norm_path(entry.path) in exclude:
                continue
            marker_path = os.path.join(entry.path, INPUT_CACHE_MARKER)
            if not (_is_input_cache_dir_name(entry.name) or os.path.exists(marker_path)):
                continue
            shutil.rmtree(entry.path)
            if logger is not None:
                logger.info(f"SCAIL-2 loop: removed stale temporary input cache folder {entry.path}")
        except Exception as e:
            if logger is not None:
                logger.warning(f"SCAIL-2 loop: failed to remove stale temporary input cache folder {entry.path}: {e}")


def create_input_cache_dir():
    path = os.path.join(
        folder_paths.get_output_directory(),
        f"{INPUT_CACHE_DIR_PREFIX}{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{os.getpid()}",
    )
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, INPUT_CACHE_MARKER), "w", encoding="utf-8") as marker_file:
        marker_file.write("WanAnimatePlus SCAIL-2 loop temporary input cache\n")
    return path


def remove_input_cache_dir(path, logger=None):
    if path is None:
        return None
    try:
        shutil.rmtree(path)
        if logger is not None:
            logger.info(f"SCAIL-2 loop: removed temporary input cache folder {path}")
        return None
    except Exception as e:
        if logger is not None:
            logger.warning(f"SCAIL-2 loop: failed to remove temporary input cache folder {path}: {e}")
        return path
