"""
TDD tests for convert_to_pdf.py helper functions.
RED phase: these tests are written BEFORE the implementation exists.
All unit tests must pass without network access.
"""
import os
import sys
import tempfile
import pytest

# Add scripts directory to path so we can import the module under test
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from convert_to_pdf import (
    clean_url,
    safe_filename,
    resolve_collision,
    should_hide_class_token,
    has_interactive_terminal,
    is_login_required,
    is_session_expired,
    looks_like_login_page,
    load_session,
    save_session,
    scroll_to_trigger_lazy_load,
    flatten_scroll_containers_for_print,
    hide_ui_elements_for_print,
    convert_url_to_pdf,
)


# --------------------------------------------------------------------------
# clean_url() — strips proxy/reader prefixes
# --------------------------------------------------------------------------

class TestCleanUrl:
    def test_strips_pure_md_prefix(self):
        url = "https://pure.md/https://example.com/article"
        assert clean_url(url) == "https://example.com/article"

    def test_leaves_normal_https_url_unchanged(self):
        url = "https://time.geekbang.org/column/article/945358"
        assert clean_url(url) == url

    def test_leaves_normal_http_url_unchanged(self):
        url = "http://example.com"
        assert clean_url(url) == url

    def test_strips_pure_md_without_double_slash(self):
        url = "https://pure.md/http://example.com"
        assert clean_url(url) == "http://example.com"

    def test_pure_md_destination_is_not_stripped_further(self):
        url = "https://pure.md/https://pure.md/https://example.com"
        assert clean_url(url) == "https://pure.md/https://example.com"


# --------------------------------------------------------------------------
# safe_filename() — sanitizes page title to a filesystem-safe string
# --------------------------------------------------------------------------

class TestSafeFilename:
    def test_sanitizes_chinese_characters(self):
        title = "08｜群策群力：Agent Teams多会话协作架构"
        result = safe_filename(title, fallback="untitled")
        assert len(result) > 0
        assert "Agent" in result or "Teams" in result

    def test_removes_reserved_path_characters(self):
        title = "article/with\\backslash:colon?question"
        result = safe_filename(title, fallback="untitled")
        for ch in r'\/:*?"<>|':
            assert ch not in result

    def test_uses_fallback_when_title_is_empty(self):
        assert safe_filename("", fallback="untitled") == "untitled"

    def test_uses_fallback_when_title_is_only_special_chars(self):
        assert safe_filename("!!!###", fallback="untitled") == "untitled"

    def test_strips_leading_trailing_whitespace(self):
        title = "  My Article  "
        result = safe_filename(title, fallback="untitled")
        assert result == result.strip()

    def test_geekbang_title_produces_non_empty_filename(self):
        title = "08｜群策群力：Agent Teams多会话协作架构-Claude Code 工程化实战-极客时间"
        result = safe_filename(title, fallback="untitled")
        assert result != "untitled"
        assert len(result) > 0


# --------------------------------------------------------------------------
# resolve_collision() — unique filenames when file already exists
# --------------------------------------------------------------------------

class TestResolveCollision:
    def test_returns_original_path_when_no_collision(self, tmp_path):
        path = str(tmp_path / "article.pdf")
        assert resolve_collision(path) == path

    def test_appends_counter_when_file_exists(self, tmp_path):
        path = str(tmp_path / "article.pdf")
        open(path, "w").close()
        new_path = resolve_collision(path)
        assert new_path == str(tmp_path / "article_1.pdf")

    def test_increments_counter_for_multiple_collisions(self, tmp_path):
        path = str(tmp_path / "article.pdf")
        open(path, "w").close()
        open(str(tmp_path / "article_1.pdf"), "w").close()
        new_path = resolve_collision(path)
        assert new_path == str(tmp_path / "article_2.pdf")


# --------------------------------------------------------------------------
# should_hide_class_token() — token-aware UI class detection
# --------------------------------------------------------------------------

