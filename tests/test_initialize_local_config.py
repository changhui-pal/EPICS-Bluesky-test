import pathlib

from tools.initialize_local_config import create_from_example


def test_create_from_example_creates_missing_target(tmp_path):
    example = tmp_path / "example.ini"
    target = tmp_path / "local" / "runtime.ini"
    example.write_text("[test]\nvalue = example\n", encoding="utf-8")

    assert create_from_example(example, target) is True
    assert target.read_text(encoding="utf-8") == example.read_text(encoding="utf-8")


def test_create_from_example_never_overwrites_local_values(tmp_path):
    example = tmp_path / "example.ini"
    target = tmp_path / "runtime.ini"
    example.write_text("example", encoding="utf-8")
    target.write_text("local", encoding="utf-8")

    assert create_from_example(example, target) is False
    assert target.read_text(encoding="utf-8") == "local"


def test_project_examples_exist_and_local_paths_are_ignored():
    project = pathlib.Path(__file__).resolve().parents[1]
    ignore = (project / ".gitignore").read_text(encoding="utf-8")

    assert (project / "config" / "runtime.example.ini").is_file()
    assert (project / "config" / "axis-assignments.example.ini").is_file()
    assert "/config/runtime.ini" in ignore
    assert "/config/axis-assignments.ini" in ignore
