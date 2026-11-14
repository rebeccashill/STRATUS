"""Launch current Part 2 source, record bounded Wolfram/AI context calls, then serve."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stratus.inspection.dashboard import Dashboard,make_server

SOURCES=['agent.py','dashboard.py','workflow.py','report.py','operator.py','ground.py','web/app.js','web/index.html','web/style.css']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--computation',choices=('wolfram','local'),default='wolfram')
    parser.add_argument('--ai',choices=('live','fallback'),default='live')
    args=parser.parse_args()
    folder=ROOT/'docs/evidence/inspection-0.0.2/part2';folder.mkdir(parents=True,exist_ok=True)
    print('Loading the saved checkpoint; checking the selected numerical adapter...',flush=True)
    app=Dashboard(computation=args.computation)
    print('Preparing a read-only proposal with the shared ground snapshot; no capture will execute...',flush=True)
    result=app.plan(mode=args.ai)
    (folder/'startup-plan.json').write_text(json.dumps(result['plan'],indent=2,allow_nan=False)+'\n',encoding='utf-8')
    server=make_server(app,args.port)
    startup={'started_at_utc':datetime.now(timezone.utc).isoformat(),'url':f'http://127.0.0.1:{server.server_port}',
             'source_sha256':{'stratus/inspection/'+p:hashlib.sha256((ROOT/'stratus/inspection'/p).read_bytes()).hexdigest() for p in SOURCES},
             'checkpoint':app.checkpoint,'numerical_mode':result['plan']['computation']['mode'],
             'agent_mode':result['plan']['execution_mode'],'ai_failure':(result['plan']['agent'] or {}).get('failure'),
             'ground_context_id':result['plan']['ground_context_id'],'aircraft_revision':app.session.state.revision,
             'state_transition_applied':False}
    (folder/'fresh-start.json').write_text(json.dumps(startup,indent=2)+'\n',encoding='utf-8')
    print('STRATUS Part 2 ready: '+startup['url'],flush=True)
    print('Numerical mode: '+startup['numerical_mode']+' | Proposal: '+startup['agent_mode'],flush=True)
    print('Keep this window open. Plan/feedback never capture; Execute is a separate explicit action.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()


if __name__=='__main__':main()
