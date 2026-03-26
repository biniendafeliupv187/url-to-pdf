import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

from site_adapters import adapter_login_signal, content_selectors_for_url


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


def looks_like_login_page_for_url(
    url: str,
    title: str,
    body_text: str,
    current_url: str = "",
) -> bool:
    """
    Return True when generic login-page heuristics or site-specific hints suggest
    the page is still an auth wall.
    """
    return looks_like_login_page(title, body_text) or adapter_login_signal(url, body_text, current_url)


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


async def detect_content_signal(page, url: str) -> bool:
    """
    Detect whether the current page appears to contain meaningful article content.
    """
    selectors = list(content_selectors_for_url(url))
    try:
        return await page.evaluate(
            """(selectors) => {
                for (const selector of selectors) {
                    const el = document.querySelector(selector);
                    if (el && (el.innerText || '').trim().length > 200) {
                        return true;
                    }
                }
                return (document.body.innerText || '').trim().length > 500;
            }""",
            selectors,
        )
    except Exception:
        return False


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
DEFAULT_PROFILES_DIR = os.path.expanduser("~/.url-to-pdf/profiles")
DEFAULT_STORAGE_STATE_FILENAME = "storage_state.json"
DEFAULT_BROWSER_PROFILE_DIRNAME = "browser_profile"


