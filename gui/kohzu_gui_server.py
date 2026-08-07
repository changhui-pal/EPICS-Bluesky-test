#!/usr/bin/env python3
"""Local-only web GUI backend for dynamic KOHZU axis panels.

The GUI uses IOC-side guarded commissioning requests.  It never writes raw
_able or controller protocol commands.
"""

import argparse
import configparser
import json
import pathlib
import re
import secrets
import subprocess
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


PROJECT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = PROJECT / "tools"
sys.path.insert(0, str(TOOLS))
import validate_stage_config as validator  # noqa: E402


PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9:_-]+$")
AXIS_PATH = re.compile(
    r"^/api/axis/([1-9]|[12][0-9]|3[0-2])/"
    r"(status|enable|disable|origin-method|home|confirmation)$")
RECOVERY_PATH = re.compile(r"^/api/recovery/(release-emg|refresh-axes)$")

STATUS_SUFFIXES = (
    ".RBV", ".VAL", ".EGU", ".DMOV", ".MOVN", ".HLS", ".LLS",
    ":OriginMethodSelectedRBV", ":HomeStatus",
    ":MoveStatus", ":PositionStatus",
    ":Commissioning:ConfigApplied",
    ":Commissioning:DirectionVerified",
    ":Commissioning:SensorsVerified",
    ":Commissioning:LimitsVerified",
    ":Commissioning:HomeEstablished",
    ":Commissioning:Ready",
)

DIAGNOSTIC_SUFFIXES = (
    "Diag:LastErrorCode", "Diag:LastErrorText", "Diag:LastErrorCommand",
    "Diag:LastErrorRaw", "Diag:LastWarningCode", "Diag:LastWarningText",
    "Diag:LastWarningCommand", "Diag:LastWarningRaw",
    "Recovery:EmergencyActive", "Recovery:Status")


def load_gui_configuration(models_path: pathlib.Path,
                           axes_path: pathlib.Path) -> dict:
    """Return validated catalog/assignment data safe to send to a browser."""
    models = validator.load_models(models_path, 50000.0, [])
    validator.validate_axes(axes_path, models)
    axes = validator.read_ini(axes_path)
    return {
        "models": [{"name": model.name, "description": model.description,
                    "egu": model.egu} for model in models.values()],
        "axes": [{"axis": axis,
                  "assigned_model": axes[f"axis:{axis}"].get("model", "").strip(),
                  "configured_enabled": axes[f"axis:{axis}"].getboolean("enabled")}
                 for axis in range(1, 33)],
    }


