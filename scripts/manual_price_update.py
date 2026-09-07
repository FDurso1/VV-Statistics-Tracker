
"""
Update the prices daily
"""

import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "mtg_data.db"
DB_ZIP_PATH = ROOT / "data" / "mtg_data.db.zip"

def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=ROOT, check=True)

def main():
    print("Running price update...\n")
    run([sys.executable, str(ROOT / "scripts" / "update_prices.py")])

    print("\nCompressing database...")
    with zipfile.ZipFile(DB_ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.write(DB_PATH, arcname=DB_PATH.name)

    print("Checking for changes to commit...")
    run(["git", "add", str(DB_ZIP_PATH.relative_to(ROOT))])

    # Non-fatal check: does staging data/mtg_data.db.zip actually change anything?
    # `git diff --staged --quiet` exits 0 if there's no difference, 1 if there is.
    diff_result = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=ROOT)
    if diff_result.returncode == 0:
        print("No price changes to commit -- nothing to push. All done.")
        return

    run(["git", "commit", "-m", "Manual card price update"])
    run(["git", "push"])
    print("\nDone -- pushed updated prices. Render will redeploy automatically.")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\nSomething went wrong running: {' '.join(e.cmd)}")
        print(
            "Check the output above for details. Common causes: git isn't "
            "configured (user.name/user.email), there's no remote set, or "
            "there's a merge conflict that needs resolving by hand."
        )
        sys.exit(1)
