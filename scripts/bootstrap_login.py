import asyncio
import sys

from playwright.async_api import async_playwright

from convert_to_pdf import DEFAULT_SESSION_PATH, save_session, wait_for_login_completion


async def bootstrap_login(url: str, session_path: str = DEFAULT_SESSION_PATH) -> None:
    print(f"Starting login bootstrap for: {url}")
    print("A browser window will open. Complete login there; the script will save the session automatically.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, timeout=60_000)
        storage = await wait_for_login_completion(page, context)
        save_session(storage, session_path)
        print(f"Session saved to {session_path}")
        await browser.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/bootstrap_login.py <url>")
        sys.exit(1)
    asyncio.run(bootstrap_login(sys.argv[1]))
