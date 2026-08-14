#!/usr/bin/env python3
"""Local web GUI for applying one catalog model to one IOC axis slot."""

from __future__ import annotations

import argparse
import asyncio
import configparser
import io
import math
import pathlib
import re
import secrets
import sys
import tempfile
import threading
from contextlib import asynccontextmanager
from decimal import Decimal, ROUND_HALF_UP

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn


PROJECT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from kohzu_runtime import runtime_from_argv  # noqa: E402
TOOLS = PROJECT / "tools"
sys.path.insert(0, str(TOOLS))
import stage_config_apply as stage_apply  # noqa: E402
import validate_stage_config as validator  # noqa: E402
from kohzu_axis_session import AxisSession  # noqa: E402


PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9:_-]+$")
ASSIGNMENT_HEADER = """# Persistent IOC axis slots and GUI panel assignments.
# model present: restore this panel at the next GUI server start.
# enabled true: the panel is active and the IOC axis is currently Enable.
"""

NUMERIC_WRITABLE_FIELDS = {
    ".VELO", ".JVEL", ".JAR", ".ACCL", ".HVEL", ".VBAS", ".VMAX",
    ".TWV", ".LLM", ".HLM", ".BDST", ".BVEL", ".BACC", ".RDBD",
    ".RTRY", ".DLY", ".FRAC", ".OFF", ".MRES", ".PREC", ".UREV",
    ".SREV", ".ERES", ".RRES",
}
INTEGER_WRITABLE_FIELDS = {".RTRY", ".PREC"}
ENUM_WRITABLE_FIELDS = {
    ".SET": {"Use", "Set"},
    ".SPMG": {"Stop", "Pause", "Move", "Go"},
    ".DIR": {"Pos", "Neg"},
    ".FOFF": {"Variable", "Frozen"},
    ".UEIP": {"No", "Yes"},
    ".URIP": {"No", "Yes"},
}
COORDINATE_WRITABLE_FIELDS = {".OFF", ".MRES", ".DIR", ".FOFF"}


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
    jog_acceleration = (
        model.default_velocity - model.base_velocity
    ) / model.acceleration_time
    fields = (
        ("DESC", model.description),
        ("EGU", model.egu),
        ("MRES", stage_apply.format_value(model.mres)),
        ("LLM", stage_apply.format_value(model.low_limit)),
        ("HLM", stage_apply.format_value(model.high_limit)),
        ("VMAX", stage_apply.format_value(model.vmax)),
        ("VELO", stage_apply.format_value(model.default_velocity)),
        ("JVEL", stage_apply.format_value(model.default_velocity)),
        ("JAR", stage_apply.format_value(jog_acceleration)),
        ("HVEL", stage_apply.format_value(model.default_velocity)),
        ("VBAS", stage_apply.format_value(model.base_velocity)),
        ("ACCL", stage_apply.format_value(model.acceleration_time)),
    )
    return stage_apply.AxisPlan(axis, model_name, fields)


def plan_user_move(values: dict[str, str], mode: str, value: float) -> dict:
    """Validate state and quantize one absolute or relative user target."""
    if mode not in {"absolute", "relative"}:
        raise ValueError("move mode must be absolute or relative")
    if not math.isfinite(value):
        raise ValueError("move value must be finite")
    enabled = values["_able"] in {"Enable", "0"}
    if not enabled:
        raise ValueError("axis is Disabled")
    if values[".SET"] not in {"Use", "0"}:
        raise ValueError("axis motor record must be in SET=Use mode")
    if values[".SPMG"] not in {"Go", "3"}:
        raise ValueError("axis motor record must be in SPMG=Go mode")
    if values[".DMOV"] not in {"1", "Yes", "Done"} or \
            values[".MOVN"] in {"1", "Yes", "Active"}:
        raise ValueError("axis must be stopped before a move")
    if any(values[suffix] in {"1", "Yes", "Active"}
           for suffix in (".HLS", ".LLS", ".LVIO")):
        raise ValueError("axis limit is active")

    current = Decimal(values[".RBV"])
    requested_value = Decimal(str(value))
    requested = requested_value if mode == "absolute" \
        else current + requested_value
    resolution = abs(Decimal(values[".MRES"]))
    if not resolution.is_finite() or resolution <= 0:
        raise ValueError("MRES must be finite and positive")
    steps = ((requested - current) / resolution).to_integral_value(
        rounding=ROUND_HALF_UP
    )
    target = current + steps * resolution
    low = Decimal(values[".LLM"])
    high = Decimal(values[".HLM"])
    if target < low or target > high:
        raise ValueError(f"quantized target {target} is outside {low}..{high}")
    return {
        "mode": mode,
        "value": float(requested_value),
        "current": float(current),
        "requested": float(requested),
        "target": float(target),
        "egu": values[".EGU"],
    }


