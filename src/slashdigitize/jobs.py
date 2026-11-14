"""Authoritative job queries shared by tabs and Close/Quit actions."""
from collections.abc import Callable


class JobRegistry:
    def __init__(self):
        self._jobs: dict[str, tuple[Callable[[], bool], bool]] = {}

    def register(self, name: str, running: Callable[[], bool], *, capture=False):
        if name in self._jobs:
            raise ValueError(f"Duplicate job: {name}")
        self._jobs[name] = running, capture

    def active(self) -> list[str]:
        return [name for name, (running, _) in self._jobs.items() if self._busy(running)]

    @staticmethod
    def _busy(running):
        try:
            return bool(running())
        except Exception:
            # An unreadable job state cannot authorize shutdown/device reuse.
            return True

    def capture_blocker(self, owner: str) -> str | None:
        return next((name for name, (running, capture) in self._jobs.items()
                     if capture and name != owner and self._busy(running)), None)
