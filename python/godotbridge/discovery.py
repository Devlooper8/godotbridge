"""Discover actual executables, never shell wrappers; probe their real versions."""

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import BridgeError


@dataclass(frozen=True)
class Godot:
    executable: Path
    version: str


def _bundle(path: Path) -> Path:
    return path / "Contents/MacOS/Godot" if path.suffix.lower() == ".app" else path


def discover(explicit: str | None = None) -> Godot:
    chosen = explicit or os.getenv("GODOT_EXECUTABLE")
    candidates: list[Path] = []
    if chosen:
        candidates = [_bundle(Path(chosen).expanduser())]
    else:
        for name in ("godot", "godot4", "godot-mono", "Godot"):
            resolved = shutil.which(name)
            if resolved:
                candidates.append(Path(resolved))
        for entry in os.get_exec_path():
            path = Path(entry)
            if path.is_dir():
                candidates.extend(path.glob("Godot*.exe"))
                candidates.extend(path.glob("godot*.exe"))
        if sys.platform == "darwin":
            candidates.extend(
                _bundle(p)
                for base in (Path("/Applications"), Path.home() / "Applications")
                for p in base.glob("*Godot*.app")
            )
        if os.name == "nt":
            for base in (
                Path(os.getenv("LOCALAPPDATA", "~")) / "Programs",
                Path.home() / "scoop/apps/godot/current",
            ):
                candidates.extend(base.glob("*Godot*/*.exe"))
    found = []
    for path in dict.fromkeys(candidates):
        if not path.is_file() or path.suffix.lower() in {".cmd", ".bat"}:
            continue
        try:
            proc = subprocess.run(
                [str(path), "--version"], capture_output=True, text=True, timeout=8, check=False
            )
            version = proc.stdout.strip()
            match = re.match(r"4\.(\d+)\.(\d+)\.stable", version)
            if proc.returncode == 0 and match and int(match[1]) >= 7:
                found.append(
                    (
                        (int(match[1]), int(match[2]), "console" in path.name),
                        Godot(path.resolve(), version),
                    )
                )
        except (OSError, subprocess.TimeoutExpired):
            continue
    if not found:
        raise BridgeError(
            "GODOT_NOT_FOUND",
            "Godot 4.7+ stable not found. Set GODOT_EXECUTABLE to the executable (or macOS .app).",
        )
    return max(found, key=lambda item: item[0])[1]
