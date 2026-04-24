import argparse
import ctypes
import logging
import os
import signal
import sys
import time
from ctypes import wintypes
from pathlib import Path


TARGET_PROCESS = "msedge.exe"
DEFAULT_INTERVAL_SECONDS = 0.2

PROCESS_TERMINATE = 0x0001
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_ALREADY_EXISTS = 183
SINGLE_INSTANCE_MUTEX_NAME = "Local\\EdgeBlockerSingleton_5A9A9F37"


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(PROCESSENTRY32W),
]
kernel32.Process32FirstW.restype = wintypes.BOOL
kernel32.Process32NextW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(PROCESSENTRY32W),
]
kernel32.Process32NextW.restype = wintypes.BOOL
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE


def get_last_error() -> int:
    return ctypes.get_last_error()


def acquire_single_instance_mutex() -> wintypes.HANDLE | None:
    mutex = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX_NAME)
    if not mutex:
        raise ctypes.WinError(get_last_error())

    if get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex)
        return None

    return mutex


def iter_processes():
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(get_last_error())

    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)

        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return

        while True:
            yield entry.th32ProcessID, entry.szExeFile

            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)


def terminate_process(pid: int) -> bool:
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        logging.debug("PID %s 종료 권한을 얻지 못했습니다. 오류=%s", pid, get_last_error())
        return False

    try:
        if not kernel32.TerminateProcess(handle, 1):
            logging.debug("PID %s 종료 실패. 오류=%s", pid, get_last_error())
            return False
        return True
    finally:
        kernel32.CloseHandle(handle)


def kill_target_processes(target_name: str, dry_run: bool) -> int:
    current_pid = os.getpid()
    killed_count = 0

    for pid, exe_name in iter_processes():
        if pid == current_pid:
            continue
        if exe_name.lower() != target_name:
            continue

        if dry_run:
            logging.info("감지됨: %s PID=%s", exe_name, pid)
            killed_count += 1
            continue

        if terminate_process(pid):
            killed_count += 1
            logging.info("차단됨: %s PID=%s", exe_name, pid)
        else:
            logging.warning("차단 실패: %s PID=%s", exe_name, pid)

    return killed_count


def build_logger(log_path: Path | None, quiet: bool) -> None:
    handlers: list[logging.Handler] = []
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    if not quiet:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)


def default_log_path() -> Path:
    base_dir = os.getenv("LOCALAPPDATA")
    if not base_dir:
        base_dir = str(Path.home())
    return Path(base_dir) / "EdgeBlocker" / "edge_blocker.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Microsoft Edge(msedge.exe)가 실행되면 감지해서 즉시 종료합니다."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="프로세스 감시 주기(초). 기본값: 0.2",
    )
    parser.add_argument(
        "--target",
        default=TARGET_PROCESS,
        help="차단할 실행 파일 이름. 기본값: msedge.exe",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="현재 실행 중인 대상만 한 번 종료하고 종료합니다.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="종료하지 않고 감지만 기록합니다.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="콘솔 출력 없이 로그 파일에만 기록합니다.",
    )
    parser.add_argument(
        "--log",
        default=str(default_log_path()),
        help="로그 파일 경로. 기본값: %%LOCALAPPDATA%%\\EdgeBlocker\\edge_blocker.log",
    )
    return parser.parse_args()


def main() -> int:
    if os.name != "nt":
        print("이 프로그램은 Windows에서만 동작합니다.", file=sys.stderr)
        return 1

    mutex = acquire_single_instance_mutex()
    if mutex is None:
        return 0

    args = parse_args()
    target_name = args.target.lower()
    interval = max(args.interval, 0.05)
    log_path = Path(args.log) if args.log else None
    keep_running = True

    def stop(_signum, _frame):
        nonlocal keep_running
        keep_running = False

    try:
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        build_logger(log_path, args.quiet)

        logging.info("%s 차단 감시를 시작합니다. 주기=%.2f초", target_name, interval)

        while keep_running:
            kill_target_processes(target_name, args.dry_run)
            if args.once:
                break
            time.sleep(interval)
    except Exception:
        logging.exception("감시 중 오류가 발생했습니다.")
        return 1
    finally:
        kernel32.CloseHandle(mutex)

    logging.info("감시를 종료합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
