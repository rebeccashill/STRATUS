"""One optional host reader and one typed live/recorded/synthetic/unavailable feed."""

import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from .actions import strict_json
from .loader import finite
from .review import GROUND_UNITS, _utc_string, ground_snapshot, utc_time

POLL_SECONDS = 5
STALE_SECONDS = 20
SETTLE_SECONDS = 30
MODE_LABELS = {"live_measured": "Live", "recorded_measured": "Recorded", "synthetic": "Synthetic example", "unavailable": "Unavailable"}
SENSORS = {"BME280": ("ground-node-001/bme280", ("temperature", "relative_humidity", "pressure")),
           "PMSA003I": ("ground-node-001/pmsa003i", ("pm1_0", "pm2_5", "pm10"))}
FIELDS = {"schema_version", "observation_id", "node_id", "sensor_id", "sensor_model", "variable", "value", "unit",
          "acquired_at_utc", "received_at_utc", "receipt_time_status", "timestamp_basis", "normalized_at_utc",
          "location", "source_mode", "acquisition_source", "quality", "calibration", "uncertainty", "context_role", "provenance"}


def validate_observation(row):
    if not isinstance(row, dict) or set(row) != FIELDS or row["schema_version"] != "1.0.0":
        raise ValueError("Observation does not match the shared v1 field contract")
    model = row["sensor_model"]
    if (model not in SENSORS or row["sensor_id"] != SENSORS[model][0] or row["variable"] not in SENSORS[model][1]
            or row["node_id"] != "ground-node-001" or row["context_role"] != "ground_context_only"
            or row["unit"] != GROUND_UNITS[row["variable"]] or row["source_mode"] not in MODE_LABELS):
        raise ValueError("Observation identity, channel, source or unit mismatch")
    value = row["value"]
    if not finite(value) or abs(value) > 1e6:
        raise ValueError("Measurement must be a bounded finite number")
    v = row["variable"]
    if ((v == "relative_humidity" and not 0 <= value <= 100) or (v == "temperature" and not -50 <= value <= 100)
            or (v == "pressure" and not 100 <= value <= 1200) or (v.startswith("pm") and value < 0)):
        raise ValueError("Measurement outside the project's documented sanity bounds")
    _utc_string(row["acquired_at_utc"]); _utc_string(row["normalized_at_utc"])
    if row["received_at_utc"] is not None: _utc_string(row["received_at_utc"])
    expected = "synthetic" if row["source_mode"] == "synthetic" else "physical_sensor"
    if row["acquisition_source"] != expected or row["quality"]["status"] not in ("unreviewed", "reviewed"):
        raise ValueError("Invalid acquisition/quality label")
    for key, fields in (("location",{"status","label","position","coordinate_frame"}),
                        ("quality",{"status","flags"}), ("calibration",{"status","reference"}),
                        ("uncertainty",{"status","value","unit","kind"}),
                        ("provenance",{"source_file","source_sha256","source_row","original_source_mode"})):
        if not isinstance(row[key],dict) or set(row[key]) != fields:
            raise ValueError("Malformed observation "+key)
    if (not isinstance(row["observation_id"],str) or not re.fullmatch(r"obs_[a-f0-9]{24}",row["observation_id"])
            or row["timestamp_basis"] != "host_read_completion" or row["source_mode"] == "unavailable"
            or row["receipt_time_status"] not in ("recorded","unknown")
            or (row["received_at_utc"] is None) != (row["receipt_time_status"] == "unknown")):
        raise ValueError("Invalid observation identity or time/source contract")
    flags = row["quality"]["flags"]
    if not isinstance(flags,list) or any(not isinstance(f,str) for f in flags) or len(set(flags)) != len(flags):
        raise ValueError("Invalid quality flags")
    location = row["location"]
    if location["status"] not in ("known","unknown") or any(location[k] is not None and not isinstance(location[k],str) for k in ("label","coordinate_frame")):
        raise ValueError("Invalid location metadata")
    if location["position"] is not None:
        p = location["position"]
        if not isinstance(p,dict) or set(p) != {"x","y","unit"} or not finite(p["x"]) or not finite(p["y"]) or p["unit"] not in ("m","deg"):
            raise ValueError("Invalid real location coordinates")
    cal,unc,prov = row["calibration"],row["uncertainty"],row["provenance"]
    if cal["status"] not in ("unknown","documented") or (cal["reference"] is not None and not isinstance(cal["reference"],str)):
        raise ValueError("Invalid calibration metadata")
    if unc["status"] not in ("unknown","estimated") or (unc["value"] is not None and (not finite(unc["value"]) or unc["value"] < 0)) or any(unc[k] is not None and not isinstance(unc[k],str) for k in ("unit","kind")):
        raise ValueError("Invalid uncertainty metadata")
    if (not isinstance(prov["source_file"],str) or not prov["source_file"] or not isinstance(prov["source_sha256"],str)
            or not re.fullmatch(r"[a-f0-9]{64}",prov["source_sha256"]) or type(prov["source_row"]) is not int
            or prov["source_row"] < 2 or prov["original_source_mode"] not in MODE_LABELS):
        raise ValueError("Invalid acquisition provenance")
    if row["location"]["status"] == "unknown" and any(row["location"].get(k) is not None for k in ("label", "position", "coordinate_frame")):
        raise ValueError("Unknown location cannot acquire simulated coordinates")
    return row


