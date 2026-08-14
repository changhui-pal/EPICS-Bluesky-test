import pathlib
import sys


PROJECT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "gui"))

from kohzu_motion import BlueskyMotionExecutor


class FakeMotor:
    def __init__(self, pv, name):
        self.pv = pv
        self.name = name
        self.stops = 0
        self.jog_forward = FakeSignal()
        self.jog_reverse = FakeSignal()

    def stop(self, success=False):
        assert success is False
        self.stops += 1

    def wait_for_connection(self, timeout):
        assert timeout == 5.0


class FakeSignal:
    def __init__(self):
        self.writes = []

    def put(self, value, *, wait, timeout=None):
        self.writes.append((value, wait, timeout))


def test_motion_executor_serializes_plan_through_runner_and_stops_motor():
    plans = []
    motors = []

    def motor_factory(pv, name):
        motor = FakeMotor(pv, name)
        motors.append(motor)
        return motor

    executor = BlueskyMotionExecutor(
        "TEST:", runner_factory=lambda: plans.append,
        motor_factory=motor_factory,
        plan_factory=lambda motor, target: (motor.pv, target),
    )
    try:
        assert executor.submit(3, 1.25).result(timeout=2) == 1.25
        assert plans == [("TEST:m3", 1.25)]
        assert executor.stop(3) is True
        assert motors[0].stops == 1
        assert executor.stop(4) is False
        executor.jog(3, forward=True)
        executor.jog(3, forward=False)
        assert motors[0].jog_forward.writes == [(1, False, None)]
        assert motors[0].jog_reverse.writes == [(1, False, None)]
    finally:
        executor.close()

    assert motors[0].stops == 1