class TestShouldHideClassToken:
    def test_matches_header_like_tokens(self):
        assert should_hide_class_token("site-header") is True
        assert should_hide_class_token("left_nav") is True
        assert should_hide_class_token("bottom-bar") is True

    def test_avoids_false_positive_on_embedded_substrings(self):
        assert should_hide_class_token("use-femenu") is False
        assert should_hide_class_token("content-navigationless") is False


# --------------------------------------------------------------------------
# is_login_required() — detect login wall from page body text
# --------------------------------------------------------------------------

class TestIsLoginRequired:
    # --- original patterns (must still pass) ---
    def test_detects_weimidenglu(self):
        assert is_login_required("欢迎来到极客时间 未登录 请先登录") is True

    def test_detects_qingdenglu(self):
        assert is_login_required("请登录后查看完整内容") is True

    def test_returns_false_for_normal_content(self):
        assert is_login_required("这是一篇关于 Agent Teams 的文章，内容很丰富。") is False

    def test_returns_false_for_empty_text(self):
        assert is_login_required("") is False

    def test_case_insensitive_for_english_login(self):
        assert is_login_required("Please login to continue") is True

    # --- new patterns ---
    def test_detects_standalone_denglu(self):
        # e.g. navbar with just "登录" button text
        assert is_login_required("首页  专栏  登录  注册") is True

    def test_detects_zhuce(self):
        # 注册 alone means unauthenticated UI
        assert is_login_required("欢迎！注册成为会员享受更多权益") is True

    def test_detects_denglu_zhuce_together(self):
        assert is_login_required("登录 / 注册") is True

    def test_detects_english_sign_up(self):
        assert is_login_required("Sign up for free to read the full article") is True

    def test_detects_english_sign_in(self):
        assert is_login_required("Sign in to continue reading") is True

    def test_no_false_positive_for_article_about_login(self):
        # An article that *discusses* login should not trigger
        assert is_login_required(
            "本文介绍如何实现一个安全的用户认证系统，包括密码哈希和 JWT 令牌管理。"
        ) is False

    def test_no_false_positive_plain_text(self):
        assert is_login_required("Welcome to the platform! Enjoy your articles.") is False

    def test_no_false_positive_designer(self):
        # "designer" contains "sign" — must not trigger
        assert is_login_required("Our lead designer built this UI.") is False

    def test_no_false_positive_unsigned(self):
        # "unsigned" contains "sign" — must not trigger
        assert is_login_required("Use an unsigned integer for the counter.") is False


# --------------------------------------------------------------------------
# is_session_expired() — strict check used when a session file already exists
# --------------------------------------------------------------------------

class TestIsSessionExpired:
    """Strict detector: only definitive 'not logged in' phrases trigger it.
    Used when session.json exists but the session may have expired.
    Must NOT trigger on standalone '登录'/'注册' (nav buttons for logged-in users).
    """

    def test_detects_weimidenglu(self):
        assert is_session_expired("欢迎来到极客时间 未登录 请先登录") is True

    def test_detects_qingdenglu(self):
        assert is_session_expired("请登录后查看完整内容") is True

    def test_detects_dengluhou(self):
        # Geekbang expired session shows "登录 后留言"
        assert is_session_expired("登录 后留言") is True
        assert is_session_expired("登录后查看") is True

    def test_detects_chongxindenglu(self):
        assert is_session_expired("session 失效，请重新登录") is True

    def test_detects_english_please_login(self):
        assert is_session_expired("Please login to continue") is True

    def test_returns_false_for_empty_text(self):
        assert is_session_expired("") is False

    def test_no_false_positive_standalone_denglu(self):
        # Logged-in page may have '登录' in nav (e.g. '退出登录') — must NOT trigger
        assert is_session_expired("首页  专栏  登录  注册") is False

    def test_no_false_positive_zhuce_alone(self):
        # '注册' alone should NOT trigger expired (ambiguous for session state)
        assert is_session_expired("欢迎注册成为会员") is False

    def test_no_false_positive_normal_content(self):
        assert is_session_expired("这是一篇关于 Agent Teams 的正常内容。") is False

    def test_no_false_positive_sign_in_form_article(self):
        # Article discussing login forms should not trigger
        assert is_session_expired(
            "本文介绍如何在 React 中实现一个 sign in 功能。"
        ) is False


