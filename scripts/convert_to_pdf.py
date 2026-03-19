import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright


# =============================================================================
# Pure helper functions (unit-testable, no browser / network side effects)
# =============================================================================

def clean_url(url: str) -> str:
    """Strip known proxy/reader prefixes (e.g. pure.md) from a URL."""
    if "pure.md/" in url:
        url = url.split("pure.md/", 1)[-1]
    return url


def safe_filename(title: str, fallback: str = "untitled") -> str:
    """
    Convert a page title to a filesystem-safe filename (without extension).
    Falls back to ``fallback`` if the sanitised result has no alphanumeric chars.
    """
    illegal = r'\/:*?"<>|'
    sanitised = "".join(
        c for c in title
        if c.isprintable() and c not in illegal and c not in '｜：'
    ).strip()
    has_alnum = any(c.isalnum() for c in sanitised)
    return sanitised if has_alnum else fallback


def resolve_collision(path: str) -> str:
    """Return ``path`` if it does not exist, otherwise append _1, _2, …"""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    counter = 1
    while True:
        candidate = f"{base}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


_UI_CLASS_TOKEN_PATTERN = re.compile(
    r"(?:^|[_-])(?:sidebar|nav|menu|header|footer|sticky)(?:$|[_-])"
    r"|(?:^|[_-])bottom(?:[_-])bar(?:$|[_-])",
    re.IGNORECASE,
)


def should_hide_class_token(token: str) -> bool:
    """
    Return True for class tokens that likely represent chrome/UI rather than
    article content.

    Matching is token-aware instead of substring-based to avoid false positives
    like ``use-femenu`` on the WeChat article ``<body>`` element.
    """
    return bool(token and _UI_CLASS_TOKEN_PATTERN.search(token))



# Compiled once at import time; used by is_login_required().
# Chinese patterns: substring match (CJK has no word-boundary concept).
# English patterns: \b word boundaries prevent false positives like
# "designer" → "sign", "unsigned" → "sign", "login form" article content.
_LOGIN_PATTERN = re.compile(
    r"未登录|请登录|登录|注册"                   # Chinese nav/UI
    r"|\b(?:sign[\s\-]?in|sign[\s\-]?up)\b"     # sign in / sign-in / sign up
    r"|\blog[\s\-]?in\b"                         # log in / log-in
    r"|\blogin\b"                                # login (single word)
    r"|\bplease\s+log\s*in\b"                    # please log in
    r"|\bplease\s+login\b"                       # please login
    r"|\blog\s+in\s+to\b"                        # log in to
    r"|\bsign\s+in\s+to\b",                      # sign in to
    re.IGNORECASE,
)


def is_login_required(text: str) -> bool:
    """
    Return True if the page body text indicates the user is not logged in.

    Uses a compiled regex with:
    - Direct substring match for Chinese patterns (登录 / 注册 / 未登录 / 请登录)
    - Word-boundary (\\b) guards for English patterns to avoid false positives
      such as "designer" → "sign", "unsigned" → "sign", etc.

    Use this function when NO session file exists (broad detection).
    Use is_session_expired() when a session file exists (strict detection).
    """
    return bool(text and _LOGIN_PATTERN.search(text))


# Strict pattern used when a session file exists but may have expired.
# Deliberately excludes standalone 登录/注册 which appear in nav bars even
# for fully authenticated users (e.g. "退出登录" dropdown).
_SESSION_EXPIRED_PATTERN = re.compile(
    r"未登录|请登录|重新登录"                       # Definitive "not logged in" Chinese
    r"|登录\s*后"                                # "登录后查看/留言" implies not logged in
    r"|\bplease\s+log(?:in|\s+in)\b"             # please login / please log in
    r"|\bplease\s+sign\s+in\b"                   # please sign in
    r"|\bsession\s+(?:expired|timed?\s*out)\b"   # session expired / timed out
    r"|\bauth(?:entication)?\s+(?:required|failed)\b",  # auth required/failed
    re.IGNORECASE,
)


def is_session_expired(text: str) -> bool:
    """
    Return True if the page text shows the session has expired / is invalid.

    Stricter than is_login_required(): standalone '登录' and '注册' do NOT
    trigger this, because logged-in users may still see those words in nav
    menus (e.g. '退出登录'). Only unambiguous 'you are NOT logged in' phrases
    cause a True return.

    Use this function when a session file already exists.
    """
    return bool(text and _SESSION_EXPIRED_PATTERN.search(text))