def unavailable(mission, reason="not_requested"):
    result = ground_snapshot(mission, "unavailable")
    result["reason"] = reason
    result["sensor_states"] = {name: {"status": "unavailable", "technical_error": None} for name in SENSORS}
    return result


def present_snapshot(snapshot, *, now=None):
    """Same presentation shape for all modes; acquisition times are never refreshed."""
    if (not isinstance(snapshot, dict) or snapshot.get("mode") not in MODE_LABELS
            or not isinstance(snapshot.get("observations"), list) or len(snapshot["observations"]) > 6
            or snapshot.get("context_role") != "ground_context_only"
            or not isinstance(snapshot.get("location"),dict)
            or set(snapshot["location"]) != {"status","label","position","coordinate_frame"}):
        raise ValueError("Expected a labeled ground snapshot and an observation list")
    result = copy.deepcopy(snapshot); when = utc_time(now); seen = set(); valid = []
    states = copy.deepcopy(result.get("sensor_states", {}))
    for row in result.get("observations", []):
        model = row.get("sensor_model") if isinstance(row, dict) else None
        try:
            validate_observation(row)
            if row["observation_id"] in seen: raise ValueError("Duplicate observation ID")
            if row["source_mode"] != result["mode"]: raise ValueError("Snapshot and observation source modes differ")
            if row["location"] != result["location"]: raise ValueError("Snapshot and observation locations differ")
            seen.add(row["observation_id"]); valid.append(row)
        except (ValueError, KeyError, TypeError) as exc:
            if model in SENSORS: states[model] = {"status": "invalid", "technical_error": str(exc)}
    sensors = []
    for model, (sensor_id, variables) in SENSORS.items():
        rows = [r for r in valid if r["sensor_model"] == model]
        status = states.get(model, {}).get("status", "fresh" if rows else "unavailable")
        if len(rows) != 3 or {r["variable"] for r in rows} != set(variables):
            if rows: status = "invalid"
            rows = []
        age = max(((when - _utc_string(r["acquired_at_utc"])).total_seconds() for r in rows), default=None)
        if age is not None and status == "fresh":
            future = any((when-_utc_string(r["acquired_at_utc"])).total_seconds() < -5 for r in rows)
            status = "invalid" if future else "stale" if age > STALE_SECONDS else "fresh"
        if status in ("invalid", "unavailable", "warming_up"): rows = []
        values = {r["variable"]: r for r in rows}
        sensors.append({"sensor_model": model, "sensor_id": sensor_id, "status": status, "age_seconds": age,
            "source_label": MODE_LABELS.get(result["mode"], "Unavailable"),
            "channels": [{"variable": v, "unit": GROUND_UNITS[v], "value": values[v]["value"] if v in values else None,
                          "acquired_at_utc": values[v]["acquired_at_utc"] if v in values else None,
                          "quality": values[v]["quality"] if v in values else {"status": status, "flags": []}}
                         for v in variables], "technical_error": states.get(model, {}).get("technical_error")})
    usable_models = {s["sensor_model"] for s in sensors if s["status"] in ("fresh", "stale")}
    result["observations"] = [r for r in valid if r["sensor_model"] in usable_models]
    result.update(sensors=sensors, source_label=MODE_LABELS.get(result["mode"], "Unavailable"),
                  polling_seconds=POLL_SECONDS, stale_seconds=STALE_SECONDS, pmsa_settle_seconds=SETTLE_SECONDS,
                  presented_at_utc=when.isoformat())
    return result


