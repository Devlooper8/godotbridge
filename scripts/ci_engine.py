"""Download the pinned official engine for the CI platform into the workspace."""

import os
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "4.7.2-stable"
suffix = {"win32": "win64.exe", "linux": "linux.x86_64", "darwin": "macos.universal"}[sys.platform]
root = Path(__file__).resolve().parents[1] / ".artifacts/engine"
root.mkdir(parents=True, exist_ok=True)
archive = root / "godot.zip"
url = f"https://github.com/godotengine/godot-builds/releases/download/{VERSION}/Godot_v{VERSION}_{suffix}.zip"
urllib.request.urlretrieve(url, archive)
with zipfile.ZipFile(archive) as package:
    package.extractall(root)
if sys.platform == "darwin":
    executable = root / "Godot.app/Contents/MacOS/Godot"
elif sys.platform == "win32":
    executable = root / f"Godot_v{VERSION}_win64.exe"
else:
    executable = root / f"Godot_v{VERSION}_linux.x86_64"
executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as stream:
    stream.write(f"GODOT_EXECUTABLE={executable}\n")
print(f"Installed official Godot at {executable}")
