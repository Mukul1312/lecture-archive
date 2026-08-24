"""Tests for the bounded monitored subprocess runner."""

from __future__ import annotations

import os
import inspect
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from scripts.youtube_enhance.process import (
    MonitoredProcessFailed,
    MonitoredProcessStalled,
    run_monitored,
)


class MonitoredProcessStreamingTests(unittest.TestCase):
    def test_streams_stdout_and_keeps_only_bounded_binary_tails(self) -> None:
        """Removing streaming or tail trimming must lose this observable data."""
        stdout = b"out-" * 80
        stderr = b"err-" * 80
        received: list[bytes] = []
        child = (
            "import sys; "
            f"sys.stdout.buffer.write({stdout!r}); sys.stdout.buffer.flush(); "
            f"sys.stderr.buffer.write({stderr!r}); sys.stderr.buffer.flush()"
        )

        result = run_monitored(
            [sys.executable, "-c", child],
            stdout_consumer=received.append,
            activity_callback=None,
            tail_bytes=37,
        )

        self.assertEqual(b"".join(received), stdout)
        self.assertEqual(result.stdout_tail, stdout[-37:])
        self.assertEqual(result.stderr_tail, stderr[-37:])
        self.assertLessEqual(len(result.stdout_tail), 37)
        self.assertLessEqual(len(result.stderr_tail), 37)
        self.assertEqual(result.output_bytes, len(stdout) + len(stderr))

    def test_treats_command_as_literal_argument_sequence_without_shell_expansion(self) -> None:
        """Changing Popen to shell execution must make the marker expand."""
        marker = "$MONITORED_RUNNER_SHELL_MARKER"
        received: list[bytes] = []
        child = "import sys; sys.stdout.buffer.write(sys.argv[1].encode())"

        result = run_monitored(
            [sys.executable, "-c", child, marker],
            stdout_consumer=received.append,
            activity_callback=None,
        )

        self.assertEqual(b"".join(received), marker.encode())
        self.assertEqual(result.args[-1], marker)


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _pid_is_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            exit_code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return exit_code.value == 259
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_test_process(pid: int) -> None:
    if not _pid_is_alive(pid):
        return
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(1, False, pid)
        if handle:
            kernel32.TerminateProcess(handle, 1)
            kernel32.CloseHandle(handle)
    else:
        os.kill(pid, 9)


class MonitoredProcessInactivityTests(unittest.TestCase):
    def test_stall_terminates_the_owned_process_tree_and_reports_evidence(self) -> None:
        """Removing stall handling must leave the owned sleeping tree running."""
        with tempfile.TemporaryDirectory() as temporary:
            pid_file = Path(temporary) / "grandchild.pid"
            clock = _FakeClock()
            events: list[tuple[str, dict[str, object]]] = []
            child = (
                "from pathlib import Path; import subprocess, sys, time; "
                "grandchild = subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(60)']); "
                "Path(sys.argv[1]).write_text(str(grandchild.pid)); "
                "sys.stderr.buffer.write(b'ready\\n'); sys.stderr.buffer.flush(); "
                "time.sleep(60)"
            )

            def advance_to_timeout(_: float) -> None:
                if not pid_file.exists() or not any(name == "output" for name, _ in events):
                    time.sleep(0.01)
                    return
                clock.advance(600)

            try:
                with self.assertRaises(MonitoredProcessStalled) as raised:
                    run_monitored(
                        [sys.executable, "-c", child, str(pid_file)],
                        stdout_consumer=None,
                        activity_callback=lambda name, data: events.append((name, dict(data))),
                        inactivity_seconds=600,
                        tail_bytes=32,
                        clock=clock,
                        wait=advance_to_timeout,
                    )
                result = raised.exception.result
                self.assertIn(b"ready", result.stderr_tail)
                self.assertFalse(_pid_is_alive(int(pid_file.read_text())))
            finally:
                if pid_file.exists():
                    _stop_test_process(int(pid_file.read_text()))

            stalled_events = [data for name, data in events if name == "stalled"]
            self.assertEqual(len(stalled_events), 1)
            self.assertEqual(stalled_events[0]["inactivity_seconds"], 600)
            self.assertGreaterEqual(stalled_events[0]["idle_seconds"], 600)

    def test_changed_artifact_probe_resets_silent_process_inactivity(self) -> None:
        """Removing probe-change activity must turn this quiet process into a stall."""
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "artifact.bin"
            clock = _FakeClock()
            waits = 0
            child = (
                "from pathlib import Path\n"
                "import sys\n"
                "import time\n"
                "artifact = Path(sys.argv[1])\n"
                "while not artifact.exists():\n"
                "    time.sleep(0.005)\n"
            )

            def grow_artifact(_: float) -> None:
                nonlocal waits
                waits += 1
                if waits == 1:
                    clock.advance(500)
                elif waits == 2:
                    artifact.write_bytes(b"more-bytes")
                    clock.advance(200)
                    time.sleep(0.05)
                else:
                    clock.advance(1)
                    time.sleep(0.01)

            result = run_monitored(
                [sys.executable, "-c", child, str(artifact)],
                stdout_consumer=None,
                activity_callback=None,
                activity_probes=(lambda: artifact.stat().st_size if artifact.exists() else 0,),
                inactivity_seconds=600,
                clock=clock,
                wait=grow_artifact,
            )

            self.assertEqual(result.returncode, 0)
            self.assertGreaterEqual(result.elapsed_seconds, 700)
            self.assertEqual(result.output_bytes, 0)