# --------------------------------------------------------------------------
# looks_like_login_page() — detect dedicated login screens
# --------------------------------------------------------------------------

class TestLooksLikeLoginPage:
    def test_detects_simple_login_title(self):
        assert looks_like_login_page("登录", "") is True
        assert looks_like_login_page("Login", "") is True

    def test_detects_login_form_hints_in_body(self):
        body = "请输入手机号、验证码并继续登录，忘记密码可重新设置。"
        assert looks_like_login_page("网易知识库", body) is True

    def test_avoids_false_positive_for_article_about_login(self):
        body = "本文讲解登录系统设计、密码哈希与验证码防刷策略。"
        assert looks_like_login_page("认证系统设计", body) is False


class TestInteractiveTerminal:
    def test_detects_interactive_terminal(self, monkeypatch):
        monkeypatch.setattr("convert_to_pdf.sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("convert_to_pdf.sys.stdout.isatty", lambda: True)
        assert has_interactive_terminal() is True

    def test_detects_non_interactive_terminal(self, monkeypatch):
        monkeypatch.setattr("convert_to_pdf.sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("convert_to_pdf.sys.stdout.isatty", lambda: True)
        assert has_interactive_terminal() is False


# --------------------------------------------------------------------------
# load_session() — restore Playwright storage state from disk
# --------------------------------------------------------------------------

class TestLoadSession:
    def test_returns_none_when_file_missing(self, tmp_path):
        path = str(tmp_path / "session.json")
        assert load_session(path) is None

    def test_returns_dict_when_valid_json(self, tmp_path):
        import json
        path = str(tmp_path / "session.json")
        data = {"cookies": [{"name": "sid", "value": "abc123"}], "origins": []}
        with open(path, "w") as f:
            json.dump(data, f)
        result = load_session(path)
        assert result == data

    def test_returns_none_when_file_is_corrupt(self, tmp_path):
        path = str(tmp_path / "session.json")
        with open(path, "w") as f:
            f.write("not valid json {{{")
        assert load_session(path) is None


# --------------------------------------------------------------------------
# save_session() — persist Playwright storage state to disk
# --------------------------------------------------------------------------

class TestSaveSession:
    def test_creates_parent_dirs_if_missing(self, tmp_path):
        path = str(tmp_path / "nested" / "deep" / "session.json")
        save_session({"cookies": [], "origins": []}, path)
        assert os.path.exists(path)

    def test_round_trips_data(self, tmp_path):
        import json
        path = str(tmp_path / "session.json")
        data = {"cookies": [{"name": "token", "value": "xyz"}], "origins": []}
        save_session(data, path)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded == data

    def test_overwrites_existing_file(self, tmp_path):
        import json
        path = str(tmp_path / "session.json")
        save_session({"cookies": [], "origins": []}, path)
        new_data = {"cookies": [{"name": "new", "value": "val"}], "origins": []}
        save_session(new_data, path)
        with open(path) as f:
            loaded = json.load(f)
        assert loaded == new_data


# --------------------------------------------------------------------------
# scroll_to_trigger_lazy_load() — scroll page to trigger lazy-loaded content
# --------------------------------------------------------------------------

class TestScrollToTriggerLazyLoad:
    """
    Tests for the two-branch scroll strategy:
    - Custom container branch: evaluate returns a container index (int)
    - Window fallback branch: evaluate returns None for find_container_js
    """

    def test_scrolls_custom_container_in_steps(self):
        """When a custom container is found, scrolls it until end."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        page = MagicMock()
        scroll_tops = [0, 800, 1600]
        call_count = [0]

        async def fake_evaluate(expr, *args):
            # find_container_js → return container index 5
            if "bestDiff" in expr:
                return 5
            # get_heights_js → return [scrollTop, scrollHeight]
            if "scrollTop, el.scrollHeight" in expr:
                idx = call_count[0]
                call_count[0] += 1
                st = scroll_tops[min(idx, len(scroll_tops) - 1)]
                return [st, 2000]
            # scroll_container_js or reset_container_js → return None
            return None

        page.evaluate = fake_evaluate
        asyncio.run(scroll_to_trigger_lazy_load(page, step=800, delay=0))
        # Should have called evaluate multiple times (find + heights + scrolls + reset)
        assert call_count[0] >= 1

    def test_resets_container_to_top_after_scrolling(self):
        """Reset function is called after scrolling the custom container."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        page = MagicMock()
        reset_called = [False]

        async def fake_evaluate(expr, *args):
            if "bestDiff" in expr:
                return 3  # container index
            if "scrollTop, el.scrollHeight" in expr:
                # Already at end → triggers exit
                return [1500, 1600]
            if "el.scrollTop = 0" in expr:
                reset_called[0] = True
            return None

        page.evaluate = fake_evaluate
        asyncio.run(scroll_to_trigger_lazy_load(page, step=800, delay=0))
        assert reset_called[0], "Container scrollTop must be reset to 0"

    def test_fallback_to_window_scroll_when_no_container(self):
        """When no custom container found, falls back to window.scrollTo."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        page = MagicMock()
        window_scrolls = []

        async def fake_evaluate(expr, *args):
            if "bestDiff" in expr:
                return None  # no custom container
            if "scrollHeight" in expr:
                return 800
            if "scrollTo" in expr:
                window_scrolls.append(expr)
            return None

        page.evaluate = fake_evaluate
        asyncio.run(scroll_to_trigger_lazy_load(page, step=800, delay=0))
        # Should have called window.scrollTo at least once (reset to 0, 0)
        assert any("scrollTo" in s for s in window_scrolls)


# --------------------------------------------------------------------------
# flatten_scroll_containers_for_print()
# --------------------------------------------------------------------------

class TestFlattenScrollContainers:
    def test_evaluates_flatten_script(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        page = MagicMock()
        page.evaluate = AsyncMock(return_value={"path": "BODY", "newHtmlHeight": 2000})

        asyncio.run(flatten_scroll_containers_for_print(page))

        # Ensure our evaluate logic was called
        page.evaluate.assert_called_once()
        args, kwargs = page.evaluate.call_args
        assert "var best =" in args[0]
        assert "cur.style.setProperty('height', 'auto', 'important')" in args[0]

    def test_handles_missing_container(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        page = MagicMock()
        # Simulate script returning string instead of dict
        page.evaluate = AsyncMock(return_value="no container found")

        # Shouldn't raise any exceptions
        asyncio.run(flatten_scroll_containers_for_print(page))
        page.evaluate.assert_called_once()

# --------------------------------------------------------------------------
# hide_ui_elements_for_print()
# --------------------------------------------------------------------------

class TestHideUiElements:
    def test_calls_add_style_tag(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        page = MagicMock()
        page.evaluate = AsyncMock()
        page.add_style_tag = AsyncMock()
        
        asyncio.run(hide_ui_elements_for_print(page))
        page.add_style_tag.assert_called_once()
        page.evaluate.assert_called_once()

    def test_css_contains_display_none(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        page = MagicMock()
        page.evaluate = AsyncMock()
        captured = {}

        async def capture(**kwargs):
            captured.update(kwargs)

        page.add_style_tag = capture
        asyncio.run(hide_ui_elements_for_print(page))
        
        content = captured.get("content", "")
        assert "@media print" in content
        assert "display: none !important" in content
        assert 'data-url-to-pdf-hide="1"' in content


# --------------------------------------------------------------------------
# convert_url_to_pdf() — login detection / post-login safety
# --------------------------------------------------------------------------

class _FakePage:
    def __init__(self, states):
        self.states = states
        self.state_index = 0
        self.pdf_paths = []
        self.url = "https://example.com/login"

    def advance(self):
        if self.state_index < len(self.states) - 1:
            self.state_index += 1
        self.url = f"https://example.com/state-{self.state_index}"

    def _state(self):
        return self.states[self.state_index]

    async def goto(self, *args, **kwargs):
        return None

    async def wait_for_load_state(self, *args, **kwargs):
        return None

    async def evaluate(self, expr, *args):
        if expr == "document.fonts.ready":
            return None
        if expr == "document.body.innerText":
            return self._state()["body"]
        if "const selectors" in expr:
            return len(self._state()["body"]) > 20
        if "bestDiff" in expr:
            return None
        if expr == "document.body.scrollHeight":
            return 800
        if "window.scrollTo" in expr:
            return None
        return None

    async def title(self):
        return self._state()["title"]

    async def add_style_tag(self, **kwargs):
        return None

    async def pdf(self, path, **kwargs):
        self.pdf_paths.append(path)
        with open(path, "wb") as f:
            f.write(b"%PDF-test-content%")

    async def close(self):
        return None


class _FakeContext:
    def __init__(self, page):
        self.page = page
        self.storage_states = [
            {"cookies": [{"name": "sid", "value": "initial"}], "origins": []}
        ]
        self.storage_index = 0

    async def new_page(self):
        return self.page

    async def add_cookies(self, cookies):
        return None

    async def storage_state(self):
        idx = min(self.storage_index, len(self.storage_states) - 1)
        state = self.storage_states[idx]
        self.storage_index += 1
        return state


class _FakeBrowser:
    def __init__(self, context):
        self.context = context

    async def new_context(self, **kwargs):
        return self.context

    async def close(self):
        return None


class _FakePlaywright:
    def __init__(self, browser):
        self.chromium = self
        self._browser = browser

    async def launch(self, **kwargs):
        return self._browser


class _FakeAsyncPlaywrightContext:
    def __init__(self, browser):
        self._playwright = _FakePlaywright(browser)

    async def __aenter__(self):
        return self._playwright

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestConvertUrlToPdfLoginFlow:
    def test_existing_session_still_triggers_login_when_title_is_login_page(self, tmp_path, monkeypatch):
        import asyncio

        session_path = tmp_path / "session.json"
        session_path.write_text('{"cookies": [], "origins": []}')

        page = _FakePage([
            {"title": "登录", "body": "欢迎来到知识库"},
            {"title": "知识库正文", "body": "这是文章正文内容。"},
        ])
        context = _FakeContext(page)
        browser = _FakeBrowser(context)
        login_calls = []

        async def fake_ensure_logged_in(url, headless_context, session_path_arg, prompt_fn=None):
            login_calls.append((url, session_path_arg))
            page.advance()

        monkeypatch.setattr("convert_to_pdf.async_playwright", lambda: _FakeAsyncPlaywrightContext(browser))
        monkeypatch.setattr("convert_to_pdf.ensure_logged_in", fake_ensure_logged_in)
        monkeypatch.setattr("convert_to_pdf.hide_ui_elements_for_print", lambda page: asyncio.sleep(0))
        monkeypatch.setattr("convert_to_pdf.flatten_scroll_containers_for_print", lambda page: asyncio.sleep(0))

        asyncio.run(
            convert_url_to_pdf(
                ["https://example.com/private"],
                str(tmp_path / "out"),
                wait_after_load=0,
                session_path=str(session_path),
            )
        )

        assert len(login_calls) == 1
        assert len(page.pdf_paths) == 1
        assert os.path.exists(page.pdf_paths[0])
        assert os.path.basename(page.pdf_paths[0]) == "知识库正文.pdf"

    def test_raises_when_page_is_still_login_screen_after_interactive_login(self, tmp_path, monkeypatch):
        import asyncio

        session_path = tmp_path / "session.json"
        session_path.write_text('{"cookies": [], "origins": []}')

        page = _FakePage([
            {"title": "登录", "body": "请输入手机号和验证码继续登录"},
            {"title": "登录", "body": "请输入手机号和验证码继续登录"},
        ])
        context = _FakeContext(page)
        browser = _FakeBrowser(context)
        login_calls = []

        async def fake_ensure_logged_in(url, headless_context, session_path_arg, prompt_fn=None):
            login_calls.append((url, session_path_arg))
            page.advance()

        monkeypatch.setattr("convert_to_pdf.async_playwright", lambda: _FakeAsyncPlaywrightContext(browser))
        monkeypatch.setattr("convert_to_pdf.ensure_logged_in", fake_ensure_logged_in)
        monkeypatch.setattr("convert_to_pdf.hide_ui_elements_for_print", lambda page: asyncio.sleep(0))
        monkeypatch.setattr("convert_to_pdf.flatten_scroll_containers_for_print", lambda page: asyncio.sleep(0))

        asyncio.run(
            convert_url_to_pdf(
                ["https://example.com/private"],
                str(tmp_path / "out"),
                wait_after_load=0,
                session_path=str(session_path),
            )
        )

        assert len(login_calls) == 1
        assert page.pdf_paths == []
        out_dir = tmp_path / "out"
        generated_pdfs = list(out_dir.rglob("*.pdf"))
        assert generated_pdfs == []

    def test_non_interactive_terminal_can_still_complete_bootstrap_login(self, tmp_path, monkeypatch):
        import asyncio

        session_path = tmp_path / "session.json"
        session_path.write_text('{"cookies": [], "origins": []}')

        page = _FakePage([
            {"title": "登录", "body": "请输入手机号和验证码继续登录"},
        ])
        context = _FakeContext(page)
        context.storage_states = [
            {"cookies": [{"name": "sid", "value": "initial"}], "origins": []},
            {"cookies": [{"name": "sid", "value": "fresh"}], "origins": []},
            {"cookies": [{"name": "sid", "value": "fresher"}], "origins": []},
        ]
        browser = _FakeBrowser(context)

        monkeypatch.setattr("convert_to_pdf.async_playwright", lambda: _FakeAsyncPlaywrightContext(browser))

        async def fake_wait_for_login_completion(page_arg, context_arg):
            page.states.append({"title": "知识库正文", "body": "这是文章正文内容。"})
            page.advance()
            return {"cookies": [{"name": "sid", "value": "abc"}], "origins": []}

        monkeypatch.setattr("convert_to_pdf.wait_for_login_completion", fake_wait_for_login_completion)
        monkeypatch.setattr("convert_to_pdf.hide_ui_elements_for_print", lambda page: asyncio.sleep(0))
        monkeypatch.setattr("convert_to_pdf.flatten_scroll_containers_for_print", lambda page: asyncio.sleep(0))
        monkeypatch.setattr("convert_to_pdf.scroll_to_trigger_lazy_load", lambda page: asyncio.sleep(0))

        asyncio.run(
            convert_url_to_pdf(
                ["https://example.com/private"],
                str(tmp_path / "out"),
                wait_after_load=0,
                session_path=str(session_path),
            )
        )

        assert len(page.pdf_paths) == 1


class TestWaitForLoginCompletion:
    def test_requires_cookie_change_before_success(self):
        import asyncio
        from types import SimpleNamespace

        class FakePage:
            def __init__(self):
                self.url = "https://example.com/auth"

            async def title(self):
                return "知识库正文"

            async def evaluate(self, expr, *args):
                if expr == "document.body.innerText":
                    return "这是一个足够长的正文内容" * 30
                if "const selectors" in expr:
                    return True
                return None

        class FakeContext:
            def __init__(self):
                self.states = [
                    {"cookies": [{"name": "sid", "domain": "example.com", "path": "/", "value": "same"}], "origins": []},
                    {"cookies": [{"name": "sid", "domain": "example.com", "path": "/", "value": "same"}], "origins": []},
                    {"cookies": [{"name": "sid", "domain": "example.com", "path": "/", "value": "new"}], "origins": []},
                    {"cookies": [{"name": "sid", "domain": "example.com", "path": "/", "value": "newer"}], "origins": []},
                ]
                self.idx = 0

            async def storage_state(self):
                state = self.states[min(self.idx, len(self.states) - 1)]
                self.idx += 1
                return state

        async def run_case():
            from convert_to_pdf import wait_for_login_completion

            page = FakePage()
            context = FakeContext()
            return await wait_for_login_completion(
                page,
                context,
                timeout_seconds=5,
                poll_interval=0,
                min_visible_seconds=0,
                stable_passes_required=1,
            )

        result = asyncio.run(run_case())
        assert result["cookies"][0]["value"] == "new"
