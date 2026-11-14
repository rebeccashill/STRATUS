"""Typed inspection costs: local Wolfram, exact-input cache, independent Python checks."""

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .actions import Proposal, parse_proposal, strict_json
from .engine import evaluate, execute_action, plain, protected_margin, state_error

MODEL = "toy-euclidean-energy-v1"
CONTRACT = "inspection-costs-v1"
ABS_TOLERANCE = 1e-8
REL_TOLERANCE = 1e-10
WL_SCRIPT = Path(__file__).resolve().parent / "wolfram" / "inspection_costs.wls"


class ComputationUnavailable(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{label} requires exactly: {', '.join(expected)}")


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError("IDs/revisions must be nonempty strings of at most 160 characters")
    return value


def _number(value, *, nonnegative=False):
    if type(value) not in (int, float) or abs(value) > 1e12 or not math.isfinite(value):
        raise ValueError("Numeric input must be finite and within the project bound of +/-1e12")
    if nonnegative and value < 0:
        raise ValueError("Costs, budgets and reserve must be nonnegative")
    return float(value) if value != 0 else 0.0


def normalize_input(value):
    value = plain(value)
    fields = ("contract_version", "model_version", "mission_id", "mission_revision", "state_revision",
              "position", "launch", "distance_unit", "energy_unit", "battery_available", "capture_cost",
              "travel_energy_per_distance", "return_reserve", "remaining_actions", "candidates")
    _keys(value, fields, "Computation input")
    if value["contract_version"] != CONTRACT or value["model_version"] != MODEL:
        raise ValueError("Unsupported computation contract/model")
    if value["distance_unit"] not in ("m", "km") or value["energy_unit"] != "simulated_energy_unit":
        raise ValueError("Use m/km and simulated_energy_unit; physical aircraft units are not implemented")
    factor = 1.0 if value["distance_unit"] == "m" else 1000.0
    result = copy.deepcopy(value)
    for field in ("mission_id", "mission_revision"):
        result[field] = _identifier(value[field])
    for field in ("state_revision", "remaining_actions"):
        if type(value[field]) is not int or not 0 <= value[field] <= 1_000_000:
            raise ValueError(f"{field} must be a bounded nonnegative integer")
    for field in ("position", "launch"):
        _keys(value[field], ("point_id", "x", "y"), field)
        result[field] = {"point_id": _identifier(value[field]["point_id"]),
                         "x": _number(_number(value[field]["x"]) * factor),
                         "y": _number(_number(value[field]["y"]) * factor)}
    if not isinstance(value["candidates"], list) or not 1 <= len(value["candidates"]) <= 128:
        raise ValueError("Supply 1-128 batched candidates")
    candidates, seen = [], set()
    for item in value["candidates"]:
        _keys(item, ("asset_id", "view_id", "x", "y"), "Candidate")
        key = (_identifier(item["asset_id"]), _identifier(item["view_id"]))
        if key in seen:
            raise ValueError("Duplicate asset/view candidate")
        seen.add(key)
        candidates.append({"asset_id": key[0], "view_id": key[1],
                           "x": _number(_number(item["x"]) * factor),
                           "y": _number(_number(item["y"]) * factor)})
    result["candidates"] = sorted(candidates, key=lambda c: (c["asset_id"], c["view_id"]))
    for field in ("battery_available", "capture_cost", "return_reserve"):
        result[field] = _number(value[field], nonnegative=True)
    result["travel_energy_per_distance"] = _number(_number(value["travel_energy_per_distance"], nonnegative=True) / factor, nonnegative=True)
    result["distance_unit"] = "m"
    return result


def python_costs(value):
    data = normalize_input(value)
    position = (data["position"]["x"], data["position"]["y"])
    launch = (data["launch"]["x"], data["launch"]["y"])
    options = []
    for candidate in data["candidates"]:
        target = (candidate["x"], candidate["y"])
        outbound = math.dist(position, target) * data["travel_energy_per_distance"]
        return_cost = math.dist(target, launch) * data["travel_energy_per_distance"]
        margin = protected_margin(data["battery_available"], outbound, data["capture_cost"], return_cost, data["return_reserve"])
        options.append({"asset_id": candidate["asset_id"], "view_id": candidate["view_id"],
                        "outbound": outbound, "capture": data["capture_cost"], "return_cost": return_cost,
                        "reserve": data["return_reserve"], "margin": margin,
                        "feasible": margin >= 0 and data["remaining_actions"] > 0})
    return {**{k: data[k] for k in ("contract_version", "model_version", "mission_id", "mission_revision", "state_revision", "distance_unit", "energy_unit")}, "options": options}


def mission_input(mission, state):
    error = state_error(mission, state)
    if error:
        raise ValueError(error)
    doc, energy = mission.document, mission.document["energy_model"]
    return normalize_input({"contract_version": CONTRACT, "model_version": energy["model_version"],
        "mission_id": doc["mission_id"], "mission_revision": doc["revision"], "state_revision": state.revision,
        "position": {"point_id": "current", "x": state.position[0], "y": state.position[1]},
        "launch": {"point_id": "launch", "x": doc["launch_point"]["x"], "y": doc["launch_point"]["y"]},
        "distance_unit": doc["coordinate_frame"]["unit"], "energy_unit": energy["energy_unit"],
        "battery_available": state.battery_available, "capture_cost": energy["capture_energy_per_action"],
        "travel_energy_per_distance": energy["travel_energy_per_m"], "return_reserve": energy["return_reserve"],
        "remaining_actions": state.actions_remaining,
        "candidates": [{"asset_id": a["asset_id"], "view_id": view, "x": a["position"]["x"], "y": a["position"]["y"]}
                       for a in doc["assets"] for view in a["planned_view_ids"]]})


class LocalWolfram:
    """Fixed script and data-only JSON files; never evaluates a model-supplied program."""
    def __init__(self, executable=None, kernel=None, timeout=25, script=None):
        if not 0 < timeout <= 60:
            raise ValueError("Local Wolfram timeout must be within 0-60 seconds")
        self.script = Path(script).resolve() if script else WL_SCRIPT.resolve()
        allowed = {WL_SCRIPT.resolve(), (WL_SCRIPT.parent / 'fleet_costs.wls').resolve()}
        if self.script not in allowed:
            raise ValueError('Only the fixed STRATUS inspection/fleet scripts may run')
        installations = []
        base = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Wolfram Research" / "Wolfram"
        if base.is_dir():
            installations = sorted(base.glob("*"), key=lambda p: tuple(int(s) if s.isdigit() else 0 for s in p.name.split(".")), reverse=True)
        self.executable = executable or os.environ.get("STRATUS_WOLFRAMSCRIPT") or shutil.which("wolframscript")
        if not self.executable:
            self.executable = next((str(p / "wolframscript.exe") for p in installations if (p / "wolframscript.exe").is_file()), None)
        self.kernel = kernel or os.environ.get("STRATUS_WOLFRAM_KERNEL")
        if not self.kernel and self.executable:
            sibling = Path(self.executable).parent / "WolframKernel.exe"
            self.kernel = str(sibling) if sibling.is_file() else None
        if not self.kernel:
            # The standalone WolframScript PATH launcher lives outside the kernel directory.
            self.kernel = next((str(p / "WolframKernel.exe") for p in installations
                                if (p / "WolframKernel.exe").is_file()), None)
        self.timeout = timeout

    def __call__(self, data):
        if not self.executable or not Path(self.executable).is_file():
            raise ComputationUnavailable("runtime_missing", "Local wolframscript was not found")
        with tempfile.TemporaryDirectory(prefix="stratus-wolfram-") as folder:
            source, target = Path(folder) / "input.json", Path(folder) / "output.json"
            source.write_text(json.dumps(data, allow_nan=False), encoding="utf-8")
            command = [str(self.executable), "-local"]
            if self.kernel:
                command.append(str(self.kernel))
            command += ["-timeout", "15", "-file", str(self.script), str(source), str(target)]
            try:
                process = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout, stdin=subprocess.DEVNULL)
            except subprocess.TimeoutExpired:
                raise ComputationUnavailable("timeout", "Local Wolfram exceeded its bounded execution time") from None
            except OSError:
                raise ComputationUnavailable("runtime_unavailable", "Local Wolfram could not be launched") from None
            if process.returncode != 0 or not target.is_file():
                raise ComputationUnavailable("runtime_failed", "Local Wolfram did not produce a successful typed result; inspect activation/access in normal PowerShell")
            if target.stat().st_size > 512_000:
                raise ComputationUnavailable("invalid_response", "Wolfram result exceeds the bounded size")
            try:
                return strict_json(target.read_text(encoding="utf-8-sig"), max_chars=512_000)
            except (ValueError, UnicodeError) as exc:
                raise ComputationUnavailable("invalid_response", "Wolfram returned invalid JSON") from exc


