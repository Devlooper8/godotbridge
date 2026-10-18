# Installation

## Requirements

- Python 3.11 or newer.
- Godot 4.7 or newer stable, standard or .NET build. Godot 3 is unsupported.
- Official Python MCP SDK 2.x, installed by this package.
- A functioning graphics driver/display for screenshots.

Tested engine: `4.7.2.stable.mono.official.ed1daf0bf` on Windows. Minimum 4.7 is
intentional: this release uses its documented EditorInterface API. Earlier 4.x
releases have not been claimed compatible.

```sh
python -m venv .venv
python -m pip install -e ".[dev]"
```

Use the environment's Python/commands. Activation: `source .venv/bin/activate`
in POSIX shells, `.venv\Scripts\Activate.ps1` in PowerShell. Activation is
optional: invoke those executable paths directly if script execution is restricted.

Build/install a distributable package:

```sh
python -m build
python -m pip install dist/godotbridge-0.1.0-py3-none-any.whl
```

The wheel contains the complete plugin. No developer-machine path is embedded.
This task has not published a package to PyPI.

## Discovery and configuration

Precedence: `--godot`, `GODOT_EXECUTABLE`, project `godotbridge.toml`, then PATH
and conventional macOS application locations. Discovery executes `--version`
and chooses the newest supported stable binary it finds. `.cmd`/`.bat` shell
wrappers are not executed; adjacent Godot executables on PATH are found directly.
Arbitrary executable filenames work with an explicit path; `.app` bundles resolve
to `Contents/MacOS/Godot`.

```sh
godotctl --godot /opt/godot/Godot --project /work/game doctor
godotctl --godot /Applications/Godot.app --project /work/game doctor
```

Windows: `godotctl --godot "D:\Tools\Godot.exe" --project "D:\Games\Arena" doctor`.

Optional `godotbridge.toml` in the project:

```toml
godot = '/absolute/path/to/Godot'
timeout = 30
```

`--project` or `GODOTBRIDGE_PROJECT` selects a project; the working directory is
the fallback. Global options precede the command family. Timeouts are seconds;
use `--timeout 120` for slow imports.

## Plugin

Close that project's editor before installation/upgrade:

```sh
godotctl --project /work/game project install-plugin
godotctl --project /work/game project open
```

Enable **GodotBridge** in **Project → Project Settings → Plugins**. The demo
already enables it. Upgrades require explicit `--replace`; commit local plugin
changes first. The installer does not rewrite project.godot.

Manual installation: copy `addons/godot_bridge`, including `schemas.json`, into
the project. Startup binds an ephemeral `127.0.0.1` port, generates a random token,
and writes private credentials. Disabling the plugin removes its credentials and
closes its clients. Only one bridge editor may own a project at a time.

## Headless operation

Import while the editor is closed:

```sh
godotctl --project /work/game --timeout 120 project import
godotctl --project /work/game --timeout 120 project validate
godotctl --project /work/game project check-script res://scripts/player.gd
```

For scene editing without a window, run the enabled plugin in a headless editor:

```sh
godot --headless --editor --path /work/game
```

Then use the regular CLI/MCP operations. One editor remains authoritative and
uses Godot scene/resource APIs; there is no concurrent scene text-file writer.
Snapshots report `partial` with no image when no renderer exists.

Validation reads saved files and imported resources, not unsaved editor changes.
Import writes caches and is refused while a bridge editor is connected. Validation
does not implicitly import resources or compile C# code.
