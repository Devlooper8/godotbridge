import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.engine


def test_documented_cli_workflow(editor):
    doctor = subprocess.run(
        [
            sys.executable,
            "-m",
            "godotbridge.cli",
            "--project",
            str(editor.config.project),
            "doctor",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert doctor.returncode == 0, doctor.stdout
    assert "scene.tree" in json.loads(doctor.stdout)["capabilities"]
    document = Path(__file__).resolve().parents[2] / "examples/cli-arena.md"
    for line in document.read_text(encoding="utf-8").splitlines():
        if not line.startswith("godotctl "):
            continue
        args = shlex.split(line)[3:]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "godotbridge.cli",
                "--project",
                str(editor.config.project),
                "--json",
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (line, result.stdout, result.stderr)
        assert json.loads(result.stdout)["ok"], line
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "godotbridge.cli",
            "--project",
            str(editor.config.project),
            "node",
            "position",
            "ObstacleA",
            "-2",
            "1",
            "3",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["result"]["position"]["value"] == [-2, 1, 3]


def test_documented_python_workflow(editor, request):
    script = Path(__file__).resolve().parents[2] / "examples/build_arena.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--project",
            str(editor.config.project),
            "--scene",
            "res://scenes/python-demo.tscn",
            "--output-dir",
            "snapshots/python-demo",
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["node_count"] == 28
    assert report["validation"]["valid"]
    expected = "complete" if request.config.getoption("--graphical") else "partial"
    assert report["snapshot"]["status"] == expected