def _check_reply(reply, expected):
    if not isinstance(reply, dict):
        raise ValueError("Wolfram result must be an object")
    _keys(reply, (*expected.keys(), "wolfram_version", "system_id"), "Wolfram result")
    for field in expected.keys() - {"options"}:
        if type(reply[field]) is not type(expected[field]) or reply[field] != expected[field]:
            raise ValueError("Wolfram result identity/model/units do not match the request")
    for field in ("wolfram_version", "system_id"):
        _identifier(reply[field])
    if not isinstance(reply["options"], list) or len(reply["options"]) != len(expected["options"]):
        raise ValueError("Wolfram result must include exactly the requested candidates")
    received = {}
    for item in reply["options"]:
        _keys(item, ("asset_id", "view_id", "outbound", "capture", "return_cost", "reserve", "margin", "feasible"), "Wolfram option")
        key = (_identifier(item["asset_id"]), _identifier(item["view_id"]))
        if key in received or type(item["feasible"]) is not bool:
            raise ValueError("Duplicate option or non-boolean feasibility")
        for field in ("outbound", "capture", "return_cost", "reserve", "margin"):
            value = item[field]
            if type(value) not in (int, float) or not math.isfinite(value) or (field != "margin" and value < 0):
                raise ValueError("Wolfram costs must be finite; debits/reserve must be nonnegative")
        received[key] = item
    expected_keys = {(i["asset_id"], i["view_id"]) for i in expected["options"]}
    if set(received) != expected_keys:
        raise ValueError("Wolfram returned unknown candidate identities")
    differences = []
    for reference in expected["options"]:
        actual = received[(reference["asset_id"], reference["view_id"])]
        for field in ("outbound", "capture", "return_cost", "reserve", "margin"):
            if not math.isclose(actual[field], reference[field], abs_tol=ABS_TOLERANCE, rel_tol=REL_TOLERANCE):
                differences.append({"asset_id": reference["asset_id"], "view_id": reference["view_id"], "field": field,
                                    "python": reference[field], "wolfram": actual[field]})
        if actual["feasible"] != reference["feasible"]:
            differences.append({"asset_id": reference["asset_id"], "view_id": reference["view_id"], "field": "feasible",
                                "python": reference["feasible"], "wolfram": actual["feasible"]})
        if (actual["margin"] >= 0) != (reference["margin"] >= 0):
            differences.append({"asset_id": reference["asset_id"], "view_id": reference["view_id"], "field": "margin_sign",
                                "python": reference["margin"], "wolfram": actual["margin"]})
    return differences