class HardwareReader:
    def __init__(self, mission, *, monotonic=time.monotonic):
        self.mission, self.clock = mission, monotonic
        self.i2c, self.devices, self.started, self.addresses = None, {}, None, []
        self.pmsa_started = None
        self.folder = mission.project_root / "context/ground-measurements/live" / (utc_time().strftime("%Y%m%dT%H%M%SZ")+"-"+uuid4().hex[:6])
        self.sequence = 0
        self.location = copy.deepcopy(ground_snapshot(mission, "unavailable")["location"])
        try:
            registry = strict_json((mission.project_root / "context/hardware-status.json").read_text(encoding="utf-8-sig"))
            self.location = registry["location"]
        except (OSError, ValueError, KeyError): pass

    def close(self):
        if self.i2c is not None:
            try: self.i2c.deinit()
            except (OSError, RuntimeError): pass
        self.i2c, self.devices, self.started, self.pmsa_started = None, {}, None, None

    def _open(self):
        os.environ["BLINKA_MCP2221"] = "1"  # Before every optional Blinka import.
        import board
        import busio
        self.i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
        self._scan()
        self.started = self.clock()

    def _scan(self):
        deadline = self.clock()+3
        while not self.i2c.try_lock():
            if self.clock() >= deadline: raise RuntimeError("I2C bus busy; close other sensor readers")
            time.sleep(0.05)
        try: self.addresses = self.i2c.scan()
        finally: self.i2c.unlock()

    def sample(self):
        snapshot = unavailable(self.mission, "no_valid_current_read")
        snapshot.update(mode="live_measured", location=copy.deepcopy(self.location), node_id="ground-node-001")
        errors, values = {}, []
        try:
            if self.i2c is None: self._open()
            elif any(model not in self.devices for model in SENSORS): self._scan()
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            self.close()
            for model in SENSORS: snapshot["sensor_states"][model] = {"status": "unavailable", "technical_error": f"{type(exc).__name__}: {exc}"}
            return snapshot
        for model in SENSORS:
            try:
                if model not in self.devices:
                    if model == "BME280":
                        from adafruit_bme280 import basic
                        address = next((a for a in (0x77,0x76) if a in self.addresses), None)
                        if address is None: raise RuntimeError("BME280 not found at 0x77/0x76")
                        self.devices[model] = basic.Adafruit_BME280_I2C(self.i2c,address=address)
                    else:
                        from adafruit_pm25.i2c import PM25_I2C
                        if 0x12 not in self.addresses: raise RuntimeError("PMSA003I not found at 0x12")
                        self.devices[model] = PM25_I2C(self.i2c,reset_pin=None,address=0x12)
                        self.pmsa_started = self.clock()
                if model == "PMSA003I" and self.clock()-self.pmsa_started < SETTLE_SECONDS:
                    snapshot["sensor_states"][model] = {"status": "warming_up", "technical_error": None}
                    continue
                device = self.devices[model]
                if model == "BME280": sample = (device.temperature,device.relative_humidity,device.pressure)
                else:
                    raw = device.read()  # Library validates frame/checksum.
                    sample = tuple(raw[k] for k in ("pm10 env","pm25 env","pm100 env"))
                acquired = utc_time().isoformat()
                # Validate the whole sensor together; never replace a failed channel with zero.
                for variable, value in zip(SENSORS[model][1],sample):
                    probe = self._record(model,variable,value,acquired,acquired,{"source_file":"pending","source_sha256":"0"*64,"source_row":2,"original_source_mode":"live_measured"})
                    validate_observation(probe)
                values.extend((model,variable,value,acquired) for variable,value in zip(SENSORS[model][1],sample))
                snapshot["sensor_states"][model] = {"status":"fresh","technical_error":None}
            except (ImportError, OSError, RuntimeError, ValueError, KeyError) as exc:
                status = "invalid" if isinstance(exc,(ValueError,KeyError)) or "checksum" in str(exc).lower() or "invalid" in str(exc).lower() else "unavailable"
                snapshot["sensor_states"][model] = {"status":status,"technical_error":f"{type(exc).__name__}: {exc}"}
                self.devices.pop(model,None); errors[model] = status
                if model == "PMSA003I": self.pmsa_started = None
        if values:
            snapshot["observations"] = self._save(values)
            snapshot.update(status="available",reason=None,physical_acquisition_performed=True)
            snapshot["source"] = {"path":snapshot["observations"][0]["provenance"]["source_file"],
                                  "sha256":snapshot["observations"][0]["provenance"]["source_sha256"]}
        snapshot["technical_details"] = {"bridge":"Adafruit 4471 MCP2221A", "frequency_hz":100000,
            "detected_addresses":[hex(a) for a in self.addresses], "BME280_product":"SparkFun SEN-15440",
            "PMSA003I_product":"Adafruit 4632", "pm_channel_convention":"environmental mass concentration",
            "pmsa_keys":["pm10 env","pm25 env","pm100 env"]}
        if len(errors) == 2: self.close()  # A later poll can detect a reconnect.
        return snapshot

    def _record(self, model, variable, value, acquired, received, provenance):
        identifier = hashlib.sha256(json.dumps([model,variable,acquired,value],allow_nan=False).encode()).hexdigest()[:24] if finite(value) else "0"*24
        return {"schema_version":"1.0.0","observation_id":"obs_"+identifier,"node_id":"ground-node-001",
            "sensor_id":SENSORS[model][0],"sensor_model":model,"variable":variable,"value":value,"unit":GROUND_UNITS[variable],
            "acquired_at_utc":acquired,"received_at_utc":received,"receipt_time_status":"recorded",
            "timestamp_basis":"host_read_completion","normalized_at_utc":received,"location":copy.deepcopy(self.location),
            "source_mode":"live_measured","acquisition_source":"physical_sensor","quality":{"status":"unreviewed","flags":["calibration_unknown","uncertainty_unknown"]},
            "calibration":{"status":"unknown","reference":None},"uncertainty":{"status":"unknown","value":None,"unit":None,"kind":None},
            "context_role":"ground_context_only","provenance":provenance}

    def _save(self, values, *, source_mode="live_measured"):
        self.folder.mkdir(parents=True,exist_ok=True); self.sequence += 1
        path = self.folder / f"sample-{self.sequence:05d}.csv"; received = utc_time().isoformat()
        stream = io.StringIO(newline=""); writer = csv.writer(stream,lineterminator="\n")
        writer.writerow(["sensor_model","variable","value","unit","acquired_at_utc","received_at_utc"])
        for model,variable,value,acquired in values: writer.writerow([model,variable,value,GROUND_UNITS[variable],acquired,received])
        raw = stream.getvalue().encode(); path.write_bytes(raw); checksum = hashlib.sha256(raw).hexdigest()
        records = [self._record(model,variable,value,acquired,received,{"source_file":path.relative_to(self.mission.project_root).as_posix(),
                   "source_sha256":checksum,"source_row":i+2,"original_source_mode":"live_measured"})
                   for i,(model,variable,value,acquired) in enumerate(values)]
        if source_mode == "synthetic":
            for row in records:
                row.update(source_mode="synthetic",acquisition_source="synthetic")
                row["provenance"]["original_source_mode"] = "synthetic"
        path.with_suffix(".jsonl").write_text("".join(json.dumps(r,allow_nan=False)+"\n" for r in records),encoding="utf-8")
        return records


