import os
import sys
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run


class TestNormalizeScriptName:
    def test_adds_py_extension(self):
        assert run.normalize_script_name("doctor") == "doctor.py"

    def test_strips_scripts_prefix(self):
        assert run.normalize_script_name("scripts/convert_to_pdf.py") == "convert_to_pdf.py"


class TestMainFlow:
    def test_main_runs_target_script_via_venv_python(self, monkeypatch, tmp_path):
        skill_dir = tmp_path
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        target_script = scripts_dir / "doctor.py"
        target_script.write_text("print('ok')")

        called = []

        monkeypatch.setattr(run, "get_skill_dir", lambda: skill_dir)
        monkeypatch.setattr(run, "ensure_venv", lambda: Path("/tmp/fake-venv-python"))
        monkeypatch.setattr(run, "ensure_playwright_package", lambda python: called.append(("pkg", str(python))))
        monkeypatch.setattr(run, "ensure_playwright_browser", lambda python: called.append(("browser", str(python))))

        class Result:
            returncode = 0

        monkeypatch.setattr(run.subprocess, "run", lambda cmd: called.append(("exec", cmd)) or Result())
        monkeypatch.setattr(sys, "argv", ["run.py", "doctor.py", "--json"])

        try:
            run.main()
        except SystemExit as exc:
            assert exc.code == 0

        assert called[0] == ("pkg", "/tmp/fake-venv-python")
        assert called[1] == ("browser", "/tmp/fake-venv-python")
        assert called[2][0] == "exec"
        assert called[2][1][0] == "/tmp/fake-venv-python"
        assert called[2][1][-1] == "--json"
