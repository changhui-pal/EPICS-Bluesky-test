"""Unit tests for the persistent Ophyd/WebSocket GUI backend."""

import concurrent.futures
import importlib.util
import pathlib
import sys
import tempfile
from unittest import mock

import pytest

PROJECT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "gui"))
SPEC = importlib.util.spec_from_file_location(
    "kohzu_gui_server", PROJECT / "gui" / "kohzu_gui_server.py")
GUI = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GUI
SPEC.loader.exec_module(GUI)


def values(**updates):
    result = {
        ".RBV": "1", ".EGU": "mm", "_able": "Enable", ".MOVN": "0",
        ".DMOV": "1", ".HLS": "0", ".LLS": "0", ".LVIO": "0",
        ".MRES": "0.0005", ".LLM": "-24.5", ".HLM": "24.5",
        ".SET": "Use", ".SPMG": "Go", ".DIR": "Pos",
    }
    result.update(updates)
    return result


class FakeSession:
    instances = {}

    def __init__(self, axis, prefix, update_callback=None):
        self.axis = axis
        self.motor = object()
        self.command_lock = __import__("threading").RLock()
        self.data = values()
        self.writes = []
        self.jogs = []
        self.stops = 0
        self.closed = False
        self.homes = []
        self.signals = {":OriginMethod": mock.Mock()}
        self.signals[":OriginMethod"].get.side_effect = \
            lambda **_kwargs: int(self.data.get(":OriginMethod", 4))
        self.update_callback = update_callback
        self.instances[axis] = self

    def snapshot(self): return dict(self.data)
    def put(self, suffix, value, **_kwargs):
        self.writes.append((suffix, value)); self.data[suffix] = str(value)
    def jog(self, forward): self.jogs.append(forward)
    def stop(self): self.stops += 1
    def home(self, timeout): self.homes.append(timeout); self.data[".RBV"] = "0"
    def close(self): self.closed = True


class FakeStore:
    def __init__(self): self.items = {}; self.methods = {}
    def panels(self):
        return [{"axis": a, "model": m, "enabled": e}
                for a, (m, e) in self.items.items()]
    def assign(self, axis, model, enabled): self.items[axis] = (model, enabled)
    def set_enabled(self, axis, enabled):
        self.items[axis] = (self.items[axis][0], enabled)
    def remove(self, axis): self.items.pop(axis)
    def home_method(self, axis): return self.methods.get(axis, 4)
    def set_home_method(self, axis, method): self.methods[axis] = method


def manager():
    store = FakeStore()
    applicator = mock.Mock(prefix="TEST:")
    applicator.prefix = "TEST:"
    applicator.apply.side_effect = lambda axis, model: {
        "axis": axis, "model": model, "record": f"TEST:m{axis}",
        "enabled": False,
    }
    motion = mock.Mock()
    future = concurrent.futures.Future(); future.set_result(None)
    motion.submit.return_value = future
    return GUI.PanelManager(store, applicator, motion,
                            session_factory=FakeSession), store, motion


def test_move_plans_quantize_and_validate():
    assert GUI.plan_user_move(values(), "absolute", 1.00126)["target"] == 1.0015
    assert GUI.plan_user_move(values(), "relative", -0.00126)["target"] == 0.9985
    with pytest.raises(ValueError, match="Disabled"):
        GUI.plan_user_move(values(**{"_able": "Disable"}), "absolute", 1)


def test_model_plan_contains_only_model_owned_fields():
    plan = GUI.build_model_plan(7, "RA04A-W01", PROJECT / "config/stage-models.ini")
    fields = dict(plan.fields)
    assert (fields["MRES"], fields["JAR"], fields["HVEL"]) == ("0.002", "3.6", "2")
    assert "DIR" not in fields and ":OriginMethod" not in fields


def test_panel_lifecycle_connects_before_enable_and_reuses_motor():
    control, store, motion = manager()
    result = control.create(6, "RA04A-W01")
    session = FakeSession.instances[6]
    assert result["enabled"] is True
    assert session.writes[:2] == [(":OriginMethod", 4), ("_able", "Enable")]
    motion.register_motor.assert_called_once_with(6, session.motor)
    assert store.items[6] == ("RA04A-W01", True)
    assert control.delete(6)["enabled"] is False
    assert session.writes[-1] == ("_able", "Disable") and session.closed
    assert 6 not in store.items


def test_jog_and_fields_use_persistent_session_not_applicator_ca():
    control, _, _ = manager(); control.create(1, "XA05A-L202")
    session = FakeSession.instances[1]
    assert control.jog_start(1, "cw")["forward"] is True
    assert session.jogs == [True]
    control.jog_stop(1)
    assert session.stops == 1
    result = control.write_field(1, ".VELO", 0.25)
    assert result["requested"] == 0.25
    assert session.writes[-1] == (".VELO", 0.25)
    assert not hasattr(GUI.ModelApplicator, "read_status")


def test_bluesky_move_uses_registered_session_motor():
    control, _, motion = manager(); control.create(1, "XA05A-L202")
    session = FakeSession.instances[1]
    session.data[".RBV"] = "1.0015"
    result = control.move(1, "absolute", 1.00126)
    motion.submit.assert_called_once_with(1, 1.0015)
    assert result["final"] == 1.0015


def test_home_method_is_persistent_and_home_uses_same_session():
    control, store, _ = manager(); control.create(1, "XA05A-L202")
    session = FakeSession.instances[1]
    assert control.set_home_method(1, 10) == {"axis": 1, "home_method": 10}
    assert store.methods[1] == 10
    result = control.home(1)
    assert session.homes == [180.0]
    assert result == {"axis": 1, "home_method": 10, "final": 0.0,
                      "egu": "mm", "done": True}


@pytest.mark.parametrize("method", [0, 16, 1.5, True])
def test_home_method_rejects_out_of_range_or_non_integer(method):
    control, _, _ = manager(); control.create(1, "XA05A-L202")
    with pytest.raises(ValueError, match="1..15"):
        control.set_home_method(1, method)


def test_configuration_exposes_catalog_and_32_axes():
    config = GUI.load_gui_configuration(PROJECT / "config/stage-models.ini")
    assert len(config["models"]) == 5
    assert config["axes"] == list(range(1, 33))


def test_assignment_store_preserves_model_on_shutdown_and_clears_on_delete():
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "axes.ini"
        path.write_text("".join(f"[axis:{a}]\nenabled = false\n" for a in range(1, 33)))
        store = GUI.AssignmentStore(path, PROJECT / "config/stage-models.ini")
        store.assign(6, "RA04A-W01", enabled=True)
        store.set_enabled(6, False)
        assert store.panels() == [{"axis": 6, "model": "RA04A-W01", "enabled": False}]
        store.remove(6)
        assert store.panels() == []
