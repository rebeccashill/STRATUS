"""Operator workflow, source honesty, partial hardware and read-only HTTP checks."""

import copy
from dataclasses import replace
from datetime import timedelta
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from stratus.inspection.dashboard import Dashboard, make_server
from stratus.inspection.ground import GroundFeed, HardwareReader, present_snapshot, validate_observation
from stratus.inspection.loader import load_mission
from stratus.inspection.review import ground_snapshot, utc_time


class GroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = load_mission()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.mission = replace(self.original, project_root=Path(self.temp.name))
        self.reader = HardwareReader(self.mission, monotonic=lambda: 100)
        self.addCleanup(self.reader.close)
        self.bme = SimpleNamespace(temperature=22.5, relative_humidity=41.0, pressure=1005.7)
        self.pm = SimpleNamespace(read=lambda: {"pm10 env": 1, "pm25 env": 2, "pm100 env": 3,
                                               "pm10 standard": 101, "particles 03um": 999})
        self.connect()

    def connect(self):
        self.reader.i2c = SimpleNamespace(deinit=lambda: None)
        self.reader.devices = {"BME280": self.bme, "PMSA003I": self.pm}
        self.reader.pmsa_started = 0
        self.reader.addresses = [0, 0x12, 0x77, 0x78]

    def test_live_six_channels_saved_with_matching_raw_hash(self):
        result = self.reader.sample()
        self.assertTrue(result["physical_acquisition_performed"])
        self.assertEqual(len(result["observations"]), 6)
        rows = result["observations"]
        self.assertEqual({r["variable"]: r["value"] for r in rows if r["sensor_model"] == "PMSA003I"},
                         {"pm1_0": 1, "pm2_5": 2, "pm10": 3})
        for row in rows:
            validate_observation(row)
            source = self.mission.project_root / row["provenance"]["source_file"]
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), row["provenance"]["source_sha256"])
            self.assertEqual(row["location"]["status"], "unknown")
            self.assertEqual(row["calibration"]["status"], "unknown")
        saved = [json.loads(s) for s in source.with_suffix(".jsonl").read_text().splitlines()]
        self.assertEqual(saved, rows)

    def test_pmsa_settles_without_hiding_working_bme(self):
        self.reader.pmsa_started = 99
        result = present_snapshot(self.reader.sample())
        self.assertEqual([s["status"] for s in result["sensors"]], ["fresh", "warming_up"])
        self.assertEqual(len(result["observations"]), 3)
        self.assertTrue(all(c["value"] is None for c in result["sensors"][1]["channels"]))

    def test_checksum_failure_is_invalid_and_does_not_fill_zero(self):
        self.pm.read = lambda: (_ for _ in ()).throw(RuntimeError("Invalid checksum"))
        result = present_snapshot(self.reader.sample())
        self.assertEqual([s["status"] for s in result["sensors"]], ["fresh", "invalid"])
        self.assertEqual(len(result["observations"]), 3)
        self.assertTrue(all(c["value"] is None for c in result["sensors"][1]["channels"]))

    def test_nonfinite_or_out_of_range_invalidates_only_its_sensor(self):
        for value in (float("nan"), float("inf"), -1, 101, True):
            with self.subTest(value=value):
                self.connect(); self.bme.relative_humidity = value
                result = present_snapshot(self.reader.sample())
                self.assertEqual([s["status"] for s in result["sensors"]], ["invalid", "fresh"])
                self.assertEqual(len(result["observations"]), 3)

    def test_missing_library_or_bridge_keeps_typed_unavailable_shape(self):
        for exc in (ModuleNotFoundError("board"), RuntimeError("no MCP2221 device found")):
            self.reader.close()
            with patch.object(self.reader, "_open", side_effect=exc):
                result = present_snapshot(self.reader.sample())
            self.assertEqual(len(result["sensors"]), 2)
            self.assertEqual(result["observations"], [])
            self.assertTrue(all(s["status"] == "unavailable" for s in result["sensors"]))

    def test_disconnect_reconnect_can_recover_without_process_restart(self):
        self.reader.close()
        with patch.object(self.reader, "_open", side_effect=OSError("disconnected")):
            self.assertEqual(self.reader.sample()["observations"], [])
        with patch.object(self.reader, "_open", side_effect=self.connect):
            self.assertEqual(len(self.reader.sample()["observations"]), 6)

    def test_freshness_is_per_sensor_and_retains_original_times(self):
        data = self.reader.sample(); now = utc_time()
        for row in data["observations"]:
            if row["sensor_model"] == "PMSA003I": row["acquired_at_utc"] = (now-timedelta(seconds=25)).isoformat()
        before = copy.deepcopy(data)
        result = present_snapshot(data, now=now)
        self.assertEqual([s["status"] for s in result["sensors"]], ["fresh", "stale"])
        self.assertEqual(data, before)
        self.assertEqual(result["observations"], before["observations"])

    def test_wrong_units_duplicate_ids_and_future_times_are_invalid(self):
        for mutation in (lambda r: r[0].update(unit="F"),
                         lambda r: r[1].update(observation_id=r[0]["observation_id"]),
                         lambda r: r[0].update(acquired_at_utc=(utc_time()+timedelta(minutes=5)).isoformat())):
            data = self.reader.sample(); mutation(data["observations"])
            result = present_snapshot(data)
            self.assertEqual(result["sensors"][0]["status"], "invalid")
            self.assertEqual(result["sensors"][1]["status"], "fresh")

    def test_replay_export_never_retimes_or_synthesizes_measurements(self):
        data = self.reader.sample(); feed = GroundFeed(self.mission, data, reader=self.reader)
        self.addCleanup(feed.close)
        exported = feed.export_recorded()
        self.assertEqual(exported["mode"], "recorded_measured")
        self.assertEqual(exported["source_label"], "Recorded")
        self.assertFalse(exported["physical_acquisition_performed"])
        self.assertEqual([r["acquired_at_utc"] for r in data["observations"]],
                         [r["acquired_at_utc"] for r in exported["observations"]])
        feed.select("unavailable")
        with self.assertRaises(ValueError): feed.export_recorded()
        example = feed.select("synthetic")
        self.assertEqual(example["source_label"], "Synthetic example")
        self.assertTrue(all(r["acquisition_source"] == "synthetic" for r in example["observations"]))
        with self.assertRaises(ValueError): feed.export_recorded()
        again = feed.select("synthetic")
        self.assertNotEqual(example["observations"][0]["provenance"]["source_file"],
                            again["observations"][0]["provenance"]["source_file"])

    def test_malformed_metadata_invalidates_sensor_without_losing_other(self):
        for key,value in (("observation_id","not-an-id"),("quality",{}),("calibration",{"status":"verified"}),
                          ("uncertainty",{}),("provenance",{}),("timestamp_basis","simulated_flight")):
            with self.subTest(key=key):
                data=self.reader.sample();data["observations"][0][key]=value
                shown=present_snapshot(data)
                self.assertEqual([s["status"] for s in shown["sensors"]],["invalid","fresh"])

    def test_malformed_snapshot_is_rejected_before_frontend(self):
        for data in ({},{"mode":"recorded_measured","observations":[]},[] ,None):
            with self.assertRaises(ValueError):present_snapshot(data)

    def test_late_live_poll_cannot_overwrite_operator_mode_change(self):
        entered, release = threading.Event(), threading.Event()
        def sample():
            entered.set(); release.wait(2); return self.reader.sample()
        fake = SimpleNamespace(sample=sample, close=lambda: None)
        recorded = ground_snapshot(self.original)
        feed = GroundFeed(self.mission, recorded, reader=fake); self.addCleanup(feed.close)
        feed.select("live"); self.assertTrue(entered.wait(2))
        feed.select("recorded"); release.set(); feed.close()
        self.assertEqual(feed.snapshot()["mode"], "recorded_measured")
        self.assertEqual(feed.snapshot()["observations"], recorded["observations"])

    def test_ordinary_import_does_not_import_optional_sensor_libraries(self):
        code = "import sys; import stratus.inspection.dashboard; assert not {'board','busio','hid','adafruit_bme280','adafruit_pm25'} & set(sys.modules)"
        result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.app = Dashboard(); self.addCleanup(self.app.close)
        self.before = self.app.session.snapshot()
        self.checkpoint = self.app.mission.project_root / "saved-runs/first-inspection.json"
        self.checksum = hashlib.sha256(self.checkpoint.read_bytes()).hexdigest()

    def test_saved_checkpoint_layout_budget_and_pending_review_agree(self):
        state = self.app.state()
        self.assertEqual(len(state["layout"]), 6)
        self.assertEqual([a["asset_id"] for a in state["layout"]], [f"P0{i}" for i in range(1,7)])
        self.assertAlmostEqual(state["run"]["aircraft_state"]["battery_available"], 79.1886116991581)
        self.assertEqual(state["run"]["aircraft_state"]["actions_remaining"], 2)
        self.assertEqual(state["operator"]["next_action"]["type"], "hold")
        self.assertEqual(state["layout"][-1]["eligibility"]["state"], "excluded")

    def test_every_asset_view_maps_to_exact_manifest_or_explicit_unavailable(self):
        for key, evidence in self.app.mission.evidence_by_view.items():
            with self.subTest(key=key):
                result = self.app.evidence(*key)
                if key[0] == "P06":
                    self.assertEqual(result["status"], "unavailable")
                    self.assertEqual(result["reason"], "asset_excluded_by_operator")
                else:
                    self.assertEqual(result["evidence_ref"]["sha256"], evidence.record["sha256"])
                    self.assertEqual((result["asset_id"],result["view_id"]), key)
                    self.assertEqual(result["assessment_mode"], "authored_replay_annotation")
        self.assertEqual(self.app.evidence("P99","overview")["finding"], "unknown")
        self.assertEqual(self.app.evidence("P01","missing")["finding"], "unknown")

    def test_bad_image_does_not_become_clear_or_debit(self):
        with patch("stratus.inspection.capture.check_image", side_effect=ValueError("hash mismatch")):
            result = self.app.evidence("P01","overview")
        self.assertEqual((result["status"],result["image_quality"],result["finding"]), ("unavailable","unknown","unknown"))
        self.assertEqual(self.app.session.snapshot(), self.before)

    def test_costs_are_exact_typed_adapter_outputs_with_both_candidate_checks(self):
        result = self.app.state()["costs"]
        self.assertEqual(result["mode"], "local_python")
        for candidate in (result["selected"],result["alternative"]):
            self.assertTrue(candidate["execution_allowed"])
            self.assertAlmostEqual(candidate["margin"], self.app.session.state.battery_available-sum(candidate[k] for k in ("outbound","capture","return_cost","reserve")))
        self.assertEqual(result["selected"]["asset_id"], "P02")
        self.assertTrue(all(not c["execution_allowed"] for c in result["candidates"] if c["asset_id"] == "P06"))

    def test_preview_can_change_to_hold_without_mutating_any_active_record(self):
        result = self.app.preview(50,20)
        self.assertIsNone(result["selected"])
        self.assertTrue(result["recommendation_changed"])
        self.assertFalse(result["state_transition_applied"])
        self.assertEqual(self.app.session.snapshot(), self.before)
        self.assertEqual(hashlib.sha256(self.checkpoint.read_bytes()).hexdigest(), self.checksum)
        self.assertEqual(self.app.preview(15,5)["selected"]["asset_id"], "P02")

    def test_preview_rejects_nonfinite_boolean_and_out_of_bounds(self):
        for reserve,capture in ((-1,5),(51,5),(15,21),(True,5),(float("nan"),5),(15,float("inf")),("15",5)):
            with self.subTest(values=(reserve,capture)), self.assertRaises(ValueError): self.app.preview(reserve,capture)
        self.assertEqual(self.app.session.snapshot(), self.before)

    def test_repeated_state_ground_refresh_evidence_and_load_never_execute(self):
        for _ in range(4):
            self.app.state(); self.app.ground.snapshot(); self.app.evidence("P03","follow-up")
            self.app.load("first-inspection.json")
        self.assertEqual(self.app.session.snapshot(), self.before)
        self.assertEqual(hashlib.sha256(self.checkpoint.read_bytes()).hexdigest(), self.checksum)

    def test_load_rejects_traversal_and_fresh_run_does_not_overwrite_checkpoint(self):
        for name in ("../first-inspection.json",str(self.checkpoint), "missing.json", 42):
            with self.assertRaises((ValueError,OSError,TypeError)): self.app.load(name)
        state = self.app.load("fresh")
        self.assertEqual(state["run"]["aircraft_state"]["actions_remaining"], 3)
        self.assertEqual(hashlib.sha256(self.checkpoint.read_bytes()).hexdigest(), self.checksum)


class DashboardHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Dashboard(); cls.server = make_server(cls.app,0)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.app.close()

    def request(self, path, data=None, **headers):
        conn = http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        try:
            if data is not None:
                headers.setdefault("Content-Type","application/json")
                conn.request("POST",path,json.dumps(data),headers)
            else: conn.request("GET",path,headers=headers)
            response = conn.getresponse(); return response.status,response.read(),dict(response.getheaders())
        finally: conn.close()

    def test_real_http_serves_one_page_script_style_and_exact_image(self):
        for path,kind in (("/","text/html"),("/app.js","text/javascript"),("/style.css","text/css"),("/image?asset=P03&view=overview","image/png")):
            with self.subTest(path=path):
                status,body,headers = self.request(path)
                self.assertEqual(status,200); self.assertTrue(headers["Content-Type"].startswith(kind))
                self.assertEqual(headers["Cache-Control"],"no-store"); self.assertGreater(len(body),100)
                if kind == "image/png": self.assertEqual(hashlib.sha256(body).hexdigest(), self.app.mission.evidence_by_view["P03","overview"].record["sha256"])

    def test_http_preview_refresh_and_export_preserve_state(self):
        before = self.app.session.snapshot()
        for path,data in (("/api/state",None),("/api/ground",None),("/api/ground/export",None),("/api/preview",{"reserve":50,"capture":20})):
            status,raw,_ = self.request(path,data); self.assertEqual(status,200)
            if path.endswith("export"):
                result = json.loads(raw); self.assertEqual(result["mode"],"recorded_measured")
        self.assertEqual(self.app.session.snapshot(),before)

    def test_http_forbids_foreign_origin_and_host(self):
        for headers in ({"Origin":"https://example.com"},{"Host":"example.com"}):
            status,_,_ = self.request("/api/preview",{"reserve":15,"capture":5},**headers)
            self.assertEqual(status,403)

    def test_http_rejects_unknown_operation_extra_fields_bad_units_and_traversal(self):
        for path,data in (("/api/execute",{"action":"inspect"}),
                          ("/api/preview",{"reserve":15,"capture":5,"apply":True}),
                          ("/api/preview",{"reserve":"15 J","capture":5}),
                          ("/api/load",{"checkpoint":"../first-inspection.json"})):
            self.assertIn(self.request(path,data)[0],(400,404))
        self.assertEqual(self.request("/../context/hardware-status.json")[0],404)
        self.assertEqual(self.request("/image?asset=P06&view=overview")[0],404)


if __name__ == "__main__": unittest.main()
