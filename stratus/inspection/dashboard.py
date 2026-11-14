"""One local stdlib backend for the inspection screen and optional ground reader."""

import argparse
import copy
from dataclasses import replace
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from .actions import strict_json
from .agent import fallback_proposal
from .capture import simulated_capture
from .computation import CostCalculator, compute_mission_options
from .engine import plain
from .ground import GroundFeed, present_snapshot
from .loader import PROJECT_ROOT, check_image, freeze, load_mission
from .operator import operator_summary
from .review import InspectionSession
from .workflow import AdaptiveWorkflow
from .report import save_report

WEB = Path(__file__).resolve().parent / "web"


class Dashboard:
    def __init__(self, mission=None, checkpoint=None, *, reader=None, recorded=None, computation="local"):
        self.mission = mission or load_mission()
        checkpoint = Path(checkpoint) if checkpoint else self.mission.project_root / "saved-runs/first-inspection.json"
        self.session = InspectionSession.load(self.mission, checkpoint)
        self.workflow=AdaptiveWorkflow(self.session)
        self.checkpoint = checkpoint.name
        self._workflow_path=checkpoint if self.workflow.data["plans"] else self.mission.project_root/"saved-runs"/("adaptive-"+self.session._run_id[4:12]+"-"+uuid4().hex[:6]+".json")
        self._lock = threading.RLock()
        self.ground = GroundFeed(self.mission,recorded or self.workflow.saved_ground(),reader=reader)
        self.computation_preference = computation
        self.calculator = CostCalculator(computation)
        self._costs = compute_mission_options(self.mission,self.session.state,self.calculator)
        self._fleet = None

    def fleet_service(self):
        with self._lock:
            if self._fleet is None:
                from .fleet_service import FleetService
                self._fleet = FleetService(self)
            return self._fleet

    def close(self): self.ground.close()

    def _options(self, computation, mission=None):
        mission = mission or self.mission
        checks = {(c["asset_id"],c["view_id"]):c for c in computation["action_checks"]}
        assets = {a["asset_id"]:a for a in mission.document["assets"]}
        choices = []
        for option in computation["output"]["options"]:
            key = option["asset_id"],option["view_id"]
            choices.append(dict(option,execution_allowed=checks[key]["execution_allowed"],reason_code=checks[key]["code"],
                                priority=assets[key[0]]["priority"]))
        allowed = sorted([c for c in choices if c["execution_allowed"]], key=lambda c:(-c["priority"],c["outbound"]+c["capture"],c["asset_id"],c["view_id"]))
        if self.workflow.data["feedback"]:
            choices,allowed=self.workflow.selection(computation,mission)
        recommendation = fallback_proposal(mission,self.session.state)
        selected = next((c for c in allowed if (c["asset_id"],c["view_id"]) == (recommendation.asset_id,recommendation.view_id)),None)
        if self.workflow.data["feedback"]:selected=allowed[0] if allowed else None
        alternative = next((c for c in allowed if c is not selected),None)
        return {"candidates":choices,"selected":selected,"alternative":alternative,
                "recommendation":recommendation.to_dict(),"mode":computation["mode"],
                "model_version":computation["model_version"],"energy_unit":"simulated_energy_unit","distance_unit":"m",
                "failure":computation["failure"],"request_counts":computation["request_counts"]}

    def state(self):
        with self._lock:
            run = self.workflow.snapshot()
            summary=operator_summary(self.session)
            latest=self.workflow.data["plans"][-1] if self.workflow.data["plans"] else None
            options=self._options(self._costs)
            if latest and latest["state_revision"]==self.session.state.revision and latest["review_revision"]==self.workflow.review_revision:
                p=latest["proposal"]
                summary["next_action"]={"type":p["action_type"] if p else "hold","label":f"Capture {p['asset_id']}/{p['view_id']}" if p else "Hold for review / return decision","reason":latest["reason"]}
                options=self._options(latest["computation"])
                options.update(selected=latest["selected"],alternative=latest["alternative"],recommendation=p or {"reason":latest["reason"]})
            layout = [dict(plain(a),review=next(x for x in run["assets"] if x["asset_id"]==a["asset_id"])) for a in self.mission.document["assets"]]
            return {"mission_id":self.mission.document["mission_id"],"mission_revision":self.mission.document["revision"],
                    "checkpoint":self.checkpoint,"computation_preference":self.computation_preference,"run":run,"layout":layout,"launch":plain(self.mission.document["launch_point"]),
                    "energy_model":plain(self.mission.document["energy_model"]),"costs":options,
                    "operator":summary,"ground":self.ground.snapshot(),"current_plan":latest,
                    "checkpoints":[p.name for p in sorted((self.mission.project_root/"saved-runs").glob("*.json"))],
                    "notices":{"flight":"Simulated aircraft / energy / capture", "images":"Self-authored synthetic illustrations",
                               "assessment":"Annotated replay; human review pending", "wolfram":self._costs["mode"],
                               "ground":"Ground node location is independent of aircraft position; no flight-clearance or defect inference"}}

    def evidence(self, asset, view):
        result = simulated_capture(self.mission,asset,view)
        # The viewer reads fixed evidence; it never appends a paid inspection.
        return result

    def set_computation(self, mode):
        if mode not in ("local", "wolfram"):
            raise ValueError("Choose local or wolfram computation")
        with self._lock:
            before = self.session.state.snapshot()
            self.calculator = CostCalculator(mode)
            self.computation_preference = mode
            result = self.workflow.plan(self.ground.snapshot(), self.calculator)
            self._costs = result["computation"]
            if self.session.state.snapshot() != before:
                raise RuntimeError("Changing computation changed aircraft state")
            self.save()
            return {"computation_preference": mode, "state": self.state(),
                    "state_transition_applied": False}

    def load(self, name):
        with self._lock:
            if name == "fresh":
                self.session = InspectionSession(self.mission); self.checkpoint = "Fresh mission"
            else:
                if not isinstance(name,str) or Path(name).name != name or not name.endswith(".json"):
                    raise ValueError("Choose a checkpoint from the saved-runs list")
                candidate=InspectionSession.load(self.mission,self.mission.project_root/"saved-runs"/name)
                AdaptiveWorkflow(candidate)  # Validate extended state before replacing the active run.
                self.session = candidate
                self.checkpoint = name
            self.workflow=AdaptiveWorkflow(self.session)
            self.ground.restore(self.workflow.saved_ground())
            self._workflow_path=(self.mission.project_root/"saved-runs"/name if self.workflow.data["plans"] else
                                 self.mission.project_root/"saved-runs"/("adaptive-"+self.session._run_id[4:12]+"-"+uuid4().hex[:6]+".json"))
            self._costs = compute_mission_options(self.mission,self.session.state,self.calculator)
            return self.state()

    def preview(self, reserve, capture):
        if (type(reserve) not in (int,float) or type(capture) not in (int,float)
            or not 0 <= reserve <= 50 or not 0 <= capture <= 20):
            raise ValueError("Preview bounds: reserve 0-50 and capture 0-20 simulated units")
        with self._lock:
            before = self.session.snapshot()
            result=self.workflow.preview(reserve,capture,self.calculator)
            if self.session.snapshot() != before: raise RuntimeError("Preview changed active state")
            if self.workflow.data["plans"]:self.save()
            return result

    def save(self):
        with self._lock:
            self.workflow._sync()
            saved=self.session.save(self._workflow_path)
            self.checkpoint=self._workflow_path.name
            return saved

    def plan(self,asset=None,view=None,mode="fallback"):
        with self._lock:
            result=self.workflow.plan(self.ground.snapshot(),self.calculator,asset=asset,view=view,mode=mode)
            self._costs=result["computation"];self.save()
            return {"plan":result,"state":self.state()}

    def feedback(self,assessment_id,action,request_id,review_revision):
        with self._lock:
            result=self.workflow.feedback(assessment_id,action,request_id=request_id,expected_review_revision=review_revision,ground=self.ground.snapshot())
            if result.get("status")!="already_processed":
                self._costs=self.workflow.plan(self.ground.snapshot(),self.calculator)["computation"]
            self.save();return {"feedback":result,"state":self.state()}

    def execute(self,plan_id):
        with self._lock:
            event=self.workflow.execute(plan_id,self.calculator)
            self.save()  # Persist the debit/receipt before preparing another read-only plan.
            if event["status"]=="executed":
                next_plan=self.workflow.plan(self.ground.snapshot(),self.calculator)
                self._costs=next_plan["computation"]
            self.save();return {"event":event,"state":self.state()}

    def report(self):
        with self._lock:
            self.save()
            saved=save_report(self.workflow,self._costs,self.mission.project_root/"saved-runs/reports")
            return {"html":saved["html"],"json":saved["json"],"download":"/api/report/download?name="+saved["html"],"checkpoint":self.checkpoint}