class CostCalculator:
    def __init__(self, mode="wolfram", runner=None):
        if mode not in ("local", "wolfram"):
            raise ValueError("Computation mode must be local or wolfram")
        self.mode, self.runner, self.cache = mode, runner if runner is not None else LocalWolfram(), {}
        self.local_kernel_calls = 0

    def compute(self, value):
        data = normalize_input(value)
        expected = python_costs(data)
        script_hash = hashlib.sha256(WL_SCRIPT.read_bytes()).hexdigest()
        key = hashlib.sha256(json.dumps({"input": data, "script_sha256": script_hash}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        result = {"mode": "local_python", "execution_permitted": True, "normalized_input": data,
                  "cache_key": key, "model_version": MODEL, "script_sha256": script_hash,
                  "output": expected, "python_output": expected, "wolfram_output": None,
                  "failure": None, "disagreements": [],
                  "tolerance": {"absolute": ABS_TOLERANCE, "relative": REL_TOLERANCE, "feasibility_sign": "strict; never relaxed by tolerance"},
                  "request_counts": {"local_kernel_calls": self.local_kernel_calls, "cloud_requests": 0, "alpha_calls": 0},
                  "state_transition_applied": False}
        if self.mode == "local":
            return copy.deepcopy(result)
        if key in self.cache:
            result.update(mode="cached_wolfram_local", output=copy.deepcopy(self.cache[key]), wolfram_output=copy.deepcopy(self.cache[key]))
            return copy.deepcopy(result)
        self.local_kernel_calls += 1
        result["request_counts"]["local_kernel_calls"] = self.local_kernel_calls
        try:
            reply = self.runner(copy.deepcopy(data))
            differences = _check_reply(reply, expected)
        except (ComputationUnavailable, ValueError, TypeError, KeyError, TimeoutError, OSError, OverflowError) as exc:
            result.update(mode="local_python_fallback", failure={"code": getattr(exc, "code", "invalid_response"),
                          "message": str(exc) if isinstance(exc, ComputationUnavailable) else "Wolfram response/transport failed typed validation; equivalent local Python used"})
            return copy.deepcopy(result)
        result["wolfram_output"] = copy.deepcopy(reply)
        if differences:
            result.update(mode="wolfram_disagreement", execution_permitted=False, disagreements=differences)
            return copy.deepcopy(result)
        result.update(mode="wolfram_local", output=copy.deepcopy(reply))
        if len(self.cache) >= 64:
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = copy.deepcopy(reply)
        return copy.deepcopy(result)


def compute_inspection_options(value, calculator=None):
    """Public typed cost tool; data only, with no state transition."""
    return (calculator or CostCalculator()).compute(value)


def compute_mission_options(mission, state, calculator=None):
    result = compute_inspection_options(mission_input(mission, state), calculator)
    checks = []
    for option in result["output"]["options"]:
        proposal = Proposal("inspect" if option["view_id"] == "overview" else "follow_up", option["asset_id"], option["view_id"],
                            "Candidate budget review", "Return or stop if infeasible")
        decision = evaluate(mission, state, proposal)
        checks.append({"asset_id": option["asset_id"], "view_id": option["view_id"],
                       "execution_allowed": decision.allowed and option["feasible"] and result["execution_permitted"],
                       "code": decision.code if result["execution_permitted"] else "numerical_disagreement"})
    result["action_checks"] = checks
    return result


def execute_computed_action(mission, state, value, calculator=None):
    proposal = parse_proposal(value)
    local = evaluate(mission, state, proposal)
    if not local.allowed or proposal.action_type in ("return", "stop"):
        return execute_action(mission, state, proposal)
    computation = compute_mission_options(mission, state, calculator)
    check = next(i for i in computation["action_checks"] if (i["asset_id"], i["view_id"]) == (proposal.asset_id, proposal.view_id))
    if not check["execution_allowed"]:
        return state, {"status": "rejected", "code": check["code"], "state_transition_applied": False, "computation": computation}
    updated, event = execute_action(mission, state, proposal)
    event["computation"] = computation
    return updated, event
