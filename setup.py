"""Bundle the canonical addon in wheels without maintaining a second source copy."""

from pathlib import Path
from shutil import copytree, ignore_patterns

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithAddon(build_py):
    def run(self):
        super().run()
        source = Path(__file__).parent / "addons/godot_bridge"
        destination = Path(self.build_lib) / "godotbridge/addon"
        copytree(source, destination, dirs_exist_ok=True, ignore=ignore_patterns("*.uid"))


setup(cmdclass={"build_py": BuildWithAddon})