class ChannelAccess:
    """Whitelisted subprocess adapter for the installed EPICS CA clients."""

    def __init__(self, epics_bin: pathlib.Path, prefix: str):
        self.caget = epics_bin / "caget"
        self.caput = epics_bin / "caput"
        self.prefix = prefix
        if not self.caget.is_file() or not self.caput.is_file():
            raise ValueError(f"caget/caput not found in {epics_bin}")

    def read_axis(self, axis: int) -> dict:
        """Read only the fixed status allowlist for one validated axis."""
        record = f"{self.prefix}m{axis}"
        pvs = [record + suffix for suffix in STATUS_SUFFIXES]
        # -S renders CHAR waveform diagnostics as strings instead of a count
        # followed by byte values; scalar motor fields are unaffected.
        result = subprocess.run([str(self.caget), "-t", "-S", *pvs], check=True,
                                capture_output=True, text=True, timeout=5.0)
        values = result.stdout.splitlines()
        if len(values) != len(pvs):
            raise ValueError("unexpected caget status value count")
        return {suffix: value for suffix, value in zip(STATUS_SUFFIXES, values)}

    def request(self, axis: int, action: str) -> None:
        """Write only a guarded commissioning request, never a motor field."""
        if action not in ("enable", "disable"):
            raise ValueError("unsupported GUI action")
        request = "EnableRequest" if action == "enable" else "DisableRequest"
        pv = f"{self.prefix}m{axis}:Commissioning:{request}"
        subprocess.run([str(self.caput), "-t", pv, "1"], check=True,
                       capture_output=True, text=True, timeout=5.0)

    def get_one(self, pv: str, string_array: bool = False,
                numeric_enum: bool = False) -> str:
        """Read one PV with the representation required by safety checks."""
        command = [str(self.caget), "-t"]
        if string_array:
            command.append("-S")
        if numeric_enum:
            command.append("-n")
        command.append(pv)
        result = subprocess.run(command, check=True, capture_output=True,
                                text=True, timeout=5.0)
        return result.stdout.strip()

    def put_one(self, pv: str, value: str) -> None:
        subprocess.run([str(self.caput), "-t", pv, value], check=True,
                       capture_output=True, text=True, timeout=5.0)

    def select_origin_method(self, axis: int, method: int) -> None:
        """Select only a driver-advertised method and invalidate old HOME."""
        if method < 1 or method > 15:
            raise ValueError("Origin method must be within 1..15")
        record = f"{self.prefix}m{axis}"
        # The user chooses the sensor-compatible method.  The GUI only checks
        # the controller's documented numeric range and disables before change.
        self.put_one(record + ":Commissioning:InvalidateHomeRequest", "1")
        self.put_one(record + ":OriginMethod", str(method))

    def set_confirmation(self, axis: int, name: str, verified: bool) -> None:
        """Record only fixed operator confirmations under stopped/Disable guards."""
        flags = {
            "direction": "DirectionVerified",
            "sensors": "SensorsVerified",
            "limits": "LimitsVerified",
            "home": "HomeEstablished",
        }
        if name not in flags:
            raise ValueError("unsupported commissioning confirmation")
        record = f"{self.prefix}m{axis}"
        # Revocation is always safety-decreasing. HOME revocation also clears
        # the machine completion latch through the IOC invalidation chain.
        if not verified:
            if name == "home":
                self.put_one(record + ":Commissioning:InvalidateHomeRequest", "1")
            else:
                self.put_one(record + ":Commissioning:DisableRequest", "1")
                self.put_one(record + ":Commissioning:" + flags[name], "0")
            return
        values = {
            "config": self.get_one(record + ":Commissioning:ConfigApplied",
                                   numeric_enum=True),
            "able": self.get_one(record + "_able", numeric_enum=True),
            "dmov": self.get_one(record + ".DMOV"),
            "movn": self.get_one(record + ".MOVN"),
        }
        if values != {"config": "1", "able": "1", "dmov": "1",
                      "movn": "0"}:
            raise ValueError(
                "Confirmation requires applied config, stopped axis and Disable")
        self.put_one(record + ":Commissioning:" + flags[name], "1")

    def request_home(self, axis: int) -> None:
        """Request the user-selected HOME method on a ready, enabled axis."""
        record = f"{self.prefix}m{axis}"
        ready = self.get_one(record + ":Commissioning:Ready")
        able = self.get_one(record + "_able", numeric_enum=True)
        if ready != "1" or able != "0":
            raise ValueError(
                "HOME requires CommissioningReady=1 and motor Enable=0")
        # HOMF and HOMR both map to the selected ARIES SYS.2 method; use HOMF
        # consistently and let the driver repeat its STR/SYS.2 safety checks.
        self.put_one(record + ".HOMF", "1")

    def read_diagnostics(self) -> dict:
        """Read decoded controller diagnostics and guarded recovery status."""
        pvs = [self.prefix + suffix for suffix in DIAGNOSTIC_SUFFIXES]
        result = subprocess.run([str(self.caget), "-t", "-S", *pvs], check=True,
                                capture_output=True, text=True, timeout=5.0)
        values = result.stdout.splitlines()
        if len(values) != len(pvs):
            raise ValueError("unexpected diagnostic value count")
        return {suffix: value for suffix, value in zip(DIAGNOSTIC_SUFFIXES, values)}

    def request_recovery(self, action: str) -> None:
        """Request only the two existing driver-guarded recovery operations."""
        suffixes = {"release-emg": "Recovery:ReleaseEMG",
                    "refresh-axes": "Recovery:RefreshAxes"}
        if action not in suffixes:
            raise ValueError("unsupported recovery action")
        subprocess.run([str(self.caput), "-t", self.prefix + suffixes[action], "1"],
                       check=True, capture_output=True, text=True, timeout=5.0)


