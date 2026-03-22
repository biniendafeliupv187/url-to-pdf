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
LATEST_AUTH_ATTEMPT_PATH = os.path.expanduser("~/.url-to-pdf/last_auth_attempt.json")


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


def save_latest_auth_attempt(payload: dict) -> None:
    os.makedirs(os.path.dirname(LATEST_AUTH_ATTEMPT_PATH) or ".", exist_ok=True)
    with open(LATEST_AUTH_ATTEMPT_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def load_latest_auth_attempt() -> Optional[dict]:
    if not os.path.exists(LATEST_AUTH_ATTEMPT_PATH):
        return None
    try:
        with open(LATEST_AUTH_ATTEMPT_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


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


def resolve_auth_context(url: Optional[str], session_path: Optional[str] = None) -> tuple[str, dict]:
    """
    Resolve an auth target either from an explicit URL or the most recent auth attempt.
    """
    if url and url != "latest":
        return url, attempt_paths_for_url(url, session_path)

    latest = load_latest_auth_attempt()
    if not latest or not latest.get("url"):
        raise RuntimeError("No recent auth attempt found. Run auth_manager.py begin <url> first.")

    return latest["url"], attempt_paths_for_url(latest["url"], latest.get("session_path"))


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
    save_latest_auth_attempt(
        {
            "url": url,
            "session_path": paths["session_path"],
            "profile_dir": paths["profile_dir"],
            "browser_profile_dir": paths["browser_profile_dir"],
            "attempt_path": paths["attempt_path"],
            "close_request_path": paths["close_request_path"],
            "status": "starting",
            "started_at": time.time(),
        }
    )

    print(f"Started auth bootstrap for: {url}")
    print(f"Auth profile: {paths['profile_dir']}")
    print("A browser window should open shortly.")
    print("After you finish logging in, reply '已登录'.")
    print("The agent should then run:")
    print("  python3 scripts/run.py auth_manager.py confirm")


def confirm_auth(url: Optional[str] = None, session_path: Optional[str] = None) -> dict:
    resolved_url, paths = resolve_auth_context(url, session_path)
    result = asyncio.run(validate_saved_session_for_url(resolved_url, paths["session_path"]))
    if result["ok"]:
        write_close_request(paths["close_request_path"])
        payload = update_auth_attempt(
            paths["attempt_path"],
            status="confirmed",
            confirmed_at=time.time(),
            last_validation=result,
        )
        save_latest_auth_attempt(payload)
        print("✅ Login confirmed and validation passed.")
        print(f"Session path: {paths['session_path']}")
    else:
        payload = update_auth_attempt(
            paths["attempt_path"],
            status="awaiting_user_confirmation",
            last_validation=result,
        )
        save_latest_auth_attempt(payload)
        print("⚠️ User confirmed login, but fallback validation did not pass yet.")
        print(f"Reason: {result.get('reason') or 'Unknown validation failure'}")
        print("Keep the browser open, finish login, then run confirm again.")
    return result


def status_auth(url: Optional[str] = None, session_path: Optional[str] = None) -> Optional[dict]:
    resolved_url, paths = resolve_auth_context(url, session_path)
    payload = load_auth_attempt(paths["attempt_path"])
    if not payload:
        print("No auth attempt found for this site.")
        return None

    print(f"URL: {resolved_url}")
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


def cancel_auth(url: Optional[str] = None, session_path: Optional[str] = None) -> None:
    resolved_url, paths = resolve_auth_context(url, session_path)
    write_close_request(paths["close_request_path"])
    payload = update_auth_attempt(paths["attempt_path"], status="canceled", canceled_at=time.time())
    save_latest_auth_attempt(payload)
    print(f"Canceled auth attempt for: {resolved_url}")
    print("Cancellation requested. The auth browser should close shortly.")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/auth_manager.py <begin|confirm|status|cancel> [url]")
        sys.exit(1)

    command = sys.argv[1].strip().lower()
    url = sys.argv[2] if len(sys.argv) > 2 else None

    if command == "begin":
        if not url:
            print("Usage: python3 scripts/auth_manager.py begin <url>")
            sys.exit(1)
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
