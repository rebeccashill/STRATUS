"""Opt-in hazard component routes mounted on the existing inspection server.

This preview uses the explicitly labeled fixture host. Part 12 can reuse
mount_routes with its own dispatcher after wiring HazardBridge to its store.
"""

from datetime import datetime, timezone
import html
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from stratus.inspection.actions import strict_json
from stratus.inspection.computation import CostCalculator
from .fixtures import crane_event
from .harness import FixtureFleetHost
from .core import rectangle

WEB = Path(__file__).resolve().parents[1] / "inspection" / "web"


def report_html(state):
    registry = state["hazards"]["registry"]
    rows = "".join("<tr>" + "".join("<td>" + html.escape(str(v)) + "</td>" for v in (
        i, d["task_id"], d["status"], d.get("checked_hazard_revision", "not assessed"), d["battery"], d["actions_used"])) + "</tr>" for i, d in state["drones"].items())
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><title>STRATUS hazard fixture report</title>"
            "<style>body{font:16px Arial;max-width:1100px;margin:40px auto;line-height:1.5}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #aaa;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"
            "<h1>STRATUS reported-hazard report</h1><p><b>Fixture host preview. Part 12 fleet integration has not run.</b></p>"
            "<p>Authored site-local rectangles; simulated movement, aircraft and captures. No real obstacle detection or collision-prevention claim.</p>"
            f"<p>Drone records: {state['size']}; hazard revision: {registry['revision']}; logical time: {state['sim_time']}.</p>"
            "<table><tr><th>Drone</th><th>Task</th><th>Status</th><th>Checked revision</th><th>Simulated EU</th><th>Captures used</th></tr>" + rows + "</table>"
            "<h2>Reported areas and source records</h2><pre>" + html.escape(json.dumps(registry, indent=2)) + "</pre>"
            "<h2>Current impact</h2><pre>" + html.escape(json.dumps(state["hazards"]["latest_impact"], indent=2)) + "</pre>"
            "<h2>Ground context</h2><pre>" + html.escape(json.dumps(state["ground"], indent=2)) + "</pre>"
            "<p><a href='https://data.ntsb.gov/carol-repgen/api/Aviation/ReportMain/GenerateNewestReport/201774/pdf'>NTSB preliminary report WPR26LA001</a>. This authored example is not a reconstruction or causal finding.</p></html>")


class FixturePreview:
    def __init__(self, root, size=2, computation="local"):
        self.root = Path(root).resolve()
        self.folder = self.root / "saved-runs" / "hazards-preview"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.calculator = CostCalculator(computation)
        self.host = FixtureFleetHost(size, calculator=self.calculator)
        self.lock = threading.RLock()

    def dispatch(self, name, data):
        with self.lock:
            return self._dispatch(name, data)

    def _dispatch(self, name, data):
        message, saved = "Updated.", None
        if name == "state":
            pass
        elif name == "reset" and set(data) == {"size"}:
            self.host = FixtureFleetHost(data["size"], calculator=self.calculator)
            message = "New authored fixture started. Previously saved previews remain available."
        elif name == "prepare" and set(data) == {"drone_id"}:
            result = self.host.prepare(data["drone_id"])
            message = "Prepared only; no capture or debit. Calculation: " + result["numerical"]["mode"]
        elif name == "execute" and set(data) == {"drone_id"}:
            result = self.host.execute(data["drone_id"], "preview-" + uuid4().hex)
            message = result["status"].upper() + ": " + result.get("reason", result.get("evidence", ""))
        elif name == "replan" and not data:
            result = self.host.replan()
            message = f"Reassigned {len(result)} eligible fixture tasks. Prepare again before trying a new simulation."
        elif name in ("report-example", "operator-report", "clear"):
            if name == "operator-report":
                rectangle(data.get("rectangle"))
            registry = self.host.bridge.registry.snapshot()
            exists = "crane-001" in registry["hazards"]
            action = "clear" if name == "clear" else ("amend" if exists else "report")
            event = crane_event(registry["revision"], action=action, effective=max(1, self.host.sim_time),
                                source="synthetic_event" if name == "report-example" else "operator_report",
                                notes=data.get("notes", "Authored example crane report; not an actual detected obstacle"),
                                rect=data.get("rectangle"))
            if name in ("operator-report", "clear"):
                stamp = datetime.now(timezone.utc).isoformat()
                event["observed_at_utc"] = event["reported_at_utc"] = stamp
            result = self.host.report(event)
            message = f"Registry revision {result['hazard_revision']}: {result['assessed_count']} drone records assessed, {result['affected_count']} affected. Old proposals require revalidation."
        elif name in ("save", "report") and not data:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            saved = "hazards-preview-" + stamp + ".json"
            state = self.host.snapshot()
            (self.folder / saved).write_text(json.dumps(state, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            if name == "report":
                (self.folder / saved.replace(".json", ".html")).write_text(report_html(state), encoding="utf-8")
            message = "Saved fixture " + ("report and run: " if name == "report" else "run: ") + saved
        elif name == "reopen" and set(data) == {"name"}:
            filename = data["name"]
            if not isinstance(filename, str) or Path(filename).name != filename or not filename.startswith("hazards-preview-") or not filename.endswith(".json"):
                raise ValueError("Choose a saved hazard preview filename")
            file = self.folder / filename
            if file.stat().st_size > 5_000_000:
                raise ValueError("Preview save exceeds 5 MB")
            loaded = strict_json(file.read_text(encoding="utf-8"), max_chars=5_000_000)
            self.host = FixtureFleetHost.restore(loaded, calculator=self.calculator)
            message, saved = "Reopened exact paused fixture state; no new observation or capture.", filename
        else:
            raise ValueError("Unsupported hazard preview operation")
        return {"state": self.host.snapshot(), "message": message, "saved_name": saved}


def mount_routes(server, dispatcher):
    """Add a page/API to an existing server without editing shared entry files."""
    base = server.RequestHandlerClass

    class HazardHandler(base):
        def do_GET(self):
            path = urlparse(self.path).path
            assets = {"/hazards": ("hazards.html", "text/html"), "/hazards.js": ("hazards.js", "text/javascript"),
                      "/hazards.css": ("hazards.css", "text/css")}
            if path in assets:
                file, kind = assets[path]
                return self.send((WEB / file).read_bytes(), kind=kind)
            if path == "/api/hazards/state":
                return self.send(dispatcher("state", {}))
            if path == "/":
                document = (WEB / "index.html").read_text(encoding="utf-8")
                document = document.replace("</header>", '<p><a href="/hazards">Open reported-hazard fixture preview →</a></p></header>', 1)
                return self.send(document.encode(), kind="text/html")
            return super().do_GET()

        def do_POST(self):
            path = urlparse(self.path).path
            if not path.startswith("/api/hazards/"):
                return super().do_POST()
            try:
                host, origin = self.headers.get("Host", ""), self.headers.get("Origin")
                if host not in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}") or (origin and origin != "http://" + host):
                    return self.send({"error": "Local same-origin requests only"}, 403)
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8000 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("Send bounded JSON")
                data = strict_json(self.rfile.read(size).decode(), max_chars=8000)
                if not isinstance(data, dict):
                    raise ValueError("Expected object")
                return self.send(dispatcher(path.rsplit("/", 1)[-1], data))
            except (ValueError, TypeError, KeyError, OSError) as exc:
                return self.send({"error": str(exc)}, 400)

    server.RequestHandlerClass = HazardHandler
    return server
