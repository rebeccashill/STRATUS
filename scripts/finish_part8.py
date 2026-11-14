"""Finish the separate live numerical checks, update the comparison report and serve it."""

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stratus.inspection.comparison import load_frozen
from stratus.inspection.comparison_checks import boundary_checks
from stratus.inspection.comparison_report import save_report
from stratus.inspection.dashboard import Dashboard,make_server
from scripts.verify_comparison import FOLDER


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local',action='store_true',help='Leave live numerical checks explicitly unrun')
    parser.add_argument('--checks-only',action='store_true',help='Update numerical evidence and report without starting a server')
    parser.add_argument('--port',type=int,default=8769)
    args=parser.parse_args();load_frozen(ROOT,FOLDER)
    print('Checking the frozen numerical boundaries; no planner inputs or mission resources will change...',flush=True)
    numerical=boundary_checks(ROOT,FOLDER,live=True) if not args.local else {
        'status':'not run; explicit local-only finish','evidence_kind':'live numerical checks not run',
        'request_counts':{'local_kernel_calls':0,'cloud_requests':0,'alpha_calls':0},
        'account_credit_consumption':'Unknown; no account usage retrieved.','boundaries':[]}
    (FOLDER/'numerical-live.json').write_text(json.dumps(numerical,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    results=[json.loads(p.read_text()) for p in sorted((FOLDER/'runs').glob('*.json'))]
    if len(results)!=9:raise RuntimeError('Run verify_comparison.py first; exactly nine saved results are required')
    saved=save_report(ROOT,FOLDER,results)
    check=json.loads((FOLDER/'verification.json').read_text())
    check.update(numerical_live=numerical['status'],numerical_request_counts=numerical['request_counts'],
                 numerical_finish_at_utc=datetime.now(timezone.utc).isoformat())
    (FOLDER/'verification.json').write_text(json.dumps(check,indent=2)+'\n',encoding='utf-8')
    if args.checks_only:
        print('Numerical live status: '+numerical['status'],flush=True)
        print('Comparison report updated: '+saved['html'],flush=True)
        return
    completed=list((ROOT/'saved-runs').glob('part6-browser-complete-*.json'))
    checkpoint=max(completed,key=lambda p:p.stat().st_mtime) if completed else None
    app=Dashboard(checkpoint=checkpoint,computation='local');server=make_server(app,args.port)
    startup={'started_at_utc':datetime.now(timezone.utc).isoformat(),'url':f'http://127.0.0.1:{server.server_port}',
        'report_url':f'http://127.0.0.1:{server.server_port}/api/report/view?name=comparison-part8.html',
        'checkpoint':app.checkpoint,'aircraft_state':app.session.state.snapshot(),
        'ground_source':app.ground.snapshot()['source_label'],'source_sha256':check['source_sha256'],
        'state_transition_applied':False}
    (FOLDER/'fresh-start.json').write_text(json.dumps(startup,indent=2)+'\n',encoding='utf-8')
    print('Numerical live status: '+numerical['status'],flush=True)
    print('STRATUS Part 8 ready: '+startup['url'],flush=True)
    print('Comparison report: '+startup['report_url'],flush=True)
    print('Keep this window open. The completed mission is restored; no capture executed.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.close()


if __name__=='__main__':main()
