"""USB session lifecycle tests; injected worker replies are not physical measurements."""

import copy
import io
import json
import queue
import subprocess
import sys
import threading
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from stratus.inspection.dashboard import Dashboard
from stratus.inspection.ground import SENSORS, present_snapshot, unavailable
from stratus.inspection.loader import load_mission
from stratus.inspection.review import ground_snapshot, utc_time
from stratus.inspection.sensor_worker import serve, receive_commands
from stratus.inspection.usb_reader import MAX_REPLY_BYTES, USBWorkerReader


class Output:
    def __init__(self): self.lines = queue.Queue()
    def readline(self, _limit): return self.lines.get(timeout=2)
    def close(self): pass


class FakeProcess:
    def __init__(self, responses):
        self.responses = iter(responses); self.stdout = Output(); self.returncode = None
        self.requests = 0; self.requested = threading.Event()
        self.stdin = SimpleNamespace(write=lambda _text: None, flush=self.respond, close=lambda: None)
    def respond(self):
        self.requests += 1; self.requested.set()
        value = next(self.responses, None)
        if value is not None: self.stdout.lines.put(json.dumps(value) if isinstance(value, dict) else value)
    def poll(self): return self.returncode
    def terminate(self): self.returncode = -1; self.stdout.lines.put('')
    def kill(self): self.terminate()
    def wait(self, timeout): return self.returncode


class USBReconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.mission = load_mission()

    def setUp(self):
        self.live = copy.deepcopy(ground_snapshot(self.mission)); now = utc_time().isoformat()
        self.live.update(mode='live_measured', physical_acquisition_performed=True,
                         sensor_states={m:{'status':'fresh','technical_error':None} for m in SENSORS})
        for row in self.live['observations']:
            row.update(source_mode='live_measured', acquired_at_utc=now, received_at_utc=now, normalized_at_utc=now)
        self.missing = unavailable(self.mission, 'injected_usb_loss'); self.missing['mode'] = 'live_measured'

    def reader(self, processes, timeout=0.1):
        values = iter(processes); self.started = []
        def factory(*args, **kwargs):
            process = next(values); self.started.append((process, args, kwargs)); return process
        reader = USBWorkerReader(self.mission, timeout=timeout, popen=factory)
        reader.set_live(True); self.addCleanup(reader.close)
        return reader

    def test_failed_usb_process_is_replaced_and_both_sensors_recover(self):
        failed, healthy = FakeProcess([self.missing]), FakeProcess([self.live])
        reader = self.reader([failed, healthy])
        lost = present_snapshot(reader.sample()); self.assertEqual(lost['observations'], [])
        self.assertIsNotNone(failed.returncode)
        recovered = present_snapshot(reader.sample())
        self.assertEqual([s['status'] for s in recovered['sensors']], ['fresh','fresh'])
        self.assertEqual(reader.starts, 2)
        self.assertEqual(recovered['observations'], self.live['observations'])

    def test_particulate_settling_keeps_one_worker_and_working_atmosphere(self):
        partial = copy.deepcopy(self.live)
        partial['observations'] = [r for r in partial['observations'] if r['sensor_model']=='BME280']
        partial['sensor_states']['PMSA003I']['status'] = 'warming_up'
        process = FakeProcess([partial, self.live]); reader = self.reader([process])
        first = present_snapshot(reader.sample())
        self.assertEqual([s['status'] for s in first['sensors']], ['fresh','warming_up'])
        self.assertEqual(len(present_snapshot(reader.sample())['observations']), 6)
        self.assertEqual(reader.starts, 1)

    def test_single_sensor_failure_does_not_restart_the_working_sensor(self):
        partial = copy.deepcopy(self.live)
        partial['observations'] = [r for r in partial['observations'] if r['sensor_model']=='BME280']
        partial['sensor_states']['PMSA003I'] = {'status':'unavailable','technical_error':'injected sensor loss'}
        reader = self.reader([FakeProcess([partial,self.live])])
        self.assertEqual([s['status'] for s in present_snapshot(reader.sample())['sensors']], ['fresh','unavailable'])
        self.assertEqual(len(reader.sample()['observations']), 6)
        self.assertEqual(reader.starts, 1)

    def test_hung_usb_read_is_bounded_and_next_attempt_uses_a_fresh_worker(self):
        hung = FakeProcess([None]); reader = self.reader([hung,FakeProcess([self.live])], timeout=0.03)
        failed = present_snapshot(reader.sample())
        self.assertTrue(all(s['status']=='unavailable' for s in failed['sensors']))
        self.assertTrue(all(c['value'] is None for s in failed['sensors'] for c in s['channels']))
        self.assertIsNotNone(hung.returncode)
        self.assertEqual(len(reader.sample()['observations']), 6)

    def test_disconnect_retries_are_one_attempt_per_poll_without_fabricated_values(self):
        reader = self.reader([FakeProcess([self.missing]) for _ in range(3)])
        for i in range(3):
            self.assertEqual(reader.sample()['observations'], [])
            self.assertEqual(reader.starts, i+1)

    def test_malformed_or_oversize_worker_reply_cannot_become_a_measurement(self):
        for reply in ('garbage', 'x'*(MAX_REPLY_BYTES+1), {'mode':'synthetic'}):
            with self.subTest(reply_type=type(reply).__name__):
                reader = self.reader([FakeProcess([reply])])
                result = present_snapshot(reader.sample())
                self.assertEqual(result['observations'], [])
                self.assertTrue(all(s['status']=='unavailable' for s in result['sensors']))

    def test_switching_to_recorded_interrupts_inflight_usb_and_prevents_new_worker(self):
        process = FakeProcess([None]); reader = self.reader([process], timeout=1)
        result = []; thread = threading.Thread(target=lambda:result.append(reader.sample()))
        thread.start(); self.assertTrue(process.requested.wait(1))
        reader.set_live(False); thread.join(1)
        self.assertFalse(thread.is_alive()); self.assertIsNotNone(process.returncode)
        self.assertEqual(reader.sample()['observations'], [])
        self.assertEqual(reader.starts, 1)

    def test_recorded_dashboard_does_not_start_an_optional_usb_process(self):
        with patch('stratus.inspection.usb_reader.subprocess.Popen', side_effect=AssertionError('Unexpected USB process')):
            app = Dashboard(); self.addCleanup(app.close)
            self.assertEqual(app.state()['ground']['mode'], 'recorded_measured')

    def test_stdio_protocol_only_samples_or_closes_and_separates_library_output(self):
        calls = []
        def sample(): print('library diagnostic'); calls.append('sample'); return self.live
        reader = SimpleNamespace(sample=sample, close=lambda:calls.append('close'))
        output, diagnostics = io.StringIO(), io.StringIO()
        with patch('sys.stderr', diagnostics):
            serve(reader, io.StringIO('{"operation":"sample"}\n{"operation":"close"}\n'), output)
        self.assertEqual(json.loads(output.getvalue()), self.live)
        self.assertEqual(calls, ['sample','close']); self.assertIn('library diagnostic', diagnostics.getvalue())
        calls.clear()
        with self.assertRaises(ValueError): serve(reader, io.StringIO('{"operation":"execute"}\n'), io.StringIO())
        self.assertEqual(calls, ['close'])

    def test_real_worker_can_start_and_close_without_optional_sensor_libraries(self):
        result = subprocess.run([sys.executable,'-B','-S','-m','stratus.inspection.sensor_worker','--root',str(self.mission.project_root)],
            cwd=self.mission.project_root,input='{"operation":"close"}\n',text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(result.stdout,'')

    def test_parent_pipe_loss_signals_exit_without_waiting_for_a_sensor_response(self):
        commands = queue.Queue(maxsize=2); exited = []
        receive_commands(io.StringIO('{"operation":"sample"}\n'), commands, lambda:exited.append(True))
        self.assertEqual(exited,[True])
        self.assertEqual(json.loads(commands.get_nowait()),{'operation':'sample'})

    def test_sensor_worker_does_not_require_aircraft_images_or_mission_files(self):
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run([sys.executable,'-B','-S','-m','stratus.inspection.sensor_worker','--root',root],
                cwd=self.mission.project_root,input='{"operation":"close"}\n',text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__ == '__main__': unittest.main()
