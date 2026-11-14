"""Loopback HTTP/service recovery tests with injected providers, never live calls."""
import copy
from dataclasses import replace
import http.client
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from stratus.inspection.agent import ServiceError
from stratus.inspection.dashboard import Dashboard,make_server
from stratus.inspection.loader import load_mission
from stratus.inspection.review import InspectionSession

class FleetServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        mission=load_mission();p=self.root/'single.json';InspectionSession(mission).save(p)
        self.app=Dashboard(checkpoint=p);self.addCleanup(self.app.close)
        self.single=copy.deepcopy(self.app.session.state.snapshot());self.app.mission=replace(mission,project_root=self.root)
        for name in ('P04-overview.png','P05-overview.png'):
            dst=self.root/'evidence/inspection/images'/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(mission.project_root/'evidence/inspection/images'/name,dst)
        self.service=self.app.fleet_service()
    def command(self,action,**extra):
        d=self.service.core.data
        return self.service.command(dict(action=action,run_id=d['run_id'],state_revision=d['state_revision'],**extra))
    def test_preview_and_paused_advance_never_capture_or_debit(self):
        before=self.service.core.outcome_digest();self.command('preview');self.command('advance',count=20)
        self.assertEqual(self.service.core.outcome_digest(),before);self.assertEqual(self.app.session.state.snapshot(),self.single)
    def test_stale_command_rejected_and_run_pause_revisions_change(self):
        state=self.service.snapshot();self.command('run')
        with self.assertRaises(ValueError):self.service.command(dict(action='step',run_id=state['run_id'],state_revision=state['state_revision']))
        self.command('pause');self.assertTrue(self.service.core.data['paused']);self.assertEqual(self.service.core.metrics()['captures'],0)
    def test_reset_requires_confirmation_and_does_not_refill_existing_run(self):
        self.command('step');before=self.service.core.outcome_digest()
        with self.assertRaises(ValueError):self.command('new',size=50,seed=11,mode='local',confirm_reset=False)
        self.assertEqual(self.service.core.outcome_digest(),before)
        self.command('new',size=50,seed=11,mode='local',confirm_reset=True);self.assertEqual(len(self.service.snapshot()['drones']),50)
    def test_save_open_pauses_and_continues_without_repeated_capture(self):
        self.command('run');self.command('advance',count=7);before=self.service.core.outcome_digest();saved=self.command('save')['saved']
        self.command('advance',count=20);self.command('open',checkpoint=saved['checkpoint'])
        self.assertTrue(self.service.core.data['paused']);self.assertEqual(before,self.service.core.outcome_digest())
        self.service.core.run_to_end();self.assertEqual(self.service.core.metrics()['captures'],6)
    def test_strict_command_fields_path_and_counts(self):
        for action,extra in [('open',{'checkpoint':'../single.json'}),('new',dict(size=True,seed=11,mode='local',confirm_reset=True)),('advance',{'count':True})]:
            if action=='advance':self.command('run')
            with self.subTest(action=action),self.assertRaises(ValueError):self.command(action,**extra)
        with self.assertRaises(ValueError):self.command('run',unrecognized=True)
    def test_one_bounded_AI_explanation_never_executes_and_outage_falls_back(self):
        class Client:
            model='injected';calls=0
            def request(inner,payload):
                inner.calls+=1;self.assertLess(len(payload['input']),12000);self.assertEqual(payload['max_output_tokens'],700)
                return {'output':[{'type':'message','content':[{'type':'output_text','text':'INJECTED explanation; not live.'}]}]}
        before=self.service.core.outcome_digest();client=Client();result=self.service.explain(True,client)
        self.assertEqual(client.calls,1);self.assertFalse(result['state_transition_applied']);self.assertEqual(before,self.service.core.outcome_digest())
        class Outage:
            model='injected'
            def request(inner,payload):raise ServiceError('timeout','Injected only')
        result=self.service.explain(True,Outage());self.assertEqual(result['mode'],'local_rule_fallback');self.assertEqual(before,self.service.core.outcome_digest())
    def test_report_and_full_50_drone_accounting_are_portable(self):
        self.command('new',size=50,seed=11,mode='local',confirm_reset=True);self.service.core.run_to_end()
        report=self.command('report')['report'];raw=(self.root/'saved-runs/reports'/report['json']).read_text();state=json.loads(raw)
        self.assertEqual(len(state['drones']),50);self.assertEqual(state['metrics']['drone_participation'],50);self.assertIn('illustration',next(iter(state['evidence'].values())))
        html=(self.root/'saved-runs/reports'/report['html']).read_text();self.assertIn('D050',html);self.assertIn('data:image/png;base64,',html)
    def test_real_HTTP_origin_bounds_static_and_report_download_match(self):
        server=make_server(self.app,0);threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        def request(path,data=None,origin=None):
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10);headers={}
            if data is not None:headers['Content-Type']='application/json'
            if origin:headers['Origin']=origin
            c.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,headers);r=c.getresponse();body=r.read();status=r.status;c.close();return status,body
        state=json.loads(request('/api/fleet')[1]);body=dict(action='step',run_id=state['run_id'],state_revision=state['state_revision'])
        self.assertEqual(request('/api/fleet/command',body,'https://foreign.example')[0],403);self.assertEqual(self.service.core.metrics()['captures'],0)
        self.assertEqual(request('/api/fleet/command',body)[0],200);self.assertEqual(request('/api/fleet/command',body)[0],400)
        for url in ('/fleet','/fleet.js','/fleet.css','/fleet_playback.js'):self.assertEqual(request(url)[0],200)
        report=self.command('report')['report'];view=request(report['view']);download=request(report['download']);self.assertEqual(view[0],200);self.assertEqual(view[1],download[1])
        self.assertEqual(self.app.session.state.snapshot(),self.single)

if __name__=='__main__':unittest.main()
