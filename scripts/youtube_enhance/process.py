"""Bounded, monitored execution for workflow subprocesses."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Hashable, Mapping, Protocol, Sequence


_READ_BYTES = 64 * 1024
_QUEUE_CHUNKS = 8
_HEARTBEAT_SECONDS = 30.0


@dataclass(frozen=True)
class MonitoredResult:
    args: Sequence[str]
    returncode: int
    stdout_tail: bytes
    stderr_tail: bytes
    elapsed_seconds: float
    output_bytes: int


class MonitoredRunner(Protocol):
    """Callable with the ``run_monitored`` signature."""

    def __call__(
        self,
        command: Sequence[str],
        *,
        stdout_consumer: Callable[[bytes], None] | None,
        activity_callback: Callable[[str, Mapping[str, Any]], None] | None,
        activity_probes: Sequence[Callable[[], Hashable]] = (),
        inactivity_seconds: float = 600.0,
        tail_bytes: int = 1_048_576,
        cwd: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], None] = time.sleep,
        check: bool = True,
    ) -> MonitoredResult: ...


class MonitoredProcessError(RuntimeError):
    """A monitored subprocess ended without a successful result."""

    def __init__(self, result: MonitoredResult, *, delivery_worker_alive: bool = False) -> None:
        self.result = result
        self.delivery_worker_alive = delivery_worker_alive
        super().__init__(
            f"command exited with status {result.returncode}: {list(result.args)!r}"
        )


class MonitoredProcessFailed(MonitoredProcessError):
    """Raised for a nonzero process exit when ``check`` is enabled."""


class MonitoredProcessStalled(MonitoredProcessError):
    """Raised after the process has been silent longer than the inactivity limit."""


class _Tail:
    """A byte-bounded deque that keeps the final part of one output stream."""

    def __init__(self, maximum: int) -> None:
        self._maximum = maximum
        self._chunks: deque[bytes] = deque()
        self._size = 0

    def append(self, chunk: bytes) -> None:
        if not self._maximum or not chunk:
            return
        if len(chunk) >= self._maximum:
            self._chunks.clear()
            self._chunks.append(chunk[-self._maximum :])
            self._size = self._maximum
            return

        self._chunks.append(chunk)
        self._size += len(chunk)
        while self._size > self._maximum:
            first = self._chunks[0]
            excess = self._size - self._maximum
            if len(first) <= excess:
                self._chunks.popleft()
                self._size -= len(first)
            else:
                self._chunks[0] = first[excess:]
                self._size -= excess

        # Limit Python-object overhead too when a pipe returns tiny reads.
        if len(self._chunks) > 16:
            combined = b"".join(self._chunks)
            self._chunks.clear()
            self._chunks.append(combined)

    def value(self) -> bytes:
        return b"".join(self._chunks)


def _claim_delivery_callback(
    delivery_lock: threading.Lock,
    delivery_cancelled: threading.Event,
    delivery_in_flight: threading.Event,
) -> bool:
    """Atomically either claim the next callback or observe cancellation."""
    with delivery_lock:
        if delivery_cancelled.is_set():
            return False
        delivery_in_flight.set()
        return True


def _expose_delivery_worker_state(error: BaseException, worker_alive: bool) -> None:
    """Keep a generic terminal error primary while reporting the worker state."""
    try:
        setattr(error, "delivery_worker_alive", worker_alive)
    except (AttributeError, TypeError):
        pass


class _WindowsJob:
    """A Windows job containing only the process tree created by this runner."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._handle: int | None = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("per_process_user_time_limit", ctypes.c_longlong),
                ("per_job_user_time_limit", ctypes.c_longlong),
                ("limit_flags", wintypes.DWORD),
                ("minimum_working_set_size", ctypes.c_size_t),
                ("maximum_working_set_size", ctypes.c_size_t),
                ("active_process_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority_class", wintypes.DWORD),
                ("scheduling_class", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "read_operation_count",
                "write_operation_count",
                "other_operation_count",
                "read_transfer_count",
                "write_transfer_count",
                "other_transfer_count",
            )]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("basic_limit_information", BasicLimitInformation),
                ("io_info", IoCounters),
                ("process_memory_limit", ctypes.c_size_t),
                ("job_memory_limit", ctypes.c_size_t),
                ("peak_process_memory_used", ctypes.c_size_t),
                ("peak_job_memory_used", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateJobObjectW(None, None)
        limits = ExtendedLimitInformation()
        limits.basic_limit_information.limit_flags = 0x00002000
        if (
            handle
            and kernel32.SetInformationJobObject(
                handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            )
            and kernel32.AssignProcessToJobObject(handle, process._handle)
        ):
            self._handle = handle
        elif handle:
            kernel32.CloseHandle(handle)
        if self._handle is None:
            _cleanup_windows_setup_failure(process, self)
            raise OSError("could not establish an owned Windows Job")
        try:
            self._resume_primary_thread(process.pid)
        except BaseException:
            _cleanup_windows_setup_failure(process, self)
            raise

    @staticmethod
    def _resume_primary_thread(process_id: int) -> None:
        """Resume the sole thread of a just-created suspended process."""
        import ctypes
        from ctypes import wintypes

        class ThreadEntry(ctypes.Structure):
            _fields_ = [
                ("size", wintypes.DWORD),
                ("usage", wintypes.DWORD),
                ("thread_id", wintypes.DWORD),
                ("owner_process_id", wintypes.DWORD),
                ("base_priority", ctypes.c_long),
                ("delta_priority", ctypes.c_long),
                ("flags", wintypes.DWORD),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = (wintypes.HANDLE, ctypes.POINTER(ThreadEntry))
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = (wintypes.HANDLE, ctypes.POINTER(ThreadEntry))
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
        kernel32.ResumeThread.restype = wintypes.DWORD
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
        invalid_handle = ctypes.c_void_p(-1).value
        if snapshot == invalid_handle:
            raise OSError(ctypes.get_last_error(), "could not enumerate process threads")
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            available = kernel32.Thread32First(snapshot, ctypes.byref(entry))
            while available:
                if entry.owner_process_id == process_id:
                    thread = kernel32.OpenThread(0x0002, False, entry.thread_id)
                    if not thread:
                        raise OSError(ctypes.get_last_error(), "could not open process thread")
                    try:
                        if kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                            raise OSError(ctypes.get_last_error(), "could not resume process thread")
                    finally:
                        kernel32.CloseHandle(thread)
                    return
                available = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        raise OSError("could not find the process primary thread")

    def terminate(self) -> bool:
        if self._handle is None:
            return False
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        return bool(kernel32.TerminateJobObject(self._handle, 1))

    def close(self) -> None:
        if self._handle is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


def _cleanup_windows_setup_failure(
    process: subprocess.Popen[bytes],
    job: _WindowsJob,
) -> None:
    """Best-effort cleanup that never replaces a Windows setup/resume error."""
    try:
        try:
            job.terminate()
        except BaseException:
            pass
        try:
            process_alive = process.poll() is None
        except BaseException:
            process_alive = True
        if process_alive:
            try:
                process.kill()
            except BaseException:
                pass
            try:
                process.wait(timeout=5)
            except BaseException:
                pass
    finally:
        try:
            job.close()
        except BaseException:
            pass


def _terminate_owned_process_tree(
    process: subprocess.Popen[bytes],
    job: _WindowsJob | None = None,
    *,
    process_group_id: int | None = None,
) -> None:
    """Terminate only the process group/tree rooted at ``process``."""
    if os.name == "nt":
        job_terminated = job is not None and job.terminate()
        if not job_terminated and process.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        # ``taskkill /T`` reaches descendants created in the narrow interval
        # before this Popen handle entered its Job Object.  The Job then kills
        # every descendant created after assignment, without touching peers.
        if not job_terminated and job is not None:
            job.terminate()
        if process.poll() is None:
            # ``taskkill`` can report before the root handle observes its exit.
            # The fallback is still limited to the Popen handle we created.
            process.kill()
    else:
        try:
            os.killpg(process_group_id if process_group_id is not None else process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_monitored(
    command: Sequence[str],
    *,
    stdout_consumer: Callable[[bytes], None] | None,
    activity_callback: Callable[[str, Mapping[str, Any]], None] | None,
    activity_probes: Sequence[Callable[[], Hashable]] = (),
    inactivity_seconds: float = 600.0,
    tail_bytes: int = 1_048_576,
    cwd: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    wait: Callable[[float], None] = time.sleep,
    check: bool = True,
) -> MonitoredResult:
    """Run a command while boundedly collecting diagnostic tails and activity."""
    if inactivity_seconds < 0:
        raise ValueError("inactivity_seconds must not be negative")
    if tail_bytes < 0:
        raise ValueError("tail_bytes must not be negative")

    args = tuple(command)
    start = clock()
    popen_options: dict[str, Any] = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
        "bufsize": 0,
        "shell": False,
    }
    if os.name == "nt":
        popen_options["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
        )
    else:
        popen_options["start_new_session"] = True

    process: subprocess.Popen[bytes] | None = None
    owned_process_group: int | None = None
    job: _WindowsJob | None = None
    events: queue.Queue[tuple[str, bytes]] = queue.Queue(maxsize=_QUEUE_CHUNKS)
    delivery_queue: queue.Queue[bytes | None] | None = (
        queue.Queue(maxsize=_QUEUE_CHUNKS) if stdout_consumer is not None else None
    )
    stdout_tail = _Tail(tail_bytes)
    stderr_tail = _Tail(tail_bytes)
    output_bytes = 0
    delivery_lock = threading.Lock()
    delivery_activity: float | None = None
    delivery_error: BaseException | None = None
    delivery_outstanding = 0
    delivery_in_flight = threading.Event()
    delivery_cancelled = threading.Event()
    reader_cancelled = threading.Event()
    readers: list[threading.Thread] = []
    consumer_thread: threading.Thread | None = None
    terminal_cleanup = False
    terminal_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    delivery_worker_alive = False
    normal_delivery_shutdown_error: RuntimeError | None = None
    stalled = False
    process_failed = False
    tree_terminated = False
    pending_event: tuple[str, bytes] | None = None
    eof_streams: set[str] = set()

    def cancel_pending_delivery() -> None:
        with delivery_lock:
            delivery_cancelled.set()

    def queue_reader_event(event: tuple[str, bytes]) -> None:
        while not reader_cancelled.is_set():
            try:
                events.put(event, timeout=0.05)
                return
            except queue.Full:
                continue

    def read_pipe(stream_name: str, pipe: Any) -> None:
        try:
            while chunk := os.read(pipe.fileno(), _READ_BYTES):
                queue_reader_event((stream_name, chunk))
        except OSError:
            pass
        finally:
            try:
                pipe.close()
            except OSError:
                pass
            queue_reader_event(("eof", stream_name.encode()))

    def deliver_stdout() -> None:
        nonlocal delivery_activity, delivery_error, delivery_outstanding
        assert delivery_queue is not None
        assert stdout_consumer is not None
        while True:
            try:
                chunk = delivery_queue.get(timeout=0.05)
            except queue.Empty:
                if delivery_cancelled.is_set():
                    return
                continue
            if chunk is None:
                return
            if not _claim_delivery_callback(
                delivery_lock,
                delivery_cancelled,
                delivery_in_flight,
            ):
                with delivery_lock:
                    delivery_outstanding -= 1
                continue
            try:
                stdout_consumer(chunk)
            except BaseException as error:
                with delivery_lock:
                    delivery_error = error
                    delivery_outstanding -= 1
                return
            finally:
                delivery_in_flight.clear()
            with delivery_lock:
                delivery_outstanding -= 1
                if not delivery_cancelled.is_set():
                    delivery_activity = clock()

    def consume(event: tuple[str, bytes], *, deliver_stdout: bool) -> bool:
        nonlocal output_bytes, delivery_outstanding
        stream_name, chunk = event
        if stream_name == "eof":
            eof_streams.add(chunk.decode())
            return True
        if stream_name == "stdout" and delivery_queue is not None and deliver_stdout:
            with delivery_lock:
                try:
                    delivery_queue.put_nowait(chunk)
                except queue.Full:
                    return False
                delivery_outstanding += 1
        output_bytes += len(chunk)
        if stream_name == "stdout":
            stdout_tail.append(chunk)
        else:
            stderr_tail.append(chunk)
        if activity_callback is not None:
            activity_callback("output", {"stream": stream_name, "bytes": len(chunk)})
        return True

    last_activity = start
    last_heartbeat = start

    def apply_delivery_activity() -> None:
        nonlocal delivery_activity, last_activity
        with delivery_lock:
            if delivery_error is not None:
                raise delivery_error
            if delivery_activity is not None:
                last_activity = max(last_activity, delivery_activity)
                delivery_activity = None

    def terminal_timeout() -> tuple[bool, float]:
        nonlocal delivery_activity, last_activity
        with delivery_lock:
            if delivery_error is not None:
                raise delivery_error
            if delivery_activity is not None:
                last_activity = max(last_activity, delivery_activity)
                delivery_activity = None
            now = clock()
            if now - last_activity >= inactivity_seconds:
                delivery_cancelled.set()
                return True, now
            return False, now

    def normal_delivery_complete() -> bool:
        assert process is not None
        with delivery_lock:
            if delivery_error is not None:
                raise delivery_error
            outstanding = delivery_outstanding
        return (
            process.poll() is not None
            and eof_streams == {"stdout", "stderr"}
            and pending_event is None
            and events.empty()
            and (
                delivery_queue is None
                or (
                    outstanding == 0
                    and delivery_queue.empty()
                    and not delivery_in_flight.is_set()
                )
            )
        )

    try:
        process = subprocess.Popen(args, **popen_options)
        if os.name != "nt":
            owned_process_group = process.pid
        if os.name == "nt":
            job = _WindowsJob(process)
        assert process.stdout is not None
        assert process.stderr is not None
        readers = [
            threading.Thread(target=read_pipe, args=("stdout", process.stdout), daemon=True),
            threading.Thread(target=read_pipe, args=("stderr", process.stderr), daemon=True),
        ]
        for reader in readers:
            reader.start()
        if delivery_queue is not None:
            consumer_thread = threading.Thread(
                target=deliver_stdout, name="monitored-stdout-delivery", daemon=True
            )
            consumer_thread.start()

        probe_values = tuple(probe() for probe in activity_probes)
        failure_drain_deadline: float | None = None
        while True:
            apply_delivery_activity()
            event = pending_event
            if event is None:
                try:
                    event = events.get_nowait()
                except queue.Empty:
                    event = None
            if event is not None:
                if consume(event, deliver_stdout=not process_failed):
                    if event[0] != "eof":
                        last_activity = clock()
                    pending_event = None
                else:
                    pending_event = event

            if not process_failed:
                current_probes = tuple(probe() for probe in activity_probes)
                if current_probes != probe_values:
                    changed = [
                        index
                        for index, (before, after) in enumerate(zip(probe_values, current_probes))
                        if before != after
                    ]
                    probe_values = current_probes
                    last_activity = clock()
                    if activity_callback is not None:
                        activity_callback("probe", {"changed": changed})

            timed_out, now = terminal_timeout()
            if now - last_heartbeat >= _HEARTBEAT_SECONDS:
                if activity_callback is not None:
                    activity_callback(
                        "heartbeat",
                        {
                            "elapsed_seconds": now - start,
                            "idle_seconds": now - last_activity,
                        },
                    )
                last_heartbeat = now

            if timed_out:
                stalled = True
                terminal_cleanup = True
                if activity_callback is not None:
                    activity_callback(
                        "stalled",
                        {
                            "inactivity_seconds": inactivity_seconds,
                            "idle_seconds": now - last_activity,
                            "probe_values": probe_values,
                        },
                    )
                _terminate_owned_process_tree(process, job, process_group_id=owned_process_group)
                tree_terminated = True
                break

            if process.poll() not in (None, 0) and check:
                process_failed = True
                terminal_cleanup = True
                cancel_pending_delivery()
                _terminate_owned_process_tree(process, job, process_group_id=owned_process_group)
                tree_terminated = True
                if failure_drain_deadline is None:
                    failure_drain_deadline = time.monotonic() + 1.0
            if process_failed:
                if (
                    eof_streams == {"stdout", "stderr"}
                    and pending_event is None
                    and events.empty()
                ) or (failure_drain_deadline is not None and time.monotonic() >= failure_drain_deadline):
                    break
                time.sleep(0.01)
                continue

            if normal_delivery_complete():
                break
            wait(min(0.05, max(0.0, inactivity_seconds - (now - last_activity))))
    except BaseException as error:
        terminal_error = error
        terminal_cleanup = True
        cancel_pending_delivery()
        raise
    finally:
        if process is not None and terminal_cleanup and not tree_terminated:
            try:
                _terminate_owned_process_tree(
                    process,
                    job,
                    process_group_id=owned_process_group,
                )
                tree_terminated = True
            except BaseException as error:
                cleanup_error = error
        if process is not None:
            try:
                if process.poll() is None:
                    process.wait(timeout=5)
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        reader_cancelled.set()
        if process is not None:
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except OSError:
                        pass
        for reader in readers:
            reader.join(timeout=1)
        if delivery_queue is not None:
            try:
                delivery_queue.put_nowait(None)
            except queue.Full:
                cancel_pending_delivery()
        if consumer_thread is not None:
            consumer_thread.join(timeout=0.25)
            delivery_worker_alive = consumer_thread.is_alive()
            if not terminal_cleanup and delivery_worker_alive:
                normal_delivery_shutdown_error = RuntimeError(
                    "stdout delivery worker did not stop after a completed drain"
                )
                terminal_cleanup = True
                cancel_pending_delivery()
                if process is not None and not tree_terminated:
                    try:
                        _terminate_owned_process_tree(
                            process,
                            job,
                            process_group_id=owned_process_group,
                        )
                        tree_terminated = True
                    except BaseException as error:
                        if cleanup_error is None:
                            cleanup_error = error
        if job is not None:
            try:
                job.close()
            except BaseException as error:
                if cleanup_error is None:
                    cleanup_error = error
        if terminal_error is not None:
            _expose_delivery_worker_state(terminal_error, delivery_worker_alive)
        if (
            cleanup_error is not None
            and terminal_error is None
            and normal_delivery_shutdown_error is None
        ):
            _expose_delivery_worker_state(cleanup_error, delivery_worker_alive)
            raise cleanup_error

    assert process is not None
    if normal_delivery_shutdown_error is not None:
        _expose_delivery_worker_state(normal_delivery_shutdown_error, delivery_worker_alive)
        raise normal_delivery_shutdown_error

    result = MonitoredResult(
        args=args,
        returncode=process.returncode,
        stdout_tail=stdout_tail.value(),
        stderr_tail=stderr_tail.value(),
        elapsed_seconds=clock() - start,
        output_bytes=output_bytes,
    )
    if stalled:
        raise MonitoredProcessStalled(result, delivery_worker_alive=delivery_worker_alive)
    if check and result.returncode:
        raise MonitoredProcessFailed(result, delivery_worker_alive=delivery_worker_alive)
    return result
