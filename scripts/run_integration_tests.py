"""Cross-platform runner with unique, project-local test artifacts."""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--graphical", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
artifacts = root / ".artifacts"
artifacts.mkdir(exist_ok=True)
command = [
    sys.executable,
    "-m",
    "pytest",
    "--engine",
    "--basetemp",
    str(artifacts / datetime.now().strftime("test-%Y%m%d-%H%M%S")),
    "-q",
]
if args.graphical:
    command.append("--graphical")
raise SystemExit(subprocess.call(command, cwd=root))