def plan_user_jog(values: dict[str, str], direction: str) -> dict:
    """Validate a physical controller CW/CCW request and map through DIR."""
    if direction not in {"cw", "ccw"}:
        raise ValueError("JOG direction must be cw or ccw")
    # Reuse the state checks without inventing a position move.  The current
    # RBV target is always on its own MRES grid and inside the active limits.
    plan_user_move(values, "absolute", float(values[".RBV"]))
    direction_positive = values[".DIR"] in {"Pos", "0"}
    forward = (direction == "cw") == direction_positive
    relevant_limit = ".HLS" if forward else ".LLS"
    if values[relevant_limit] in {"1", "Yes", "Active"}:
        raise ValueError(f"cannot JOG toward active {relevant_limit} limit")
    return {"direction": direction, "forward": forward, "egu": values[".EGU"]}


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
            "enabled": False,
        }

    def disable(self, axis: int) -> None:
        pv = f"{self.prefix}m{axis}_able"
        if self.client.get(pv, numeric_enum=True) == "1":
            return
        self.client.put(pv, "Disable")
        if self.client.get(pv, numeric_enum=True) != "1":
            raise ValueError(f"axis {axis}: Disable readback failed")

class PanelManager:
    """Own persistent panel sessions and serialize each axis's commands."""

    def __init__(self, store, applicator, motion=None, *, session_factory=None,
                 update_callback=None):
        self.store, self.applicator, self.motion = store, applicator, motion
        self.session_factory = session_factory or AxisSession
        self.update_callback = update_callback
        self.lock = threading.RLock()
        self.active = {}
        self.sessions = {}
        self.moving_axes, self.jogging_axes = set(), set()

    @staticmethod
    def _log(axis, message):
        print(f"GUI axis {axis}: {message}", flush=True)

    @staticmethod
    def _is_on(value):
        return value in {"1", "Yes", "Active"}

    def _session(self, axis):
        try:
            return self.sessions[axis]
        except KeyError:
            raise ValueError(f"axis {axis}: panel does not exist") from None

    def _activate(self, axis, model):
        result = self.applicator.apply(axis, model)
        session = self.session_factory(
            axis, self.applicator.prefix, update_callback=self.update_callback)
        try:
            session.put("_able", "Enable")
            self.store.assign(axis, model, enabled=True)
            result["enabled"] = True
            self.sessions[axis], self.active[axis] = session, result
            if self.motion is not None:
                self.motion.register_motor(axis, session.motor)
            self._log(axis, f"panel ready, model={model}")
            return result
        except BaseException:
            session.close()
            self.applicator.disable(axis)
            raise

    def restore(self):
        for item in self.store.panels():
            self._activate(item["axis"], item["model"])

    def list(self):
        with self.lock:
            return [self.active[a] for a in sorted(self.active)]

    def snapshots(self):
        with self.lock:
            return {str(a): s.snapshot() for a, s in self.sessions.items()}

    def create(self, axis, model):
        with self.lock:
            if axis in self.active:
                raise ValueError(f"axis {axis}: panel already exists")
            return self._activate(axis, model)

    def stop(self, axis):
        session = self._session(axis)
        session.stop()
        with self.lock:
            self.jogging_axes.discard(axis)
        self._log(axis, "STOP requested")
        return {"axis": axis, "stopped": True}

    def jog_start(self, axis, direction):
        session = self._session(axis)
        with session.command_lock:
            if axis in self.moving_axes or axis in self.jogging_axes:
                raise ValueError(f"axis {axis}: a motion request is already active")
            request = plan_user_jog(session.snapshot(), direction)
            session.jog(forward=request["forward"])
            self.jogging_axes.add(axis)
        self._log(axis, f"{direction.upper()} JOG started")
        return {"axis": axis, "jogging": True, **request}

    def jog_stop(self, axis):
        result = self.stop(axis)
        result["jogging"] = False
        return result

    def move(self, axis, mode, value):
        session = self._session(axis)
        with session.command_lock:
            if axis in self.moving_axes or axis in self.jogging_axes:
                raise ValueError(f"axis {axis}: a motion request is already active")
            request = plan_user_move(session.snapshot(), mode, value)
            self.moving_axes.add(axis)
            future = self.motion.submit(axis, request["target"])
        try:
            future.result()
            final = session.snapshot()
            return {"axis": axis, **request, "final": float(final[".RBV"]),
                    "done": final[".DMOV"] in {"1", "Yes", "Done"}}
        finally:
            self.moving_axes.discard(axis)

    def write_field(self, axis, suffix, value):
        session = self._session(axis)
        if suffix in NUMERIC_WRITABLE_FIELDS:
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)):
                raise ValueError(f"{suffix} requires a finite numeric value")
            if suffix in INTEGER_WRITABLE_FIELDS and float(value) != int(value):
                raise ValueError(f"{suffix} requires an integer value")
            requested = int(value) if suffix in INTEGER_WRITABLE_FIELDS else float(value)
        elif suffix in ENUM_WRITABLE_FIELDS:
            if value not in ENUM_WRITABLE_FIELDS[suffix]:
                raise ValueError(f"invalid {suffix} value")
            requested = value
        else:
            raise ValueError(f"field {suffix!r} is not writable from this GUI")
        with session.command_lock:
            status = session.snapshot()
            if axis in self.moving_axes or axis in self.jogging_axes or \
                    self._is_on(status[".MOVN"]):
                raise ValueError(f"axis {axis}: must be stopped before field edit")
            if suffix in COORDINATE_WRITABLE_FIELDS and \
                    status[".SET"] not in {"Set", "1"}:
                raise ValueError(f"axis {axis}: {suffix} edit requires SET=Set mode")
            session.put(suffix, requested)
        return {"axis": axis, "field": suffix, "requested": requested}

    def delete(self, axis):
        with self.lock:
            session = self._session(axis)
            if axis in self.moving_axes or axis in self.jogging_axes:
                raise ValueError(f"axis {axis}: cannot delete during motion")
            session.put("_able", "Disable")
            if self.motion is not None:
                self.motion.unregister_motor(axis)
            session.close()
            removed = self.active.pop(axis)
            self.sessions.pop(axis)
            self.store.remove(axis)
            return {"axis": axis, "model": removed["model"], "enabled": False}

    def stop_axes(self, axes):
        for axis in set(axes):
            if axis in self.sessions:
                self.stop(axis)

    def shutdown(self):
        errors = []
        for axis in list(self.sessions):
            try:
                self.stop(axis)
                self.sessions[axis].put("_able", "Disable")
                self.store.set_enabled(axis, False)
                self.sessions[axis].close()
            except BaseException as error:
                errors.append(f"axis {axis}: {error}")
        self.sessions.clear(); self.active.clear()
        if self.motion is not None:
            try: self.motion.close()
            except BaseException as error: errors.append(str(error))
        return errors


