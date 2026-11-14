"""Fleet commands share the existing backend/ground station and one numeric adapter."""
import copy
import json
from pathlib import Path
import threading
from .agent import OpenAIClient,ServiceError
from .fleet import FleetSession
from .fleet_costs import FleetCalculator
from .fleet_report import save_fleet_report
from .workflow import freeze_context

class FleetService:
    def __init__(self,app):
        self.app=app;self.root=app.mission.project_root;self.folder=self.root/'saved-runs/fleet';self.lock=threading.RLock()
        self.mode=app.computation_preference;self.core=FleetSession(2,11,freeze_context(app.ground.snapshot()),calculator=FleetCalculator(self.mode))
        self._reported_hazards=None
    def reported_hazards(self):
        with self.lock:
            if self._reported_hazards is None:
                from stratus.hazards.integration import LiveFleetHazards
                self._reported_hazards=LiveFleetHazards(self)
            return self._reported_hazards
    def snapshot(self):
        with self.lock:
            s=self.core.snapshot();s.update(computation_preference=self.mode,checkpoints=[p.name for p in sorted(self.folder.glob('*.json'))])
            s['allocations']=[{'round':a['round'],'time':a['time'],'candidate_pairs':len(a['shortlist']['pairs']),
                'selected':a['selected'],'mode':a['calculation']['mode'] if a['calculation'] else 'no candidates',
                'wall_seconds':a['wall_seconds'],'ownership_conflicts_skipped':len(a['ownership_conflicts_skipped']),
                'failure':a['calculation']['failure'] if a['calculation'] else None} for a in s['allocations'][-5:]]
            s['journal']=s['journal'][-20:];s['queue']=s['queue'][:60];s.pop('receipts');s.pop('ground_history')
            return s
    def command(self,data):
        shapes={'new':{'size','seed','mode','confirm_reset'},'run':set(),'pause':set(),'step':set(),'advance':{'count'},'save':set(),'open':{'checkpoint'},
                'preview':set(),'report':set(),'unavailable':{'drone_id'},'priority':{'asset_id','value'},'request_view':{'asset_id'},'context':set(),'explain':{'live'}}
        action=data.get('action')
        if action not in shapes or set(data)!={'action','run_id','state_revision'}|shapes[action]:raise ValueError('Unexpected fleet command fields')
        with self.lock,self.core.lock:
            if data['run_id']!=self.core.data['run_id'] or data['state_revision']!=self.core.data['state_revision']:raise ValueError('Fleet changed; refresh before applying this command')
            extra={}
            if action=='new':
                if data['mode'] not in ('local','wolfram'):raise ValueError('Choose local or wolfram')
                if (self.core.data['journal'] or self.core.data['assignments']) and data['confirm_reset'] is not True:raise ValueError('Confirm a new simulation; saved runs are preserved')
                self.mode=data['mode'];self.core=FleetSession(data['size'],data['seed'],freeze_context(self.app.ground.snapshot()),calculator=FleetCalculator(self.mode))
            elif action=='run':
                if self.core.data['status'] not in ('complete','stopped'):self.core.data.update(paused=False,status='running',state_revision=self.core.data['state_revision']+1)
            elif action=='pause':
                self.core.data['paused']=True
                self.core.data['state_revision']+=1
                if self.core.data['status']=='running':self.core.data['status']='paused'
            elif action in ('advance','step'):
                if action=='step':self.core.data.update(paused=True,status='paused' if self.core.data['status'] not in ('complete','stopped') else self.core.data['status'])
                if action=='step' or not self.core.data['paused']:self.core.advance(1 if action=='step' else data['count'])
            elif action=='preview':extra['preview']=self.core.preview()
            elif action=='save':extra['saved']=self.core.save(self.folder/(self.core.data['run_id']+'.json'))
            elif action=='open':
                name=data['checkpoint']
                if not isinstance(name,str) or Path(name).name!=name or not name.startswith('fleet-') or not name.endswith('.json'):raise ValueError('Choose a saved fleet run')
                self.core=FleetSession.load(self.folder/name);self.mode=self.core.calculator.mode
            elif action=='report':
                extra['saved']=self.core.save(self.folder/(self.core.data['run_id']+'.json'));extra['report']=save_fleet_report(self.core,self.root)
            elif action=='unavailable':self.core.unavailable(data['drone_id'])
            elif action=='priority':self.core.priority(data['asset_id'],data['value'])
            elif action=='request_view':self.core.request_view(data['asset_id'])
            elif action=='context':self.core.set_ground(freeze_context(self.app.ground.snapshot()))
            elif action=='explain':extra['explanation']=self.explain(data['live'])
            return {'state':self.snapshot(),**extra}

    def explain(self,live=False,client=None):
        if type(live) is not bool:raise ValueError('Choose live or local explanation')
        m=self.core.metrics();local=f"{m['drone_participation']}/{m['fleet_size']} drones have captured evidence. {m['unique_usable_assets']}/200 assets have a usable replay view; {m['unresolved_assets']} still need evidence. Assignments use exclusive ownership and per-drone reserve/capture checks; the heuristic is not globally optimal."
        result={'mode':'local_rule_explanation','text':local,'failure':None,'state_transition_applied':False,'model':None}
        if live:
            try:
                client=client or OpenAIClient.from_environment();self.core.data['ai_requests']+=1
                payload={'model':client.model,'store':False,'max_output_tokens':700,'instructions':'Explain this synthetic fleet summary in at most 100 words. No flight commands or defect/safety claims. Allocation is deterministic, images are authored replay, one ground node is separate. Do not claim global optimality or certified collision avoidance.',
                    'input':json.dumps({'metrics':{k:v for k,v in m.items() if k!='allocation_wall_seconds'},'method':self.core.data['method'],'recent_choices':[{'round':a['round'],'selected':a['selected'][:3]} for a in self.core.data['allocations'][-1:]]})}
                if client.model.startswith('gpt-5'):payload['reasoning']={'effort':'minimal'}
                reply=client.request(payload)
                texts=[c['text'] for item in reply.get('output',[]) if isinstance(item,dict) and item.get('type')=='message' for c in item.get('content',[]) if c.get('type')=='output_text' and isinstance(c.get('text'),str)]
                text=' '.join(texts).strip()
                if not text or len(text)>4000:raise ServiceError('invalid_response','No bounded explanation returned')
                result.update(mode='live_ai_explanation',text=text,model=client.model,response_id=reply.get('id'),usage=reply.get('usage'))
            except (ServiceError,ValueError,TypeError,KeyError):result.update(mode='local_rule_fallback',failure='AI unavailable or response invalid; no retry and no action executed')
        self.core.data['explanations'].append(copy.deepcopy(result));return result
