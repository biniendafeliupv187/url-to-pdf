import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from convert_to_pdf import resolve_auth_paths, validate_saved_session_for_url


AUTH_ATTEMPT_FILENAME = "auth_attempt.json"
AUTH_CLOSE_REQUEST_FILENAME = "close_requested.flag"


def attempt_paths_for_url(url: str, session_path: Optional[str] = None) -> dict:
    auth_paths = resolve_auth_paths(url, session_path)
    return {
        "attempt_path": os.path.join(auth_paths["profile_dir"], AUTH_ATTEMPT_FILENAME),
        "close_request_path": os.path.join(auth_paths["profile_dir"], AUTH_CLOSE_REQUEST_FILENAME),
        "session_path": auth_paths["session_path"],
        "profile_dir": auth_paths["profile_dir"],
        "browser_profile_dir": auth_paths["browser_profile_dir"],
    }


def load_auth_attempt(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def save_auth_attempt(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def update_auth_attempt(path: str, **updates) -> dict:
    payload = load_auth_attempt(path) or {}
    payload.update(updates)
    save_auth_attempt(path, payload)
    return payload


def write_close_request(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("close\n")


def clear_close_request(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)


def close_request_exists(path: str) -> bool:
    return os.path.exists(path)


def begin_auth(url: str, session_path: Optional[str] = None) -> None:
    paths = attempt_paths_for_url(url, session_path)
    clear_close_request(paths["close_request_path"])

    worker_script = Path(__file__).resolve().with_name("auth_browser_worker.py")
    proc = subprocess.Popen(
        [sys.executable, str(worker_script), url, paths["session_path"]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    save_auth_attempt(
        paths["attempt_path"],
        {
            "status": "starting",
            "url": url,
            "pid": proc.pid,
            "started_at": time.time(),
            "session_path": paths["session_path"],
            "profile_dir": paths["profile_dir"],
            "browser_profile_dir": paths["browser_profile_dir"],
        },
    )

    print(f"Started auth bootstrap for: {url}")
    print(f"Auth profile: {paths['profile_dir']}")
    print("A browser window should open shortly.")
    print("After you finish logging in, reply '已登录' and then run:")
    print(f"  python3 scripts/run.py auth_manager.py confirm {url}")


def confirm_auth(url: str, session_path: Optional[str] = None) -> dict:
    paths = attempt_paths_for_url(url, session_path)
    result = asyncio.run(validate_saved_session_for_url(url, paths["session_path"]))
    if result["ok"]:
        write_close_request(paths["close_request_path"])
        update_auth_attempt(
            paths["attempt_path"],
            status="confirmed",
            confirmed_at=time.time(),
            last_validation=result,
        )
        print("✅ Login confirmed and validation passed.")
        print(f"Session path: {paths['session_path']}")
    else:
        update_auth_attempt(
            paths["attempt_path"],
            status="awaiting_user_confirmation",
            last_validation=result,
        )
        print("⚠️ User confirmed login, but fallback validation did not pass yet.")
        print(f"Reason: {result.get('reason') or 'Unknown validation failure'}")
        print("Keep the browser open, finish login, then run confirm again.")
    return result


def status_auth(url: str, session_path: Optional[str] = None) -> Optional[dict]:
    paths = attempt_paths_for_url(url, session_path)
    payload = load_auth_attempt(paths["attempt_path"])
    if not payload:
        print("No auth attempt found for this site.")
        return None

    print(f"Status: {payload.get('status', 'unknown')}")
    print(f"Profile: {paths['profile_dir']}")
    print(f"Session: {paths['session_path']}")
    if payload.get("last_url"):
        print(f"Last URL: {payload['last_url']}")
    if payload.get("last_title"):
        print(f"Last Title: {payload['last_title']}")
    if payload.get("last_validation"):
        print(f"Last Validation OK: {payload['last_validation'].get('ok')}")
    return payload


def cancel_auth(url: str, session_path: Optional[str] = None) -> None:
    paths = attempt_paths_for_url(url, session_path)
    write_close_request(paths["close_request_path"])
    update_auth_attempt(paths["attempt_path"], status="canceled", canceled_at=time.time())
    print("Cancellation requested. The auth browser should close shortly.")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/auth_manager.py <begin|confirm|status|cancel> <url>")
        sys.exit(1)

    command = sys.argv[1].strip().lower()
    url = sys.argv[2]

    if command == "begin":
        begin_auth(url)
    elif command == "confirm":
        result = confirm_auth(url)
        sys.exit(0 if result["ok"] else 2)
    elif command == "status":
        status_auth(url)
    elif command == "cancel":
        cancel_auth(url)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