_LOGIN_TITLE_PATTERN = re.compile(
    r"^(?:登录|登入|login|log[\s\-]?in|sign[\s\-]?in)(?:[\s\-_｜|].*)?$",
    re.IGNORECASE,
)
_LOGIN_FORM_HINT_PATTERNS = (
    re.compile(r"账号|邮箱|手机号|用户名|\b(?:email|phone number|username|account)\b", re.IGNORECASE),
    re.compile(r"验证码|密码|忘记密码|\b(?:verification code|password|forgot password)\b", re.IGNORECASE),
    re.compile(r"立即登录|继续登录|统一认证|请登录|sign[\s\-]?in|log[\s\-]?in", re.IGNORECASE),
)


def looks_like_login_page(title: str, body_text: str) -> bool:
    """
    Return True if the page is very likely a login screen.

    This is stricter than ``is_login_required()`` for article pages that mention
    login conceptually, but broader than ``is_session_expired()`` so we can catch
    dedicated login screens such as a page titled simply "登录".
    """
    normalized_title = " ".join((title or "").strip().split())
    normalized_body = body_text or ""
    title_is_login = bool(normalized_title and _LOGIN_TITLE_PATTERN.search(normalized_title))
    form_hint_matches = sum(
        1 for pattern in _LOGIN_FORM_HINT_PATTERNS if pattern.search(normalized_body)
    )
    body_has_login_form_hints = bool(
        normalized_body and (
            is_session_expired(normalized_body)
            or (
                len(normalized_body) <= 400
                and form_hint_matches >= 2
            )
        )
    )
    return title_is_login or body_has_login_form_hints


def load_session(path: str) -> Optional[dict]:
    """
    Load a Playwright storage_state dict from *path*.
    Returns None if the file is missing or corrupt.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_session(storage_state: dict, path: str) -> None:
    """
    Persist a Playwright storage_state dict to *path*.
    Creates parent directories if they do not exist.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(storage_state, f, ensure_ascii=False, indent=2)


async def scroll_to_trigger_lazy_load(
    page,
    step: int = 800,
    delay: float = 0.5,
) -> None:
    """
    Scroll the page in *step*-pixel increments to trigger lazy-loaded content.

    Detection strategy:
    1. Look for a custom scroll container (e.g. Geekbang's simplebar-content-wrapper).
       Scroll whichever container has the largest scrollHeight > clientHeight.
    2. Fall back to window.scrollTo for regular pages.

    Resets scroll to the top before returning so the PDF starts at the page header.
    """
    # Find the largest scroll container (custom scrollbar or overflow wrapper)
    find_container_js = """() => {
        var all = document.querySelectorAll('*');
        var best = null;
        var bestDiff = 0;
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var diff = el.scrollHeight - el.clientHeight;
            if (diff > bestDiff) {
                bestDiff = diff;
                best = el;
            }
        }
        if (!best || bestDiff < 100) return null;
        // Return a unique JS path to the element via index in querySelectorAll('*')
        var all2 = document.querySelectorAll('*');
        for (var j = 0; j < all2.length; j++) {
            if (all2[j] === best) return j;
        }
        return null;
    }"""

    container_idx = await page.evaluate(find_container_js)

    if container_idx is not None:
        # Scroll the custom container
        scroll_container_js = """(args) => {
            var idx = args[0], step = args[1];
            var el = document.querySelectorAll('*')[idx];
            if (!el) return -1;
            el.scrollTop += step;
            return el.scrollTop;
        }"""
        reset_container_js = """(idx) => {
            var el = document.querySelectorAll('*')[idx];
            if (el) el.scrollTop = 0;
        }"""
        get_heights_js = """(idx) => {
            var el = document.querySelectorAll('*')[idx];
            if (!el) return [0, 0];
            return [el.scrollTop, el.scrollHeight];
        }"""

        pos = 0
        while True:
            heights = await page.evaluate(get_heights_js, container_idx)
            scroll_top, scroll_height = heights[0], heights[1]
            if scroll_top + step >= scroll_height:
                break
            await page.evaluate(scroll_container_js, [container_idx, step])
            if delay:
                await asyncio.sleep(delay)

        await page.evaluate(reset_container_js, container_idx)
        print(f"  Scrolled custom container (scrollH={scroll_height}px) in {step}px steps")
    else:
        # Fallback: window scroll for regular pages
        total = await page.evaluate("document.body.scrollHeight")
        pos = 0
        while pos < total:
            pos += step
            await page.evaluate(f"window.scrollTo(0, {pos})")
            if delay:
                await asyncio.sleep(delay)
            total = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, 0)")
        print(f"  Scrolled window (scrollH={total}px)")