def site_key_from_url(url: str) -> str:
    """
    Convert a URL into a stable site key used for auth profile directories.
    """
    host = (urlsplit(clean_url(url)).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    key = re.sub(r"[^a-z0-9._-]+", "-", host).strip("-")
    return key or "default"


def default_profile_dir_for_url(url: str) -> str:
    """Return the default auth profile directory for a URL's host."""
    return os.path.join(DEFAULT_PROFILES_DIR, site_key_from_url(url))


def default_session_path_for_url(url: str) -> str:
    """Return the default storage_state JSON path for a URL's host."""
    return os.path.join(default_profile_dir_for_url(url), DEFAULT_STORAGE_STATE_FILENAME)


def default_browser_profile_dir_for_url(url: str) -> str:
    """Return the persistent headed-browser profile dir for a URL's host."""
    return os.path.join(default_profile_dir_for_url(url), DEFAULT_BROWSER_PROFILE_DIRNAME)


def resolve_auth_paths(url: str, session_path: Optional[str] = None) -> dict:
    """
    Resolve storage_state and browser profile paths for a URL.

    If *session_path* is explicitly provided, it remains authoritative and the
    browser profile directory is placed alongside it. Otherwise, a site-scoped
    directory under ``~/.url-to-pdf/profiles/<host>/`` is used.
    """
    if session_path:
        resolved_session_path = os.path.expanduser(session_path)
        profile_dir = os.path.dirname(resolved_session_path) or "."
    else:
        profile_dir = default_profile_dir_for_url(url)
        resolved_session_path = os.path.join(profile_dir, DEFAULT_STORAGE_STATE_FILENAME)

    return {
        "profile_dir": profile_dir,
        "session_path": resolved_session_path,
        "browser_profile_dir": os.path.join(profile_dir, DEFAULT_BROWSER_PROFILE_DIRNAME),
    }


def _cookie_domain_matches_host(domain: str, host: str) -> bool:
    normalized_domain = (domain or "").lstrip(".").lower()
    normalized_host = (host or "").lower()
    return bool(
        normalized_domain
        and normalized_host
        and (
            normalized_host == normalized_domain
            or normalized_host.endswith(f".{normalized_domain}")
        )
    )


def session_matches_url(storage_state: Optional[dict], url: str) -> bool:
    """
    Return True when the storage_state contains cookies relevant to *url*'s host.
    """
    if not storage_state:
        return False
    host = (urlsplit(clean_url(url)).hostname or "").lower()
    cookies = storage_state.get("cookies", [])
    return any(
        _cookie_domain_matches_host(cookie.get("domain", ""), host)
        for cookie in cookies
    )


def load_session_for_url(url: str, session_path: Optional[str] = None) -> Tuple[dict, Optional[dict]]:
    """
    Load the best available storage_state for *url*.

    Returns ``(auth_paths, saved_session)``. With default site-scoped storage, a
    matching legacy ``~/.url-to-pdf/session.json`` file is migrated into the
    site profile directory on first use.
    """
    auth_paths = resolve_auth_paths(url, session_path)
    saved_session = load_session(auth_paths["session_path"])
    if saved_session is not None or session_path:
        return auth_paths, saved_session

    legacy_session = load_session(DEFAULT_SESSION_PATH)
    if session_matches_url(legacy_session, url):
        save_session(legacy_session, auth_paths["session_path"])
        print(
            f"Migrated legacy session from {DEFAULT_SESSION_PATH} "
            f"to {auth_paths['session_path']}"
        )
        return auth_paths, legacy_session

    return auth_paths, None


def has_interactive_terminal() -> bool:
    """Return True when stdin/stdout are attached to a real interactive terminal."""
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


@dataclass(frozen=True)
class LoginStrategy:
    name: str
    requires_headed_browser: bool
    confirmation_mode: str


def resolve_login_strategy(
    *,
    interactive_terminal: bool,
    headed_browser_available: bool,
) -> LoginStrategy:
    """
    Resolve login handling policy from environment capabilities.

    This keeps TTY detection, headed-browser availability, and login completion
    mode as separate concepts instead of encoding them directly in the main
    conversion flow.
    """
    if not headed_browser_available:
        return LoginStrategy(
            name="unsupported",
            requires_headed_browser=False,
            confirmation_mode="unavailable",
        )

    if interactive_terminal:
        return LoginStrategy(
            name="auto_bootstrap",
            requires_headed_browser=True,
            confirmation_mode="browser_polling",
        )

    return LoginStrategy(
        name="explicit_confirm",
        requires_headed_browser=True,
        confirmation_mode="explicit_user_confirm",
    )


def unsupported_login_flow_message(url: str) -> str:
    """Return guidance when the environment cannot launch a headed browser."""
    return (
        "Login required, but this environment cannot launch a headed browser for authentication.\n"
        f"Finish login in a desktop environment first, then retry: {url}"
    )


def explicit_auth_flow_message(url: str) -> str:
    """Return operator guidance for login-required pages in non-interactive environments."""
    return (
        "Login required in a non-interactive environment must use the explicit auth flow.\n"
        f"Run: python3 scripts/run.py auth_manager.py begin {url}\n"
        "After login in the browser, reply '已登录' and run:\n"
        "  python3 scripts/run.py auth_manager.py confirm"
    )


async def wait_for_login_completion(
    page,
    context,
    url: str,
    timeout_seconds: int = 300,
    poll_interval: float = 2.0,
    min_visible_seconds: float = 90.0,
    stable_passes_required: int = 1,
) -> dict:
    """
    Poll a headed browser session until it appears to be authenticated.

    This avoids requiring a TTY-only ``input()`` confirmation flow, which is
    brittle in agent environments that can open a browser window but do not
    provide interactive stdin.
    """
    deadline = time.monotonic() + timeout_seconds
    started_at = time.monotonic()
    last_title = ""
    last_url = ""
    stable_passes = 0
    initial_storage = await context.storage_state()
    initial_cookies = {
        (cookie.get("name"), cookie.get("domain"), cookie.get("path"), cookie.get("value"))
        for cookie in initial_storage.get("cookies", [])
    }

    while time.monotonic() < deadline:
        try:
            last_title = await page.title()
        except Exception:
            last_title = ""
        try:
            body_text = await page.evaluate("document.body.innerText")
        except Exception:
            body_text = ""
        try:
            last_url = page.url
        except Exception:
            last_url = ""
        content_signal = await detect_content_signal(page, url)

        elapsed = time.monotonic() - started_at
        if elapsed >= min_visible_seconds and not looks_like_login_page_for_url(url, last_title, body_text, last_url):
            storage = await context.storage_state()
            current_cookies = {
                (cookie.get("name"), cookie.get("domain"), cookie.get("path"), cookie.get("value"))
                for cookie in storage.get("cookies", [])
            }
            cookies_changed = bool(current_cookies and current_cookies != initial_cookies)
            if cookies_changed and content_signal:
                stable_passes += 1
                if stable_passes >= stable_passes_required:
                    return storage
            else:
                stable_passes = 0

        await asyncio.sleep(poll_interval)

    raise RuntimeError(
        "Timed out waiting for login bootstrap to complete. "
        f"Last page title: {last_title or '<unknown>'}, URL: {last_url or '<unknown>'}"
    )


async def ensure_logged_in(
    url: str,
    headless_context,
    session_path: str,
    prompt_fn=None,
) -> None:
    """
    Open a HEADED browser at *url*, wait for the user to log in, then copy
    cookies into *headless_context* and persist the session to *session_path*.

    Parameters
    ----------
    url: str
        The URL that triggered the login wall.
    headless_context:
        The Playwright BrowserContext currently in use for headless rendering.
    session_path: str
        Where to save the Playwright storage_state JSON.
    prompt_fn: callable, optional
        Optional callback used only for user-facing messaging in custom flows.
        No stdin confirmation is required; login completion is detected by polling.
    """
    print("\n" + "=" * 60)
    print("⚠️  Login required — opening browser for authentication…")
    print("=" * 60)
    print("Please complete login in the browser window. The script will continue automatically.")
    if prompt_fn is not None:
        prompt_fn("Login bootstrap started in a browser window.")

    auth_paths = resolve_auth_paths(url, session_path)
    async with async_playwright() as p_headed:
        headed_context = await p_headed.chromium.launch_persistent_context(
            user_data_dir=auth_paths["browser_profile_dir"],
            headless=False,
        )
        existing_pages = getattr(headed_context, "pages", [])
        headed_page = existing_pages[0] if existing_pages else await headed_context.new_page()
        await headed_page.goto(url, timeout=60_000)
        storage = await wait_for_login_completion(headed_page, headed_context, url)

        # Copy cookies from headed context → headless context
        await headless_context.add_cookies(storage.get("cookies", []))

        # Persist for future runs
        save_session(storage, auth_paths["session_path"])
        print(f"✅ Session saved to {auth_paths['session_path']}")

        await headed_context.close()


async def validate_saved_session_for_url(
    url: str,
    session_path: str,
    wait_after_load: int = 3,
) -> dict:
    """
    Validate a saved site session by opening the target URL headlessly once.

    Intended as a lightweight fallback check after the user explicitly says
    "已登录" in a non-interactive environment such as Claude Code.
    """
    saved_session = load_session(session_path)
    if not saved_session:
        return {
            "ok": False,
            "reason": "No saved storage_state found yet",
            "login_page": True,
            "content_signal": False,
            "title": "",
            "current_url": "",
        }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1200, "height": 800},
            device_scale_factor=2,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            storage_state=saved_session,
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            try:
                await page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            if wait_after_load > 0:
                await asyncio.sleep(wait_after_load)

            title = await page.title()
            body_text = await page.evaluate("document.body.innerText")
            current_url = getattr(page, "url", "")
            content_signal = await detect_content_signal(page, url)
            login_page = looks_like_login_page_for_url(url, title, body_text, current_url)
            expired = is_session_expired(body_text)
            ok = bool(not login_page and not expired and content_signal)
            return {
                "ok": ok,
                "reason": "" if ok else "Page still looks unauthenticated or lacks article content",
                "login_page": login_page,
                "content_signal": content_signal,
                "title": title,
                "current_url": current_url,
            }
        finally:
            await page.close()
            close_context = getattr(context, "close", None)
            if close_context is not None:
                await close_context()
            await browser.close()


