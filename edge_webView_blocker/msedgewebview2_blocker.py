import argparse
import atexit
import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PROCESS_NAME = "msedgewebview2.exe"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EdgeWebView2Blocker"
PID_FILE = APP_DIR / "blocker.pid"
LOG_FILE = APP_DIR / "blocker.log"
CREATE_NO_WINDOW = 0x08000000


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )


def log(message: str) -> None:
    ensure_app_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def parse_tasklist_csv(output: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("INFO:"):
            continue
        parsed = next(csv.reader([line]), [])
        if parsed:
            rows.append(parsed)
    return rows


def get_matching_pids() -> list[int]:
    result = run_command(
        ["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}", "/FO", "CSV", "/NH"]
    )
    pids: list[int] = []
    for row in parse_tasklist_csv(result.stdout):
        if len(row) < 2:
            continue
        image_name = row[0].strip().lower()
        pid_text = row[1].strip().replace(",", "")
        if image_name != PROCESS_NAME:
            continue
        try:
            pids.append(int(pid_text))
        except ValueError:
            continue
    return pids


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    result = run_command(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    for row in parse_tasklist_csv(result.stdout):
        if len(row) < 2:
            continue
        try:
            if int(row[1].strip().replace(",", "")) == pid:
                return True
        except ValueError:
            continue
    return False


def read_pid_file() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def remove_pid_file() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def write_pid_file() -> None:
    ensure_app_dir()
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(remove_pid_file)


def ensure_single_instance() -> bool:
    existing_pid = read_pid_file()
    if existing_pid and existing_pid != os.getpid() and is_pid_running(existing_pid):
        print(
            "Edge WebView2 차단기가 이미 실행 중입니다. "
            f"(PID {existing_pid})\n"
            "먼저 '--stop' 옵션으로 종료하세요."
        )
        return False
    write_pid_file()
    return True


def kill_webview2() -> tuple[list[int], str]:
    pids = get_matching_pids()
    if not pids:
        return [], ""

    result = run_command(["taskkill", "/F", "/T", "/IM", PROCESS_NAME])
    if result.returncode == 0:
        return pids, ""

    remaining = set(get_matching_pids())
    killed = [pid for pid in pids if pid not in remaining]
    errors = (result.stdout + "\n" + result.stderr).strip()
    return killed, errors


def stop_running_instance() -> int:
    existing_pid = read_pid_file()
    if not existing_pid:
        print("실행 중인 차단기 인스턴스를 찾지 못했습니다.")
        return 1

    if not is_pid_running(existing_pid):
        remove_pid_file()
        print("오래된 PID 파일만 남아 있고 현재 실행 중인 차단기는 없습니다.")
        return 1

    result = run_command(["taskkill", "/F", "/PID", str(existing_pid), "/T"])
    if result.returncode == 0:
        remove_pid_file()
        print(f"차단기 인스턴스를 종료했습니다. (PID {existing_pid})")
        return 0

    errors = (result.stdout + "\n" + result.stderr).strip()
    print(f"차단기 인스턴스 종료에 실패했습니다. (PID {existing_pid})")
    if errors:
        print(errors)
    return 1


def show_status() -> int:
    existing_pid = read_pid_file()
    if existing_pid and is_pid_running(existing_pid):
        print(f"차단기가 실행 중입니다. PID: {existing_pid}")
        print(f"로그 파일: {LOG_FILE}")
        return 0

    print("차단기가 실행 중이 아닙니다.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Continuously blocks msedgewebview2.exe by terminating it."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Polling interval in seconds. Default: 0.5",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop a previously started blocker instance.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show whether the blocker is currently running.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.stop:
        return stop_running_instance()

    if args.status:
        return show_status()

    if args.interval < 0.1:
        parser.error("--interval must be 0.1 or higher.")

    if not ensure_single_instance():
        return 1

    log(
        f"{PROCESS_NAME} 차단을 시작합니다. "
        f"{args.interval:.1f}초 간격으로 감시합니다. 종료하려면 Ctrl+C를 누르세요."
    )

    last_error = ""
    last_error_at = 0.0

    try:
        while True:
            killed_pids, errors = kill_webview2()
            if killed_pids:
                pid_text = ", ".join(str(pid) for pid in killed_pids)
                log(f"{PROCESS_NAME} 인스턴스를 종료했습니다: {pid_text}")
            if errors:
                now = time.monotonic()
                if errors != last_error or now - last_error_at >= 60:
                    log(f"{PROCESS_NAME} 종료 시도 중 다음 메시지가 발생했습니다: {errors}")
                    last_error = errors
                    last_error_at = now
            time.sleep(args.interval)
    except KeyboardInterrupt:
        log("Ctrl+C 입력으로 차단기를 종료합니다.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
