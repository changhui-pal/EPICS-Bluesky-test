#!/usr/bin/env python3
"""Local web GUI for applying one catalog model to one IOC axis slot."""

from __future__ import annotations

import argparse
import configparser
import io
import json
import pathlib
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


PROJECT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
sys.path.insert(0, str(TOOLS))
import stage_config_apply as stage_apply  # noqa: E402
import validate_stage_config as validator  # noqa: E402


PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9:_-]+$")
PANEL_PATH = "/api/panels"
PANEL_ITEM_PATH = re.compile(r"^/api/panels/([1-9]|[12][0-9]|3[0-2])$")
PANEL_STATUS_PATH = re.compile(
    r"^/api/panels/([1-9]|[12][0-9]|3[0-2])/status$")
STATUS_SUFFIXES = (
    ".RBV", ".EGU", "_able", ".MOVN", ".DMOV", ".HLS", ".LLS",
    ".LVIO", ".LLM", ".HLM", ".VELO", ".VMAX", ".DIR", ".MRES",
    ":OriginMethodSelectedRBV",
)
ASSIGNMENT_HEADER = """# Persistent IOC axis slots and GUI panel assignments.
# model present: restore this panel at the next GUI server start.
# enabled true: the panel is active and the IOC axis is currently Enable.
"""


def load_gui_configuration(models_path: pathlib.Path) -> dict:
    """Return the validated stage catalog exposed to the browser."""
    models = validator.load_models(models_path, 50000.0, [])
    return {
        "models": [
            {
                "name": model.name,
                "description": model.description,
                "egu": model.egu,
            }
            for model in models.values()
        ],
        "axes": list(range(1, 33)),
    }


