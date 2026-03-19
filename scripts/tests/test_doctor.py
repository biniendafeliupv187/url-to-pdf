import sys


sys.path.insert(0, "/Users/majianming/.codex/skills/url-to-pdf/scripts")

import doctor


class TestGetDiagnostics:
    def test_exposes_explicit_nlm_auth_scope(self, monkeypatch):
        monkeypatch.setattr(doctor, "check_playwright", lambda: "ok")
        monkeypatch.setattr(doctor, "check_command", lambda cmd: True)

        def fake_run(*args, **kwargs):
            class Result:
                returncode = 0
            return Result()

        monkeypatch.setattr(doctor.subprocess, "run", fake_run)

        diagnostics = doctor.get_diagnostics()

        assert diagnostics["auth_scope"] == "notebooklm_upload_only"
        assert diagnostics["nlm_auth_valid"] is True
        assert diagnostics["auth_valid"] is True


class TestMainOutput:
    def test_human_output_clarifies_auth_scope(self, monkeypatch, capsys):
        monkeypatch.setattr(
            doctor,
            "get_diagnostics",
            lambda: {
                "uv": True,
                "playwright": True,
                "playwright_package": True,
                "nlm": True,
                "python_version": "3.9.6",
                "auth_scope": "notebooklm_upload_only",
                "auth_valid": False,
                "nlm_auth_valid": False,
                "is_ready": False,
            },
        )
        monkeypatch.setattr(sys, "argv", ["doctor.py"])

        doctor.main()
        output = capsys.readouterr().out

        assert "Only affects NotebookLM upload" in output
        assert "not target website login state" in output
