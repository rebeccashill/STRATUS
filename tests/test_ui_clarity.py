"""Calculation selection is a read-only planning operation; fake replies are labeled tests."""

import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from stratus.inspection.computation import ComputationUnavailable, python_costs
from stratus.inspection.dashboard import Dashboard, make_server
from stratus.inspection.report import build_report, render_html
from stratus.inspection.review import InspectionSession
from stratus.inspection.loader import load_mission
from http_test_support import connection_for


class CalculationChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.checkpoint=Path(self.temp.name)/'fresh.json'
        InspectionSession(load_mission()).save(self.checkpoint)
        self.app=Dashboard(checkpoint=self.checkpoint);self.addCleanup(self.app.close)
        self.app._workflow_path=Path(self.temp.name)/'workflow.json'
        self.before=self.app.session.state.snapshot()

    def test_python_choice_replans_without_executing_or_mutating_original(self):
        original=self.checkpoint.read_bytes();result=self.app.set_computation('local')
        self.assertEqual(result['state']['computation_preference'],'local')
        self.assertEqual(result['state']['costs']['mode'],'local_python')
        self.assertFalse(result['state_transition_applied'])
        self.assertEqual(self.app.session.state.snapshot(),self.before)
        self.assertEqual(self.checkpoint.read_bytes(),original)
        self.assertEqual(len(self.app.workflow.data['plans']),1)
        self.assertEqual(len(self.app.session.snapshot()['events']),0)

    def test_checked_wolfram_and_exact_cache_are_distinct(self):
        def injected(data):return dict(python_costs(data),wolfram_version='INJECTED TEST',system_id='test')
        with patch('stratus.inspection.computation.LocalWolfram.__call__',side_effect=injected):
            result=self.app.set_computation('wolfram')
            self.assertEqual(result['state']['costs']['mode'],'wolfram_local')
            preview=self.app.preview(15,5)
        self.assertEqual(preview['mode'],'cached_wolfram_local')
        self.assertEqual(self.app.session.state.snapshot(),self.before)
        self.assertEqual(result['state']['costs']['request_counts']['cloud_requests'],0)

    def test_unavailable_runtime_is_labeled_fallback_without_debit(self):
        with patch('stratus.inspection.computation.LocalWolfram.__call__',side_effect=ComputationUnavailable('timeout','Injected timeout')):
            result=self.app.set_computation('wolfram')
        self.assertEqual(result['state']['computation_preference'],'wolfram')
        self.assertEqual(result['state']['costs']['mode'],'local_python_fallback')
        self.assertEqual(result['state']['costs']['failure']['code'],'timeout')
        self.assertEqual(self.app.session.state.snapshot(),self.before)

    def test_numerical_disagreement_cannot_offer_capture(self):
        def wrong(data):
            value=dict(python_costs(data),wolfram_version='INJECTED TEST',system_id='test')
            value['options'][0]['margin']+=10
            return value
        with patch('stratus.inspection.computation.LocalWolfram.__call__',side_effect=wrong):
            result=self.app.set_computation('wolfram')
        self.assertEqual(result['state']['costs']['mode'],'wolfram_disagreement')
        self.assertIsNone(result['state']['current_plan']['proposal'])
        self.assertEqual(self.app.session.state.snapshot(),self.before)

    def test_invalid_choice_does_not_replace_calculator_or_history(self):
        calculator=self.app.calculator;before=copy.deepcopy(self.app.workflow.data)
        for mode in ('cloud','alpha',None,True,{},[]):
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.app.set_computation(mode)
        self.assertIs(self.app.calculator,calculator)
        self.assertEqual(self.app.workflow.data,before)

    def test_http_choice_uses_same_origin_and_preserves_flight(self):
        server=make_server(self.app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        for origin,expected in ((None,200),('https://foreign.example',403)):
            connection=connection_for(server, timeout=5)
            headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            connection.request('POST','/api/computation',json.dumps({'mode':'local'}),headers)
            response=connection.getresponse();body=json.loads(response.read());connection.close()
            self.assertEqual(response.status,expected)
            if expected==200:self.assertFalse(body['state_transition_applied'])
        self.assertEqual(self.app.session.state.snapshot(),self.before)

    def test_report_retains_data_and_explains_computation_and_task_resolution(self):
        self.app.set_computation('local');data=build_report(self.app.workflow,self.app._costs)
        html=render_html(data)
        self.assertEqual(data['aircraft_state'],self.app.workflow.snapshot()['aircraft_state'])
        self.assertIn('Wolfram results are independently checked by Python',html)
        self.assertIn('#ffb21a',html)
        self.assertIn('Ground conditions',html)
        self.assertIn('Energy after reserve',html)


if __name__=='__main__':unittest.main()