class AssignmentStore:
    """Atomically maintain persistent axis/model and session enable state."""

    def __init__(self, path: pathlib.Path, models_path: pathlib.Path):
        self.path = path
        self.models_path = models_path
        self.lock = threading.RLock()
        models = validator.load_models(models_path, 50000.0, [])
        validator.validate_axes(path, models)

    def _read(self) -> configparser.ConfigParser:
        return validator.read_ini(self.path)

    def _write(self, parser: configparser.ConfigParser) -> None:
        models = validator.load_models(self.models_path, 50000.0, [])
        directory = self.path.parent
        temporary_path = None
        try:
            rendered = io.StringIO()
            parser.write(rendered)
            contents = ASSIGNMENT_HEADER + rendered.getvalue().rstrip() + "\n"
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=directory,
                    prefix=self.path.name + ".", suffix=".tmp",
                    delete=False) as stream:
                stream.write(contents)
                stream.flush()
                temporary_path = pathlib.Path(stream.name)
            validator.validate_axes(temporary_path, models)
            temporary_path.replace(self.path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def panels(self) -> list[dict]:
        """Return every model assignment that should be restored as a panel."""
        with self.lock:
            parser = self._read()
            return [
                {
                    "axis": axis,
                    "model": parser[f"axis:{axis}"].get("model", "").strip(),
                    "enabled": parser[f"axis:{axis}"].getboolean("enabled"),
                }
                for axis in range(1, 33)
                if parser[f"axis:{axis}"].get("model", "").strip()
            ]

    def assign(self, axis: int, model: str, *, enabled: bool) -> None:
        with self.lock:
            parser = self._read()
            section = parser[f"axis:{axis}"]
            section["model"] = model
            section["enabled"] = str(enabled).lower()
            # New empty slots need a valid installation placeholder. These are
            # not written to the IOC by model apply and may be edited later.
            if not section.get("direction", "").strip():
                section["direction"] = "Pos"
            if not section.get("sensors", "").strip():
                section["sensors"] = "none"
            if not section.get("home_method", "").strip():
                section["home_method"] = "4"
            self._write(parser)

    def set_enabled(self, axis: int, enabled: bool) -> None:
        with self.lock:
            parser = self._read()
            parser[f"axis:{axis}"]["enabled"] = str(enabled).lower()
            self._write(parser)

    def remove(self, axis: int) -> None:
        with self.lock:
            parser = self._read()
            section = parser[f"axis:{axis}"]
            section["enabled"] = "false"
            section.pop("model", None)
            self._write(parser)


def build_model_plan(axis: int, model_name: str, models_path: pathlib.Path
                     ) -> stage_apply.AxisPlan:
    """Build one runtime plan containing model-owned fields only."""
    if axis < 1 or axis > 32:
        raise ValueError("axis must be within 1..32")
    models = validator.load_models(models_path, 50000.0, [])
    if model_name not in models:
        raise ValueError("unknown stage model")
    model = models[model_name]
    fields = (
        ("DESC", model.description),
        ("EGU", model.egu),
        ("MRES", stage_apply.format_value(model.mres)),
        ("LLM", stage_apply.format_value(model.low_limit)),
        ("HLM", stage_apply.format_value(model.high_limit)),
        ("VMAX", stage_apply.format_value(model.vmax)),
        ("VELO", stage_apply.format_value(model.default_velocity)),
        ("VBAS", stage_apply.format_value(model.base_velocity)),
        ("ACCL", stage_apply.format_value(model.acceleration_time)),
    )
    return stage_apply.AxisPlan(axis, model_name, fields)


class ModelApplicator:
    """Apply a single reviewed model through the shared CA implementation."""

    def __init__(self, epics_bin: pathlib.Path, prefix: str,
                 models_path: pathlib.Path):
        self.client = stage_apply.ChannelAccess(epics_bin)
        self.prefix = prefix
        self.models_path = models_path

    def apply(self, axis: int, model_name: str) -> dict:
        plan = build_model_plan(axis, model_name, self.models_path)
        record = f"{self.prefix}m{axis}"
        dmov = self.client.get(record + ".DMOV")
        movn = self.client.get(record + ".MOVN")
        if dmov != "1" or movn != "0":
            raise ValueError(
                f"axis {axis}: model apply requires DMOV=1 and MOVN=0")
        # Startup recovery and explicit creation both take the bootstrap lock
        # before applying. This also permits a clean GUI restart after a prior
        # process ended without running its shutdown handler.
        self.disable(axis)
        stage_apply.apply_plans(self.client, self.prefix, [plan])
        return {
            "axis": axis,
            "model": model_name,
            "record": f"{self.prefix}m{axis}",
            "enabled": True,
        }

    def disable(self, axis: int) -> None:
        pv = f"{self.prefix}m{axis}_able"
        if self.client.get(pv, numeric_enum=True) == "1":
            return
        self.client.put(pv, "Disable")
        if self.client.get(pv, numeric_enum=True) != "1":
            raise ValueError(f"axis {axis}: Disable readback failed")

    def read_status(self, axis: int) -> dict:
        """Read one panel's fixed status allowlist in one CA invocation."""
        record = f"{self.prefix}m{axis}"
        pvs = [
            record + suffix if suffix != "_able" else record + "_able"
            for suffix in STATUS_SUFFIXES
        ]
        result = subprocess.run(
            [str(self.client.caget), "-t", "-S", *pvs], check=True,
            capture_output=True, text=True, timeout=5.0,
        )
        values = result.stdout.splitlines()
        if len(values) != len(pvs):
            raise ValueError("unexpected panel status value count")
        return dict(zip(STATUS_SUFFIXES, values))


class PanelManager:
    """Synchronize browser panels, assignments and IOC enable state."""

    def __init__(self, store: AssignmentStore, applicator: ModelApplicator):
        self.store = store
        self.applicator = applicator
        self.lock = threading.RLock()
        self.active: dict[int, dict] = {}

    def restore(self) -> None:
        """Apply and enable all persistent model assignments at GUI startup."""
        restored = []
        try:
            for assignment in self.store.panels():
                result = self.applicator.apply(
                    assignment["axis"], assignment["model"])
                restored.append(assignment["axis"])
                self.store.set_enabled(assignment["axis"], True)
                self.active[assignment["axis"]] = result
        except BaseException:
            for axis in restored:
                try:
                    self.applicator.disable(axis)
                finally:
                    self.store.set_enabled(axis, False)
            raise

    def list(self) -> list[dict]:
        with self.lock:
            return [self.active[axis] for axis in sorted(self.active)]

    def status(self, axis: int) -> dict:
        with self.lock:
            if axis not in self.active:
                raise ValueError(f"axis {axis}: panel does not exist")
        return {
            "axis": axis,
            "values": self.applicator.read_status(axis),
        }

    def create(self, axis: int, model: str) -> dict:
        with self.lock:
            if axis in self.active:
                raise ValueError(f"axis {axis}: panel already exists")
            result = self.applicator.apply(axis, model)
            try:
                self.store.assign(axis, model, enabled=True)
            except BaseException:
                self.applicator.disable(axis)
                raise
            self.active[axis] = result
            return result

    def delete(self, axis: int) -> dict:
        with self.lock:
            if axis not in self.active:
                raise ValueError(f"axis {axis}: panel does not exist")
            self.applicator.disable(axis)
            self.store.remove(axis)
            removed = self.active.pop(axis)
            return {"axis": axis, "model": removed["model"], "enabled": False}

    def shutdown(self) -> list[str]:
        """Disable every panel axis and preserve its model for next startup."""
        errors = []
        with self.lock:
            for axis in sorted(self.active):
                try:
                    self.applicator.disable(axis)
                except BaseException as error:
                    errors.append(f"axis {axis} Disable failed: {error}")
                try:
                    self.store.set_enabled(axis, False)
                except BaseException as error:
                    errors.append(f"axis {axis} assignment update failed: {error}")
            self.active.clear()
        return errors


class GuiHandler(SimpleHTTPRequestHandler):
    """Serve static assets and the one minimal model-apply endpoint."""

    server_version = "KohzuLocalGui/0.2"

    def send_json(self, value: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/config":
            value = dict(self.server.gui_config)
            value["prefix"] = self.server.manager.applicator.prefix
            value["token"] = self.server.write_token
            value["panels"] = self.server.manager.list()
            self.send_json(value)
            return
        status_match = PANEL_STATUS_PATH.fullmatch(path)
        if status_match:
            try:
                self.send_json(
                    self.server.manager.status(int(status_match.group(1))))
            except (ValueError, subprocess.SubprocessError, OSError) as error:
                self.send_json(
                    {"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != PANEL_PATH:
            self.send_json({"error": "unsupported endpoint"}, HTTPStatus.NOT_FOUND)
            return
        if not secrets.compare_digest(
                self.headers.get("X-Kohzu-Token", ""), self.server.write_token):
            self.send_json({"error": "invalid write token"}, HTTPStatus.FORBIDDEN)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1024:
                raise ValueError("invalid request body length")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            axis = body.get("axis")
            model = body.get("model")
            if not isinstance(axis, int) or not isinstance(model, str):
                raise ValueError("axis must be an integer and model must be text")
            self.send_json(self.server.manager.create(axis, model))
        except (ValueError, subprocess.SubprocessError, OSError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:  # noqa: N802
        match = PANEL_ITEM_PATH.fullmatch(urlparse(self.path).path)
        if not match:
            self.send_json({"error": "unsupported endpoint"}, HTTPStatus.NOT_FOUND)
            return
        if not secrets.compare_digest(
                self.headers.get("X-Kohzu-Token", ""), self.server.write_token):
            self.send_json({"error": "invalid write token"}, HTTPStatus.FORBIDDEN)
            return
        try:
            self.send_json(self.server.manager.delete(int(match.group(1))))
        except (ValueError, subprocess.SubprocessError, OSError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)

    def log_message(self, message: str, *args) -> None:
        print(f"GUI {self.client_address[0]}: " + message % args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--prefix", default="KOHZU:")
    parser.add_argument("--models", type=pathlib.Path,
                        default=PROJECT / "config" / "stage-models.ini")
    parser.add_argument("--axes", type=pathlib.Path,
                        default=PROJECT / "config" / "axis-assignments.ini")
    parser.add_argument("--epics-bin", type=pathlib.Path,
                        default=pathlib.Path(
                            "/usr/local/epics/base-7.0.7/bin/linux-x86_64"))
    arguments = parser.parse_args()
    try:
        if arguments.listen != "127.0.0.1":
            raise ValueError("GUI is restricted to 127.0.0.1")
        if not PREFIX_PATTERN.fullmatch(arguments.prefix):
            raise ValueError("invalid PV prefix")
        gui_config = load_gui_configuration(arguments.models)
        applicator = ModelApplicator(
            arguments.epics_bin, arguments.prefix, arguments.models)
        manager = PanelManager(
            AssignmentStore(arguments.axes, arguments.models), applicator)
        manager.restore()
        handler = lambda *values, **kwargs: GuiHandler(  # noqa: E731
            *values, directory=str(PROJECT / "gui" / "static"), **kwargs)
        server = ThreadingHTTPServer((arguments.listen, arguments.port), handler)
        server.gui_config = gui_config
        server.manager = manager
        server.write_token = secrets.token_urlsafe(32)
        print(f"KOHZU GUI listening on http://{arguments.listen}:{arguments.port}")
        previous_term = signal.getsignal(signal.SIGTERM)
        signal.signal(
            signal.SIGTERM,
            lambda _signum, _frame: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("KOHZU GUI shutdown requested")
        finally:
            server.server_close()
            for message in manager.shutdown():
                print(f"KOHZU GUI shutdown warning: {message}", file=sys.stderr)
            signal.signal(signal.SIGTERM, previous_term)
    except (ValueError, configparser.Error, OSError) as error:
        print(f"Cannot start KOHZU GUI: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
