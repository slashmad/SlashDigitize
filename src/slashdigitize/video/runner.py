from __future__ import annotations

import threading
from typing import Callable
from slashdigitize.process import BackendProcess


class FFmpegRunner:
    def __init__(
        self,
        on_output: Callable[[str], None],
        on_exit: Callable[[int], None],
    ) -> None:
        self._on_output = on_output
        self._on_exit = on_exit
        self._process: BackendProcess | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self, cmd: list[str]) -> None:
        if self._process is not None:
            raise RuntimeError("Process already running")

        process = BackendProcess(cmd, forward_output=True)
        self._process = process

        self._thread = threading.Thread(target=self._reader, args=(process,), daemon=True)
        self._thread.start()

    def _reader(self, process: BackendProcess) -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    if line:
                        try:
                            self._on_output(line.rstrip("\n"))
                        except Exception:
                            pass  # Keep draining if a UI consumer fails.
        finally:
            if process.stdout is not None:
                process.stdout.close()
            rc = process.wait()
            if self._process is process:
                self._process = None
            self._on_exit(rc)

    def stop(self) -> None:
        process = self._process
        if process is None:
            return

        # Return immediately. The reader owns drain/wait and finalization.
        # Never force TERM/KILL after an arbitrary recording timeout.
        process.interrupt()
