"""Recorder transport; native signals and Flatpak host control stay distinct."""
import json
import os
from pathlib import Path
import signal
import subprocess


def is_flatpak():
    return bool(os.environ.get("FLATPAK_ID") or os.environ.get("FLATPAK_SANDBOX_DIR"))


def host_command(command):
    return ["flatpak-spawn", "--host", *command] if is_flatpak() else command


class BackendProcess:
    def __init__(self, command, *, forward_output=False):
        self.host = is_flatpak()
        self.forward_output = forward_output
        if command[:2] == ["flatpak-spawn", "--host"]:
            command = command[2:]
        if self.host:
            bridge = Path(__file__).with_name("host_bridge.py").read_text()
            command = ["flatpak-spawn", "--host", "--watch-bus", "/usr/bin/python3",
                       "-u", "-c", bridge, json.dumps(command), "stdout" if forward_output else "quiet"]
        self.transport = subprocess.Popen(
            command, stdin=subprocess.PIPE if self.host else subprocess.DEVNULL,
            stdout=subprocess.PIPE if forward_output else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if forward_output else subprocess.PIPE,
            text=forward_output, bufsize=1 if forward_output else -1, start_new_session=True)
        self.stdout = self.transport.stdout
        self.stderr = self.transport.stderr
        self.pid = self.transport.pid

    def poll(self):
        return self.transport.poll()

    def wait(self):
        try:
            return self.transport.wait()
        finally:
            if self.transport.stdin:
                self.transport.stdin.close()

    def interrupt(self):
        if self.poll() is not None:
            return
        try:
            if self.host:
                self.transport.stdin.write("stop\n" if self.forward_output else b"stop\n")
                self.transport.stdin.flush()
            else:
                os.killpg(self.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