class PanelRequest(BaseModel):
    axis: int
    model: str


class EventHub:
    """Bridge CA callback threads to all connected browser WebSockets."""

    def __init__(self):
        self.loop = None
        self.clients = set()
        self.jog_owners = {}

    def publish_from_thread(self, axis, values):
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(
                self.broadcast({"type": "axis_update", "axis": axis,
                                "values": values}), self.loop)

    async def broadcast(self, message):
        dead = []
        for client in tuple(self.clients):
            try: await client.send_json(message)
            except Exception: dead.append(client)
        for client in dead: self.clients.discard(client)


def create_app(manager, gui_config, token):
    hub = EventHub()
    manager.update_callback = hub.publish_from_thread

    @asynccontextmanager
    async def lifespan(_app):
        hub.loop = asyncio.get_running_loop()
        await asyncio.to_thread(manager.restore)
        yield
        for message in await asyncio.to_thread(manager.shutdown):
            print(f"KOHZU GUI shutdown warning: {message}", file=sys.stderr)

    app = FastAPI(lifespan=lifespan)

    def authorize(value):
        if not value or not secrets.compare_digest(value, token):
            raise HTTPException(403, "invalid write token")

    @app.get("/")
    async def index():
        return FileResponse(PROJECT / "gui" / "static" / "index.html")

    @app.get("/api/config")
    async def config():
        return {**gui_config, "prefix": manager.applicator.prefix,
                "token": token, "panels": manager.list()}

    @app.post("/api/panels")
    async def create_panel(body: PanelRequest, x_kohzu_token: str = Header("")):
        authorize(x_kohzu_token)
        try:
            result = await asyncio.to_thread(manager.create, body.axis, body.model)
            await hub.broadcast({"type": "panel_ready", "panel": result})
            await hub.broadcast({"type": "axis_update", "axis": body.axis,
                                 "values": manager.sessions[body.axis].snapshot()})
            return result
        except Exception as error:
            raise HTTPException(502, str(error)) from error

    @app.delete("/api/panels/{axis}")
    async def delete_panel(axis: int, x_kohzu_token: str = Header("")):
        authorize(x_kohzu_token)
        try:
            result = await asyncio.to_thread(manager.delete, axis)
            await hub.broadcast({"type": "panel_removed", "axis": axis})
            return result
        except Exception as error:
            raise HTTPException(502, str(error)) from error

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        supplied = websocket.query_params.get("token", "")
        if not secrets.compare_digest(supplied, token):
            await websocket.close(code=1008); return
        await websocket.accept(); hub.clients.add(websocket)
        await websocket.send_json({"type": "hello", "panels": manager.list(),
                                   "snapshots": manager.snapshots()})
        send_lock = asyncio.Lock()
        background = set()
        controlled_axes = set()

        async def run_move(command):
            try:
                result = await asyncio.to_thread(
                    manager.move, command["axis"], command.get("mode"),
                    command.get("value"))
                message = {"type": "command_result", "id": command.get("id"),
                           "result": result}
            except Exception as error:
                message = {"type": "command_error", "id": command.get("id"),
                           "error": str(error)}
            async with send_lock:
                await websocket.send_json(message)

        try:
            while True:
                command = await websocket.receive_json()
                request_id = command.get("id")
                kind, axis = command.get("type"), command.get("axis")
                if not isinstance(axis, int):
                    raise ValueError("command axis must be an integer")
                controlled_axes.add(axis)
                if kind == "jog_start":
                    result = await asyncio.to_thread(
                        manager.jog_start, axis, command.get("direction"))
                    hub.jog_owners[axis] = websocket
                elif kind == "jog_stop":
                    result = await asyncio.to_thread(manager.jog_stop, axis)
                    hub.jog_owners.pop(axis, None)
                elif kind == "stop":
                    result = await asyncio.to_thread(manager.stop, axis)
                    hub.jog_owners.pop(axis, None)
                elif kind == "move":
                    task = asyncio.create_task(run_move(dict(command)))
                    background.add(task)
                    task.add_done_callback(background.discard)
                    continue
                elif kind == "field_write":
                    result = await asyncio.to_thread(
                        manager.write_field, axis, command.get("field"),
                        command.get("value"))
                else:
                    raise ValueError(f"unsupported command {kind!r}")
                async with send_lock:
                    await websocket.send_json({"type": "command_result",
                                               "id": request_id, "result": result})
        except WebSocketDisconnect:
            pass
        except Exception as error:
            try: await websocket.send_json({"type": "command_error",
                                            "id": command.get("id"),
                                            "error": str(error)})
            except Exception: pass
        finally:
            hub.clients.discard(websocket)
            owned = [a for a, owner in hub.jog_owners.items() if owner is websocket]
            await asyncio.to_thread(
                manager.stop_axes,
                set(owned) | (controlled_axes & manager.moving_axes),
            )
            for axis in owned: hub.jog_owners.pop(axis, None)
            if background:
                await asyncio.gather(*background, return_exceptions=True)

    app.mount("/", StaticFiles(directory=PROJECT / "gui" / "static"), name="static")
    return app


