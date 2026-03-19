import os
import sys
import shutil
import subprocess
import json
from pathlib import Path


def recommended_install_steps():
    """Return a stable first-run setup sequence for Python Playwright."""
    return [
        "python3 -m venv .venv",
        "source .venv/bin/activate",
        "python -m pip install -U pip",
        "python -m pip install playwright",
        "python -m playwright install chromium",
    ]

def check_command(cmd):
    """Checks if a command exists in PATH."""
    return shutil.which(cmd) is not None

def check_playwright():
    """Verifies playwright package and chromium browser."""
    try:
        import playwright
        # Check if chromium is installed by running the help command via python module
        # This is more reliable than checking PATH for 'playwright'
        try:
            res = subprocess.run([sys.executable, "-m", "playwright", "install", "--help"], capture_output=True, text=True)
            if res.returncode == 0:
                return "ok"
            else:
                return "package_only"
        except FileNotFoundError:
            return "package_only"
    except ImportError:
        return "missing"

def get_diagnostics():
    """Returns environment status for local tooling and NotebookLM upload auth."""
    pw_status = check_playwright()
    python_version = sys.version.split()[0]
    python_info = sys.version_info
    diagnostics = {
        "uv": check_command("uv") or check_command(str(Path.home() / ".local/bin/uv")),
        "playwright": pw_status == "ok",
        "playwright_package": pw_status != "missing",
        "nlm": check_command("nlm") or check_command(str(Path.home() / ".local/bin/nlm")),
        "python_version": python_version,
        "python_executable": sys.executable,
        "python_supported": python_info >= (3, 9),
        "interactive_terminal": bool(sys.stdin.isatty() and sys.stdout.isatty()),
        "auth_scope": "notebooklm_upload_only",
        "recommended_install_steps": recommended_install_steps(),
        "is_ready": False
    }
    
    # Check if we can run nlm login --check
    if diagnostics["nlm"]:
        try:
            nlm_bin = shutil.which("nlm") or str(Path.home() / ".local/bin/nlm")
            res = subprocess.run([nlm_bin, "login", "--check"], capture_output=True, text=True)
            diagnostics["auth_valid"] = (res.returncode == 0)
        except:
            diagnostics["auth_valid"] = False
    else:
        diagnostics["auth_valid"] = False

    # Backward-compatible key plus explicit alias so callers do not confuse this
    # with the login state of arbitrary target websites being rendered to PDF.
    diagnostics["nlm_auth_valid"] = diagnostics["auth_valid"]

    # Final readiness
    diagnostics["is_ready"] = (diagnostics["uv"] and diagnostics["nlm"] and diagnostics["auth_valid"] and diagnostics["playwright"])
    
    return diagnostics

def main():
    if "--json" in sys.argv:
        print(json.dumps(get_diagnostics(), indent=2))
        return

    diag = get_diagnostics()
    print("🏥 url-to-pdf Diagnostic Report")
    print(f"-------------------------------")
    print(f"Python:     {diag['python_version']}")
    print(f"Python Bin: {diag['python_executable']}")
    print(f"uv:         {'✅' if diag['uv'] else '❌ (Required for portable installs)'}")
    print(f"Playwright: {'✅' if diag['playwright'] else '⚠️ (Needed for conversion)'}")
    print(f"NLM CLI:    {'✅' if diag['nlm'] else '❌ (Needed for upload)'}")
    print(f"NLM Auth:   {'✅' if diag['auth_valid'] else '❌ (Run nlm login)'}")
    print("            (Only affects NotebookLM upload, not target website login state)")
    print(f"TTY:        {'✅' if diag['interactive_terminal'] else '⚠️ (Non-interactive runs cannot complete login bootstrap)'}")
    print(f"-------------------------------")

    if diag["is_ready"]:
        print("🚀 System is ready for use!")
    else:
        print("🛠️  Action Required:")
        if not diag["python_supported"]:
            print("   - Use Python 3.9+ for the smoothest Playwright setup.")
        if not diag["playwright_package"] or not diag["playwright"]:
            print("   - Recommended first-run setup:")
            for step in diag["recommended_install_steps"]:
                print(f"     {step}")
        if not diag["uv"]:
            print("   - Run: curl -LsSf https://astral.sh/uv/install.sh | sh")
        if not diag["nlm"]:
            print("   - Run: uv tool install notebooklm-mcp-cli")
        if not diag["auth_valid"] and diag["nlm"]:
            print("   - Run: nlm login")
        if not diag["interactive_terminal"]:
            print("   - Use an interactive terminal when a site may require browser login bootstrap.")

if __name__ == "__main__":
    main()