async def convert_url_to_pdf(urls, output_base_dir, wait_after_load: int = 10,
                              session_path: Optional[str] = None):
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
    session_path : str | None
        Optional explicit path to the Playwright storage_state JSON.
        When omitted, the tool uses ``~/.url-to-pdf/profiles/<site>/storage_state.json``.
    """
    os.makedirs(output_base_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(output_base_dir, timestamp)
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {output_dir}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for url in urls:
            url = clean_url(url)

            if not url.startswith(("http://", "https://")):
                print(f"Skipping invalid URL: {url}")
                continue

            auth_paths, saved_session = load_session_for_url(url, session_path)
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
                print(f"Loaded session from {auth_paths['session_path']}")

            context = await browser.new_context(**context_kwargs)
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
                current_url = getattr(page, "url", url)
                session_exists = bool(saved_session or os.path.exists(auth_paths["session_path"]))
                needs_login = (
                    is_session_expired(body_text) if session_exists
                    else is_login_required(body_text)
                )
                needs_login = needs_login or looks_like_login_page_for_url(url, title, body_text, current_url)
                if needs_login:
                    login_strategy = resolve_login_strategy(
                        interactive_terminal=has_interactive_terminal(),
                        headed_browser_available=True,
                    )
                    if login_strategy.confirmation_mode == "unavailable":
                        raise RuntimeError(unsupported_login_flow_message(url))
                    if login_strategy.confirmation_mode == "explicit_user_confirm":
                        raise RuntimeError(explicit_auth_flow_message(url))
                    if session_exists:
                        print("Detected missing or expired site session — starting login bootstrap…")
                    else:
                        print("No reusable site session found — starting first-time login bootstrap…")
                    await ensure_logged_in(url, context, auth_paths["session_path"])
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
                    current_url = getattr(page, "url", url)
                    if looks_like_login_page_for_url(url, title, body_text, current_url):
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
                close_context = getattr(context, "close", None)
                if close_context is not None:
                    await close_context()

        await browser.close()

    print("Conversion complete.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python convert_to_pdf.py <url1> <url2> ...")
        sys.exit(1)

    urls = sys.argv[1:]
    downloads_pdf = os.path.expanduser("~/Downloads/PDF")
    asyncio.run(convert_url_to_pdf(urls, downloads_pdf))
