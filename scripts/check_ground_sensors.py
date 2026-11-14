"""Read the purchased ground sensors; no simulated aircraft state is changed."""

import argparse
import csv
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = {
    "PMSA003I": (("pm1_0", "ug/m3"), ("pm2_5", "ug/m3"), ("pm10", "ug/m3")),
    "BME280": (("temperature", "degC"), ("relative_humidity", "%RH"), ("pressure", "hPa")),
}
PACKAGES = ("hidapi", "adafruit-blinka", "adafruit-circuitpython-bme280", "adafruit-circuitpython-pm25")


def now():
    return datetime.now(timezone.utc).isoformat()


def read_values(name, sensor):
    if name == "PMSA003I":
        raw = sensor.read()  # The installed PM25 driver checks header, length and checksum.
        values = tuple(raw[key] for key in ("pm10 env", "pm25 env", "pm100 env"))
    else:
        values = (sensor.temperature, sensor.relative_humidity, sensor.pressure)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("Invalid non-finite or non-numeric measurement")
    if name == "PMSA003I" and any(v < 0 for v in values):
        raise ValueError("Invalid negative particulate concentration")
    if name == "BME280" and not 0 <= values[1] <= 100:
        raise ValueError("Invalid relative humidity outside 0-100 percent")
    return values


def collect(sensors, errors, output, *, samples, interval, location):
    counts = {name: 0 for name in sensors}
    fields = ("received_at_utc", "acquired_at_utc", "sensor_id", "location", "source_mode",
              "quality", "variable", "value", "unit", "error")
    with output.open("x", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for sample in range(samples):
            for name, sensor in sensors.items():
                values, acquired, error, quality = None, "", errors.get(name, ""), "unavailable"
                if sensor is not None:
                    try:
                        values = read_values(name, sensor)
                        acquired, quality = now(), "unreviewed"
                        counts[name] += 1
                    except (RuntimeError, OSError, ValueError, KeyError) as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        quality = "invalid" if isinstance(exc, (ValueError, KeyError)) or "invalid" in str(exc).lower() else "unavailable"
                received = now()
                for index, (variable, unit) in enumerate(CHANNELS[name]):
                    writer.writerow({"received_at_utc": received, "acquired_at_utc": acquired,
                                     "sensor_id": name, "location": location,
                                     "source_mode": "live_measured" if values is not None else "unavailable",
                                     "quality": quality, "variable": variable,
                                     "value": values[index] if values is not None else "", "unit": unit,
                                     "error": error})
                if values is None:
                    print(f"{name}: {quality} - {error}", flush=True)
                else:
                    print(name + ": " + " | ".join(f"{v:.2f} {unit}" for v, (_, unit) in zip(values, CHANNELS[name])) + " | unreviewed", flush=True)
            file.flush()
            if sample + 1 < samples:
                time.sleep(interval)
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pmsa", "both"), required=True)
    parser.add_argument("--location", default="not_supplied", help="Actual ground location label; never a simulated aircraft coordinate")
    args = parser.parse_args()
    os.environ["BLINKA_MCP2221"] = "1"  # Must precede all Blinka imports.
    try:
        import board
        import busio
        from adafruit_pm25.i2c import PM25_I2C
        i2c = busio.I2C(board.SCL, board.SDA, frequency=100000)
    except (ImportError, RuntimeError, OSError, ValueError) as exc:
        print(f"Cannot open the USB bridge: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    try:
        deadline = time.monotonic() + 3
        while not i2c.try_lock():
            if time.monotonic() >= deadline:
                raise RuntimeError("I2C bus is busy; close other sensor readers")
            time.sleep(0.05)
        try:
            addresses = i2c.scan()
        finally:
            i2c.unlock()
        print("I2C devices:", [hex(a) for a in addresses], flush=True)
        if args.mode == "pmsa" and any(a in addresses for a in (0x77, 0x76)):
            print("BME280 address also detected. Unplug USB and disconnect the BME280 for the PMSA003I-only test.", file=sys.stderr)
            return 2
        names = ["PMSA003I"] + (["BME280"] if args.mode == "both" else [])
        sensors, errors, selected_addresses = dict.fromkeys(names), {}, {}
        for name in names:
            address = 0x12 if name == "PMSA003I" else next((a for a in (0x77, 0x76) if a in addresses), None)
            selected_addresses[name] = hex(address) if address is not None else None
            try:
                if address not in addresses:
                    raise RuntimeError("Expected sensor address not found")
                if name == "PMSA003I":
                    sensors[name] = PM25_I2C(i2c, reset_pin=None, address=address)
                else:
                    from adafruit_bme280 import basic
                    sensors[name] = basic.Adafruit_BME280_I2C(i2c, address=address)
            except (ImportError, RuntimeError, OSError, ValueError) as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"
                print(f"{name}: unavailable - {errors[name]}", flush=True)
        if sensors["PMSA003I"] is not None:
            print("Waiting 30 seconds before sampling the PMSA003I...", flush=True)
            time.sleep(30)  # Project settling allowance; not a calibration claim.
        output_dir = ROOT / "context" / "ground-measurements"
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stem = f"{args.mode}-{stamp}-{uuid4().hex[:6]}"
        output = output_dir / (stem + ".csv")
        counts = collect(sensors, errors, output, samples=5, interval=2, location=args.location)
        complete = all(count == 5 for count in counts.values())
        versions = {}
        for package in PACKAGES:
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = "not_installed"
        summary = {"finished_at_utc": now(), "mode": args.mode, "requested_i2c_frequency_hz": 100000,
                   "detected_addresses": [hex(a) for a in addresses], "sensor_addresses": selected_addresses,
                   "successful_reads": counts, "expected_reads_per_sensor": 5, "initialization_errors": errors,
                   "result": "PASS" if complete else "PARTIAL_OR_FAILED", "csv": str(output),
                   "location": args.location, "quality": "unreviewed; calibration not verified",
                   "particulate_convention": "environmental mass concentration; ug/m3 means micrograms per cubic metre",
                   "pmsa_library_keys": {"pm1_0": "pm10 env", "pm2_5": "pm25 env", "pm10": "pm100 env"},
                   "package_versions": versions, "real_flight": False, "mission_state_changed": False}
        summary_path = output_dir / (stem + ".json")
        summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        for name, count in counts.items():
            print(f"{name}: {count}/5 successful reads")
        print("Result:", summary["result"])
        print("Saved:", output)
        print("Summary:", summary_path)
        return 0 if complete else 3
    finally:
        i2c.deinit()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Stopped by operator; no mission state changed.", file=sys.stderr)
        raise SystemExit(130)
