"""Start a fresh Part 1 app and record one bounded actual Wolfram attempt."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stratus.inspection.computation import CostCalculator, compute_mission_options
from stratus.inspection.dashboard import Dashboard, make_server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8767)
    args=parser.parse_args()
    app=Dashboard()
    folder=ROOT/'docs/evidence/inspection-0.0.2/part1'
    folder.mkdir(parents=True,exist_ok=True)
    print('Checking the installed Wolfram adapter once (maximum 25 seconds)...',flush=True)
    calculator=CostCalculator('wolfram')
    result=compute_mission_options(app.mission,app.session.state,calculator)
    when=datetime.now(timezone.utc).isoformat()
    evidence={'attempted_at_utc':when,'scope':'Actual installed local adapter; not a mock',
              'result':result,'live_integration_complete':result['mode']=='wolfram_local',
              'fallback_allowed_by':'W008: if blocked, label live integration incomplete and use equivalent Python',
              'cloud_requests':0,'alpha_calls':0}
    (folder/'wolfram-final-check.json').write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if result['mode']=='wolfram_local':
        app.calculator=calculator
    # A failed start is bounded once. Subsequent local previews remain immediate.
    app._costs=result
    server=make_server(app,args.port)
    paths=[ROOT/'stratus/inspection/ground.py',ROOT/'stratus/inspection/dashboard.py',
           ROOT/'stratus/inspection/web/app.js']
    startup={'started_at_utc':when,'url':f'http://127.0.0.1:{server.server_port}',
             'computation_mode':result['mode'],'live_wolfram_integration_complete':evidence['live_integration_complete'],
             'source_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
             'ground_default':'recorded_measured','checkpoint':'saved-runs/first-inspection.json'}
    (folder/'fresh-start.json').write_text(json.dumps(startup,indent=2)+'\n',encoding='utf-8')
    print('Wolfram: '+result['mode']+(' (live integration incomplete)' if result['failure'] else ''),flush=True)
    print('STRATUS ready: '+startup['url'],flush=True)
    print('Keep this window open. Stop with Ctrl+C.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()


if __name__=='__main__':main()
