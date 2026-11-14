"""Fork the actual paused browser run for an explicitly labeled replay test."""
import json
from pathlib import Path
import sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from stratus.inspection.fleet import FleetSession
from fleet_benchmark import OUT,write
from offline_checks import audit
if __name__=='__main__':
    sys.addaudithook(audit)
    source=OUT/'browser-fifty-paused.json';core=FleetSession.load(source);before=core.outcome_digest();original=core.data['run_id']
    core.data['run_id']='fleet-'+uuid4().hex
    assert core.outcome_digest()==before
    target=ROOT/'saved-runs/fleet'/(core.data['run_id']+'.json');saved=core.save(target)
    write(OUT/'browser-recovery-fork.json',{'source':'actual paused browser checkpoint; replay fork, no new captures acquired','source_run_id':original,'new_run_id':core.data['run_id'],'checkpoint':target.name,'outcome_digest_unchanged':True,'captured_views':core.metrics()['captures'],'saved':saved})
    print(json.dumps({'checkpoint':target.name,'captures':core.metrics()['captures'],'replay_fork':True}))
