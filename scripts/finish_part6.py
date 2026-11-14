"""Serve the verified partial Part 6 run with current recovery code; no automatic capture."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stratus.inspection.dashboard import Dashboard, make_server
from scripts.verify_resilience import SOURCES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8769)
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--computation',choices=('local','wolfram'),default='local')
    args=parser.parse_args();folder=ROOT/'docs/evidence/inspection-0.0.2/part6'
    verified=json.loads((folder/'verification.json').read_text())
    checkpoint=args.checkpoint or ROOT/verified['partial_checkpoint']
    app=Dashboard(checkpoint=checkpoint,computation=args.computation)
    server=make_server(app,args.port)
    startup={'started_at_utc':datetime.now(timezone.utc).isoformat(),'url':f'http://127.0.0.1:{server.server_port}',
             'checkpoint':app.checkpoint,'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},
             'aircraft_state':app.session.state.snapshot(),'ground':app.ground.snapshot(),
             'state_transition_applied':False,'hardware_automatically_polled':False}
    (folder/'fresh-start.json').write_text(json.dumps(startup,indent=2)+'\n',encoding='utf-8')
    print('STRATUS Part 6 ready: '+startup['url'],flush=True)
    print('Partial run reopened. Ground is recorded history; select Live for a new device read.',flush=True)
    print('No capture ran. Keep this window open; Ctrl+C stops the app.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()


if __name__=='__main__':main()