class MonitoredProcessFailureTests(unittest.TestCase):
    def test_nonzero_exit_raises_with_the_bounded_result_when_checking(self) -> None:
        """Removing check handling must return instead of exposing this result."""
        with self.assertRaises(MonitoredProcessFailed) as raised:
            run_monitored(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.buffer.write(b'failure-tail'); sys.exit(9)",
                ],
                stdout_consumer=None,
                activity_callback=None,
                tail_bytes=4,
            )

        self.assertEqual(raised.exception.result.returncode, 9)
        self.assertEqual(raised.exception.result.stderr_tail, b"tail")

    def test_successful_runner_never_terminates_an_unrelated_process(self) -> None:
        """Broad termination must not kill a sibling the runner did not create."""
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            result = run_monitored(
                [sys.executable, "-c", "pass"],
                stdout_consumer=None,
                activity_callback=None,
            )
            self.assertEqual(result.returncode, 0)
            self.assertTrue(_pid_is_alive(unrelated.pid))
        finally:
            if unrelated.poll() is None:
                unrelated.kill()
            unrelated.wait(timeout=5)

    def test_accepted_success_never_invokes_owned_tree_termination(self) -> None:
        """Routing accepted success through abnormal cleanup must call these seams."""
        from scripts.youtube_enhance import process as process_module

        with mock.patch.object(
            process_module, "_terminate_owned_process_tree"
        ) as terminate_owned, mock.patch.object(
            process_module.os, "killpg", create=True
        ) as kill_process_group:
            result = run_monitored(
                [sys.executable, "-c", "pass"],
                stdout_consumer=None,
                activity_callback=None,
            )

        self.assertEqual(result.returncode, 0)
        terminate_owned.assert_not_called()
        kill_process_group.assert_not_called()


