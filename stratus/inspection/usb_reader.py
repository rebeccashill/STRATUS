"""Restartable local sensor worker; failed HID handles never re-enter the app."""

import json
import os
import queue
import subprocess
import sys
import threading

from .actions import strict_json

READ_TIMEOUT_SECONDS = 12
MAX_REPLY_BYTES = 512_000


class USBWorkerReader:
    """One attempt per ground poll, with a fresh process after USB/driver failure."""

    def __init__(self, mission, *, timeout=READ_TIMEOUT_SECONDS, popen=None):
        if not 0 < timeout <= 30:
            raise ValueError("Sensor worker timeout must be within 0-30 seconds")
        self.mission, self.timeout = mission, timeout
        self._popen = popen or subprocess.Popen
        self._process, self._replies = None, None
        self._enabled, self._closed = False, False
        self._state_lock, self._sample_lock = threading.RLock(), threading.Lock()
        self.starts = 0

    @staticmethod
    def _read_output(process, replies):
        try:
            while True:
                line = process.stdout.readline(MAX_REPLY_BYTES + 1)
                if not line:
                    replies.put(None, timeout=0.2)
                    return
                replies.put(line, timeout=0.2)
                if len(line) > MAX_REPLY_BYTES:
                    return
        except (OSError, ValueError, queue.Full):
            return
        finally:
            try: process.stdout.close()
            except (OSError, ValueError): pass

    def _discard(self):
        """Caller holds state lock; termination never waits on a USB read."""
        process, self._process, self._replies = self._process, None, None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try: process.wait(timeout=0.2)
                    except subprocess.TimeoutExpired: pass
        except OSError:
            pass
        # The output reader owns stdout; closing it across threads can block.
        if process.poll() is not None:
            try: process.stdin.close()
            except (OSError, ValueError): pass

    def set_live(self, enabled):
        with self._state_lock:
            self._enabled = bool(enabled) and not self._closed
            if not self._enabled:
                self._discard()

    def _start(self):
        command = [sys.executable, '-B', '-m', 'stratus.inspection.sensor_worker',
                   '--root', str(self.mission.project_root)]
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        self._process = self._popen(command, cwd=self.mission.project_root,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', bufsize=1, creationflags=flags)
        self._replies = queue.Queue(maxsize=2)
        self.starts += 1
        threading.Thread(target=self._read_output, args=(self._process, self._replies),
                         name='stratus-usb-output', daemon=True).start()

    def _unavailable(self, reason):
        from .ground import SENSORS, unavailable
        data = unavailable(self.mission, 'usb_reconnecting')
        data['mode'] = 'live_measured'
        message = reason + '; retrying automatically on the next live poll'
        data['sensor_states'] = {name: {'status': 'unavailable', 'technical_error': message} for name in SENSORS}
        data['technical_details'] = {'recovery': 'automatic fresh USB worker',
            'worker_starts': self.starts, 'read_timeout_seconds': self.timeout}
        return data

    def sample(self):
        from .ground import present_snapshot
        with self._sample_lock:
            try:
                with self._state_lock:
                    if not self._enabled or self._closed:
                        return self._unavailable('Live reader is paused')
                    if self._process is None or self._process.poll() is not None:
                        self._discard(); self._start()
                    process, replies = self._process, self._replies
                    process.stdin.write('{"operation":"sample"}\n')
                    process.stdin.flush()
                line = replies.get(timeout=self.timeout)
                if line is None:
                    raise OSError('USB reader stopped')
                if len(line) > MAX_REPLY_BYTES:
                    raise ValueError('USB reply exceeds its bound')
                data = strict_json(line, max_chars=MAX_REPLY_BYTES)
                if not isinstance(data, dict) or data.get('mode') != 'live_measured':
                    raise ValueError('USB reader returned an invalid source')
                shown = present_snapshot(data)
                states = [s['status'] for s in shown['sensors']]
                with self._state_lock:
                    if self._process is not process or not self._enabled:
                        return self._unavailable('Discarded an older USB session')
                    # Keep a healthy worker during PMSA settling or a partial sensor loss.
                    # Losing both sensors retires the driver's process and its singleton.
                    if all(s in ('unavailable', 'invalid') for s in states):
                        self._discard()
                data.setdefault('technical_details', {})
                if data['technical_details'] is None: data['technical_details'] = {}
                data['technical_details'].update(recovery='automatic fresh USB worker',
                    worker_starts=self.starts, read_timeout_seconds=self.timeout)
                return data
            except (OSError, ValueError, TypeError, KeyError, queue.Empty) as exc:
                with self._state_lock:
                    self._discard()
                reason = 'USB reader timed out' if isinstance(exc, queue.Empty) else str(exc)
                return self._unavailable(reason)

    def close(self):
        with self._state_lock:
            self._closed, self._enabled = True, False
            self._discard()