def make_server(app, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass

        def send(self, value, status=200, kind="application/json",download=None):
            raw = json.dumps(value,allow_nan=False).encode() if kind=="application/json" else value
            self.send_response(status); self.send_header("Content-Type",kind+"; charset=utf-8" if kind.startswith("text/") else kind)
            self.send_header("Content-Length",str(len(raw))); self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            if download:self.send_header("Content-Disposition",'attachment; filename="'+download+'"')
            self.send_header("Content-Security-Policy","default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(raw)

        def do_GET(self):
            try:
                parsed = urlparse(self.path); query = parse_qs(parsed.query)
                if parsed.path == "/api/state": return self.send(app.state())
                if parsed.path == "/api/fleet": return self.send(app.fleet_service().snapshot())
                if parsed.path == "/api/hazards/state": return self.send(app.fleet_service().reported_hazards().dispatch('state',{}))
                if parsed.path == "/api/ground": return self.send(app.ground.snapshot())
                if parsed.path == "/api/ground/export": return self.send(app.ground.export_recorded())
                if parsed.path == "/api/evidence": return self.send(app.evidence(query.get("asset",[""])[0],query.get("view",[""])[0]))
                if parsed.path in ("/api/report/download","/api/report/view"):
                    name=query.get("name",[""])[0]
                    if Path(name).name!=name or Path(name).suffix not in (".html",".json"):raise ValueError("Invalid report name")
                    path=app.mission.project_root/"saved-runs/reports"/name
                    return self.send(path.read_bytes(),kind="text/html" if path.suffix==".html" else "application/octet-stream",download=name if parsed.path.endswith("download") else None)
                if parsed.path == "/image":
                    key = query.get("asset",[""])[0],query.get("view",[""])[0]
                    evidence = app.mission.evidence_by_view.get(key)
                    if evidence is None: return self.send({"error":"Evidence mapping unavailable"},404)
                    if app.evidence(*key)["status"] != "available": return self.send({"error":"Evidence unavailable or excluded"},404)
                    check_image(evidence,app.mission.project_root)
                    return self.send(evidence.image_path.read_bytes(),kind="image/png")
                static = {"/":("index.html","text/html"),"/app.js":("app.js","text/javascript"),"/style.css":("style.css","text/css"),
                          "/fleet":("fleet.html","text/html"),"/fleet.js":("fleet.js","text/javascript"),"/fleet.css":("fleet.css","text/css"),"/fleet_playback.js":("fleet_playback.js","text/javascript"),
                          "/hazards":("hazards.html","text/html"),"/hazards.js":("hazards.js","text/javascript"),"/hazards.css":("hazards.css","text/css")}
                if parsed.path in static:
                    file,kind=static[parsed.path];return self.send((WEB/file).read_bytes(),kind=kind)
                self.send({"error":"Not found"},404)
            except (ValueError,OSError,KeyError) as exc: self.send({"error":str(exc)},400)

        def do_POST(self):
            try:
                size=int(self.headers.get("Content-Length","0"))
                if not 0 < size <= 4000 or self.headers.get("Content-Type","").split(";")[0] != "application/json":
                    raise ValueError("Send bounded JSON")
                raw=self.rfile.read(size).decode()
                host=self.headers.get("Host","");origin=self.headers.get("Origin")
                if host not in (f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}") or (origin and origin not in ("http://"+host,)):
                    return self.send({"error":"Local same-origin requests only"},403)
                data=strict_json(raw)
                if not isinstance(data,dict):raise ValueError("Expected JSON object")
                if self.path == "/api/fleet/command":return self.send(app.fleet_service().command(data))
                if self.path.startswith('/api/hazards/'):
                    return self.send(app.fleet_service().reported_hazards().dispatch(self.path.rsplit('/',1)[-1],data))
                if self.path == "/api/load" and set(data)=={"checkpoint"}: return self.send(app.load(data["checkpoint"]))
                if self.path == "/api/ground" and set(data)=={"mode"}: return self.send(app.ground.select(data["mode"]))
                if self.path == "/api/preview" and set(data)=={"reserve","capture"}:return self.send(app.preview(data["reserve"],data["capture"]))
                if self.path == "/api/plan" and set(data)=={"asset","view","mode"}:return self.send(app.plan(**data))
                if self.path == "/api/computation" and set(data)=={"mode"}:return self.send(app.set_computation(data["mode"]))
                if self.path == "/api/feedback" and set(data)=={"assessment_id","action","request_id","review_revision"}:return self.send(app.feedback(**data))
                if self.path == "/api/execute" and set(data)=={"plan_id"}:return self.send(app.execute(**data))
                if self.path == "/api/save" and not data:return self.send(app.save())
                if self.path == "/api/report" and not data:return self.send(app.report())
                self.send({"error":"Unsupported operation"},404)
            except (ValueError,TypeError,OSError,KeyError) as exc:self.send({"error":str(exc)},400)
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler);server.daemon_threads=True
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",type=int,default=8765);parser.add_argument("--checkpoint",type=Path)
    parser.add_argument("--recorded-ground",type=Path,help="Explicit exported measured ground snapshot; no remote USB is implied")
    parser.add_argument("--computation",choices=("local","wolfram"),default="local",help="Optional bounded local Wolfram attempt, with labeled Python fallback")
    args=parser.parse_args()
    recorded=None
    if args.recorded_ground:
        try:
            if args.recorded_ground.stat().st_size>2_000_000:raise ValueError("Ground export exceeds 2 MB")
            recorded=strict_json(args.recorded_ground.read_text(encoding="utf-8-sig"),max_chars=2_000_000)
            if not isinstance(recorded,dict) or recorded.get("mode")!="recorded_measured":raise ValueError("Export must be explicitly recorded measured data")
            present_snapshot(recorded)
        except (OSError,ValueError,TypeError,KeyError) as exc:parser.error(str(exc))
    app=Dashboard(checkpoint=args.checkpoint,recorded=recorded,computation=args.computation);server=make_server(app,args.port)
    print(f"STRATUS dashboard: http://127.0.0.1:{server.server_port} | checkpoint: {app.checkpoint}",flush=True)
    print(f"Recorded ground / {app._costs['mode']} / synthetic evidence. Choose Live explicitly for the local USB reader.",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()


if __name__ == "__main__":main()
