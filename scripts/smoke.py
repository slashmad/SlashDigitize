"""Run GTK UI checks in an isolated headless Weston display (Linux only)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="slash-gtk-smoke-") as folder:
    env = {**os.environ, "XDG_RUNTIME_DIR": folder, "WAYLAND_DISPLAY": "slash-gtk-test", "GDK_BACKEND": "wayland", "GSK_RENDERER": "cairo", "PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    with open(Path(folder) / "weston.log", "w+") as log:
        display = subprocess.Popen(["weston", "--backend=headless", "--width=1440", "--height=1000", "--socket=slash-gtk-test", "--idle-time=0"], env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while not (Path(folder) / "slash-gtk-test").exists():
                if display.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Headless Weston failed to start")
                time.sleep(.03)
            subprocess.run([sys.executable, "-B", "-m", "unittest", "tests.test_rows"], cwd=root, env=env, check=True, timeout=40)
            subprocess.run([sys.executable, "-B", str(root / "tests/ui_driver.py")], cwd=root, env=env, check=True, timeout=60)
        finally:
            display.terminate()
            try: display.wait(timeout=3)
            except subprocess.TimeoutExpired: display.kill(); display.wait()
