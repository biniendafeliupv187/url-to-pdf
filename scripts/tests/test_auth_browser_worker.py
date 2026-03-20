import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth_browser_worker


class _FakePage:
    def __init__(self):
        self.url = "https://example.com/private"
        self.goto_calls = []

    async def goto(self, url, timeout=0):
        self.goto_calls.append((url, timeout))

    async def title(self):
        return "正文页"


class _FakeContext:
    def __init__(self, page):
        self.pages = [page]
        self.closed = False
        self.storage_calls = 0

    async def new_page(self):
        return self.pages[0]

    async def storage_state(self):
        self.storage_calls += 1
        return {"cookies": [{"name": "sid", "value": f"v{self.storage_calls}"}], "origins": []}

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


class TestAuthBrowserWorker:
    def test_worker_refreshes_session_until_close_requested(self, monkeypatch, tmp_path):
        page = _FakePage()
        context = _FakeContext(page)
        playwright = _FakePlaywright(context)
        attempt_store = {}
        saved_sessions = []
        close_checks = iter([False, True])

        monkeypatch.setattr(
            auth_browser_worker,
            "resolve_auth_paths",
            lambda url, session_path=None: {
                "profile_dir": str(tmp_path / "profiles" / "example.com"),
                "session_path": str(tmp_path / "profiles" / "example.com" / "storage_state.json"),
                "browser_profile_dir": str(tmp_path / "profiles" / "example.com" / "browser_profile"),
            },
        )
        monkeypatch.setattr(
            auth_browser_worker,
            "attempt_paths_for_url",
            lambda url, session_path=None: {
                "attempt_path": str(tmp_path / "profiles" / "example.com" / "auth_attempt.json"),
                "close_request_path": str(tmp_path / "profiles" / "example.com" / "close_requested.flag"),
                "session_path": str(tmp_path / "profiles" / "example.com" / "storage_state.json"),
                "profile_dir": str(tmp_path / "profiles" / "example.com"),
                "browser_profile_dir": str(tmp_path / "profiles" / "example.com" / "browser_profile"),
            },
        )
        monkeypatch.setattr(
            auth_browser_worker,
            "async_playwright",
            lambda: _FakeAsyncPlaywrightContext(playwright),
        )
        monkeypatch.setattr(
            auth_browser_worker,
            "save_auth_attempt",
            lambda path, payload: attempt_store.update(payload),
        )
        monkeypatch.setattr(
            auth_browser_worker,
            "load_auth_attempt",
            lambda path: dict(attempt_store),
        )
        monkeypatch.setattr(
            auth_browser_worker,
            "save_session",
            lambda storage, path: saved_sessions.append((storage, path)),
        )
        monkeypatch.setattr(
            auth_browser_worker,
            "close_request_exists",
            lambda path: next(close_checks),
        )

        async def fake_sleep(seconds):
            return None

        monkeypatch.setattr(auth_browser_worker.asyncio, "sleep", fake_sleep)

        asyncio.run(auth_browser_worker.run_auth_browser_worker("https://example.com/private"))

        assert playwright.launch_kwargs["headless"] is False
        assert playwright.launch_kwargs["user_data_dir"].endswith("/browser_profile")
        assert page.goto_calls == [("https://example.com/private", 60000)]
        assert saved_sessions[0][0]["cookies"][0]["value"] == "v1"
        assert attempt_store["status"] == "closed"
        assert context.closed is True
