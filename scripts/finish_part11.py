"""Launch the clearer operator desk, with actual bounded Wolfram checks or explicit local mode."""

import argparse
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stratus.inspection.comparison_checks import boundary_checks
from stratus.inspection.dashboard import Dashboard,make_server
from stratus.inspection.loader import load_mission
from stratus.inspection.review import InspectionSession

FOLDER=ROOT/'docs/evidence/inspection-0.0.2/part11'
SOURCES=['stratus/inspection/'+n for n in ['dashboard.py','report.py','ground.py','computation.py','workflow.py','web/index.html','web/style.css','web/app.js']]


def write(name,data):
    FOLDER.mkdir(parents=True,exist_ok=True)
    (FOLDER/name).write_text(json.dumps(data,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local',action='store_true',help='Use Python only, with live Wolfram checks explicitly unrun')
    parser.add_argument('--port',type=int,default=8769)
    parser.add_argument('--checkpoint',type=Path,help='Reopen a chosen run instead of creating a fresh demo')
    args=parser.parse_args()
    print('Checking Wolfram boundaries and units; no mission action is executed...',flush=True)
    numerical=boundary_checks(ROOT,ROOT/'docs/evidence/inspection-0.0.2/part8',live=True) if not args.local else {
        'status':'explicit local-only startup; live checks unrun','request_counts':{'local_kernel_calls':0,'cloud_requests':0,'alpha_calls':0},'boundaries':[]}
    write('wolfram-boundaries.json',numerical)
    print('Wolfram boundaries: '+numerical['status'],flush=True)
    checkpoint=args.checkpoint
    if checkpoint is None:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        checkpoint=ROOT/'saved-runs'/('ui11-start-'+stamp+'.json')
        InspectionSession(load_mission()).save(checkpoint)
    recorded=json.loads((ROOT/'docs/evidence/inspection-0.0.2/part8/ground-input.json').read_text())
    mode='wolfram' if not args.local and numerical['status']=='passed' else 'local'
    app=Dashboard(checkpoint=checkpoint,recorded=recorded,computation=mode)
    server=make_server(app,args.port)
    versions={}
    for name in ['hidapi','adafruit-blinka','adafruit-circuitpython-bme280','adafruit-circuitpython-pm25']:
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]='not installed; optional for replay'
    startup={'started_at_utc':datetime.now(timezone.utc).isoformat(),'url':f'http://127.0.0.1:{server.server_port}/',
        'checkpoint':app.checkpoint,'aircraft_state':app.session.state.snapshot(),'ground_source':app.ground.snapshot()['source_label'],
        'computation':app._costs,'boundary_request_counts':numerical['request_counts'],
        'dependency_versions':versions,'source_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in SOURCES},
        'state_transition_applied':False,'hardware_automatically_polled':False,'credits_consumed':'Unknown; no account usage retrieved',
        'live_ai_or_vision_run':False}
    write('fresh-start.json',startup)
    write('wolfram-typed-input.json',app._costs['normalized_input'])
    write('wolfram-typed-result.json',app._costs)
    print('STRATUS Part 11 ready: '+startup['url'],flush=True)
    print('Cost calculation: '+app._costs['mode']+'; Python validation is mandatory.',flush=True)
    print('Recorded measurements loaded. Select Live sensors for current readings.',flush=True)
    print('Fresh demo uses a new saved run; earlier completed runs remain available. Keep this window open.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()


if __name__=='__main__':main()
