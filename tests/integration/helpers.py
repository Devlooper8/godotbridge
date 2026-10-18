import pytest
from godotbridge.errors import BridgeError


def write(editor, relative, text):
    """Write a project file the way a user would; the editor loads it from disk on demand."""
    file = editor.config.project / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8", newline="\n")
    return file


def read(editor, relative):
    return (editor.config.project / relative).read_text(encoding="utf-8")


def rejected(editor, method, code, **params):
    with pytest.raises(BridgeError) as caught:
        editor.call(method, **params)
    assert caught.value.code == code, caught.value