def main() -> int:
    runtime_path, runtime = runtime_from_argv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-config", type=pathlib.Path,
                        default=runtime_path)
    parser.add_argument("--listen", default=runtime.gui_listen)
    parser.add_argument("--port", type=int, default=runtime.gui_port)
    parser.add_argument("--move-timeout", type=float,
                        default=runtime.gui_move_timeout)
    parser.add_argument("--prefix", default=runtime.epics_prefix)
    parser.add_argument("--models", type=pathlib.Path,
                        default=PROJECT / "config" / "stage-models.ini")
    parser.add_argument("--axes", type=pathlib.Path,
                        default=PROJECT / "config" / "axis-assignments.ini")
    parser.add_argument("--epics-bin", type=pathlib.Path,
                        default=runtime.epics_bin)
    arguments = parser.parse_args()
    try:
        if not arguments.listen.strip():
            raise ValueError("GUI listen address must not be empty")
        if not 1 <= arguments.port <= 65535:
            raise ValueError("GUI port must be between 1 and 65535")
        if arguments.move_timeout <= 0:
            raise ValueError("GUI move timeout must be greater than zero")
        if not PREFIX_PATTERN.fullmatch(arguments.prefix):
            raise ValueError("invalid PV prefix")
        gui_config = load_gui_configuration(arguments.models)
        applicator = ModelApplicator(
            arguments.epics_bin, arguments.prefix, arguments.models)
        from kohzu_motion import BlueskyMotionExecutor
        manager = PanelManager(
            AssignmentStore(arguments.axes, arguments.models), applicator,
            BlueskyMotionExecutor(
                arguments.prefix, move_timeout=arguments.move_timeout),
        )
        write_token = secrets.token_urlsafe(32)
        app = create_app(manager, gui_config, write_token)
        if arguments.listen not in {"127.0.0.1", "::1", "localhost"}:
            print(
                "WARNING: GUI is exposed beyond loopback without user "
                "authentication or TLS; use only on a trusted network.",
                file=sys.stderr,
            )
        print(f"KOHZU GUI listening on http://{arguments.listen}:{arguments.port}")
        uvicorn.run(app, host=arguments.listen, port=arguments.port,
                    log_level="info", access_log=False)
    except (ValueError, configparser.Error, OSError) as error:
        print(f"Cannot start KOHZU GUI: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