class MonitoredProcessSupervisionRegressionTests(unittest.TestCase):
    def test_slow_consumer_does_not_block_heartbeats_or_use_pre_delivery_time(self) -> None:
        """Putting consumer delivery on the monitor thread must false-stall here."""
        with tempfile.TemporaryDirectory() as temporary:
            completed = Path(temporary) / "consumer-completed"
            clock = _FakeClock()
            consumer_started = threading.Event()
            release_consumer = threading.Event()
            release_thread_done = threading.Event()
            events: list[tuple[str, dict[str, object]]] = []
            child = (
                "from pathlib import Path\n"
                "import sys\n"
                "import time\n"
                "sys.stdout.buffer.write(b'x' * (64 * 1024)); sys.stdout.buffer.flush()\n"
                "time.sleep(0.3)\n"
            )

            def consume(_: bytes) -> None:
                consumer_started.set()
                self.assertTrue(release_consumer.wait(2))
                completed.write_bytes(b"done")

            def release_later() -> None:
                self.assertTrue(consumer_started.wait(2))
                time.sleep(0.15)
                clock.advance(90)
                release_consumer.set()
                release_thread_done.set()

            def advance_while_blocked(_: float) -> None:
                if release_consumer.is_set():
                    time.sleep(0.02)
                else:
                    time.sleep(0.05)
                    if not release_consumer.is_set():
                        clock.advance(30)

            releaser = threading.Thread(target=release_later)
            releaser.start()
            try:
                result = run_monitored(
                    [sys.executable, "-c", child, str(completed)],
                    stdout_consumer=consume,
                    activity_callback=lambda name, data: events.append((name, dict(data))),
                    inactivity_seconds=600,
                    clock=clock,
                    wait=advance_while_blocked,
                )
            finally:
                release_consumer.set()
                releaser.join(timeout=2)

            self.assertTrue(release_thread_done.is_set())
            self.assertEqual(result.returncode, 0)
            heartbeats = [data["elapsed_seconds"] for name, data in events if name == "heartbeat"]
            self.assertGreaterEqual(len(heartbeats), 2)
            self.assertTrue(all(after - before >= 30 for before, after in zip(heartbeats, heartbeats[1:])))

    def test_initial_probe_exception_terminates_the_owned_tree(self) -> None:
        """Moving initial probes outside cleanup must leak this root and descendant."""
        with tempfile.TemporaryDirectory() as temporary:
            root_pid_file = Path(temporary) / "root.pid"
            grandchild_pid_file = Path(temporary) / "grandchild.pid"
            child = (
                "from pathlib import Path; import os, subprocess, sys, time; "
                "Path(sys.argv[1]).write_text(str(os.getpid())); "
                "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                "Path(sys.argv[2]).write_text(str(grandchild.pid)); time.sleep(60)"
            )

            def failing_probe() -> int:
                deadline = time.monotonic() + 2
                while not grandchild_pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                raise RuntimeError("probe failed")

            try:
                with self.assertRaisesRegex(RuntimeError, "probe failed"):
                    run_monitored(
                        [sys.executable, "-c", child, str(root_pid_file), str(grandchild_pid_file)],
                        stdout_consumer=None,
                        activity_callback=None,
                        activity_probes=(failing_probe,),
                    )
                self.assertFalse(_pid_is_alive(int(root_pid_file.read_text())))
                self.assertFalse(_pid_is_alive(int(grandchild_pid_file.read_text())))
            finally:
                for pid_file in (root_pid_file, grandchild_pid_file):
                    if pid_file.exists():
                        _stop_test_process(int(pid_file.read_text()))

    def test_timeout_kills_descendants_when_the_root_exits_at_the_deadline(self) -> None:
        """Leader-only cleanup must leave this owned grandchild alive."""
        with tempfile.TemporaryDirectory() as temporary:
            exit_file = Path(temporary) / "exit"
            grandchild_pid_file = Path(temporary) / "grandchild.pid"
            clock = _FakeClock()
            child = (
                "from pathlib import Path\n"
                "import subprocess\n"
                "import sys\n"
                "import time\n"
                "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                "Path(sys.argv[2]).write_text(str(grandchild.pid))\n"
                "while not Path(sys.argv[1]).exists():\n"
                "    time.sleep(0.005)\n"
            )

            def exit_at_deadline(_: float) -> None:
                if not grandchild_pid_file.exists():
                    time.sleep(0.01)
                    return
                exit_file.write_bytes(b"exit")
                clock.advance(600)
                time.sleep(0.05)

            try:
                with self.assertRaises(MonitoredProcessStalled):
                    run_monitored(
                        [sys.executable, "-c", child, str(exit_file), str(grandchild_pid_file)],
                        stdout_consumer=None,
                        activity_callback=None,
                        inactivity_seconds=600,
                        clock=clock,
                        wait=exit_at_deadline,
                    )
                self.assertFalse(_pid_is_alive(int(grandchild_pid_file.read_text())))
            finally:
                if grandchild_pid_file.exists():
                    _stop_test_process(int(grandchild_pid_file.read_text()))


