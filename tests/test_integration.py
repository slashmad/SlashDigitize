import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from slashdigitize.jobs import JobRegistry
from slashdigitize.video.encode import build_ffmpeg_command
from slashdigitize.video.runner import FFmpegRunner


class JobTests(unittest.TestCase):
    def test_pixel_format_table_accepts_five_flags_and_skips_legend(self):
        from slashdigitize.video.ffmpeg import _parse_pixel_formats
        table = "Pixel formats:\nI.... = Supported Input format\nFLAGS NAME NB_COMPONENTS BITS_PER_PIXEL BIT_DEPTHS\nIO... yuv420p 3 12 8-8-8\n..H.. cuda 0 0 0\n"
        self.assertEqual([item.name for item in _parse_pixel_formats(table)], ["yuv420p", "cuda"])

    def test_unknown_capture_state_blocks_shutdown_and_reuse(self):
        jobs = JobRegistry()
        def unavailable():
            raise RuntimeError("state unavailable")
        jobs.register("recorder", unavailable, capture=True)
        self.assertEqual(jobs.active(), ["recorder"])
        self.assertEqual(jobs.capture_blocker("video"), "recorder")

    def test_xruns_split_across_reads_are_counted_once(self):
        from slashdigitize.audio.core import XrunCounter
        counter = XrunCounter()
        count = sum(counter.feed(part) for part in ["ov", "err", "un!!!\nxr", "un", "\nxrunning\nXR", "UN"])
        self.assertEqual(count + counter.finish(), 3)
        self.assertEqual(counter.finish(), 0)

    def test_capture_excludes_other_owner_but_export_can_run(self):
        jobs = JobRegistry()
        jobs.register("audio", lambda: True, capture=True)
        jobs.register("export", lambda: True)
        self.assertEqual(jobs.capture_blocker("video"), "audio")
        self.assertIsNone(jobs.capture_blocker("audio"))
        self.assertEqual(jobs.active(), ["audio", "export"])

    def test_h264_default_is_bounded_and_420_with_source_override(self):
        args = dict(ffmpeg_cmd=["ffmpeg"], list_file="input.ffconcat",
                    output_file="out.mp4", fps=25, codec="libx264", quality=20,
                    preset=None, tune=None, pix_fmt=None, extra_args=None)
        cmd = build_ffmpeg_command(**args)
        self.assertEqual(cmd[cmd.index("-pix_fmt") + 1], "yuv420p")
        self.assertIn("1920", cmd[cmd.index("-vf") + 1])
        self.assertNotIn("-vf", build_ffmpeg_command(**args, output_size=None))


class ProcessTests(unittest.TestCase):
    def test_native_stop_returns_before_finalization_and_drains_after_callback_error(self):
        ready = threading.Event()
        finished = threading.Event()
        lines = []
        def output(line):
            lines.append(line)
            if line == "READY":
                ready.set()
                raise RuntimeError("simulated UI failure")
        script = """import signal,time
stopped=False
def stop(*args):
 global stopped
 stopped=True
signal.signal(signal.SIGINT,stop)
print('READY',flush=True)
while not stopped: time.sleep(.01)
time.sleep(.2)
print('FINALIZED',flush=True)
"""
        with patch.dict(os.environ, {"FLATPAK_ID": "", "FLATPAK_SANDBOX_DIR": ""}):
            runner = FFmpegRunner(output, lambda code: finished.set())
            runner.start([sys.executable, "-u", "-c", script])
            try:
                self.assertTrue(ready.wait(3))
                started = time.monotonic()
                runner.stop()
                self.assertLess(time.monotonic() - started, .15)
                self.assertTrue(runner.running)
                self.assertTrue(finished.wait(3))
                self.assertIn("FINALIZED", lines)
                self.assertFalse(runner.running)
            finally:
                if runner.running:
                    runner.stop()
                    finished.wait(3)

    def test_host_bridge_control_and_disconnect_finalize_child(self):
        bridge = Path(__file__).parents[1] / "src/slashdigitize/host_bridge.py"
        import json
        script = """import signal,time,sys
stop=False
def handler(*args):
 global stop
 stop=True
signal.signal(signal.SIGINT,handler)
print('READY',file=sys.stderr,flush=True)
while not stop:time.sleep(.01)
time.sleep(.1)
print('FINALIZED',file=sys.stderr,flush=True)
"""
        for request in [b"stop\n", None]:
            with self.subTest(request=request):
                child = subprocess.Popen([sys.executable, "-u", str(bridge), json.dumps([sys.executable, "-u", "-c", script])],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.assertEqual(child.stderr.readline().strip(), b"READY")
                    if request:
                        child.stdin.write(request)
                        child.stdin.flush()
                    else:
                        child.stdin.close()
                        child.stdin = None
                    out, err = child.communicate(timeout=4)
                    self.assertEqual(child.returncode, 0)
                    self.assertIn(b"FINALIZED", err)
                finally:
                    if child.poll() is None:
                        child.stdin.close()
                        child.wait(timeout=4)
