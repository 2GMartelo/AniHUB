"""Run blocking work (network, disk, DB) in the Qt thread pool and deliver results on the GUI thread."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Slot

from anihub.core.i18n import tr

log = logging.getLogger(__name__)


class _Bridge(QObject):
    """Lives in the GUI thread; emitting from a worker thread queues the call onto it."""

    deliver = Signal(object, object)  # (callback, argument)

    def __init__(self):
        super().__init__()
        self.deliver.connect(self._invoke)

    @Slot(object, object)
    def _invoke(self, callback, arg) -> None:
        try:
            callback(arg)
        except RuntimeError as exc:
            # Typically "Internal C++ object already deleted": the widget was closed while loading.
            log.debug("dropped callback: %s", exc)


_bridge: _Bridge | None = None


def _get_bridge() -> _Bridge:
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()
    return _bridge


class _Runnable(QRunnable):
    def __init__(self, fn: Callable, args: tuple, on_done, on_error, bridge: _Bridge):
        super().__init__()
        self.fn, self.args = fn, args
        self.on_done, self.on_error, self.bridge = on_done, on_error, bridge

    def run(self) -> None:
        try:
            result = self.fn(*self.args)
        except Exception as exc:  # noqa: BLE001 - forwarded to the GUI thread
            log.warning("worker failed: %s", exc, exc_info=True)
            self._deliver(self.on_error, exc)
        else:
            self._deliver(self.on_done, result)

    def _deliver(self, callback, arg) -> None:
        if callback is None:
            return
        try:
            self.bridge.deliver.emit(callback, arg)
        except RuntimeError:
            pass  # the application is shutting down and the bridge is already gone


_thumb_pool: QThreadPool | None = None


def thumb_pool() -> QThreadPool:
    """A small, low-priority pool for thumbnails: a page of them used to be handed to the global pool (one thread per
    core), so decoding a couple of hundred pictures kept every core busy and the window lagged for seconds."""
    global _thumb_pool
    if _thumb_pool is None:
        _thumb_pool = QThreadPool()
        _thumb_pool.setMaxThreadCount(4)
        _thumb_pool.setThreadPriority(QThread.Priority.LowPriority)
    return _thumb_pool


def run_async(fn: Callable, *args, on_done: Callable | None = None, on_error: Callable | None = None,
              pool: QThreadPool | None = None) -> None:
    """Call from the GUI thread. `on_done(result)` / `on_error(exc)` run on the GUI thread."""
    (pool or QThreadPool.globalInstance()).start(_Runnable(fn, args, on_done, on_error, _get_bridge()))


def run_status(fn: Callable, *args, status, on_done: Callable | None = None, pool: QThreadPool | None = None) -> None:
    """`run_async` with the error branch every *View class was hand-writing the same way: show `status.error` on
    the given label (a QLabel, or anything with `.setText`)."""
    run_async(fn, *args, on_done=on_done, on_error=lambda exc: status.setText(tr("status.error", msg=str(exc))), pool=pool)


def post_to_gui(callback: Callable, arg=None) -> None:
    """Queue `callback(arg)` onto the GUI thread; safe to call from any thread, including from inside a `run_async`
    `fn` that wants to report progress partway through instead of only at on_done -- e.g. a long batch that hands
    back each of its own pieces as they finish, not just the final combined result."""
    try:
        _get_bridge().deliver.emit(callback, arg)
    except RuntimeError:
        pass  # the application is shutting down and the bridge is already gone
