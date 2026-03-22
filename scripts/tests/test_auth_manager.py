import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth_manager


class TestAuthManagerHelpers:
    def test_attempt_paths_follow_site_profile_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth_manager, "LATEST_AUTH_ATTEMPT_PATH", str(tmp_path / "latest.json"))
        monkeypatch.setattr(auth_manager, "resolve_auth_paths", lambda url, session_path=None: {
            "profile_dir": str(tmp_path / "profiles" / "time.geekbang.org"),
            "session_path": str(tmp_path / "profiles" / "time.geekbang.org" / "storage_state.json"),
            "browser_profile_dir": str(tmp_path / "profiles" / "time.geekbang.org" / "browser_profile"),
        })

        paths = auth_manager.attempt_paths_for_url("https://time.geekbang.org/column/article/1")

        assert paths["attempt_path"].endswith("profiles/time.geekbang.org/auth_attempt.json")
        assert paths["close_request_path"].endswith("profiles/time.geekbang.org/close_requested.flag")

    def test_resolve_auth_context_can_use_latest_attempt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth_manager, "LATEST_AUTH_ATTEMPT_PATH", str(tmp_path / "latest.json"))
        monkeypatch.setattr(
            auth_manager,
            "load_latest_auth_attempt",
            lambda: {
                "url": "https://example.com/article",
                "session_path": str(tmp_path / "storage_state.json"),
            },
        )
        monkeypatch.setattr(auth_manager, "attempt_paths_for_url", lambda url, session_path_arg=None: {
            "attempt_path": str(tmp_path / "auth_attempt.json"),
            "close_request_path": str(tmp_path / "close.flag"),
            "session_path": str(tmp_path / "storage_state.json"),
            "profile_dir": str(tmp_path),
            "browser_profile_dir": str(tmp_path / "browser_profile"),
        })

        resolved_url, paths = auth_manager.resolve_auth_context(None)

        assert resolved_url == "https://example.com/article"
        assert paths["session_path"].endswith("storage_state.json")

    def test_confirm_auth_marks_success_and_requests_close(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth_manager, "LATEST_AUTH_ATTEMPT_PATH", str(tmp_path / "latest.json"))
        session_path = tmp_path / "storage_state.json"
        attempt_path = tmp_path / "auth_attempt.json"
        close_path = tmp_path / "close.flag"

        monkeypatch.setattr(auth_manager, "attempt_paths_for_url", lambda url, session_path_arg=None: {
            "attempt_path": str(attempt_path),
            "close_request_path": str(close_path),
            "session_path": str(session_path),
            "profile_dir": str(tmp_path),
            "browser_profile_dir": str(tmp_path / "browser_profile"),
        })

        async def fake_validate(url, session_path_arg, wait_after_load=3):
            return {"ok": True, "reason": "", "login_page": False, "content_signal": True}

        monkeypatch.setattr(auth_manager, "validate_saved_session_for_url", fake_validate)
        auth_manager.save_auth_attempt(str(attempt_path), {"status": "waiting_for_user_confirmation"})

        result = auth_manager.confirm_auth("https://example.com/article")

        assert result["ok"] is True
        assert close_path.exists()
        payload = auth_manager.load_auth_attempt(str(attempt_path))
        assert payload["status"] == "confirmed"

    def test_confirm_auth_without_url_uses_latest_attempt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth_manager, "LATEST_AUTH_ATTEMPT_PATH", str(tmp_path / "latest.json"))
        session_path = tmp_path / "storage_state.json"
        attempt_path = tmp_path / "auth_attempt.json"
        close_path = tmp_path / "close.flag"

        monkeypatch.setattr(
            auth_manager,
            "load_latest_auth_attempt",
            lambda: {"url": "https://example.com/article", "session_path": str(session_path)},
        )
        monkeypatch.setattr(auth_manager, "attempt_paths_for_url", lambda url, session_path_arg=None: {
            "attempt_path": str(attempt_path),
            "close_request_path": str(close_path),
            "session_path": str(session_path),
            "profile_dir": str(tmp_path),
            "browser_profile_dir": str(tmp_path / "browser_profile"),
        })

        async def fake_validate(url, session_path_arg, wait_after_load=3):
            assert url == "https://example.com/article"
            return {"ok": True, "reason": "", "login_page": False, "content_signal": True}

        monkeypatch.setattr(auth_manager, "validate_saved_session_for_url", fake_validate)
        auth_manager.save_auth_attempt(str(attempt_path), {"status": "waiting_for_user_confirmation"})

        result = auth_manager.confirm_auth()

        assert result["ok"] is True
        assert close_path.exists()

    def test_confirm_auth_keeps_browser_open_when_validation_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(auth_manager, "LATEST_AUTH_ATTEMPT_PATH", str(tmp_path / "latest.json"))
        session_path = tmp_path / "storage_state.json"
        attempt_path = tmp_path / "auth_attempt.json"
        close_path = tmp_path / "close.flag"

        monkeypatch.setattr(auth_manager, "attempt_paths_for_url", lambda url, session_path_arg=None: {
            "attempt_path": str(attempt_path),
            "close_request_path": str(close_path),
            "session_path": str(session_path),
            "profile_dir": str(tmp_path),
            "browser_profile_dir": str(tmp_path / "browser_profile"),
        })

        async def fake_validate(url, session_path_arg, wait_after_load=3):
            return {"ok": False, "reason": "Still on login page", "login_page": True, "content_signal": False}

        monkeypatch.setattr(auth_manager, "validate_saved_session_for_url", fake_validate)
        auth_manager.save_auth_attempt(str(attempt_path), {"status": "waiting_for_user_confirmation"})

        result = auth_manager.confirm_auth("https://example.com/article")

        assert result["ok"] is False
        assert not close_path.exists()
        payload = auth_manager.load_auth_attempt(str(attempt_path))
        assert payload["status"] == "awaiting_user_confirmation"
