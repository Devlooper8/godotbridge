"""Convenience wrapper; installed users can run godotctl project install-plugin."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from godotbridge.config import Config
from godotbridge.install import install

parser = argparse.ArgumentParser()
parser.add_argument("project", type=Path)
parser.add_argument("--replace", action="store_true")
args = parser.parse_args()
print(install(Config.load(args.project), replace=args.replace))
