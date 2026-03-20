#!/usr/bin/env python3
"""
Unified runner for url-to-pdf skill scripts.

This wrapper keeps first-run setup deterministic:
- create `.venv` inside the skill folder if missing
- install the Python Playwright package into that venv if missing
- install the Playwright Chromium browser if missing
- execute the requested script inside the venv
"""

import os
import subprocess
import sys
from pathlib import Path


def get_skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def get_venv_dir() -> Path:
    return get_skill_dir() / ".venv"


def get_venv_python() -> Path:
    venv_dir = get_venv_dir()
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def normalize_script_name(script_name: str) -> str:
    if script_name.startswith("scripts/"):
        script_name = script_name[len("scripts/"):]
    if not script_name.endswith(".py"):
        script_name += ".py"
    return script_name


def run_checked(cmd) -> None:
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(map(str, cmd))}")


def ensure_venv() -> Path:
    venv_dir = get_venv_dir()
    venv_python = get_venv_python()
    if not venv_python.exists():
        print("🔧 First-time setup: creating isolated Python environment...")
        run_checked([sys.executable, "-m", "venv", str(venv_dir)])
    return venv_python


def venv_has_playwright(venv_python: Path) -> bool:
    result = subprocess.run(
        [str(venv_python), "-c", "import playwright"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def ensure_playwright_package(venv_python: Path) -> None:
    if venv_has_playwright(venv_python):
        return
    print("📦 Installing Playwright Python package into .venv...")
    run_checked([str(venv_python), "-m", "pip", "install", "-U", "pip"])
    run_checked([str(venv_python), "-m", "pip", "install", "playwright"])


def ensure_playwright_browser(venv_python: Path) -> None:
    print("🌐 Ensuring Playwright Chromium browser is installed...")
    run_checked([str(venv_python), "-m", "playwright", "install", "chromium"])


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/run.py <script_name> [args...]")
        print("\nExamples:")
        print("  python3 scripts/run.py doctor.py --json")
        print("  python3 scripts/run.py convert_to_pdf.py https://example.com")
        print("  python3 scripts/run.py bootstrap_login.py https://example.com/login")
        print("  python3 scripts/run.py auth_manager.py begin https://example.com/login")
        sys.exit(1)

    script_name = normalize_script_name(sys.argv[1])
    script_args = sys.argv[2:]
    script_path = get_skill_dir() / "scripts" / script_name

    if not script_path.exists():
        print(f"❌ Script not found: {script_name}")
        print(f"Looked for: {script_path}")
        sys.exit(1)

    try:
        venv_python = ensure_venv()
        ensure_playwright_package(venv_python)
        ensure_playwright_browser(venv_python)
        result = subprocess.run([str(venv_python), str(script_path), *script_args])
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
        sys.exit(130)
    except Exception as exc:
        print(f"❌ {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
