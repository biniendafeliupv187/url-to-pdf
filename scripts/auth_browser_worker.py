import asyncio
import sys
import time
from typing import Optional

from playwright.async_api import async_playwright

from auth_manager import (
    attempt_paths_for_url,
    close_request_exists,
    load_auth_attempt,
    save_auth_attempt,
)
from convert_to_pdf import resolve_auth_paths, save_session


async def run_auth_browser_worker(url: str, session_path: Optional[str] = None) -> None:
    auth_paths = resolve_auth_paths(url, session_path)
    paths = attempt_paths_for_url(url, session_path)

    attempt = load_auth_attempt(paths["attempt_path"]) or {}
    attempt.update(
        {
            "status": "waiting_for_user_confirmation",
            "url": url,
            "session_path": auth_paths["session_path"],
            "profile_dir": auth_paths["profile_dir"],
            "browser_profile_dir": auth_paths["browser_profile_dir"],
            "worker_started_at": time.time(),
        }
    )
    save_auth_attempt(paths["attempt_path"], attempt)

    try:
        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=auth_paths["browser_profile_dir"],
                headless=False,
            )
            existing_pages = getattr(context, "pages", [])
            page = existing_pages[0] if existing_pages else await context.new_page()
            await page.goto(url, timeout=60_000)

            while True:
                if close_request_exists(paths["close_request_path"]):
                    break

                storage = await context.storage_state()
                save_session(storage, auth_paths["session_path"])

                try:
                    last_title = await page.title()
                except Exception:
                    last_title = ""
                try:
                    last_url = page.url
                except Exception:
                    last_url = ""

                attempt = load_auth_attempt(paths["attempt_path"]) or {}
                attempt.update(
                    {
                        "status": "waiting_for_user_confirmation",
                        "last_title": last_title,
                        "last_url": last_url,
                        "last_seen_at": time.time(),
                    }
                )
                save_auth_attempt(paths["attempt_path"], attempt)
                await asyncio.sleep(2)

            await context.close()
            attempt = load_auth_attempt(paths["attempt_path"]) or {}
            attempt.update({"status": "closed", "closed_at": time.time()})
            save_auth_attempt(paths["attempt_path"], attempt)
    except Exception as exc:
        attempt = load_auth_attempt(paths["attempt_path"]) or {}
        attempt.update({"status": "error", "error": str(exc), "failed_at": time.time()})
        save_auth_attempt(paths["attempt_path"], attempt)
        raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/auth_browser_worker.py <url> [session_path]")
        sys.exit(1)
    session_path_arg = sys.argv[2] if len(sys.argv) > 2 else None
    asyncio.run(run_auth_browser_worker(sys.argv[1], session_path_arg))
