import asyncio
import sys
from typing import Optional

from playwright.async_api import async_playwright

from convert_to_pdf import resolve_auth_paths, save_session, wait_for_login_completion


async def bootstrap_login(url: str, session_path: Optional[str] = None) -> None:
    auth_paths = resolve_auth_paths(url, session_path)
    print(f"Starting login bootstrap for: {url}")
    print("A browser window will open. Complete login there; the script will save the session automatically.")
    print(f"Using auth profile: {auth_paths['profile_dir']}")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=auth_paths["browser_profile_dir"],
            headless=False,
        )
        existing_pages = getattr(context, "pages", [])
        page = existing_pages[0] if existing_pages else await context.new_page()
        await page.goto(url, timeout=60_000)
        storage = await wait_for_login_completion(page, context, url)
        save_session(storage, auth_paths["session_path"])
        print(f"Session saved to {auth_paths['session_path']}")
        await context.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/bootstrap_login.py <url>")
        sys.exit(1)
    asyncio.run(bootstrap_login(sys.argv[1]))