class MonitoredProcessDeliveryRegressionTests(unittest.TestCase):
    def test_terminal_cancellation_wins_before_a_delivery_callback_is_claimed(self) -> None:
        """A split cancellation check/claim must start this queued callback."""
        from scripts.youtube_enhance import process as process_module

        clock = _FakeClock()
        callback_started = threading.Event()
        worker_checked = threading.Event()
        claim_attempted = threading.Event()
        cancellation_done = threading.Event()
        allow_worker_claim = threading.Event()
        real_event = threading.Event
        real_lock = threading.Lock

        class TrackingLock:
            def __init__(self) -> None:
                self._lock = real_lock()
                self._paused_worker_claim = False

            def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
                if (
                    threading.current_thread().name == "monitored-stdout-delivery"
                    and not self._paused_worker_claim
                ):
                    self._paused_worker_claim = True
                    claim_attempted.set()
                    self_case.assertTrue(allow_worker_claim.wait(2))
                if timeout == -1:
                    return self._lock.acquire(blocking)
                return self._lock.acquire(blocking, timeout)

            def release(self) -> None:
                self._lock.release()

            def __enter__(self) -> "TrackingLock":
                self.acquire()
                return self

            def __exit__(self, *unused: object) -> None:
                self.release()

        class RaceCancellationEvent:
            def __init__(self) -> None:
                self._event = real_event()

            def set(self) -> None:
                self._event.set()
                cancellation_done.set()

            def is_set(self) -> bool:
                if (
                    threading.current_thread().name == "monitored-stdout-delivery"
                    and not self._event.is_set()
                ):
                    worker_checked.set()
                    self_case.assertTrue(cancellation_done.wait(2))
                    # This is the old non-atomic snapshot: cancellation has now
                    # won, but the stale false value still permits a callback.
                    return False
                return self._event.is_set()

            def wait(self, timeout: float | None = None) -> bool:
                return self._event.wait(timeout)

        def is_runner_call() -> bool:
            frame = inspect.currentframe()
            frame = frame.f_back if frame is not None else None
            while frame is not None and (
                "unittest\\mock.py" in frame.f_code.co_filename
                or frame.f_code.co_name in {"event_factory", "lock_factory", "is_runner_call"}
            ):
                frame = frame.f_back
            return bool(
                frame is not None
                and frame.f_code.co_name == "run_monitored"
                and frame.f_code.co_filename == process_module.__file__
            )

        tracking_lock = TrackingLock()
        runner_event_count = 0
        cancellation_events: list[RaceCancellationEvent] = []
        coordinator_errors: list[BaseException] = []
        self_case = self

        def event_factory(*args: object, **kwargs: object) -> threading.Event:
            nonlocal runner_event_count
            if is_runner_call():
                runner_event_count += 1
                if runner_event_count == 2:
                    event = RaceCancellationEvent()
                    cancellation_events.append(event)
                    return event  # type: ignore[return-value]
            return real_event(*args, **kwargs)

        def lock_factory(*args: object, **kwargs: object) -> threading.Lock:
            if is_runner_call():
                return tracking_lock  # type: ignore[return-value]
            return real_lock(*args, **kwargs)

        def cancel_at_boundary() -> None:
            try:
                deadline = time.monotonic() + 2
                while not (worker_checked.is_set() or claim_attempted.is_set()):
                    self_case.assertLess(time.monotonic(), deadline)
                    time.sleep(0.005)
                with tracking_lock:
                    self_case.assertEqual(len(cancellation_events), 1)
                    cancellation_events[0].set()
            except BaseException as error:
                coordinator_errors.append(error)
            finally:
                allow_worker_claim.set()

        coordinator = threading.Thread(target=cancel_at_boundary)
        coordinator.start()
        child = (
            "import sys, time\n"
            "sys.stdout.buffer.write(b'race'); sys.stdout.buffer.flush()\n"
            "time.sleep(60)\n"
        )

        def advance_after_cancellation(_: float) -> None:
            if cancellation_done.is_set():
                clock.advance(600)
            else:
                time.sleep(0.005)

        try:
            with mock.patch.object(process_module.threading, "Event", side_effect=event_factory), mock.patch.object(
                process_module.threading, "Lock", side_effect=lock_factory
            ):
                with self.assertRaises(MonitoredProcessStalled):
                    run_monitored(
                        [sys.executable, "-c", child],
                        stdout_consumer=lambda _: callback_started.set(),
                        activity_callback=None,
                        inactivity_seconds=600,
                        clock=clock,
                        wait=advance_after_cancellation,
                    )
            self.assertEqual(coordinator_errors, [])
            self.assertTrue(worker_checked.is_set() or claim_attempted.is_set())
            self.assertTrue(cancellation_done.is_set())
            self.assertFalse(callback_started.is_set())
        finally:
            allow_worker_claim.set()
            coordinator.join(timeout=2)

        self.assertFalse(coordinator.is_alive())

    def test_generic_terminal_error_reports_a_lingering_delivery_worker(self) -> None:
        """Generic terminal errors must expose a callback worker left running."""
        callback_started = threading.Event()
        release_callback = threading.Event()
        child = (
            "import sys, time\n"
            "sys.stdout.buffer.write(b'x' * (64 * 1024)); sys.stdout.buffer.flush()\n"
            "time.sleep(60)\n"
        )

        def blocked_consumer(_: bytes) -> None:
            callback_started.set()
            release_callback.wait()

        def fail_after_delivery_starts(name: str, _: object) -> None:
            if name == "output":
                self.assertTrue(callback_started.wait(2))
                raise RuntimeError("activity callback failed")

        try:
            with self.assertRaisesRegex(RuntimeError, "activity callback failed") as raised:
                run_monitored(
                    [sys.executable, "-c", child],
                    stdout_consumer=blocked_consumer,
                    activity_callback=fail_after_delivery_starts,
                )
            self.assertTrue(getattr(raised.exception, "delivery_worker_alive", False))
        finally:
            release_callback.set()

        deadline = time.monotonic() + 2
        while any(thread.name == "monitored-stdout-delivery" for thread in threading.enumerate()):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    def test_termination_cleanup_failure_preserves_the_primary_error(self) -> None:
        """Owned-tree cleanup failure must not replace an active primary error."""
        from scripts.youtube_enhance import process as process_module

        callback_started = threading.Event()
        release_callback = threading.Event()
        real_terminate = process_module._terminate_owned_process_tree
        child = (
            "import sys, time\n"
            "sys.stdout.buffer.write(b'x' * (64 * 1024)); sys.stdout.buffer.flush()\n"
            "time.sleep(60)\n"
        )

        def blocked_consumer(_: bytes) -> None:
            callback_started.set()
            release_callback.wait()

        def fail_primary(name: str, _: object) -> None:
            if name == "output":
                self.assertTrue(callback_started.wait(2))
                raise RuntimeError("primary activity failure")

        def terminate_then_fail(*args: object, **kwargs: object) -> None:
            real_terminate(*args, **kwargs)
            raise OSError("termination cleanup failed")

        try:
            with mock.patch.object(
                process_module,
                "_terminate_owned_process_tree",
                side_effect=terminate_then_fail,
            ):
                with self.assertRaisesRegex(RuntimeError, "primary activity failure") as raised:
                    run_monitored(
                        [sys.executable, "-c", child],
                        stdout_consumer=blocked_consumer,
                        activity_callback=fail_primary,
                    )
            self.assertTrue(getattr(raised.exception, "delivery_worker_alive", False))
        finally:
            release_callback.set()

        deadline = time.monotonic() + 2
        while any(thread.name == "monitored-stdout-delivery" for thread in threading.enumerate()):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    def test_wait_cleanup_failure_preserves_the_primary_error(self) -> None:
        """Process-wait cleanup failure must not replace an active primary error."""
        from scripts.youtube_enhance import process as process_module

        callback_started = threading.Event()
        release_callback = threading.Event()
        real_wait = subprocess.Popen.wait
        child = (
            "import sys, time\n"
            "sys.stdout.buffer.write(b'x' * (64 * 1024)); sys.stdout.buffer.flush()\n"
            "time.sleep(60)\n"
        )

        def blocked_consumer(_: bytes) -> None:
            callback_started.set()
            release_callback.wait()

        def fail_primary(name: str, _: object) -> None:
            if name == "output":
                self.assertTrue(callback_started.wait(2))
                raise RuntimeError("primary activity failure")

        def kill_reap_then_fail(
            process: subprocess.Popen[bytes], timeout: float | None = None
        ) -> int:
            process.kill()
            real_wait(process, timeout=timeout)
            raise OSError("wait cleanup failed")

        try:
            with mock.patch.object(
                process_module, "_terminate_owned_process_tree", return_value=None
            ), mock.patch.object(subprocess.Popen, "wait", new=kill_reap_then_fail):
                with self.assertRaisesRegex(RuntimeError, "primary activity failure") as raised:
                    run_monitored(
                        [sys.executable, "-c", child],
                        stdout_consumer=blocked_consumer,
                        activity_callback=fail_primary,
                    )
            self.assertTrue(getattr(raised.exception, "delivery_worker_alive", False))
        finally:
            release_callback.set()

        deadline = time.monotonic() + 2
        while any(thread.name == "monitored-stdout-delivery" for thread in threading.enumerate()):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    def test_unstopped_delivery_worker_makes_completed_drain_owned_cleanup(self) -> None:
        """Detecting a live worker after drain must enter abnormal tree cleanup."""
        from scripts.youtube_enhance import process as process_module

        sentinel_taken = threading.Event()
        release_sentinel = threading.Event()
        termination_calls: list[tuple[object, ...]] = []
        original_get = process_module.queue.Queue.get

        def delay_delivery_sentinel(queue_instance: object, *args: object, **kwargs: object) -> object:
            item = original_get(queue_instance, *args, **kwargs)
            if item is None and threading.current_thread().name == "monitored-stdout-delivery":
                sentinel_taken.set()
                self.assertTrue(release_sentinel.wait(2))
            return item

        def record_owned_cleanup(*args: object, **kwargs: object) -> None:
            termination_calls.append(args)

        try:
            with mock.patch.object(process_module.queue.Queue, "get", new=delay_delivery_sentinel), mock.patch.object(
                process_module, "_terminate_owned_process_tree", side_effect=record_owned_cleanup
            ):
                with self.assertRaisesRegex(RuntimeError, "delivery worker did not stop") as raised:
                    run_monitored(
                        [sys.executable, "-c", "pass"],
                        stdout_consumer=lambda _: None,
                        activity_callback=None,
                    )
            self.assertTrue(sentinel_taken.is_set())
            self.assertEqual(len(termination_calls), 1)
            self.assertTrue(getattr(raised.exception, "delivery_worker_alive", False))
        finally:
            release_sentinel.set()

        deadline = time.monotonic() + 2
        while any(thread.name == "monitored-stdout-delivery" for thread in threading.enumerate()):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    @unittest.skipUnless(os.name == "nt", "Windows Job setup is Windows-only")
    def test_windows_resume_failure_closes_job_after_process_cleanup_errors(self) -> None:
        """Resume cleanup must preserve its error while always closing the Job."""
        import ctypes

        from scripts.youtube_enhance import process as process_module

        class NativeCall:
            def __init__(self, result: object) -> None:
                self.calls: list[tuple[object, ...]] = []
                self.result = result

            def __call__(self, *args: object) -> object:
                self.calls.append(args)
                return self.result

        class Kernel32:
            def __init__(self) -> None:
                self.CreateJobObjectW = NativeCall(1234)
                self.SetInformationJobObject = NativeCall(True)
                self.AssignProcessToJobObject = NativeCall(True)
                self.CloseHandle = NativeCall(True)
                self.TerminateJobObject = NativeCall(True)

        class NativeLibraries:
            def __init__(self, kernel32: Kernel32) -> None:
                self.kernel32 = kernel32

        class FailingProcess:
            _handle = 999
            pid = 4321

            def __init__(self) -> None:
                self.kill_calls = 0
                self.wait_calls = 0

            def poll(self) -> None:
                return None

            def kill(self) -> None:
                self.kill_calls += 1
                raise OSError("kill cleanup failed")

            def wait(self, timeout: float) -> None:
                self.wait_calls += 1
                raise OSError("wait cleanup failed")

        kernel32 = Kernel32()
        process = FailingProcess()
        with mock.patch.object(ctypes, "windll", NativeLibraries(kernel32)), mock.patch.object(
            process_module._WindowsJob,
            "_resume_primary_thread",
            side_effect=OSError("resume failed"),
        ):
            with self.assertRaisesRegex(OSError, "resume failed"):
                process_module._WindowsJob(process)  # type: ignore[arg-type]

        self.assertEqual(process.kill_calls, 1)
        self.assertEqual(process.wait_calls, 1)
        self.assertIn((1234,), kernel32.CloseHandle.calls)

    def test_stall_returns_boundedly_when_the_current_consumer_callback_is_blocked(self) -> None:
        """An unbounded delivery join must keep this runner thread alive."""
        clock = _FakeClock()
        callback_started = threading.Event()
        release_callback = threading.Event()
        completed = threading.Event()
        outcome: list[BaseException | MonitoredResult] = []
        child = (
            "import sys, time\n"
            "sys.stdout.buffer.write(b'x' * (64 * 1024)); sys.stdout.buffer.flush()\n"
            "time.sleep(60)\n"
        )

        def blocked_consumer(_: bytes) -> None:
            callback_started.set()
            release_callback.wait()

        def run() -> None:
            try:
                outcome.append(
                    run_monitored(
                        [sys.executable, "-c", child],
                        stdout_consumer=blocked_consumer,
                        activity_callback=None,
                        inactivity_seconds=600,
                        clock=clock,
                        wait=lambda _: clock.advance(600) if callback_started.is_set() else time.sleep(0.01),
                    )
                )
            except BaseException as error:
                outcome.append(error)
            finally:
                completed.set()

        runner = threading.Thread(target=run)
        runner.start()
        try:
            self.assertTrue(callback_started.wait(2))
            self.assertTrue(completed.wait(1), "terminal delivery wait was not bounded")
            self.assertIsInstance(outcome[0], MonitoredProcessStalled)
            self.assertTrue(getattr(outcome[0], "delivery_worker_alive", False))
        finally:
            release_callback.set()
            runner.join(timeout=2)

        self.assertFalse(runner.is_alive())

    def test_normal_success_drains_a_full_delivery_queue_in_exact_order(self) -> None:
        """Discarding a full-queue event during drain must lose these bytes."""
        from scripts.youtube_enhance import process as process_module

        expected = b"0123456789AB"
        received: list[bytes] = []
        callback_started = threading.Event()
        release_callback = threading.Event()
        child = (
            "import sys\n"
            "payload = b'0123456789AB'\n"
            "sys.stdout.buffer.write(payload); sys.stdout.buffer.flush()\n"
        )

        def slow_consumer(data: bytes) -> None:
            callback_started.set()
            release_callback.wait(2)
            received.append(data)

        releaser = threading.Thread(target=lambda: (callback_started.wait(2), time.sleep(0.15), release_callback.set()))
        releaser.start()
        try:
            with mock.patch.object(process_module, "_READ_BYTES", 1):
                result = run_monitored(
                    [sys.executable, "-c", child],
                    stdout_consumer=slow_consumer,
                    activity_callback=None,
                    inactivity_seconds=5,
                )
        finally:
            release_callback.set()
            releaser.join(timeout=2)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(b"".join(received), expected)
        self.assertFalse(any(thread.name == "monitored-stdout-delivery" for thread in threading.enumerate()))

    def test_consumer_failure_after_root_exit_is_not_lost(self) -> None:
        """Ignoring delivery errors after the main loop must return success here."""
        child = "import sys; sys.stdout.buffer.write(b'consumer-error'); sys.stdout.buffer.flush()"

        def failing_consumer(_: bytes) -> None:
            raise ValueError("consumer failed after exit")

        with self.assertRaisesRegex(ValueError, "consumer failed after exit"):
            run_monitored(
                [sys.executable, "-c", child],
                stdout_consumer=failing_consumer,
                activity_callback=None,
            )

    @unittest.skipUnless(os.name == "nt", "Windows Job setup is Windows-only")
    def test_windows_job_setup_failure_kills_the_suspended_root(self) -> None:
        """Fail-open Job setup must leave the injected Popen root alive."""
        from scripts.youtube_enhance import process as process_module

        created: list[subprocess.Popen[bytes]] = []
        real_popen = subprocess.Popen

        def recording_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
            process = real_popen(*args, **kwargs)
            created.append(process)
            return process

        try:
            with mock.patch.object(process_module.subprocess, "Popen", side_effect=recording_popen), mock.patch.object(
                process_module, "_WindowsJob", side_effect=OSError("Job setup failed")
            ):
                with self.assertRaisesRegex(OSError, "Job setup failed"):
                    run_monitored(
                        [sys.executable, "-c", "import time; time.sleep(60)"],
                        stdout_consumer=None,
                        activity_callback=None,
                    )

            self.assertGreaterEqual(len(created), 1)
            self.assertIsNotNone(created[0].poll())
        finally:
            for process in created:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