def historical_snapshot(snapshot):
    """Reopen measurements as history; keep IDs, original times and raw provenance."""
    result = copy.deepcopy(snapshot)
    result.pop("sensors", None)
    result["physical_acquisition_performed"] = False
    if result["mode"] in ("live_measured", "recorded_measured"):
        result["mode"] = "recorded_measured"
        for row in result["observations"]:
            row["source_mode"] = "recorded_measured"
        result["sensor_states"] = {
            model: {"status": "stale" if any(r["sensor_model"] == model for r in result["observations"]) else "unavailable",
                    "technical_error": None} for model in SENSORS}
    return result


class GroundFeed:
    def __init__(self, mission, recorded, *, reader=None):
        self.mission, self.recorded = mission, historical_snapshot(recorded)
        if reader is None:
            from .usb_reader import USBWorkerReader
            reader = USBWorkerReader(mission)
        self.reader = reader
        self.mode, self._snapshot = "recorded", copy.deepcopy(self.recorded)
        self._lock, self._stop, self._thread = threading.RLock(), threading.Event(), None
        self._generation = 0

    def restore(self, snapshot):
        """Invalidate any late live poll before displaying the reopened run's context."""
        with self._lock:
            if hasattr(self.reader, 'set_live'): self.reader.set_live(False)
            self.recorded = historical_snapshot(snapshot)
            self.mode = "recorded"
            self._generation += 1
            self._snapshot = copy.deepcopy(self.recorded)
        return self.snapshot()

    def select(self, mode):
        if mode not in ("live","recorded","synthetic","unavailable"): raise ValueError("Unknown ground mode")
        with self._lock:
            self.mode = mode; self._generation += 1
            if hasattr(self.reader, 'set_live'): self.reader.set_live(mode == 'live')
            if mode == "recorded": self._snapshot = copy.deepcopy(self.recorded)
            elif mode == "unavailable": self._snapshot = unavailable(self.mission,"operator_selected_unavailable")
            elif mode == "synthetic":
                example = HardwareReader(self.mission)
                example.folder = self.mission.project_root / "context/ground-measurements/examples" / (utc_time().strftime("%Y%m%dT%H%M%SZ")+"-"+uuid4().hex[:6])
                values = [(model,v,value,"2026-11-14T00:00:00+00:00") for model,items in
                          (("BME280",(("temperature",21.0),("relative_humidity",45.0),("pressure",1013.0))),
                           ("PMSA003I",(("pm1_0",1.0),("pm2_5",2.0),("pm10",3.0)))) for v,value in items]
                records = example._save(values,source_mode="synthetic")
                self._snapshot = unavailable(self.mission)
                self._snapshot.update(status="available",mode="synthetic",node_id="ground-node-001",observations=records,
                                      sensor_states={m:{"status":"fresh","technical_error":None} for m in SENSORS})
            else:
                self._snapshot = unavailable(self.mission,"starting_live_reader")
                self._snapshot.update(mode="live_measured",sensor_states={m:{"status":"warming_up","technical_error":None} for m in SENSORS})
                if self._thread is None:
                    self._thread = threading.Thread(target=self._poll,name="stratus-ground",daemon=True);self._thread.start()
        return self.snapshot()

    def _poll(self):
        while not self._stop.is_set():
            with self._lock: mode,generation = self.mode,self._generation
            if mode == "live":
                try: data = self.reader.sample()
                except Exception as exc:
                    data = unavailable(self.mission,"reader_failed"); data["technical_details"] = {"error":f"{type(exc).__name__}: {exc}"}
                with self._lock:
                    if self.mode == "live" and self._generation == generation:
                        self._snapshot = data
                        if data.get("mode") == "live_measured" and data.get("observations"):
                            self.recorded = historical_snapshot(present_snapshot(data))
            self._stop.wait(POLL_SECONDS)
        self.reader.close()

    def snapshot(self):
        with self._lock: return present_snapshot(self._snapshot)

    def export_recorded(self):
        with self._lock:
            data = copy.deepcopy(self._snapshot)
        if data["mode"] not in ("live_measured","recorded_measured") or not data["observations"]:
            raise ValueError("Export requires an actual measured sample")
        data = present_snapshot(data)
        if not data["observations"]: raise ValueError("Export requires valid actual measured channels")
        data.pop("sensors",None)
        data.update(mode="recorded_measured",source_label="Recorded",physical_acquisition_performed=False)
        for row in data["observations"]: row["source_mode"] = "recorded_measured"
        return data

    def close(self):
        self._stop.set()
        if self._thread: self._thread.join(timeout=0.2)
        if not self._thread or not self._thread.is_alive(): self.reader.close()