# JS injected before page.pdf() to ensure all scrollable containers and their
# parents are fully expanded in print output (overrides flex/grid/overflow limits).
async def flatten_scroll_containers_for_print(page) -> None:
    """
    Finds the largest scrollable container on the page and recursively walks
    up the DOM to the document root, forcing all elements in that path to 
    auto-height and visible-overflow, disabling grid/flex limits.
    """
    script = """() => {
        // 1. Find biggest scroll container
        var best = null, bestDiff = 0;
        var all = document.querySelectorAll('*');
        for (var el of all) {
            var diff = el.scrollHeight - el.clientHeight;
            if (diff > bestDiff) {
                bestDiff = diff;
                best = el;
            }
        }
        if (!best) return "no container found";
        
        // 2. Walk UP the DOM and break all flex/height limits
        var cur = best;
        var path = [];
        while (cur && cur !== document.documentElement) {
            path.push(cur.tagName + (cur.className ? '.' + cur.className.split(' ')[0] : ''));
            
            // Force expansion for print
            cur.style.setProperty('height', 'auto', 'important');
            cur.style.setProperty('max-height', 'none', 'important');
            cur.style.setProperty('overflow', 'visible', 'important');
            
            // Break flex/grid constraints
            cur.style.setProperty('position', 'static', 'important');
            cur.style.setProperty('flex', 'none', 'important');
            cur.style.setProperty('display', 'block', 'important'); 
            
            cur = cur.parentElement;
        }
        
        return {
            path: path.reverse().join(' > '),
            newHtmlHeight: document.documentElement.scrollHeight
        };
    }"""
    
    res = await page.evaluate(script)
    if isinstance(res, dict):
        print(f"  Flattened DOM from scroll container up to body (path={res['path'][:50]}...)")
    else:
        print("  No custom scroll container found to flatten.")


async def hide_ui_elements_for_print(page) -> None:
    """
    Hide obvious chrome (nav/header/footer/sidebar) without nuking content.

    We intentionally avoid raw CSS substring selectors such as ``[class*="menu"]``
    because they can match unrelated tokens like ``use-femenu`` on WeChat pages
    and hide the entire document during printing.
    """
    await page.evaluate(
        """() => {
            const tokenPattern = /(?:^|[_-])(?:sidebar|nav|menu|header|footer|sticky)(?:$|[_-])|(?:^|[_-])bottom(?:[_-])bar(?:$|[_-])/i;
            const protectedSelectors = [
              'html',
              'body',
              'main',
              'article',
              '#js_content',
              '#img-content',
              '.rich_media',
              '.rich_media_content',
              '.rich_media_wrp',
            ];
            const isProtected = (el) => protectedSelectors.some((selector) => {
              try {
                return el.matches(selector);
              } catch (_) {
                return false;
              }
            });

            for (const el of document.querySelectorAll('*')) {
              if (isProtected(el)) continue;

              const tag = (el.tagName || '').toLowerCase();
              const classes = Array.from(el.classList || []);
              const shouldHide =
                ['nav', 'header', 'footer', 'aside'].includes(tag) ||
                classes.some((token) => tokenPattern.test(token)) ||
                classes.some((token) => (
                  token.startsWith('Index_nav_') ||
                  token.startsWith('Index_contentWrapScroller_') ||
                  token.startsWith('Index_side_') ||
                  token.startsWith('Header_')
                ));

              if (shouldHide) {
                el.setAttribute('data-url-to-pdf-hide', '1');
              }
            }
        }"""
    )
    await page.add_style_tag(
        content="""
@media print {
  [data-url-to-pdf-hide="1"] {
    display: none !important;
  }
}
"""
    )

DEFAULT_SESSION_PATH = os.path.expanduser("~/.url-to-pdf/session.json")


def has_interactive_terminal() -> bool:
    """Return True when stdin/stdout are attached to a real interactive terminal."""
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


async def ensure_logged_in(
    url: str,
    headless_context,
    session_path: str,
    prompt_fn=None,
) -> None:
    """
    Open a HEADED browser at *url*, wait for the user to log in (blocking
    on *prompt_fn*), then copy cookies into *headless_context* and persist
    the session to *session_path*.

    Parameters
    ----------
    url: str
        The URL that triggered the login wall.
    headless_context:
        The Playwright BrowserContext currently in use for headless rendering.
    session_path: str
        Where to save the Playwright storage_state JSON.
    prompt_fn: callable, optional
        Called with a message string to block until the user is ready.
        Defaults to ``input``. Inject a no-op in tests.
    """
    if prompt_fn is None:
        prompt_fn = input

    if not has_interactive_terminal():
        raise RuntimeError(
            "Interactive login bootstrap requires a TTY. "
            "Please rerun this command in an interactive terminal so the browser "
            "can open and you can confirm login."
        )

    print("\n" + "=" * 60)
    print("⚠️  Login required — opening browser for authentication…")
    print("=" * 60)

    async with async_playwright() as p_headed:
        headed_browser = await p_headed.chromium.launch(headless=False)
        headed_context = await headed_browser.new_context()
        headed_page = await headed_context.new_page()
        await headed_page.goto(url, timeout=60_000)

        prompt_fn(
            "\n✅ Please log in in the browser window that just opened.\n"
            "   Once you are logged in, press Enter here to continue…"
        )

        # Copy cookies from headed context → headless context
        storage = await headed_context.storage_state()
        await headless_context.add_cookies(storage.get("cookies", []))

        # Persist for future runs
        save_session(storage, session_path)
        print(f"✅ Session saved to {session_path}")

        await headed_browser.close()


