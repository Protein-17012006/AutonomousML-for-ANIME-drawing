"""Bounded process-local admission for session/GPU work.

The HTTP adapter may have many concurrent clients, but it must not create an
unbounded number of worker threads or queue arbitrary amounts of GPU work.
"""
from __future__ import annotations

import threading

from service.core.config import (
    max_concurrent_gpu_jobs,
    max_concurrent_sessions,
    runtime_queue_size,
    runtime_queue_timeout_seconds,
)
from service.core.errors import RuntimeBusy, UnknownEngine


class AdmissionLease:
    """Idempotent release handle suitable for ownership by a worker thread."""

    def __init__(self, controller: "AdmissionController"):
        self._controller = controller
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._controller._release()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.release()


class AdmissionController:
    def __init__(self, capacity: int, queue_size: int, timeout: float):
        self.capacity = max(1, int(capacity))
        self.queue_size = max(0, int(queue_size))
        self.timeout = max(0.0, float(timeout))
        self._slots = threading.BoundedSemaphore(self.capacity)
        self._state_lock = threading.Lock()
        self._active = 0
        self._waiting = 0

    def acquire(self) -> AdmissionLease:
        # Fast path: an idle slot never consumes queue capacity.
        if self._slots.acquire(blocking=False):
            with self._state_lock:
                self._active += 1
            return AdmissionLease(self)

        with self._state_lock:
            if self._waiting >= self.queue_size:
                raise RuntimeBusy(
                    f"runtime busy: {self._active} active job(s), "
                    f"queue limit {self.queue_size} reached"
                )
            self._waiting += 1

        try:
            admitted = self._slots.acquire(timeout=self.timeout)
        finally:
            with self._state_lock:
                self._waiting -= 1
        if not admitted:
            raise RuntimeBusy(
                f"runtime busy: timed out after {self.timeout:g}s waiting for capacity"
            )
        with self._state_lock:
            self._active += 1
        return AdmissionLease(self)

    def _release(self) -> None:
        with self._state_lock:
            self._active -= 1
        self._slots.release()

    def snapshot(self) -> tuple[int, int]:
        with self._state_lock:
            return self._active, self._waiting


_QUEUE_SIZE = runtime_queue_size()
_TIMEOUT = runtime_queue_timeout_seconds()
_BOX_ADMISSION = AdmissionController(
    max_concurrent_gpu_jobs(), _QUEUE_SIZE, _TIMEOUT)
_STUB_ADMISSION = AdmissionController(
    max_concurrent_sessions(), _QUEUE_SIZE, _TIMEOUT)


def engine_admission(name: str) -> AdmissionController:
    if name == "box":
        return _BOX_ADMISSION
    if name == "stub":
        return _STUB_ADMISSION
    raise UnknownEngine(f"Unknown engines: {name!r}")
