"""GUI-side supervisor for a ManagedProcess (Forge, Suwayomi): polls the state, starts/stops on request,
stops an idle service to free resources."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer, Signal

from anihub.services.procservice import ManagedProcess, ServiceState as ForgeState
from anihub.ui.workers import run_async

POLL_MS = 2000
IDLE_CHECK_MS = 30_000


class ServiceController(QObject):
    state_changed = Signal(str)  # ForgeState value
    error = Signal(str)

    def __init__(self, manager: ManagedProcess, idle_minutes=lambda: 0, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._idle_minutes = idle_minutes  # callable: reads the live setting
        self._polling = False
        self._busy = False
        self._last_activity = time.monotonic()
        self._last_state: ForgeState | None = None
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll)
        self.poll_timer.start(POLL_MS)
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self._check_idle)
        self.idle_timer.start(IDLE_CHECK_MS)

    @property
    def state(self) -> ForgeState:
        return self.manager.state

    def poll(self) -> None:
        if self._polling:
            return
        self._polling = True

        def done(state: ForgeState) -> None:
            self._polling = False
            self._publish(state)

        def failed(_exc) -> None:
            self._polling = False

        run_async(self.manager.refresh, on_done=done, on_error=failed)

    def _publish(self, state: ForgeState) -> None:
        if state != self._last_state:
            self._last_state = state
            self.state_changed.emit(state.value)

    def start(self) -> None:
        self.touch()

        def done(state: ForgeState) -> None:
            self._publish(state)

        run_async(self.manager.start, on_done=done, on_error=lambda exc: self.error.emit(str(exc)))

    def stop(self) -> None:
        def done(_):
            self._publish(ForgeState.STOPPED)

        run_async(self.manager.stop, on_done=done)

    def stop_blocking(self) -> None:
        """For application shutdown."""
        self.manager.stop()

    def touch(self) -> None:
        self._last_activity = time.monotonic()

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.touch()

    def pause_polling(self) -> None:
        """Stops the 2-second state poll while nobody is looking at this service's tab -- skipped outright while an
        active job is running (set_busy(True)), so progress/completion is never silently missed just because the
        user switched away. The idle-shutdown timer (stopping a truly idle Forge) is separate and keeps running."""
        if self._busy:
            return
        self.poll_timer.stop()

    def resume_polling(self) -> None:
        """The moment the tab is visible again: back to the normal cadence, plus one poll right away."""
        if not self.poll_timer.isActive():
            self.poll_timer.start(POLL_MS)
            self.poll()

    def _check_idle(self) -> None:
        minutes = self._idle_minutes()
        if (minutes and not self._busy and self.manager.state == ForgeState.RUNNING
                and time.monotonic() - self._last_activity > minutes * 60):
            self.stop()  # only ever stops a Forge that AniHUB started itself


ForgeController = ServiceController  # original name, still used by the SD page
