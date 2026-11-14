"""Start the current STRATUS desk with automatic live USB recovery."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stratus.inspection.dashboard import Dashboard, make_server
from scripts.verify_resilience import SOURCES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8769)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--computation', choices=('local','wolfram'), default='local')
    args = parser.parse_args()
    completed = list((ROOT/'saved-runs').glob('part6-browser-complete-*.json'))
    checkpoint = args.checkpoint or (max(completed, key=lambda p:p.stat().st_mtime) if completed else None)
    app = Dashboard(checkpoint=checkpoint, computation=args.computation)
    server = make_server(app, args.port)
    folder = ROOT/'docs/evidence/inspection-0.0.2/hotplug'; folder.mkdir(parents=True, exist_ok=True)
    sources = SOURCES + ['stratus/inspection/usb_reader.py','stratus/inspection/sensor_worker.py']
    startup = {'started_at_utc':datetime.now(timezone.utc).isoformat(),
        'url':f'http://127.0.0.1:{server.server_port}', 'checkpoint':app.checkpoint,
        'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},
        'aircraft_state':app.session.state.snapshot(), 'hardware_automatically_polled':False,
        'state_transition_applied':False, 'usb_recovery':'automatic fresh worker on a later live poll'}
    (folder/'startup.json').write_text(json.dumps(startup, indent=2)+'\n', encoding='utf-8')
    print('STRATUS ready: '+startup['url'], flush=True)
    print('Saved mission restored. Select Live USB reader for current measurements.', flush=True)
    print('USB reconnects automatically; particulate warm-up is 30 seconds. Keep this window open.', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); app.close()


if __name__=='__main__': main()
