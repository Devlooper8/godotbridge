import pytest
import typer
from godotbridge.commands.runtime import parse_variable_path


def test_dotted_bracket_paths():
    assert parse_variable_path("inventory") == ["inventory"]
    assert parse_variable_path("party[0].stats[12]") == [
        "party",
        {"index": 0},
        {"property": "stats"},
        {"index": 12},
    ]
    assert parse_variable_path("a.b.c") == ["a", {"property": "b"}, {"property": "c"}]


@pytest.mark.parametrize("bad", ["", "[0]", "a[", "a[x]", "a..b", "a[1]b"])
def test_bad_paths_are_rejected(bad):
    with pytest.raises(typer.BadParameter):
        parse_variable_path(bad)
