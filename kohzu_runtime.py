"""Shared, validated runtime configuration for production entry points."""

from __future__ import annotations

import argparse
import configparser
import dataclasses
import pathlib
import re
from collections.abc import Sequence


PROJECT = pathlib.Path(__file__).resolve().parent
DEFAULT_RUNTIME_PATH = PROJECT / "config" / "runtime.ini"
PREFIX_PATTERN = re.compile(r"[A-Za-z0-9_:-]+")


@dataclasses.dataclass(frozen=True)
class RuntimeConfig:
    controller_host: str
    controller_port: int
    epics_prefix: str
    epics_bin: pathlib.Path
    ca_addr_list: str
    gui_listen: str
    gui_port: int
    gui_move_timeout: float
    gui_home_timeout: float
    python_executable: pathlib.Path

    def get(self, key: str) -> str:
        values = {
            "controller.host": self.controller_host,
            "controller.port": str(self.controller_port),
            "epics.prefix": self.epics_prefix,
            "epics.bin": str(self.epics_bin),
            "epics.ca_addr_list": self.ca_addr_list,
            "gui.listen": self.gui_listen,
            "gui.port": str(self.gui_port),
            "gui.move_timeout": str(self.gui_move_timeout),
            "gui.home_timeout": str(self.gui_home_timeout),
            "python.executable": str(self.python_executable),
        }
        try:
            return values[key]
        except KeyError as error:
            raise ValueError(f"unknown runtime setting: {key}") from error


def _port(parser: configparser.ConfigParser, section: str, option: str) -> int:
    value = parser.getint(section, option)
    if not 1 <= value <= 65535:
        raise ValueError(f"{section}.{option} must be between 1 and 65535")
    return value


def _text(parser: configparser.ConfigParser, section: str, option: str) -> str:
    value = parser.get(section, option).strip()
    if not value:
        raise ValueError(f"{section}.{option} must not be empty")
    return value


def _positive_float(parser: configparser.ConfigParser, section: str,
                    option: str) -> float:
    value = parser.getfloat(section, option)
    if value <= 0:
        raise ValueError(f"{section}.{option} must be greater than zero")
    return value


def load_runtime_config(path: pathlib.Path = DEFAULT_RUNTIME_PATH) -> RuntimeConfig:
    """Read and validate the common production runtime configuration."""
    parser = configparser.ConfigParser(interpolation=None)
    path = pathlib.Path(path).expanduser()
    if not parser.read(path):
        raise FileNotFoundError(f"runtime configuration not found: {path}")
    prefix = _text(parser, "epics", "prefix")
    if not PREFIX_PATTERN.fullmatch(prefix):
        raise ValueError("epics.prefix contains unsupported characters")
    return RuntimeConfig(
        controller_host=_text(parser, "controller", "host"),
        controller_port=_port(parser, "controller", "port"),
        epics_prefix=prefix,
        epics_bin=pathlib.Path(_text(parser, "epics", "bin")).expanduser(),
        ca_addr_list=_text(parser, "epics", "ca_addr_list"),
        gui_listen=_text(parser, "gui", "listen"),
        gui_port=_port(parser, "gui", "port"),
        gui_move_timeout=_positive_float(parser, "gui", "move_timeout"),
        gui_home_timeout=_positive_float(parser, "gui", "home_timeout"),
        python_executable=pathlib.Path(
            _text(parser, "python", "executable")
        ).expanduser(),
    )


def runtime_from_argv(
    argv: Sequence[str] | None = None,
) -> tuple[pathlib.Path, RuntimeConfig]:
    """Pre-parse --runtime-config so a CLI can derive its other defaults."""
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--runtime-config", type=pathlib.Path, default=DEFAULT_RUNTIME_PATH
    )
    arguments, _ = pre_parser.parse_known_args(argv)
    return arguments.runtime_config, load_runtime_config(arguments.runtime_config)