class GuiHandler(SimpleHTTPRequestHandler):
    """Serve static assets and a minimal same-origin JSON API."""

    server_version = "KohzuLocalGui/0.1"

    def send_json(self, value: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        if path == "/api/config":
            value = dict(self.server.gui_config)
            value["prefix"] = self.server.ca.prefix
            value["token"] = self.server.write_token
            self.send_json(value)
            return
        if path == "/api/diagnostics":
            try:
                self.send_json({"values": self.server.ca.read_diagnostics()})
            except (ValueError, subprocess.SubprocessError, OSError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        match = AXIS_PATH.fullmatch(path)
        if match and match.group(2) == "status":
            try:
                self.send_json({"axis": int(match.group(1)), "values":
                                self.server.ca.read_axis(int(match.group(1)))})
            except (ValueError, subprocess.SubprocessError, OSError) as error:
                self.send_json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        path = urlparse(self.path).path
        match = AXIS_PATH.fullmatch(path)
        recovery_match = RECOVERY_PATH.fullmatch(path)
        if (not match and not recovery_match) or (match and match.group(2) == "status"):
            self.send_json({"error": "unsupported endpoint"}, HTTPStatus.NOT_FOUND)
            return
        if not secrets.compare_digest(self.headers.get("X-Kohzu-Token", ""),
                                      self.server.write_token):
            self.send_json({"error": "invalid write token"}, HTTPStatus.FORBIDDEN)
            return
        try:
            if recovery_match:
                action = recovery_match.group(1)
                self.server.ca.request_recovery(action)
                self.send_json({"requested": action})
            else:
                axis = int(match.group(1))
                action = match.group(2)
                if action == "origin-method":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 1 or length > 1024:
                        raise ValueError("invalid request body length")
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    method = body.get("method")
                    if not isinstance(method, int):
                        raise ValueError("method must be an integer")
                    self.server.ca.select_origin_method(axis, method)
                elif action == "confirmation":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 1 or length > 1024:
                        raise ValueError("invalid request body length")
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    name = body.get("name")
                    verified = body.get("verified")
                    if not isinstance(name, str) or not isinstance(verified, bool):
                        raise ValueError("name must be text and verified must be boolean")
                    self.server.ca.set_confirmation(axis, name, verified)
                elif action == "home":
                    self.server.ca.request_home(axis)
                else:
                    self.server.ca.request(axis, action)
                self.send_json({"axis": axis, "requested": action})
        except (ValueError, subprocess.SubprocessError, OSError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_GATEWAY)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

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
            raise ValueError("GUI foundation is restricted to 127.0.0.1")
        if not PREFIX_PATTERN.fullmatch(arguments.prefix):
            raise ValueError("invalid PV prefix")
        gui_config = load_gui_configuration(arguments.models, arguments.axes)
        ca = ChannelAccess(arguments.epics_bin, arguments.prefix)
        handler = lambda *values, **kwargs: GuiHandler(  # noqa: E731
            *values, directory=str(PROJECT / "gui" / "static"), **kwargs)
        server = ThreadingHTTPServer((arguments.listen, arguments.port), handler)
        server.gui_config = gui_config
        server.ca = ca
        server.write_token = secrets.token_urlsafe(32)
        print(f"KOHZU GUI listening on http://{arguments.listen}:{arguments.port}")
        server.serve_forever()
    except (ValueError, configparser.Error, OSError) as error:
        print(f"Cannot start KOHZU GUI: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
