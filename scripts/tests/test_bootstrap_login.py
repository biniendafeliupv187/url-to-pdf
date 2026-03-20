import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bootstrap_login


class _FakePage:
    def __init__(self):
        self.url = "https://example.com/login"
        self.goto_calls = []

    async def goto(self, url, timeout=0):
        self.goto_calls.append((url, timeout))


class _FakeContext:
    def __init__(self, page):
        self.pages = [page]
        self.closed = False

    async def new_page(self):
        return self.pages[0]

    async def close(self):
        self.closed = True


class _FakePlaywright:
    def __init__(self, context):
        self.chromium = self
        self._context = context
        self.launch_kwargs = None

    async def launch_persistent_context(self, **kwargs):
        self.launch_kwargs = kwargs
        return self._context


class _FakeAsyncPlaywrightContext:
    def __init__(self, playwright):
        self._playwright = playwright

    async def __aenter__(self):
        return self._playwright

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestBootstrapLogin:
    def test_bootstrap_login_uses_persistent_profile_and_saves_session(self, monkeypatch, tmp_path):
        page = _FakePage()
        context = _FakeContext(page)
        playwright = _FakePlaywright(context)
        saved = {}

        monkeypatch.setattr(
            bootstrap_login,
            "resolve_auth_paths",
            lambda url, session_path=None: {
                "profile_dir": str(tmp_path / "profiles" / "example.com"),
                "session_path": str(tmp_path / "profiles" / "example.com" / "storage_state.json"),
                "browser_profile_dir": str(tmp_path / "profiles" / "example.com" / "browser_profile"),
            },
        )
        monkeypatch.setattr(
            bootstrap_login,
            "async_playwright",
            lambda: _FakeAsyncPlaywrightContext(playwright),
        )

        async def fake_wait_for_login_completion(page_arg, context_arg, url_arg):
            assert page_arg is page
            assert context_arg is context
            assert url_arg == "https://example.com/private"
            return {"cookies": [{"name": "sid", "value": "abc"}], "origins": []}

        monkeypatch.setattr(bootstrap_login, "wait_for_login_completion", fake_wait_for_login_completion)
        monkeypatch.setattr(
            bootstrap_login,
            "save_session",
            lambda storage, path: saved.update({"storage": storage, "path": path}),
        )

        asyncio.run(bootstrap_login.bootstrap_login("https://example.com/private"))

        assert playwright.launch_kwargs["headless"] is False
        assert playwright.launch_kwargs["user_data_dir"].endswith("/browser_profile")
        assert page.goto_calls == [("https://example.com/private", 60000)]
        assert saved["path"].endswith("/storage_state.json")
        assert saved["storage"]["cookies"][0]["value"] == "abc"
        assert context.closed is True
