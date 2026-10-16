"""Bounded media reconstruction with a deadline shared by queueing and work."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from open_webui.utils.otel_instrumentation import add_metric_counter


class ReconstructionTimeout(TimeoutError):
    def __init__(self, partial_result=None):
        self.partial_result = partial_result
        super().__init__("Media reconstruction deadline exceeded")


class ReconstructionFailure(RuntimeError):
    def __init__(self, partial_result=None):
        self.partial_result = partial_result
        super().__init__("Media reconstruction failed")


@dataclass(eq=False)
class ReconstructionControl:
    deadline: float
    cancelled: threading.Event = field(default_factory=threading.Event)
    source_changed: set[str] = field(default_factory=set)
    partial_result: object = None
    resources: ExitStack = field(default_factory=ExitStack)
    source_cache: dict = field(default_factory=dict)

    @property
    def stopped(self) -> bool:
        return self.cancelled.is_set() or time.monotonic() >= self.deadline

    def timeout(self, maximum: float) -> float:
        if self.stopped:
            raise ReconstructionTimeout()
        return min(maximum, self.deadline - time.monotonic())


class ReconstructionExecutor:
    """Keep capacity assigned until the real worker exits, even on cancellation."""

    def __init__(self, workers: int = 2, budget_seconds: float = 30):
        self.budget_seconds = budget_seconds
        self._executor = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="media_reconstruction"
        )
        self._capacity = asyncio.BoundedSemaphore(workers)
        self._controls: set[ReconstructionControl] = set()
        self._closed = False

    async def reconstruct(self, sources: list[dict], *, request=None, **kwargs):
        from open_webui.retrieval.visuals import reconstruct_and_sanitize_sources

        control = ReconstructionControl(time.monotonic() + self.budget_seconds)
        acquired = False
        submitted = False
        disconnect_task = None

        async def wait_for_disconnect():
            while not await request.is_disconnected():
                await asyncio.sleep(0.25)

        def run_reconstruction():
            with control.resources:
                return reconstruct_and_sanitize_sources(
                    sources, control=control, **kwargs
                )

        try:
            await asyncio.wait_for(
                self._capacity.acquire(), timeout=control.timeout(self.budget_seconds)
            )
            acquired = True
            if self._closed:
                raise RuntimeError("Media reconstruction is shutting down")
            if request is not None and await request.is_disconnected():
                raise asyncio.CancelledError()
            control.timeout(self.budget_seconds)
            loop = asyncio.get_running_loop()
            self._controls.add(control)
            future = self._executor.submit(run_reconstruction)
            submitted = True

            def release_capacity():
                self._controls.discard(control)
                self._capacity.release()

            def worker_finished(_future):
                # asyncio cancellation must not release an occupied worker slot.
                if not loop.is_closed():
                    loop.call_soon_threadsafe(release_capacity)

            future.add_done_callback(worker_finished)
            wrapped = asyncio.wrap_future(future)
            # Retrieve late exceptions even if the client has already disconnected.
            wrapped.add_done_callback(
                lambda result: None if result.cancelled() else result.exception()
            )
            if request is not None:
                disconnect_task = asyncio.create_task(wait_for_disconnect())
                completed, _ = await asyncio.wait(
                    {wrapped, disconnect_task},
                    timeout=control.timeout(self.budget_seconds),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if wrapped in completed:
                    result = wrapped.result()
                    if result.timed_out:
                        add_metric_counter("retrieval.reconstruction.timeout")
                    return result
                if disconnect_task in completed:
                    disconnect_task.result()
                    raise asyncio.CancelledError()
                raise ReconstructionTimeout()
            return await asyncio.wait_for(
                asyncio.shield(wrapped), timeout=control.timeout(self.budget_seconds)
            )
        except TimeoutError:
            control.cancelled.set()
            add_metric_counter("retrieval.reconstruction.timeout")
            raise ReconstructionTimeout(control.partial_result) from None
        except asyncio.CancelledError:
            control.cancelled.set()
            raise
        except Exception:
            control.cancelled.set()
            raise ReconstructionFailure(control.partial_result) from None
        finally:
            if disconnect_task is not None:
                disconnect_task.cancel()
                await asyncio.gather(disconnect_task, return_exceptions=True)
            if acquired and not submitted:
                self._controls.discard(control)
                self._capacity.release()

    async def shutdown(self):
        self._closed = True
        for control in list(self._controls):
            control.cancelled.set()
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)
