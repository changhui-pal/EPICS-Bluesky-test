import pathlib

import pytest

from kohzu_runtime import load_runtime_config


def write_config(path: pathlib.Path, *, gui_port: int = 8080,
                 prefix: str = "TEST:") -> None:
    path.write_text(
        f"""[controller]
host = controller.example
port = 12321

[epics]
prefix = {prefix}
bin = /opt/epics/bin
ca_addr_list = 10.0.0.255

[gui]
listen = 0.0.0.0
port = {gui_port}
move_timeout = 180
home_timeout = 300

[python]
executable = /opt/venv/bin/python
""",
        encoding="utf-8",
    )


def test_runtime_config_reads_all_shared_values(tmp_path):
    path = tmp_path / "runtime.ini"
    write_config(path)

    config = load_runtime_config(path)

    assert config.controller_host == "controller.example"
    assert config.controller_port == 12321
    assert config.epics_prefix == "TEST:"
    assert config.epics_bin == pathlib.Path("/opt/epics/bin")
    assert config.ca_addr_list == "10.0.0.255"
    assert config.gui_listen == "0.0.0.0"
    assert config.gui_port == 8080
    assert config.gui_move_timeout == 180
    assert config.gui_home_timeout == 300
    assert config.python_executable == pathlib.Path("/opt/venv/bin/python")
    assert config.get("controller.host") == "controller.example"


def test_tracked_runtime_example_is_valid_and_non_production():
    project = pathlib.Path(__file__).resolve().parents[1]

    config = load_runtime_config(project / "config" / "runtime.example.ini")

    assert config.controller_host == "192.0.2.10"
    assert str(config.python_executable).startswith("/path/to/")


@pytest.mark.parametrize(
    ("gui_port", "prefix", "message"),
    [(0, "TEST:", "between 1 and 65535"),
     (8080, "bad prefix!", "unsupported characters")],
)
def test_runtime_config_rejects_invalid_values(
        tmp_path, gui_port, prefix, message):
    path = tmp_path / "runtime.ini"
    write_config(path, gui_port=gui_port, prefix=prefix)

    with pytest.raises(ValueError, match=message):
        load_runtime_config(path)
