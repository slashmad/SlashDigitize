"""Standalone host helper: only the parent controls graceful recorder stop.

Sent as Python source to flatpak-spawn so the host needs no installed package.
Media stays in arecord's output WAV; the control pipe contains only 'stop'.
"""
import json
import os
import signal
import subprocess
import sys
import threading


def run(command, forward_stdout=False):
    process = None
    stopping = False

    def interrupt(*_args):
        nonlocal stopping
        stopping = True
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                               stdout=sys.stdout if forward_stdout else subprocess.DEVNULL,
                               stderr=sys.stderr, start_new_session=True)
    if stopping:
        interrupt()

    def controls():
        for line in sys.stdin:
            if line.strip() == "stop":
                interrupt()
        # A disconnected GUI must still request WAV finalization.
        interrupt()

    threading.Thread(target=controls, daemon=True).start()
    result = process.wait()
    return result if result >= 0 else 128 - result


if __name__ == "__main__":
    try:
        raise SystemExit(run(json.loads(sys.argv[1]), len(sys.argv) > 2 and sys.argv[2] == "stdout"))
    except OSError as error:
        print(f"arecord host helper: {error}", file=sys.stderr, flush=True)
        raise SystemExit(127)
