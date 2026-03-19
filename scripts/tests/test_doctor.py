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

    def test_includes_recommended_install_steps_and_terminal_flags(self, monkeypatch):
        monkeypatch.setattr(doctor, "check_playwright", lambda: "missing")
        monkeypatch.setattr(doctor, "check_command", lambda cmd: False)
        monkeypatch.setattr(doctor.sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(doctor.sys.stdout, "isatty", lambda: False)

        diagnostics = doctor.get_diagnostics()

        assert diagnostics["interactive_terminal"] is False
        assert diagnostics["recommended_install_steps"][0] == "python3 -m venv .venv"
        assert "python -m playwright install chromium" in diagnostics["recommended_install_steps"]


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
                "python_executable": "/usr/bin/python3",
                "python_supported": True,
                "interactive_terminal": False,
                "auth_scope": "notebooklm_upload_only",
                "auth_valid": False,
                "nlm_auth_valid": False,
                "recommended_install_steps": [
                    "python3 -m venv .venv",
                    "source .venv/bin/activate",
                    "python -m pip install -U pip",
                    "python -m pip install playwright",
                    "python -m playwright install chromium",
                ],
                "is_ready": False,
            },
        )
        monkeypatch.setattr(sys, "argv", ["doctor.py"])

        doctor.main()
        output = capsys.readouterr().out

        assert "Only affects NotebookLM upload" in output
        assert "not target website login state" in output
        assert "interactive terminal" in output
        assert "Run: nlm login" in output
        assert "interactive terminal" in output
