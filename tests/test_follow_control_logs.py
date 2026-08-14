import pathlib
import subprocess
import sys
import time


PROJECT = pathlib.Path(__file__).resolve().parents[1]


def test_log_follower_prefixes_and_preserves_each_source(tmp_path):
    ioc = tmp_path / "ioc.log"
    gui = tmp_path / "gui.log"
    session = tmp_path / "session.log"
    ioc.write_text("IOC ready\n", encoding="utf-8")
    gui.write_text("", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable, str(PROJECT / "tools" / "follow_control_logs.py"),
            "--session", str(session),
            "--source", f"IOC={ioc}", "--source", f"GUI={gui}",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        time.sleep(0.2)
        with gui.open("a", encoding="utf-8") as stream:
            stream.write("panel connected\n")
        time.sleep(0.2)
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=3)

    assert process.returncode == 0, stderr
    assert "[IOC] IOC ready" in stdout
    assert "[GUI] panel connected" in stdout
    assert "[IOC] IOC ready" in session.read_text(encoding="utf-8")
    assert "[GUI] panel connected" in session.read_text(encoding="utf-8")
