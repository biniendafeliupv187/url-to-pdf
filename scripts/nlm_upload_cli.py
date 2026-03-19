import os
import sys
import subprocess
import shutil
from pathlib import Path

def create_notebook(nlm_path):
    """Creates a new notebook and returns its ID."""
    from datetime import datetime
    title = f"PDF Uploads - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    print(f"🆕 Creating new notebook: '{title}'...")
    try:
        cmd = [nlm_path, "notebook", "create", title]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # The output usually contains the new ID. Let's try to extract it.
            # Output format often: "Created notebook: [Title] (ID: [ID])"
            import re
            match = re.search(r"ID: ([a-f0-9-]+)", result.stdout)
            if match:
                new_id = match.group(1)
                print(f"   ✅ Created! ID: {new_id}")
                return new_id
            else:
                print(f"   ⚠️ Created, but couldn't parse ID. Output: {result.stdout.strip()}")
                return None
        else:
            print(f"   ❌ Failed to create notebook: {result.stderr.strip()}")
            return None
    except Exception as e:
        print(f"   ❌ Error during creation: {str(e)}")
        return None

def upload_pdfs(directory_path, notebook_id_or_url):
    """
    Upload all PDFs in a directory to a NotebookLM notebook using the 'nlm' CLI.
    """
    directory = Path(directory_path)
    if not directory.is_dir():
        print(f"❌ Error: {directory_path} is not a directory.")
        return

    pdf_files = list(directory.glob("*.pdf"))
    if not pdf_files:
        print(f"ℹ️ No PDF files found in {directory_path}.")
        return

    # Path to the nlm executable (dynamic detection)
    nlm_path = shutil.which("nlm") or str(Path.home() / ".local/bin/nlm")
    
    if not Path(nlm_path).exists() and not shutil.which("nlm"):
        print(f"❌ Error: 'nlm' CLI not found. Please run 'uv tool install notebooklm-mcp-cli'.")
        return

    # Handle automatic creation if requested
    if notebook_id_or_url == "CREATE_NEW":
        new_id = create_notebook(nlm_path)
        if not new_id:
            print("❌ Aborting upload due to notebook creation failure.")
            return
        notebook_id_or_url = new_id

    print(f"🚀 Found {len(pdf_files)} PDF(s) to upload.")
    
    for i, pdf_file in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] 📤 Uploading: {pdf_file.name}...")
        
        try:
            # Command: nlm source add [notebook] --file [path] --wait
            # Note: The 'nlm' command from notebooklm-mcp-cli v0.2.0+ handles uploads via HTTP.
            cmd = [
                nlm_path, 
                "source", "add", 
                notebook_id_or_url, 
                "--file", str(pdf_file),
                "--wait"
            ]
            
            # Run the command and capture output
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"   ✅ Success!")
            else:
                print(f"   ❌ Failed: {result.stderr.strip()}")
                if "Authentication failed" in result.stderr:
                    print("\n🚨 AUTHENTICATION REQUIRED: Please run 'nlm login' in your terminal.")
                    break
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")

    print("\n✨ Upload cycle finished.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 nlm_upload_cli.py <directory> <notebook_id_or_url>")
        sys.exit(1)
        
    upload_pdfs(sys.argv[1], sys.argv[2])