async def convert_url_to_pdf(urls, output_base_dir, wait_after_load: int = 10,
                              session_path: str = DEFAULT_SESSION_PATH):
    """
    Convert a list of URLs to PDF files, saved under a timestamped folder.

    Parameters
    ----------
    urls : list[str]
        URLs to convert.
    output_base_dir : str
        Root directory for output (e.g. ~/Downloads/PDF).
    wait_after_load : int
        Extra seconds to wait after networking is idle, to let heavy JS
        frameworks (e.g. Geekbang / Next.js) finish rendering. Default: 10.
    session_path : str
        Path to the Playwright storage_state JSON for Cookie persistence.
        Default: ~/.url-to-pdf/session.json.
    """
    os.makedirs(output_base_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(output_base_dir, timestamp)
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # Restore saved session cookies if available
        saved_session = load_session(session_path)
        context_kwargs: dict = {
            "viewport": {"width": 1200, "height": 800},
            "device_scale_factor": 2,
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
        }
        if saved_session:
            context_kwargs["storage_state"] = saved_session
            print(f"Loaded session from {session_path}")

        # High-resolution context (mirrors Puppeteer's deviceScaleFactor: 2)
        context = await browser.new_context(**context_kwargs)

        for url in urls:
            url = clean_url(url)

            if not url.startswith(("http://", "https://")):
                print(f"Skipping invalid URL: {url}")
                continue

            page = await context.new_page()
            try:
                print(f"Navigating to: {url}")
                # Mirror JS reference: wait for both domcontentloaded AND networkidle
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                # Wait for networkidle separately so timeout is independent
                try:
                    await page.wait_for_load_state("networkidle", timeout=30_000)
                except Exception:
                    print("networkidle timeout — continuing anyway")

                # Equivalent of Puppeteer's `document.fonts.ready`
                try:
                    await page.evaluate("document.fonts.ready")
                except Exception:
                    pass

                # Extra wait for JS-heavy pages (e.g. React/Vue SPA hydration)
                if wait_after_load > 0:
                    print(f"Extra wait: {wait_after_load}s for JS hydration…")
                    await asyncio.sleep(wait_after_load)

                # --- Session-aware login detection ---
                # With no session: use broad patterns (登录/注册 in nav = not logged in).
                # With session: use strict patterns only (nav may still show 登录 even
                # when authenticated; only definitive "未登录"/"请登录" means expired).
                title = await page.title()
                body_text = await page.evaluate("document.body.innerText")
                session_exists = os.path.exists(session_path)
                needs_login = (
                    is_session_expired(body_text) if session_exists
                    else is_login_required(body_text)
                )
                needs_login = needs_login or looks_like_login_page(title, body_text)
                if needs_login:
                    if session_exists:
                        print("Detected missing or expired site session — starting login bootstrap…")
                    else:
                        print("No reusable site session found — starting first-time login bootstrap…")
                    await ensure_logged_in(url, context, session_path)
                    # Reload in headless context with new cookies
                    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=30_000)
                    except Exception:
                        pass
                    if wait_after_load > 0:
                        await asyncio.sleep(wait_after_load)
                    title = await page.title()
                    body_text = await page.evaluate("document.body.innerText")
                    if looks_like_login_page(title, body_text):
                        raise RuntimeError("Still on login page after interactive authentication")

                # Derive filename from page title
                filename = safe_filename(title, fallback=f"untitled_{int(time.time())}")
                raw_path = os.path.join(output_dir, f"{filename}.pdf")
                output_path = resolve_collision(raw_path)

                # Scroll to trigger lazy-loaded sections, then expand containers for print
                print("Scrolling to load lazy content…")
                await scroll_to_trigger_lazy_load(page)

                # Flatten nested scroll containers to ensure full height prints
                await flatten_scroll_containers_for_print(page)

                # Hide sidebars, navigation, and other UI clutter
                await hide_ui_elements_for_print(page)

                print(f"Saving PDF: {output_path}")
                await page.pdf(
                    path=output_path,
                    format="A4",
                    print_background=True,
                )

            except Exception as e:
                print(f"Error converting {url}: {e}")
            finally:
                await page.close()

        await browser.close()

    print("Conversion complete.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert_to_pdf.py <url1> <url2> ...")
        sys.exit(1)

    urls = sys.argv[1:]
    downloads_pdf = os.path.expanduser("~/Downloads/PDF")
    asyncio.run(convert_url_to_pdf(urls, downloads_pdf))
